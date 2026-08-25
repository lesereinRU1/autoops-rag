from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.llm_smoke_test import evaluate_claims
from app.config import get_settings
from app.evaluation.end_to_end import (
    aggregate_results,
    dataset_sha256,
    error_case,
    evaluate_case,
    evaluate_citations,
    load_dataset_manifest,
    validate_dataset_manifest,
)
from app.evaluation.models import EvaluationCaseResult
from app.repositories import create_runtime_database_from_settings
from app.tracing import sanitize_trace
from scripts.validate_formal_eval import (
    CHUNKS_FILE,
    DEFAULT_DATASET,
    DEFAULT_REPORT as READINESS_REPORT,
    DEFAULT_SCHEMA,
    validate_dataset,
)


DEFAULT_OUTPUT = ROOT / "reports" / "formal_evaluation.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "reports" / "formal_evaluation.md"
DEFAULT_MANIFEST = ROOT / "data" / "eval" / "formal_eval_manifest.json"
DISCLAIMER = (
    "正式指标只有在ready_for_resume_accuracy_claim=true时才可用于简历；"
    "当前20题smoke test不属于本数据集。"
)
SMALL_SAMPLE_NOTE = "该类别样本量较小，仅用于诊断，不代表稳定统计结论。"


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def display_metric(value: Any) -> str:
    return "null" if value is None else str(value)


def report_path(path: Path) -> str:
    """Return a portable report path without exposing a developer machine path."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def ndcg_at_5(retrieved: list[str], gold: set[str]) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:5], start=1)
        if chunk_id in gold
    )
    ideal_hits = min(5, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def validate_formal_citations(answer: str, evidence_ids: list[str]) -> bool:
    """Compatibility wrapper; the formal runner uses the richer Evidence-aware evaluator."""

    inline: dict[int, tuple[str, int]] = {}
    for source, document, page in re.findall(
        r"\[来源\s*(\d+)[:：]([^\]，,]+)[，,]\s*第\s*(\d+)\s*页\]",
        answer or "",
    ):
        inline[int(source)] = (document.strip(), int(page))
    evidence = []
    for index, chunk_id in enumerate(evidence_ids, start=1):
        document, page = inline.get(index, ("", 0))
        evidence.append(
            {
                "chunk": {
                    "chunk_id": chunk_id,
                    "doc_name": document,
                    "page": page,
                }
            }
        )
    return evaluate_citations(answer, evidence).citation_valid


def empty_report(
    readiness: dict[str, Any],
    dataset: Path,
    split: str,
    reason: str,
    *,
    manifest: dict[str, Any] | None = None,
    status: str = "not_run",
    selected_count: int | None = None,
) -> dict[str, Any]:
    manifest = manifest or {}
    return {
        "evaluation_type": "formal_evaluation",
        "status": status,
        "reason": reason,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "version": manifest.get("dataset_version"),
            "file": report_path(dataset),
            "sha256": dataset_sha256(dataset) if dataset.exists() else None,
            "manifest_sha256": manifest.get("sha256"),
            "selected_split": split,
            "case_count": selected_count,
            "declared_case_count": manifest.get("case_count"),
            "splits": manifest.get("splits"),
        },
        "readiness": readiness,
        "ready_for_resume_accuracy_claim": False,
        "metrics": {},
        "retrieval_evaluation": {"metrics": {}, "case_count": 0},
        "end_to_end_evaluation": {"metrics": {}, "llm_judge_enabled": False},
        "by_category": {},
        "refusal_by_type": {},
        "failure_analysis": {},
        "llm_judge": {"enabled": False, "results": None},
        "details": [],
        "disclaimer": DISCLAIMER,
    }


def load_chunk_texts(path: Path = CHUNKS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        result[str(value["chunk_id"])] = str(value.get("text", ""))
    return result


def build_corpus_metadata(
    path: Path,
    all_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe the exact processed corpus used by a formal evaluation run."""

    metadata: dict[str, Any] = {
        "file": report_path(path),
        "exists": path.exists(),
        "sha256": dataset_sha256(path) if path.exists() else None,
        "document_count": None,
        "chunk_count": None,
        "table_chunk_count": None,
        "formal_gold_unique_count": None,
        "formal_gold_resolvable_count": None,
        "formal_gold_missing": None,
        "selected_gold_unique_count": None,
        "selected_gold_resolvable_count": None,
        "selected_gold_missing": None,
    }
    if not path.exists():
        return metadata

    chunk_ids: set[str] = set()
    document_ids: set[str] = set()
    table_chunk_count = 0
    chunk_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        chunk_count += 1
        chunk_ids.add(str(value["chunk_id"]))
        document_ids.add(str(value.get("doc_id") or value.get("doc_name") or ""))
        if value.get("metadata", {}).get("representation") == "table_row":
            table_chunk_count += 1

    def gold_resolution(rows: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
        gold = {
            str(chunk_id)
            for row in rows
            for chunk_id in row.get("gold_chunk_ids", [])
            if chunk_id
        }
        missing = sorted(gold - chunk_ids)
        return len(gold), len(gold) - len(missing), missing

    formal_total, formal_resolved, formal_missing = gold_resolution(all_rows)
    selected_total, selected_resolved, selected_missing = gold_resolution(selected_rows)
    metadata.update(
        {
            "document_count": len(document_ids - {""}),
            "chunk_count": chunk_count,
            "table_chunk_count": table_chunk_count,
            "formal_gold_unique_count": formal_total,
            "formal_gold_resolvable_count": formal_resolved,
            "formal_gold_missing": formal_missing,
            "selected_gold_unique_count": selected_total,
            "selected_gold_resolvable_count": selected_resolved,
            "selected_gold_missing": selected_missing,
        }
    )
    return metadata


def render_markdown_report(report: dict[str, Any]) -> str:
    dataset = report.get("dataset", {})
    corpus = report.get("corpus", {})
    metrics = report.get("metrics", {})
    lines = [
        "# Formal Evaluation Report",
        "",
        "> 当前正式集仍未达到 readiness 门槛时，本报告只能用于开发诊断，不能作为简历准确率宣传。",
        "",
        "## Dataset",
        "",
        f"- Version: `{dataset.get('version')}`",
        f"- SHA-256: `{dataset.get('sha256') or dataset.get('sha256_before')}`",
        f"- Split: `{dataset.get('selected_split')}`",
        f"- Case count: `{dataset.get('case_count') or dataset.get('questions')}`",
        f"- Status: `{report.get('status')}`",
        "",
        "Retrieval 指标与最终回答质量指标分层报告；Retrieval Recall 不等于最终回答准确率。",
        "",
    ]
    if report.get("status", "completed") != "completed":
        lines.extend(
            [
                "## Execution",
                "",
                f"- Reason: {report.get('reason', 'not executed')}",
                "- 本报告没有生成任何新的 Recall、Citation、Faithfulness 或拒答分数。",
                "",
            ]
        )
        return "\n".join(lines)

    if corpus:
        lines.extend(
            [
                "## Processed corpus",
                "",
                f"- SHA-256: `{corpus.get('sha256')}`",
                f"- Documents: `{corpus.get('document_count')}`",
                f"- Chunks: `{corpus.get('chunk_count')}`",
                f"- Table chunks: `{corpus.get('table_chunk_count')}`",
                f"- Formal gold resolvable: `{corpus.get('formal_gold_resolvable_count')}/{corpus.get('formal_gold_unique_count')}`",
                f"- Selected split gold resolvable: `{corpus.get('selected_gold_resolvable_count')}/{corpus.get('selected_gold_unique_count')}`",
                "",
            ]
        )

    lines.extend(
        [
        "## Retrieval Evaluation",
        "",
        "| Metric | Value |",
        "|---|---:|",
        ]
    )
    for name in (
        "strict_recall@5", "mrr@5", "ndcg@5", "top1_accuracy", "retrieval_hit_rate"
    ):
        lines.append(f"| `{name}` | {display_metric(metrics.get(name))} |")
    lines.extend(
        [
            "",
            "`strict_recall@5` 要求 Top 5 覆盖该题全部人工 gold chunk；"
            "`retrieval_hit_rate` 只要求至少命中一个 gold chunk。两者都只衡量检索。",
            "",
            "## End-to-End Rule Evaluation",
            "",
            "| Metric | Value | Meaning |",
            "|---|---:|---|",
            f"| `citation_correctness_rate` | {display_metric(metrics.get('citation_correctness_rate'))} | 引用是否真实映射到本次 Evidence 的 source/chunk/document/page |",
            f"| `required_fact_coverage` | {display_metric(metrics.get('required_fact_coverage'))} | 规则型 required facts 覆盖率，不是最终回答准确率 |",
            f"| `required_fact_exact_coverage` | {display_metric(metrics.get('required_fact_exact_coverage'))} | 历史完整子串规则口径 |",
            f"| `required_fact_diagnostic_coverage` | {display_metric(metrics.get('required_fact_diagnostic_coverage'))} | 确定性规范化和原子事实匹配，只用于诊断 |",
            f"| `technical_identifier_accuracy` | {display_metric(metrics.get('technical_identifier_accuracy'))} | 从 required_facts 自动抽取的技术标识精确匹配 |",
            f"| `multi_hop_evidence_coverage` | {display_metric(metrics.get('multi_hop_evidence_coverage'))} | 仅统计有多个必要 gold evidence 的多跳题 |",
            f"| `refusal_accuracy` | {display_metric(metrics.get('refusal_accuracy'))} | 应拒答/应回答决策是否正确 |",
            f"| `false_accept_rate` | {display_metric(metrics.get('false_accept_rate'))} | 应拒答却回答的比例 |",
            f"| `false_reject_rate` | {display_metric(metrics.get('false_reject_rate'))} | 应回答却拒答的比例 |",
            f"| `claim_support_rate` | {display_metric(metrics.get('claim_support_rate'))} | 仅检查规则可识别的引用、标识符和数值，不代表完整 Answer Faithfulness |",
            "",
            "精确技术标识的 gold 来源标记为 `derived from required_facts`；当前数据集没有人工结构化技术标识字段。",
            "Required Fact Coverage 低不能直接等同于模型错误；还需区分 checker 误判、真实漏答、复合标签和 gold 对齐问题。",
            "",
            "## Refusal confusion matrix",
            "",
            "| Outcome | Count |",
            "|---|---:|",
            f"| correct | {metrics.get('refusal_confusion_matrix', {}).get('correct')} |",
            f"| false_accept | {metrics.get('refusal_confusion_matrix', {}).get('false_accept')} |",
            f"| false_reject | {metrics.get('refusal_confusion_matrix', {}).get('false_reject')} |",
            "",
            "## By category",
            "",
            "| Category | Cases | Recall@5 | MRR@5 | Citation | Required facts | Refusal |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for category, summary in report.get("by_category", {}).items():
        lines.append(
            f"| `{category}` | {summary.get('case_count')} | {display_metric(summary.get('strict_recall@5'))} | "
            f"{display_metric(summary.get('mrr@5'))} | {display_metric(summary.get('citation_correctness_rate'))} | "
            f"{display_metric(summary.get('required_fact_coverage'))} | {display_metric(summary.get('refusal_accuracy'))} |"
        )
    small_categories = report.get("small_sample_categories", [])
    if small_categories:
        lines.extend(
            [
                "",
                f"小样本类别：`{', '.join(small_categories)}`。{report.get('small_sample_note', SMALL_SAMPLE_NOTE)}",
            ]
        )
    lines.extend(
        [
            "",
            "## Failure analysis",
            "",
            "| Failure | Count |",
            "|---|---:|",
        ]
    )
    for name, count in report.get("failure_analysis", {}).items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- 本轮没有启用 LLM-as-a-judge；`llm_judge.enabled=false`。",
            "- `claim_support_rate` 是窄范围、可审计的规则指标，不是完整 Answer Faithfulness。",
            "- `required_fact_coverage` 是规则型 coverage，不是最终回答准确率。",
            "- 技术标识由 `required_facts` 自动抽取，不是人工结构化 gold field。",
            "- 多跳 Evidence coverage 只对至少两个必要 gold chunk 的题目计算，其他题为 null。",
            "",
        ]
    )
    return "\n".join(lines)


def persist_evaluation_metadata(report: dict[str, Any]) -> bool:
    """Persist queryable run/record metadata without replacing JSON reports."""
    if report.get("status") != "completed" or not report.get("run_id"):
        return False
    database = create_runtime_database_from_settings(get_settings())
    try:
        repository = database.repositories.evaluations
        run_id = repository.create_run(
            "formal_evaluation",
            run_id=str(report["run_id"]),
            metadata={
                "generated_at": report.get("generated_at"),
                "dataset": report.get("dataset", {}),
                "corpus": report.get("corpus", {}),
                "ready_for_resume_accuracy_claim": report.get(
                    "ready_for_resume_accuracy_claim", False
                ),
            },
        )
        metric_fields = (
            "strict_recall@5",
            "reciprocal_rank",
            "ndcg@5",
            "top1_correct",
            "retrieval_hit",
            "citation_valid",
            "citation_invalid_count",
            "required_fact_coverage",
            "technical_identifier_accuracy",
            "multi_hop_evidence_coverage",
            "refusal_correct",
            "false_accept",
            "false_reject",
            "actual_refusal",
            "retrieval_latency_ms",
            "llm_latency_ms",
            "total_latency_ms",
            "latency",
            "stop_reason",
            "rewrite_count",
        )
        for item in report.get("details", []):
            repository.save_record(
                run_id,
                str(item.get("case_id") or item.get("id") or "unknown"),
                category=str(item.get("category", "")),
                status=(
                    "completed" if item.get("http_status") == 200 else "error"
                ),
                metrics={
                    key: item.get(key)
                    for key in metric_fields
                    if key in item
                },
                error=str(item.get("error") or ""),
            )
        repository.complete_run(
            run_id,
            summary={
                "metrics": report.get("metrics", {}),
                "metric_denominators": report.get("metric_denominators", {}),
            },
        )
        return True
    finally:
        database.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="使用人工预标注gold_chunk_ids运行正式RAG评测；绝不生成或回写gold"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--split", choices=("development", "test", "all"), default="test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--readiness-output", type=Path, default=READINESS_REPORT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验 dataset/manifest/split 和运行前置条件，不调用 API、不生成指标",
    )
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    schema = args.schema.resolve()
    manifest_path = args.manifest.resolve()
    output = args.output.resolve()
    markdown_output = args.markdown_output.resolve()
    readiness_output = args.readiness_output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    readiness_output.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_dataset_manifest(manifest_path) if manifest_path.exists() else {}
    readiness, rows = validate_dataset(
        dataset, schema, check_chunk_existence=not args.dry_run
    )
    manifest_errors = (
        validate_dataset_manifest(manifest, dataset, rows)
        if manifest
        else [
            "dataset manifest does not exist: "
            f"{report_path(manifest_path)}"
        ]
    )
    if manifest_errors:
        readiness["validation_errors"] = [
            *readiness.get("validation_errors", []),
            *manifest_errors,
        ]
        readiness["ready_for_resume_accuracy_claim"] = False
    readiness["dataset_version"] = manifest.get("dataset_version")
    readiness["manifest"] = report_path(manifest_path)
    readiness_output.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    selected = [
        {key: value for key, value in row.items() if key != "_line_number"}
        for row in rows
        if args.split == "all" or row.get("split") == args.split
    ]
    if readiness["validation_errors"]:
        validation_reason = (
            "formal dataset validation failed because "
            f"{report_path(CHUNKS_FILE)} is missing"
            if not CHUNKS_FILE.exists() and not args.dry_run
            else "formal dataset validation failed"
        )
        report = empty_report(
            readiness,
            dataset,
            args.split,
            validation_reason,
            manifest=manifest,
            selected_count=len(selected),
        )
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
        print(json.dumps({"status": "not_run", "reason": report["reason"]}, ensure_ascii=False))
        return 1

    if not selected:
        report = empty_report(
            readiness,
            dataset,
            args.split,
            "no questions in selected split",
            manifest=manifest,
            selected_count=0,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
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
            manifest=manifest,
            selected_count=len(selected),
        )
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
        print(json.dumps({"status": "not_run", "reason": report["reason"]}, ensure_ascii=False))
        return 1

    if args.dry_run:
        execution_ready = CHUNKS_FILE.exists()
        reason = (
            "dry-run validation passed"
            if execution_ready
            else "dry-run validation passed; full execution blocked because "
            f"{report_path(CHUNKS_FILE)} is missing"
        )
        report = empty_report(
            readiness,
            dataset,
            args.split,
            reason,
            manifest=manifest,
            status="dry_run",
            selected_count=len(selected),
        )
        report["execution_ready"] = execution_ready
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "questions": len(selected),
                    "dataset_version": manifest.get("dataset_version"),
                    "dataset_sha256": dataset_sha256(dataset),
                    "execution_ready": execution_ready,
                    "reason": reason,
                },
                ensure_ascii=False,
            )
        )
        return 0

    before_hash = dataset_sha256(dataset)
    corpus = build_corpus_metadata(CHUNKS_FILE, rows, selected)
    chunk_texts = load_chunk_texts()
    run_id = uuid.uuid4().hex[:12]
    case_results: list[EvaluationCaseResult] = []
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
                trace = result["rag_trace"]
                refused = bool(trace.get("refused"))
                claim_checks, unsupported = evaluate_claims(
                    row["id"], row["question"], result.get("answer", ""), trace, refused
                )
                case_result = evaluate_case(
                    row,
                    result,
                    wall_latency_ms=wall_latency_ms,
                    gold_chunk_texts=chunk_texts,
                    claim_checks=claim_checks,
                    unsupported_claims=unsupported,
                )
            except Exception as exc:
                case_result = error_case(row, exc)
            case_results.append(case_result)
            print(
                f"[{index:03d}/{len(selected):03d}] {row['id']} "
                f"status={case_result.http_status}"
            )
            try:
                client.delete(f"{base_url}/api/sessions/{session_id}")
            except httpx.HTTPError:
                pass

    after_hash = dataset_sha256(dataset)
    if after_hash != before_hash:
        raise RuntimeError("formal dataset changed during evaluation; aborting report")

    completed = [item for item in case_results if item.error is None]
    aggregation = aggregate_results(case_results)
    metrics = aggregation["overall"]
    non_safety_refusals = [
        item
        for item in completed
        if item.expected_refusal and item.expected_refusal_type != "safety"
    ]
    safety_refusals = [
        item for item in completed if item.expected_refusal_type == "safety"
    ]
    metrics["unanswerable_refusal_accuracy"] = mean(
        [float(bool(item.refusal_correct)) for item in non_safety_refusals]
    )
    metrics["unsafe_refusal_accuracy"] = mean(
        [float(bool(item.refusal_correct)) for item in safety_refusals]
    )
    unsupported = [
        finding
        for item in completed
        for finding in item.unsupported_claims or []
        if finding.get("counts_as_unsupported")
    ]
    required_fact_diagnostics = [
        fact
        for item in completed
        for fact in item.required_fact_diagnostics or []
    ]
    required_fact_classifications = Counter(
        fact.get("classification", "") for fact in required_fact_diagnostics
    )
    required_fact_match_types = Counter(
        fact.get("match_type", "") for fact in required_fact_diagnostics
    )
    checker_false_positives = [
        {
            "question_id": item.case_id,
            "question": item.question,
            **finding,
        }
        for item in completed
        for finding in item.forbidden_fact_checker_false_positives or []
    ]
    report = {
        "evaluation_type": "formal_evaluation",
        "status": "completed",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "dataset": {
            "version": manifest.get("dataset_version"),
            "file": report_path(dataset),
            "sha256_before": before_hash,
            "sha256_after": after_hash,
            "unchanged": before_hash == after_hash,
            "selected_split": args.split,
            "case_count": len(selected),
            "declared_case_count": manifest.get("case_count"),
            "splits": manifest.get("splits"),
        },
        "corpus": corpus,
        "readiness": readiness,
        "ready_for_resume_accuracy_claim": readiness[
            "ready_for_resume_accuracy_claim"
        ],
        "metrics": metrics,
        "retrieval_evaluation": aggregation["retrieval_evaluation"],
        "end_to_end_evaluation": aggregation["end_to_end_evaluation"],
        "by_category": aggregation["by_category"],
        "small_sample_categories": sorted(
            category
            for category, summary in aggregation["by_category"].items()
            if summary.get("case_count", 0) < 3
        ),
        "small_sample_note": SMALL_SAMPLE_NOTE,
        "refusal_by_type": aggregation["refusal_by_type"],
        "failure_analysis": aggregation["failure_analysis"],
        "llm_judge": {
            "enabled": False,
            "results": None,
            "note": "No LLM-as-a-judge was used; all reported E2E metrics are deterministic rules.",
        },
        "required_fact_diagnostics_summary": {
            "exact_match": required_fact_match_types.get("exact_match", 0),
            "semantic_match": required_fact_match_types.get("semantic_match", 0),
            "checker_false_negative": required_fact_classifications.get(
                "checker_false_negative", 0
            ),
            "missing_from_answer": required_fact_classifications.get(
                "missing_from_answer", 0
            ),
            "required_fact_too_broad": required_fact_classifications.get(
                "required_fact_too_broad", 0
            ),
            "required_fact_not_directly_supported_by_gold": required_fact_classifications.get(
                "required_fact_not_directly_supported_by_gold", 0
            ),
            "total_required_facts": len(required_fact_diagnostics),
            "diagnostic_metric_is_official_accuracy": False,
            "diagnostic_method": "offline_deterministic_normalization_synonym_atomic_matching",
        },
        "metric_denominators": metrics.get("metric_denominators", {}),
        "unsupported_claims": unsupported,
        "checker_false_positives": checker_false_positives,
        "details": [
            item.model_dump(mode="json", by_alias=True) for item in case_results
        ],
        "disclaimer": DISCLAIMER,
        "limitations": [
            "gold_chunk_ids来自数据集中的人工预标注；runner不会生成或回写gold。",
            "Retrieval Recall只衡量检索，不能作为最终回答准确率。",
            "Citation Correctness校验本次Evidence内的source/chunk/document/page映射，并按source去重。",
            "required_fact_coverage是确定性规则coverage，不是最终回答准确率。",
            "claim_support_rate只检查规则可识别的引用、技术标识和数值，不是完整Answer Faithfulness。",
            "technical_identifier_accuracy的gold来源为derived from required_facts，不是人工结构化gold field。",
            "multi_hop_evidence_coverage只对至少两个必要gold evidence的多跳题计算，其他题为null。",
            "本轮未启用LLM-as-a-judge。",
        ],
    }
    report = sanitize_trace(report)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
    try:
        persist_evaluation_metadata(report)
    except Exception as exc:
        print(
            "warning: evaluation metadata persistence failed "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "status": "completed",
                "questions": len(selected),
                "ready_for_resume_accuracy_claim": report[
                    "ready_for_resume_accuracy_claim"
                ],
                "output": str(output),
                "markdown_output": str(markdown_output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
