from __future__ import annotations

import json
import hashlib
import math
import statistics
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "eval" / "gold_questions.jsonl"
REPORT_FILE = ROOT / "reports" / "gold_evaluation.json"
API_URL = "http://127.0.0.1:8000"
STRATEGIES = ("dense", "bm25", "hybrid")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def ndcg_at_10(ids: list[str], gold: set[str]) -> float:
    dcg = sum((1.0 / math.log2(rank + 1)) for rank, cid in enumerate(ids[:10], start=1) if cid in gold)
    ideal_hits = min(len(gold), 10)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def retrieval_eval(rows: list[dict], strategy: str, include_details: bool = True) -> dict:
    hits_at_5: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    failures: list[str] = []
    details: list[dict] = []
    category_scores: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        started = time.perf_counter()
        result = post(
            "/api/search",
            {
                "query": row["question"], "model": row["model"], "version": "",
                "top_k": 10, "strategy": strategy,
            },
        )
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [hit["chunk"]["chunk_id"] for hit in result["hits"]]
        gold = set(row["gold_chunk_ids"])
        ranks = [rank for rank, cid in enumerate(ids, start=1) if cid in gold]
        retrieved_at_5 = set(ids[:5])
        recall = len(retrieved_at_5 & gold) / len(gold) if gold else 0.0
        hit = 1.0 if retrieved_at_5 & gold else 0.0
        reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0
        ndcg = ndcg_at_10(ids, gold)
        hits_at_5.append(hit)
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        ndcgs.append(ndcg)
        category = row.get("category", "uncategorized")
        scores = category_scores.setdefault(category, {"hit": [], "recall": [], "rr": [], "ndcg": []})
        scores["hit"].append(hit)
        scores["recall"].append(recall)
        scores["rr"].append(reciprocal_rank)
        scores["ndcg"].append(ndcg)
        if not ranks:
            failures.append(row["id"])
        if include_details:
            details.append(
                {
                    "id": row["id"],
                    "category": category,
                    "gold_source": "project_supplement" if all(cid.startswith("autoops_") for cid in gold) else "official_manual",
                    "gold_chunks": len(gold),
                    "gold_in_top_5": len(retrieved_at_5 & gold),
                    "hit@5": hit,
                    "recall@5": round(recall, 4),
                    "relevant_ranks": ranks,
                    "top_10": [
                        {
                            "rank": rank,
                            "chunk_id": item["chunk"]["chunk_id"],
                            "document": item["chunk"]["doc_name"],
                            "page": item["chunk"]["page"],
                            "score": round(item["score"], 6),
                        }
                        for rank, item in enumerate(result["hits"], start=1)
                    ],
                }
            )
    by_category = {
        category: {
            "questions": len(scores["recall"]),
            "hit@5": round(statistics.fmean(scores["hit"]), 4),
            "recall@5": round(statistics.fmean(scores["recall"]), 4),
            "mrr@10": round(statistics.fmean(scores["rr"]), 4),
            "ndcg@10": round(statistics.fmean(scores["ndcg"]), 4),
        }
        for category, scores in sorted(category_scores.items())
    }
    summary = {
        "hit@5": round(statistics.fmean(hits_at_5), 4),
        "recall@5": round(statistics.fmean(recalls), 4),
        "mrr@10": round(statistics.fmean(reciprocal_ranks), 4),
        "ndcg@10": round(statistics.fmean(ndcgs), 4),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "failures": failures,
        "by_category": by_category,
    }
    if include_details:
        summary["details"] = details
    return summary


def agent_eval(rows: list[dict], run_id: str) -> dict:
    tool_correct = 0
    citation_valid = 0
    gold_hits = 0
    gold_recalls: list[float] = []
    trace_present = 0
    details: list[dict] = []
    for row in rows:
        result = post(
            "/api/chat",
            {
                "query": row["question"], "model": row["model"], "version": "",
                "top_k": 5, "strategy": "hybrid", "session_id": f"gold-eval-{run_id}-{row['id']}",
            },
        )
        tool_correct += result["selected_tool"] == row["expected_tool"]
        citation_valid += not result["warnings"]
        trace_present += bool(result.get("agent_trace"))
        evidence_ids = {hit["chunk"]["chunk_id"] for hit in result["evidence"]}
        gold = set(row["gold_chunk_ids"])
        gold_hits += bool(evidence_ids & gold)
        gold_recalls.append(len(evidence_ids & gold) / len(gold) if gold else 0.0)
        details.append(
            {
                "id": row["id"],
                "selected_tool": result["selected_tool"],
                "expected_tool": row["expected_tool"],
                "evidence_chunk_ids": sorted(evidence_ids),
                "warnings": result["warnings"],
                "runtime": result.get("runtime", {}),
                "trace": result.get("agent_trace", []),
            }
        )
    total = len(rows)
    return {
        "tool_accuracy": round(tool_correct / total, 4),
        "citation_valid_rate": round(citation_valid / total, 4),
        "gold_evidence_hit@5": round(gold_hits / total, 4),
        "gold_evidence_recall@5": round(statistics.fmean(gold_recalls), 4),
        "agent_trace_coverage": round(trace_present / total, 4),
        "details": details,
    }


def main() -> None:
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise SystemExit("Service is not running. Start it with .\\scripts\\start_background.ps1") from exc

    rows = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    run_id = uuid4().hex[:12]
    project_rows = [row for row in rows if all(cid.startswith("autoops_") for cid in row["gold_chunk_ids"])]
    official_rows = [row for row in rows if all(not cid.startswith("autoops_") for cid in row["gold_chunk_ids"])]
    report = {
        "evaluation_type": "small-curated-gold-chunk-pilot",
        "run_id": run_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "file": str(EVAL_FILE.relative_to(ROOT)),
            "sha256": hashlib.sha256(EVAL_FILE.read_bytes()).hexdigest(),
            "category_distribution": dict(sorted(Counter(row.get("category", "uncategorized") for row in rows).items())),
        },
        "questions": len(rows),
        "corpus_chunks": health["indexed_chunks"],
        "configuration": {
            "embedding_backend": health["embedding_backend"],
            "embedding_model": health["embedding_model"],
            "dense_candidates": 30,
            "bm25_candidates": 30,
            "fusion": "RRF k=60, limit=20",
            "returned_hits": 10,
        },
        "retrieval_ablation": {strategy: retrieval_eval(rows, strategy) for strategy in STRATEGIES},
        "hybrid_by_source": {
            "official_manual_questions": retrieval_eval(official_rows, "hybrid", include_details=False),
            "project_supplement_questions": retrieval_eval(project_rows, "hybrid", include_details=False),
        },
        "workflow_checks": agent_eval(rows, run_id),
        "limitations": [
            f"Pilot set contains only {len(rows)} curated questions and was not independently blind-reviewed.",
            f"Only {len(official_rows)} questions use official-manual gold chunks; {len(project_rows)} use project-authored supplement chunks.",
            "Citation validation checks whether a cited chunk exists; it is not a human factual-accuracy or faithfulness score for the final answer.",
            "Expand to 100+ independently reviewed questions before production claims.",
        ],
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
