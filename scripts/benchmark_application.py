from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "eval" / "application_questions.jsonl"
LOCK_FILE = ROOT / "data" / "eval" / "application_eval.lock.json"
REPORT = ROOT / "reports" / "application_evaluation.json"
BASELINE_REPORT = ROOT / "reports" / "application_evaluation_baseline.json"
API_URL = "http://127.0.0.1:8000"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
REFUSAL_MARKERS = (
    "没有找到足够证据", "证据不足", "现有资料中没有", "无法从现有资料",
    "未收录", "超出当前资料", "不能提供", "不提供",
)


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def clear_session(session_id: str) -> None:
    request = urllib.request.Request(
        f"{API_URL}/api/sessions/{urllib.parse.quote(session_id)}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except OSError:
        pass


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * ratio) - 1)]


def dataset_readiness(rows: list[dict]) -> dict:
    official = sum(row["source_scope"] == "official_manual" for row in rows if row["answerable"])
    answerable = sum(row["answerable"] for row in rows)
    independently_reviewed = sum(row["review_status"] == "independent_reviewed" for row in rows)
    unanswerable = len(rows) - answerable
    checks = {
        "questions_at_least_60": len(rows) >= 60,
        "regression_questions_at_least_20": sum(row["split"] == "regression" for row in rows) >= 20,
        "official_share_at_least_70_percent": official / max(1, answerable) >= 0.70,
        "unanswerable_questions_at_least_10": unanswerable >= 10,
        "independently_reviewed_at_least_30": independently_reviewed >= 30,
    }
    return {
        "ready_for_resume_accuracy_claim": all(checks.values()),
        "checks": checks,
        "counts": {
            "total": len(rows),
            "answerable": answerable,
            "official_answerable": official,
            "unanswerable": unanswerable,
            "independently_reviewed": independently_reviewed,
        },
    }


def validate_rows(rows: list[dict]) -> None:
    required = {
        "id", "split", "category", "question", "model", "answerable",
        "gold_chunk_ids", "expected_tool", "required_fact_groups", "source_scope", "review_status",
    }
    ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        missing = required - set(row)
        if missing:
            raise ValueError(f"第{index}行缺少字段：{', '.join(sorted(missing))}")
        if row["id"] in ids:
            raise ValueError(f"重复题号：{row['id']}")
        ids.add(row["id"])
        if row["answerable"] and not row["gold_chunk_ids"]:
            raise ValueError(f"可回答题缺少gold_chunk_ids：{row['id']}")
        if not row["answerable"] and row["gold_chunk_ids"]:
            raise ValueError(f"不可回答题不应设置gold_chunk_ids：{row['id']}")


def fact_coverage(answer: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    if not groups:
        return 0.0, []
    lowered = answer.lower().replace(" ", "")
    missing = [
        group for group in groups
        if not any(value.lower().replace(" ", "") in lowered for value in group)
    ]
    return (len(groups) - len(missing)) / len(groups), missing


def main() -> None:
    parser = argparse.ArgumentParser(description="运行不依赖外部大模型的应用层回归评测")
    parser.add_argument("--split", choices=("development", "regression", "all"), default="all")
    args = parser.parse_args()

    raw = DATASET.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    validate_rows(rows)
    readiness = dataset_readiness(rows)
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8")) if LOCK_FILE.exists() else {}
    dataset_hash = hashlib.sha256(raw).hexdigest()
    lock_matches = lock.get("sha256") == dataset_hash
    selected = rows if args.split == "all" else [row for row in rows if row["split"] == args.split]

    run_id = uuid4().hex[:12]
    details: list[dict] = []
    retrieval_recalls: list[float] = []
    retrieval_hits: list[float] = []
    reciprocal_ranks: list[float] = []
    fact_scores: list[float] = []
    citation_scores: list[float] = []
    tool_scores: list[float] = []
    refusal_scores: list[float] = []
    latencies: list[float] = []

    for row in selected:
        session_id = f"application-eval-{run_id}-{row['id']}"
        started = time.perf_counter()
        result = post(
            "/api/chat",
            {
                "query": row["question"], "model": row["model"], "version": "",
                "top_k": 5, "strategy": "hybrid", "session_id": session_id,
            },
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        evidence_ids = [hit["chunk"]["chunk_id"] for hit in result["evidence"]]
        gold = set(row["gold_chunk_ids"])
        ranks = [rank for rank, cid in enumerate(evidence_ids, start=1) if cid in gold]
        refused = (not result["evidence_sufficient"]) or any(
            marker in result["answer"] for marker in REFUSAL_MARKERS
        )
        fact_score, missing_facts = fact_coverage(result["answer"], row["required_fact_groups"])
        tool_correct = result["selected_tool"] == row["expected_tool"]

        if row["answerable"]:
            recall = len(set(evidence_ids) & gold) / len(gold)
            hit = float(bool(set(evidence_ids) & gold))
            rr = 1.0 / min(ranks) if ranks else 0.0
            citation_ok = float(bool(evidence_ids) and not result["warnings"])
            retrieval_recalls.append(recall)
            retrieval_hits.append(hit)
            reciprocal_ranks.append(rr)
            fact_scores.append(fact_score)
            citation_scores.append(citation_ok)
        else:
            recall = hit = rr = citation_ok = None
            refusal_scores.append(float(refused))
        tool_scores.append(float(tool_correct))
        if row["answerable"] and not hit:
            failure_type = "retrieval_miss"
        elif row["answerable"] and fact_score < 1.0:
            failure_type = "answer_fact_missing"
        elif row["answerable"] and not citation_ok:
            failure_type = "citation_invalid"
        elif not row["answerable"] and not refused:
            failure_type = "refusal_failure"
        elif row["answerable"] and rr < 1.0:
            failure_type = "ranking_late"
        else:
            failure_type = "passed"
        details.append(
            {
                "id": row["id"], "split": row["split"], "category": row["category"],
                "answerable": row["answerable"], "source_scope": row["source_scope"],
                "review_status": row["review_status"], "retrieval_hit@5": hit,
                "failure_type": failure_type,
                "retrieval_recall@5": recall, "reciprocal_rank": rr,
                "fact_string_coverage": round(fact_score, 4) if row["answerable"] else None,
                "missing_fact_groups": missing_facts, "citation_exists": citation_ok,
                "refused": refused, "tool_correct": tool_correct,
                "evidence_sufficient": result["evidence_sufficient"],
                "evidence_chunk_ids": evidence_ids, "answer": result["answer"],
                "runtime": result.get("runtime", {}), "latency_ms": round(latency_ms, 2),
            }
        )
        clear_session(session_id)

    metrics = {
        "retrieval_hit@5": round(statistics.fmean(retrieval_hits), 4) if retrieval_hits else None,
        "retrieval_recall@5": round(statistics.fmean(retrieval_recalls), 4) if retrieval_recalls else None,
        "retrieval_mrr@5": round(statistics.fmean(reciprocal_ranks), 4) if reciprocal_ranks else None,
        "fact_string_coverage": round(statistics.fmean(fact_scores), 4) if fact_scores else None,
        "citation_exists_rate": round(statistics.fmean(citation_scores), 4) if citation_scores else None,
        "tool_accuracy": round(statistics.fmean(tool_scores), 4) if tool_scores else None,
        "unanswerable_refusal_accuracy": round(statistics.fmean(refusal_scores), 4) if refusal_scores else None,
        "latency_p50_ms": round(percentile(latencies, 0.50), 2),
        "latency_p95_ms": round(percentile(latencies, 0.95), 2),
    }
    baseline_metrics = {}
    if BASELINE_REPORT.exists():
        baseline_metrics = json.loads(BASELINE_REPORT.read_text(encoding="utf-8")).get("metrics", {})
    comparable = (
        "retrieval_hit@5", "retrieval_recall@5", "retrieval_mrr@5", "fact_string_coverage",
        "citation_exists_rate", "tool_accuracy", "unanswerable_refusal_accuracy",
    )
    report = {
        "evaluation_type": "application-regression-with-deterministic-fact-checks",
        "run_id": run_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "file": str(DATASET.relative_to(ROOT)), "sha256": dataset_hash,
            "lock_matches": lock_matches, "selected_split": args.split,
            "questions": len(selected), "category_distribution": dict(Counter(row["category"] for row in selected)),
        },
        "readiness": readiness,
        "metrics": metrics,
        "baseline_comparison": {
            "baseline_file": str(BASELINE_REPORT.relative_to(ROOT)),
            "baseline_metrics": baseline_metrics,
            "delta": {
                key: round(metrics[key] - baseline_metrics[key], 4)
                for key in comparable
                if metrics.get(key) is not None and baseline_metrics.get(key) is not None
            },
        },
        "bad_case_distribution": dict(Counter(item["failure_type"] for item in details)),
        "details": details,
        "limitations": [
            "fact_string_coverage only checks reviewed strings; it is not semantic Answer Correctness.",
            "citation_exists_rate checks citation structure, not whether every statement is supported.",
            "The current set is self-checked and too small for a resume accuracy claim.",
            "Use independent reviewers and freeze a larger test set before reporting production quality.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
