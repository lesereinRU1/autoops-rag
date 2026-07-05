from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.intent import classify_intent
from app.agent.iterative import (
    assess_evidence,
    build_retry_query,
    merge_evidence_rounds,
    retry_stop_reason,
    should_retry_retrieval,
)
from scripts.eval_ranking_only import aggregate, evaluate_row


DEFAULT_DATASET = ROOT / "data" / "eval" / "formal_questions.jsonl"
DEFAULT_JSON_REPORT = ROOT / "reports" / "iterative_retrieval_eval.json"
DEFAULT_MD_REPORT = ROOT / "reports" / "iterative_retrieval_eval.md"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 2)


def _legacy_rewrite(row: dict[str, Any]) -> str:
    import re

    query = re.sub(r"(请问|麻烦|一下|应该如何|怎么办)", " ", row["question"])
    context = " ".join(
        filter(
            None,
            [
                row.get("device_model") or "S7-1200",
                row.get("manual_version") or row.get("firmware_version") or "",
                "故障诊断 参数 手册",
            ],
        )
    )
    return f"{query.strip()} {context}"


def _search(retriever, row: dict[str, Any], query: str):
    return retriever.search(
        query,
        top_k=5,
        model=row.get("device_model") or "S7-1200",
        version=row.get("manual_version") or row.get("firmware_version") or "",
    )


def _rows(dataset: Path, split: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    selected = [row for row in rows if split == "all" or row.get("split") == split]
    answerable = [row for row in selected if row.get("answerable")]
    policy = [row for row in selected if not row.get("answerable")]
    for row in answerable:
        if not row.get("gold_chunk_ids") or row.get("gold_label_source") != "human_pre_labeled":
            raise ValueError(f"{row.get('id')}: answerable case lacks human-pre-labeled gold")
    return answerable, policy


def run_evaluation(
    dataset: Path = DEFAULT_DATASET,
    *,
    split: str = "development",
    retriever=None,
    max_rounds: int = 2,
    max_tool_calls: int = 4,
    max_rewrites: int = 1,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    before_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    answerable, policy_rows = _rows(dataset, split)
    owns_retriever = retriever is None
    if retriever is None:
        from app.config import get_settings
        from app.retrieval.hybrid import HybridRetriever

        retriever = HybridRetriever(get_settings())

    config = SimpleNamespace(
        enable_iterative_retrieval=True,
        max_agent_rounds=max_rounds,
        max_tool_calls=max_tool_calls,
        max_llm_calls=2,
        agent_timeout_seconds=timeout_seconds,
        max_rewrites=max_rewrites,
    )
    baseline_details: list[dict[str, Any]] = []
    iterative_details: list[dict[str, Any]] = []
    case_details: list[dict[str, Any]] = []
    baseline_latencies: list[float] = []
    iterative_latencies: list[float] = []
    retry_count = 0
    retry_count_before_filter = 0
    retry_blocked_by_generic_terms = 0
    unnecessary_retries = 0
    filtered_missing_terms_total = 0
    generic_terms_ignored_total = 0
    budget_stop_count = 0
    loop_violation_count = 0

    try:
        for index, row in enumerate(answerable, start=1):
            initial_started = time.perf_counter()
            first_hits = _search(retriever, row, row["question"])
            initial_ms = (time.perf_counter() - initial_started) * 1000
            intent = classify_intent(
                row["question"],
                model=row.get("device_model") or "S7-1200",
                version=row.get("manual_version") or row.get("firmware_version") or "",
            )["intent"]
            assessment = assess_evidence(
                row["question"], first_hits, round_count=1, intent=intent
            )
            would_retry_before_filter = bool(
                assessment["retry_would_trigger_before_filter"]
            )
            retry_count_before_filter += int(would_retry_before_filter)
            retry_blocked_by_generic_terms += int(
                assessment["retry_blocked_by_generic_terms"]
            )
            filtered_missing_terms_total += len(assessment["filtered_missing_terms"])
            generic_terms_ignored_total += len(assessment["generic_terms_ignored"])

            # Baseline mirrors the existing one-rewrite path, including replacing
            # first-round evidence with the second-round result.
            baseline_hits = first_hits
            baseline_ms = initial_ms
            if not assessment["sufficient_before_filter"]:
                started = time.perf_counter()
                baseline_hits = _search(retriever, row, _legacy_rewrite(row))
                baseline_ms += (time.perf_counter() - started) * 1000

            state = {
                "question": row["question"],
                "model": row.get("device_model") or "S7-1200",
                "version": row.get("manual_version") or row.get("firmware_version") or "",
                "intent": {"intent": intent},
                "round_count": 1,
                "retry_count": 0,
                "tool_calls": [{"tool": "search_manual", "round": 1}],
                "agent_started_at": time.monotonic(),
            }
            candidate_hits = first_hits
            candidate_ms = initial_ms
            retried = should_retry_retrieval(state, assessment, config)
            stop_reason = "evidence_sufficient" if assessment["sufficient"] else "insufficient_evidence"
            rounds = 1
            if retried:
                retry_count += 1
                state["retry_count"] = 1
                rewritten = build_retry_query(row["question"], state, assessment)
                started = time.perf_counter()
                retry_hits = _search(retriever, row, rewritten)
                candidate_ms += (time.perf_counter() - started) * 1000
                candidate_hits = merge_evidence_rounds(first_hits, retry_hits)
                rounds = 2
                state["round_count"] = rounds
                state["tool_calls"].append({"tool": "search_manual", "round": 2})
                final_assessment = assess_evidence(
                    rewritten, candidate_hits, round_count=2, intent=intent
                )
                stop_reason = (
                    "evidence_sufficient"
                    if final_assessment["sufficient"]
                    else retry_stop_reason(
                        state,
                        config,
                        assessment=final_assessment,
                    )
                )
                if stop_reason in {
                    "max_rounds_reached",
                    "max_rewrites_reached",
                    "max_tool_calls_reached",
                    "timeout_reached",
                }:
                    budget_stop_count += 1
            elif not assessment["sufficient"]:
                stop_reason = retry_stop_reason(
                    state,
                    config,
                    assessment=assessment,
                )
                if stop_reason in {
                    "max_rounds_reached",
                    "max_rewrites_reached",
                    "max_tool_calls_reached",
                    "timeout_reached",
                }:
                    budget_stop_count += 1

            initial_eval = evaluate_row(row, [hit.chunk.chunk_id for hit in first_hits])
            baseline_eval = evaluate_row(row, [hit.chunk.chunk_id for hit in baseline_hits])
            iterative_eval = evaluate_row(row, [hit.chunk.chunk_id for hit in candidate_hits])
            unnecessary = retried and initial_eval["strict_recall@5"] == 1.0
            unnecessary_retries += int(unnecessary)
            loop_violation = rounds > max_rounds or int(retried) > max_rewrites
            loop_violation_count += int(loop_violation)
            baseline_details.append(baseline_eval)
            iterative_details.append(iterative_eval)
            baseline_latencies.append(round(baseline_ms, 2))
            iterative_latencies.append(round(candidate_ms, 2))
            case_details.append(
                {
                    "id": row["id"],
                    "intent": intent,
                    "assessment": assessment,
                    "retry_would_trigger_before_filter": would_retry_before_filter,
                    "retry_blocked_by_generic_terms": assessment[
                        "retry_blocked_by_generic_terms"
                    ],
                    "retry_triggered": retried,
                    "unnecessary_retry": unnecessary,
                    "rounds": rounds,
                    "stop_reason": stop_reason,
                    "baseline_top5": baseline_eval["top5_chunk_ids"],
                    "iterative_top5": iterative_eval["top5_chunk_ids"],
                    "strict_recall_gain": round(
                        iterative_eval["strict_recall@5"] - baseline_eval["strict_recall@5"], 4
                    ),
                }
            )
            print(f"[{index:03}/{len(answerable):03}] {row['id']} retry={retried} rounds={rounds}")
    finally:
        if owns_retriever and retriever is not None:
            retriever.close()

    safety_regressions = 0
    out_of_scope_regressions = 0
    policy_details = []
    for row in policy_rows:
        expected_intent = "safety_risk" if row.get("category") == "unsafe_request" else "out_of_scope"
        state = {
            "intent": {"intent": expected_intent},
            "round_count": 0,
            "retry_count": 0,
            "tool_calls": [],
            "agent_started_at": time.monotonic(),
        }
        retry = should_retry_retrieval(
            state,
            {"sufficient": False, "recommended_next_action": "rewrite_and_retry"},
            config,
        )
        if expected_intent == "safety_risk":
            safety_regressions += int(retry)
        else:
            out_of_scope_regressions += int(retry)
        policy_details.append({"id": row["id"], "expected_intent": expected_intent, "retry_triggered": retry})

    after_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("formal dataset changed while iterative evaluation was running")
    baseline_metrics = aggregate(baseline_details)
    iterative_metrics = aggregate(iterative_details)
    total = len(answerable)
    metrics = {
        "total_cases": total,
        "retry_trigger_count_before_filter": retry_count_before_filter,
        "retry_trigger_count": retry_count,
        "retry_blocked_by_generic_terms": retry_blocked_by_generic_terms,
        "generic_term_retry_block_count": retry_blocked_by_generic_terms,
        "retry_trigger_rate_before_filter": round(retry_count_before_filter / total, 4) if total else None,
        "retry_trigger_rate_after_filter": round(retry_count / total, 4) if total else None,
        "retry_trigger_rate": round(retry_count / total, 4) if total else None,
        "unnecessary_retry_count": unnecessary_retries,
        "unnecessary_retry_rate": round(unnecessary_retries / retry_count, 4) if retry_count else 0.0,
        "filtered_missing_terms_avg": round(filtered_missing_terms_total / total, 4) if total else None,
        "generic_terms_ignored_avg": round(generic_terms_ignored_total / total, 4) if total else None,
        "iterative_retrieval_gain": round(
            iterative_metrics["strict_recall@5"] - baseline_metrics["strict_recall@5"], 4
        ),
        "strict_recall@5_baseline": baseline_metrics["strict_recall@5"],
        "strict_recall@5_iterative": iterative_metrics["strict_recall@5"],
        "mrr@5_baseline": baseline_metrics["mrr@5"],
        "mrr@5_iterative": iterative_metrics["mrr@5"],
        "ndcg@5_baseline": baseline_metrics["ndcg@5"],
        "ndcg@5_iterative": iterative_metrics["ndcg@5"],
        "top1_accuracy_baseline": baseline_metrics["top1_accuracy"],
        "top1_accuracy_iterative": iterative_metrics["top1_accuracy"],
        "avg_rounds": round((total + retry_count) / total, 4) if total else None,
        "p50_latency_ms_baseline": round(statistics.median(baseline_latencies), 2) if baseline_latencies else None,
        "p95_latency_ms_baseline": _percentile(baseline_latencies, 0.95),
        "p50_latency_ms_iterative": round(statistics.median(iterative_latencies), 2) if iterative_latencies else None,
        "p95_latency_ms_iterative": _percentile(iterative_latencies, 0.95),
        "budget_stop_count": budget_stop_count,
        "loop_violation_count": loop_violation_count,
        "safety_regression_count": safety_regressions,
        "out_of_scope_regression_count": out_of_scope_regressions,
    }
    return {
        "evaluation_type": "evidence_driven_iterative_retrieval_ab",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(dataset.resolve()),
        "dataset_sha256": before_hash,
        "split": split,
        "external_llm_called": False,
        "api_called": False,
        "answers_generated": False,
        "metrics": metrics,
        "metric_notes": {
            "iterative_retrieval_gain": "Filtered candidate minus legacy one-rewrite baseline Strict Recall@5; gain may come from avoiding an unnecessary retry.",
            "unnecessary_retry_rate": "Retries whose first-round Top5 already contained all human gold chunks / all retries.",
            "retry_trigger_rate_before_filter": "Counterfactual trigger rate using the pre-filter identifier gate.",
            "retry_blocked_by_generic_terms": "Retries blocked because every missing identifier was generic.",
            "scope": "Retrieval evidence only; this is not final answer accuracy.",
        },
        "details": case_details,
        "policy_details": policy_details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    labels = {
        "total_cases": "Total Cases",
        "retry_trigger_count_before_filter": "Retry Trigger Count Before Filtering",
        "retry_trigger_count": "Retry Trigger Count After Filtering",
        "generic_term_retry_block_count": "Generic Term Retry Block Count",
        "retry_trigger_rate_before_filter": "Retry Trigger Rate Before Filtering",
        "retry_trigger_rate_after_filter": "Retry Trigger Rate After Filtering",
        "retry_trigger_rate": "Retry Trigger Rate",
        "unnecessary_retry_count": "Unnecessary Retry Count",
        "unnecessary_retry_rate": "Unnecessary Retry Rate",
        "filtered_missing_terms_avg": "Filtered Missing Terms Avg",
        "generic_terms_ignored_avg": "Generic Terms Ignored Avg",
        "iterative_retrieval_gain": "Iterative Retrieval Gain",
        "strict_recall@5_baseline": "Strict Recall@5 Baseline",
        "strict_recall@5_iterative": "Strict Recall@5 Iterative",
        "mrr@5_baseline": "MRR@5 Baseline",
        "mrr@5_iterative": "MRR@5 Iterative",
        "ndcg@5_baseline": "nDCG@5 Baseline",
        "ndcg@5_iterative": "nDCG@5 Iterative",
        "top1_accuracy_baseline": "Top1 Accuracy Baseline",
        "top1_accuracy_iterative": "Top1 Accuracy Iterative",
        "avg_rounds": "Avg Rounds",
        "p50_latency_ms_baseline": "P50 Latency Baseline (ms)",
        "p95_latency_ms_baseline": "P95 Latency Baseline (ms)",
        "p50_latency_ms_iterative": "P50 Latency Iterative (ms)",
        "p95_latency_ms_iterative": "P95 Latency Iterative (ms)",
        "budget_stop_count": "Budget Stop Count",
        "loop_violation_count": "Loop Violation Count",
        "safety_regression_count": "Safety Regression Count",
        "out_of_scope_regression_count": "Out-of-scope Regression Count",
    }
    lines = [
        "# Iterative Retrieval A/B Evaluation",
        "",
        "> This report evaluates retrieval evidence only. It does not call an LLM or measure final answer accuracy.",
        "",
        f"- Split: `{report['split']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, label in labels.items():
        value = metrics.get(key)
        lines.append(f"| {label} | {'N/A' if value is None else value} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Baseline mirrors the existing bounded one-rewrite behavior.",
            "- Iterative mode retries only after an insufficient evidence assessment and merges both rounds by `chunk_id`.",
            "- Identifier filtering is deterministic and rule-based; no LLM is used to decide retries.",
            "- Generic terms such as `0`, `PLC`, `manual`, `手册` and broad device names do not justify a retry by themselves.",
            "- Latency and retry rates must be considered alongside retrieval gain.",
            "- Safety and out-of-scope cases are policy checks and never execute retrieval in this evaluation.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="A/B evaluate bounded evidence-driven iterative retrieval without LLM calls.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("development", "test", "all"), default="development")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_REPORT)
    args = parser.parse_args()

    report = run_evaluation(args.dataset.resolve(), split=args.split)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.md_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "json": str(args.json_output), "md": str(args.md_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
