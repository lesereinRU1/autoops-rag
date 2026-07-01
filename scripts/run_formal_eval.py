from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.llm_smoke_test import evaluate_claims, extract_cited_chunk_ids
from scripts.validate_formal_eval import (
    DEFAULT_DATASET,
    DEFAULT_REPORT as READINESS_REPORT,
    DEFAULT_SCHEMA,
    validate_dataset,
)


DEFAULT_OUTPUT = ROOT / "reports" / "formal_evaluation.json"
DISCLAIMER = (
    "正式指标只有在ready_for_resume_accuracy_claim=true时才可用于简历；"
    "当前20题smoke test不属于本数据集。"
)


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * ratio) - 1)], 2)


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def normalized_contains(text: str, fact: str) -> bool:
    normalize = lambda value: "".join(value.lower().split())
    return normalize(fact) in normalize(text)


def ndcg_at_5(retrieved: list[str], gold: set[str]) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:5], start=1)
        if chunk_id in gold
    )
    ideal_hits = min(5, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def empty_report(
    readiness: dict[str, Any], dataset: Path, split: str, reason: str
) -> dict[str, Any]:
    return {
        "evaluation_type": "formal_evaluation",
        "status": "not_run",
        "reason": reason,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(dataset),
        "selected_split": split,
        "readiness": readiness,
        "ready_for_resume_accuracy_claim": False,
        "metrics": {},
        "details": [],
        "disclaimer": DISCLAIMER,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="使用人工预标注gold_chunk_ids运行正式RAG评测；绝不生成或回写gold"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--split", choices=("development", "test", "all"), default="test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    schema = args.schema.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    READINESS_REPORT.parent.mkdir(parents=True, exist_ok=True)

    readiness, rows = validate_dataset(dataset, schema, check_chunk_existence=True)
    READINESS_REPORT.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if readiness["validation_errors"]:
        report = empty_report(readiness, dataset, args.split, "formal dataset validation failed")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "not_run", "reason": report["reason"]}, ensure_ascii=False))
        return 1

    selected = [
        {key: value for key, value in row.items() if key != "_line_number"}
        for row in rows
        if args.split == "all" or row.get("split") == args.split
    ]
    if not selected:
        report = empty_report(readiness, dataset, args.split, "no questions in selected split")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "not_run",
                    "reason": report["reason"],
                    "ready_for_resume_accuracy_claim": False,
                },
                ensure_ascii=False,
            )
        )
        return 0

    not_reviewable = [
        row["id"] for row in selected
        if row["review_status"] == "needs_review"
        or (row["answerable"] and row["gold_label_source"] != "human_pre_labeled")
    ]
    if not_reviewable:
        report = empty_report(
            readiness,
            dataset,
            args.split,
            "selected questions still need human review: " + ", ".join(not_reviewable),
        )
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "not_run", "reason": report["reason"]}, ensure_ascii=False))
        return 1

    before_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    run_id = uuid.uuid4().hex[:12]
    details: list[dict[str, Any]] = []
    base_url = args.base_url.rstrip("/")

    with httpx.Client(timeout=120, trust_env=False) as client:
        health = client.get(f"{base_url}/health")
        health.raise_for_status()
        for index, row in enumerate(selected, start=1):
            session_id = f"formal-eval-{run_id}-{row['id']}"
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{base_url}/api/chat",
                    json={
                        "query": row["question"],
                        "model": row["device_model"],
                        "version": row["manual_version"] or row["firmware_version"],
                        "top_k": 5,
                        "strategy": "hybrid",
                        "session_id": session_id,
                    },
                )
                wall_latency_ms = round((time.perf_counter() - started) * 1000, 2)
                response.raise_for_status()
                result = response.json()
                runtime = result["runtime"]
                trace = result["rag_trace"]
                evidence_ids = [
                    hit["chunk"]["chunk_id"] for hit in result.get("evidence", [])[:5]
                ]
                gold = set(row["gold_chunk_ids"])
                ranks = [rank for rank, chunk_id in enumerate(evidence_ids, 1) if chunk_id in gold]
                refused = bool(trace.get("refused")) and not result.get(
                    "evidence_sufficient", False
                )
                claim_checks, unsupported = evaluate_claims(
                    row["id"], row["question"], result.get("answer", ""), trace, refused
                )
                cited_ids = extract_cited_chunk_ids(result.get("answer", ""))
                citation_valid = (
                    bool(cited_ids) and set(cited_ids).issubset(set(evidence_ids))
                    if row["answerable"]
                    else None
                )
                required_hits = [
                    fact for fact in row["required_facts"]
                    if normalized_contains(result.get("answer", ""), fact)
                ]
                forbidden_hits = [
                    fact for fact in row["forbidden_facts"]
                    if normalized_contains(result.get("answer", ""), fact)
                ]
                fallback_event = (
                    runtime.get("external_llm_calls", 0) > 0
                    and runtime.get("generation_mode") == "local_extractive"
                    and bool(runtime.get("generation_fallback_reason"))
                )
                fallback_success = (
                    fallback_event
                    and bool(result.get("answer"))
                    and bool(evidence_ids)
                    and bool(cited_ids)
                )
                detail = {
                    "id": row["id"],
                    "question": row["question"],
                    "category": row["category"],
                    "split": row["split"],
                    "answerable": row["answerable"],
                    "expected_tool": row["expected_tool"],
                    "selected_tool": result.get("selected_tool", ""),
                    "expected_tool_matched": result.get("selected_tool")
                    == row["expected_tool"],
                    "request_id": result["request_id"],
                    "http_status": response.status_code,
                    "evidence_chunk_ids": evidence_ids,
                    "gold_chunk_ids": row["gold_chunk_ids"],
                    "strict_recall@5": (
                        float(gold.issubset(set(evidence_ids)))
                        if row["answerable"] else None
                    ),
                    "reciprocal_rank@5": (
                        1.0 / min(ranks) if row["answerable"] and ranks else 0.0
                    ) if row["answerable"] else None,
                    "ndcg@5": ndcg_at_5(evidence_ids, gold) if row["answerable"] else None,
                    "top1_correct": (
                        bool(evidence_ids and evidence_ids[0] in gold)
                        if row["answerable"] else None
                    ),
                    "claim_checks": claim_checks,
                    "unsupported_claims": unsupported,
                    "citation_chunk_valid": citation_valid,
                    "required_fact_hits": required_hits,
                    "required_fact_total": len(row["required_facts"]),
                    "forbidden_fact_hits": forbidden_hits,
                    "refused": refused,
                    "fallback_event": fallback_event,
                    "fallback_success": fallback_success,
                    "fallback_reason": runtime.get("generation_fallback_reason", ""),
                    "retrieval_latency_ms": runtime.get("retrieval_latency_ms", 0.0),
                    "llm_latency_ms": runtime.get("llm_latency_ms", 0.0),
                    "total_latency_ms": runtime.get("total_ms"),
                    "first_token_latency_ms": runtime.get("first_token_latency_ms"),
                    "wall_latency_ms": wall_latency_ms,
                    "generation_mode": runtime.get("generation_mode"),
                    "answer": result.get("answer", ""),
                }
            except Exception as exc:
                detail = {
                    "id": row["id"],
                    "question": row["question"],
                    "category": row["category"],
                    "split": row["split"],
                    "answerable": row["answerable"],
                    "expected_tool": row["expected_tool"],
                    "http_status": getattr(getattr(exc, "response", None), "status_code", 0),
                    "error_type": type(exc).__name__,
                    "request_failed": True,
                }
            details.append(detail)
            print(f"[{index:03d}/{len(selected):03d}] {row['id']} status={detail['http_status']}")
            try:
                client.delete(f"{base_url}/api/sessions/{session_id}")
            except httpx.HTTPError:
                pass

    after_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if after_hash != before_hash:
        raise RuntimeError("formal dataset changed during evaluation; aborting report")

    successful = [item for item in details if item.get("http_status") == 200]
    answerable_details = [item for item in successful if item.get("answerable")]
    unanswerable_details = [
        item for item in successful
        if not item.get("answerable") and item.get("category") != "unsafe_request"
    ]
    unsafe_details = [
        item for item in successful if item.get("category") == "unsafe_request"
    ]
    claim_checks = [
        check for item in successful for check in item.get("claim_checks", [])
    ]
    unsupported = [
        finding for item in successful for finding in item.get("unsupported_claims", [])
        if finding.get("counts_as_unsupported")
    ]
    total_required = sum(item.get("required_fact_total", 0) for item in answerable_details)
    hit_required = sum(len(item.get("required_fact_hits", [])) for item in answerable_details)
    fallback_events = [item for item in successful if item.get("fallback_event")]
    retrieval_latencies = [float(item["retrieval_latency_ms"]) for item in successful]
    llm_latencies = [
        float(item["llm_latency_ms"])
        for item in successful if item.get("llm_latency_ms") is not None
        and float(item.get("llm_latency_ms", 0.0)) > 0
    ]
    total_latencies = [float(item["total_latency_ms"]) for item in successful]

    metrics = {
        "strict_recall@5": mean([item["strict_recall@5"] for item in answerable_details]),
        "mrr@5": mean([item["reciprocal_rank@5"] for item in answerable_details]),
        "ndcg@5": mean([item["ndcg@5"] for item in answerable_details]),
        "top1_accuracy": mean(
            [float(item["top1_correct"]) for item in answerable_details]
        ),
        "claim_support_rate": mean(
            [
                float(
                    not check.get(
                        "counts_as_unsupported", not bool(check.get("supported"))
                    )
                )
                for check in claim_checks
            ]
        ),
        "unsupported_claim_count": len(unsupported),
        "citation_chunk_valid_rate": mean(
            [float(item["citation_chunk_valid"]) for item in answerable_details]
        ),
        "required_fact_coverage": round(hit_required / total_required, 4)
        if total_required else None,
        "forbidden_fact_violation_count": sum(
            len(item.get("forbidden_fact_hits", [])) for item in successful
        ),
        "unanswerable_refusal_accuracy": mean(
            [float(item["refused"]) for item in unanswerable_details]
        ),
        "unsafe_refusal_accuracy": mean(
            [float(item["refused"]) for item in unsafe_details]
        ),
        "fallback_success_rate": mean(
            [float(item["fallback_success"]) for item in fallback_events]
        ),
        "retrieval_latency_p50_ms": percentile(retrieval_latencies, 0.50),
        "retrieval_latency_p95_ms": percentile(retrieval_latencies, 0.95),
        "llm_latency_p50_ms": percentile(llm_latencies, 0.50),
        "llm_latency_p95_ms": percentile(llm_latencies, 0.95),
        "total_latency_p50_ms": percentile(total_latencies, 0.50),
        "total_latency_p95_ms": percentile(total_latencies, 0.95),
    }
    report = {
        "evaluation_type": "formal_evaluation",
        "status": "completed",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "dataset": {
            "file": str(dataset),
            "sha256_before": before_hash,
            "sha256_after": after_hash,
            "unchanged": before_hash == after_hash,
            "selected_split": args.split,
            "questions": len(selected),
        },
        "readiness": readiness,
        "ready_for_resume_accuracy_claim": readiness[
            "ready_for_resume_accuracy_claim"
        ],
        "metrics": metrics,
        "metric_denominators": {
            "successful_requests": len(successful),
            "answerable": len(answerable_details),
            "unanswerable_non_unsafe": len(unanswerable_details),
            "unsafe": len(unsafe_details),
            "claim_sentences": len(claim_checks),
            "required_facts": total_required,
            "fallback_events": len(fallback_events),
        },
        "unsupported_claims": unsupported,
        "details": details,
        "disclaimer": DISCLAIMER,
        "limitations": [
            "gold_chunk_ids来自数据集中的人工预标注；runner不会生成或回写gold。",
            "required_fact_coverage和forbidden facts使用预标注短语匹配。",
            "claim_support_rate使用可审计规则检查，正式发布前仍需人工抽查。",
            "Recall@5不能单独作为项目质量结论。",
        ],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "completed",
                "questions": len(selected),
                "ready_for_resume_accuracy_claim": report[
                    "ready_for_resume_accuracy_claim"
                ],
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
