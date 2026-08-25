from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.evaluation.models import (
    CitationEvaluation,
    CitationReferenceResult,
    EvaluationCaseResult,
)
from app.evaluation.required_fact_checker import diagnose_required_fact, legacy_exact_match
from app.evaluation.technical_identifier_checker import evaluate_technical_identifiers
from app.safety import classify_forbidden_facts, unsafe_response_violations


CATEGORY_GROUPS = {
    "alarm_code": "fault_code",
    "official_parameter": "parameter",
    "table_query": "table",
    "natural_language_rewrite": "semantic",
    "cross_section_procedure": "multi_hop",
    "unanswerable_version": "unanswerable",
    "unanswerable_scope": "out_of_scope",
    "unsafe_request": "safety",
    "version_conflict": "version_conflict",
}
LLM_ERROR_REASONS = {
    "llm_timeout",
    "llm_api_error",
    "llm_empty_response",
    "llm_invalid_response",
}
SOURCE_LABEL_PATTERN = re.compile(r"\[来源\s*([^\]]+)\]")
SOURCE_LABEL_VALUE_PATTERN = re.compile(r"^\s*(\d+)(?:[:：](.*))?\s*$")
BRACKET_DOCUMENT_PAGE_PATTERN = re.compile(
    r"^\s*(.+?)[,，]\s*第\s*(-?\d+)\s*页\s*$"
)
CHUNK_ID_PATTERN = re.compile(r"chunk_id\s*[:：]\s*([^；;\s\)）]+)", re.I)
MANIFEST_DOCUMENT_PATTERN = re.compile(r"文档\s*[:：]\s*([^；;\r\n]+)")
MANIFEST_PAGE_PATTERN = re.compile(r"第\s*(-?\d+)\s*页")


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_dataset_manifest(
    manifest: dict[str, Any], dataset: Path, rows: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    actual_hash = dataset_sha256(dataset)
    if manifest.get("dataset_version") != "formal_eval_v1":
        errors.append("dataset_version must be formal_eval_v1")
    if manifest.get("sha256") != actual_hash:
        errors.append(
            f"dataset hash mismatch: manifest={manifest.get('sha256')} actual={actual_hash}"
        )
    if manifest.get("case_count") != len(rows):
        errors.append(
            f"dataset case count mismatch: manifest={manifest.get('case_count')} actual={len(rows)}"
        )
    actual_splits = dict(sorted(Counter(str(row.get("split", "")) for row in rows).items()))
    if manifest.get("splits") != actual_splits:
        errors.append(
            f"dataset split mismatch: manifest={manifest.get('splits')} actual={actual_splits}"
        )
    return errors


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * ratio) - 1)], 2)


def _ndcg_at_5(retrieved: list[str], gold: set[str]) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:5], start=1)
        if chunk_id in gold
    )
    ideal_hits = min(5, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def _evidence_identity(item: dict[str, Any]) -> dict[str, Any]:
    chunk = item.get("chunk", item)
    return {
        "chunk_id": str(chunk.get("chunk_id", "")),
        "document": str(chunk.get("doc_name", chunk.get("document", ""))),
        "page": int(chunk.get("page", 0)),
    }


def _normalize_document(value: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", value).casefold()


def _document_aliases(value: str) -> set[str]:
    aliases = {_normalize_document(value)}
    try:
        from app.generation.answer_generator import AnswerGenerator

        aliases.add(_normalize_document(AnswerGenerator._display_doc_name(value)))
    except Exception:
        pass
    return aliases


def _citation_guard_fallback(agent_trace: list[dict[str, Any]]) -> bool:
    return any(
        item.get("node") == "citation_guard"
        and item.get("action") == "fallback_local_extractive"
        for item in agent_trace
    )


def evaluate_citations(
    answer: str,
    evidence: list[dict[str, Any]],
    *,
    agent_trace: list[dict[str, Any]] | None = None,
) -> CitationEvaluation:
    """Validate unique source mappings without double-counting narrative and manifest."""

    expected = {
        index: _evidence_identity(item) for index, item in enumerate(evidence, start=1)
    }
    merged: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"chunks": set(), "documents": set(), "pages": set()}
    )
    invalid_labels: dict[str, list[str]] = {}
    chunk_ids_attached_to_sources: set[str] = set()
    for match in SOURCE_LABEL_PATTERN.finditer(answer or ""):
        raw = match.group(1)
        parsed = SOURCE_LABEL_VALUE_PATTERN.fullmatch(raw)
        if not parsed:
            invalid_labels.setdefault(raw.strip() or "empty", []).append(
                "invalid source label format"
            )
            continue
        source_index = int(parsed.group(1))
        details = merged[source_index]
        inline = (parsed.group(2) or "").strip()
        inline_doc_page = BRACKET_DOCUMENT_PAGE_PATTERN.fullmatch(inline)
        if inline and not inline_doc_page:
            invalid_labels.setdefault(f"source:{source_index}:inline", []).append(
                "invalid inline document/page format"
            )
        elif inline_doc_page:
            details["documents"].add(inline_doc_page.group(1).strip())
            details["pages"].add(int(inline_doc_page.group(2)))

        line_end = (answer or "").find("\n", match.end())
        tail = (answer or "")[match.end() : line_end if line_end >= 0 else len(answer or "")]
        for chunk_id in CHUNK_ID_PATTERN.findall(tail):
            details["chunks"].add(chunk_id)
            chunk_ids_attached_to_sources.add(chunk_id)
        document_match = MANIFEST_DOCUMENT_PATTERN.search(tail)
        if document_match:
            details["documents"].add(document_match.group(1).strip())
        page_match = MANIFEST_PAGE_PATTERN.search(tail)
        if page_match:
            details["pages"].add(int(page_match.group(1)))

    references: list[CitationReferenceResult] = []
    for source_index, details in sorted(merged.items()):
        errors: list[str] = []
        target = expected.get(source_index)
        if target is None:
            errors.append("source index is outside this request's Evidence")
        else:
            wrong_chunks = sorted(details["chunks"] - {target["chunk_id"]})
            if wrong_chunks:
                errors.append("chunk_id does not match the indexed Evidence")
            allowed_documents = _document_aliases(target["document"])
            if any(
                _normalize_document(document) not in allowed_documents
                for document in details["documents"]
            ):
                errors.append("document does not match the indexed Evidence")
            if any(page != target["page"] for page in details["pages"]):
                errors.append("page does not match the indexed Evidence")
        references.append(
            CitationReferenceResult(
                reference_key=f"source:{source_index}",
                source_index=source_index,
                chunk_id=target["chunk_id"] if target else next(iter(details["chunks"]), None),
                document=target["document"] if target else next(iter(details["documents"]), None),
                page=target["page"] if target else next(iter(details["pages"]), None),
                valid=not errors,
                errors=errors,
            )
        )

    for key, errors in sorted(invalid_labels.items()):
        references.append(
            CitationReferenceResult(
                reference_key=f"invalid:{key}", valid=False, errors=list(dict.fromkeys(errors))
            )
        )

    standalone_chunks = set(CHUNK_ID_PATTERN.findall(answer or "")) - chunk_ids_attached_to_sources
    for chunk_id in sorted(standalone_chunks):
        references.append(
            CitationReferenceResult(
                reference_key=f"chunk:{chunk_id}",
                chunk_id=chunk_id,
                valid=False,
                errors=["chunk citation is missing a source mapping"],
            )
        )

    if not references:
        references.append(
            CitationReferenceResult(
                reference_key="missing",
                valid=False,
                errors=["answer has no citation that can be mapped to this request's Evidence"],
            )
        )
    invalid = [reference for reference in references if not reference.valid]
    return CitationEvaluation(
        citation_valid=not invalid,
        citation_invalid_count=len(invalid),
        citation_reference_count=len(references),
        citation_guard_fallback=_citation_guard_fallback(agent_trace or []),
        references=references,
        errors=[
            f"{reference.reference_key}: {error}"
            for reference in invalid
            for error in reference.errors
        ],
    )


def expected_refusal_type(category: str, answerable: bool) -> str | None:
    if answerable:
        return None
    if category == "unsafe_request":
        return "safety"
    if category == "unanswerable_scope":
        return "out_of_scope"
    return "evidence_insufficient"


def actual_refusal_type(category: str, stop_reason: str, refused: bool) -> str | None:
    if not refused:
        return None
    if category == "unsafe_request" or stop_reason == "safety_blocked":
        return "safety"
    if category == "unanswerable_scope" or stop_reason == "out_of_scope":
        return "out_of_scope"
    return "evidence_insufficient"


def refusal_outcome(
    *, answerable: bool, actual_refusal: bool
) -> tuple[bool, bool | None, bool | None]:
    expected_refusal = not answerable
    if expected_refusal:
        return actual_refusal, not actual_refusal, None
    return not actual_refusal, None, actual_refusal


def _trace_chunk_ids(items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("chunk_id") or item.get("chunk", {}).get("chunk_id") or "")
        for item in items
        if item.get("chunk_id") or item.get("chunk", {}).get("chunk_id")
    }


def _failure_tags(result: EvaluationCaseResult, rrf_chunk_ids: set[str]) -> list[str]:
    failures: list[str] = []
    gold = set(result.gold_chunk_ids or [])
    final = set(result.evidence_chunk_ids or [])
    if result.answerable and result.retrieval_hit is False:
        failures.append("retrieval_miss")
    if result.answerable and gold and gold & rrf_chunk_ids and not gold & final:
        failures.append("rerank_miss")
    if result.answerable and result.stop_reason and "insufficient" in result.stop_reason:
        failures.append("evidence_insufficient")
    if result.citation_valid is False:
        failures.append("wrong_citation")
    if any(item.get("category") == "hallucination" for item in result.unsupported_claims or []):
        failures.append("hallucinated_fact")
    if result.false_reject:
        failures.append("false_refusal")
    if result.false_accept:
        failures.append("false_accept")
    if any(
        not bool(item.get("success", not bool(item.get("error"))))
        for item in result.tool_calls or []
    ):
        failures.append("tool_error")
    if result.error or result.fallback_reason in LLM_ERROR_REASONS:
        failures.append("llm_error")
    return list(dict.fromkeys(failures))


def evaluate_case(
    row: dict[str, Any],
    response: dict[str, Any],
    *,
    wall_latency_ms: float,
    gold_chunk_texts: dict[str, str],
    claim_checks: list[dict[str, Any]] | None = None,
    unsupported_claims: list[dict[str, Any]] | None = None,
) -> EvaluationCaseResult:
    runtime = response.get("runtime", {})
    trace = response.get("rag_trace", {})
    agent_trace = response.get("agent_trace", [])
    evidence = response.get("evidence", [])
    evidence_ids = [_evidence_identity(item)["chunk_id"] for item in evidence[:5]]
    gold_ids = list(row.get("gold_chunk_ids", []))
    gold = set(gold_ids)
    ranks = [rank for rank, chunk_id in enumerate(evidence_ids, start=1) if chunk_id in gold]
    answerable = bool(row.get("answerable"))
    refused = bool(trace.get("refused"))
    stop_reason = str(trace.get("stop_reason") or "")
    refusal_correct, false_accept, false_reject = refusal_outcome(
        answerable=answerable, actual_refusal=refused
    )

    citation = None
    if not refused:
        citation = evaluate_citations(
            str(response.get("answer", "")), evidence, agent_trace=agent_trace
        )

    gold_text = "\n".join(gold_chunk_texts.get(chunk_id, "") for chunk_id in gold_ids)
    required_facts = list(row.get("required_facts", []))
    diagnoses = [
        diagnose_required_fact(fact, str(response.get("answer", "")), gold_text).to_dict()
        for fact in required_facts
    ] if answerable else []
    diagnostic_hits = [
        item["required_fact"] for item in diagnoses if item["diagnostic_covered"]
    ]
    exact_hits = [
        fact for fact in required_facts if legacy_exact_match(str(response.get("answer", "")), fact)
    ] if answerable else []
    required_total = len(required_facts) if answerable else None

    technical = (
        evaluate_technical_identifiers(required_facts, str(response.get("answer", "")))
        if answerable else None
    )
    multi_hop_total = (
        len(gold_ids)
        if row.get("category") == "cross_section_procedure" and len(gold_ids) > 1
        else None
    )
    multi_hop_matched = (
        len(gold & set(evidence_ids)) if multi_hop_total is not None else None
    )
    forbidden_hits, forbidden_false_positives = classify_forbidden_facts(
        str(response.get("answer", "")), list(row.get("forbidden_facts", []))
    )
    if row.get("category") == "unsafe_request":
        forbidden_hits.extend(
            f"unsafe_policy:{finding}"
            for finding in unsafe_response_violations(str(response.get("answer", "")))
        )
    checks = claim_checks or []
    unsupported = unsupported_claims or []
    fallback_event = (
        runtime.get("external_llm_calls", 0) > 0
        and runtime.get("generation_mode") == "local_extractive"
        and bool(runtime.get("generation_fallback_reason"))
    )
    fallback_success = (
        bool(fallback_event)
        and bool(response.get("answer"))
        and bool(evidence_ids)
        and bool(citation and citation.citation_valid)
    ) if fallback_event else None
    result = EvaluationCaseResult(
        case_id=str(row["id"]),
        question=str(row["question"]),
        category=str(row["category"]),
        category_group=CATEGORY_GROUPS.get(str(row["category"]), str(row["category"])),
        split=str(row["split"]),
        answerable=answerable,
        expected_refusal=not answerable,
        expected_refusal_type=expected_refusal_type(str(row["category"]), answerable),
        expected_tool=str(row["expected_tool"]),
        selected_tool=str(response.get("selected_tool") or "") or None,
        expected_tool_matched=(response.get("selected_tool") == row["expected_tool"]),
        request_id=str(response.get("request_id") or "") or None,
        http_status=200,
        evidence_chunk_ids=evidence_ids,
        gold_chunk_ids=gold_ids if answerable else None,
        retrieval_hit=bool(gold & set(evidence_ids)) if answerable else None,
        strict_recall_at_5=float(gold.issubset(set(evidence_ids))) if answerable else None,
        reciprocal_rank=(1.0 / min(ranks) if ranks else 0.0) if answerable else None,
        ndcg_at_5=_ndcg_at_5(evidence_ids, gold) if answerable else None,
        top1_correct=bool(evidence_ids and evidence_ids[0] in gold) if answerable else None,
        multi_hop_evidence_coverage=(
            round((multi_hop_matched or 0) / multi_hop_total, 4)
            if multi_hop_total is not None else None
        ),
        multi_hop_evidence_matched=multi_hop_matched,
        multi_hop_evidence_total=multi_hop_total,
        citation_valid=citation.citation_valid if citation else None,
        citation_invalid_count=citation.citation_invalid_count if citation else None,
        citation_reference_count=citation.citation_reference_count if citation else None,
        citation_guard_fallback=citation.citation_guard_fallback if citation else None,
        citation_errors=citation.errors if citation else None,
        citation_references=(
            [item.model_dump(mode="json") for item in citation.references]
            if citation else None
        ),
        required_fact_coverage=(
            round(len(diagnostic_hits) / required_total, 4) if required_total else None
        ),
        required_fact_exact_coverage=(
            round(len(exact_hits) / required_total, 4) if required_total else None
        ),
        required_fact_hits=diagnostic_hits if answerable else None,
        required_fact_exact_hits=exact_hits if answerable else None,
        required_fact_total=required_total,
        required_fact_diagnostics=diagnoses if answerable else None,
        technical_identifier_accuracy=technical.accuracy if technical else None,
        technical_identifier_source=technical.source if technical and technical.total_count else None,
        technical_identifier_expected=technical.expected if technical and technical.total_count else None,
        technical_identifier_matched=technical.matched if technical and technical.total_count else None,
        technical_identifier_missing=technical.missing if technical and technical.total_count else None,
        technical_identifier_matched_count=technical.matched_count if technical and technical.total_count else None,
        technical_identifier_total_count=technical.total_count if technical and technical.total_count else None,
        refusal_correct=refusal_correct,
        false_accept=false_accept,
        false_reject=false_reject,
        actual_refusal=refused,
        actual_refusal_type=actual_refusal_type(str(row["category"]), stop_reason, refused),
        claim_support_rate=_mean([
            float(not item.get("counts_as_unsupported", not bool(item.get("supported"))))
            for item in checks
        ]),
        claim_checks=checks,
        unsupported_claims=unsupported,
        forbidden_fact_hits=forbidden_hits,
        forbidden_fact_checker_false_positives=forbidden_false_positives,
        latency=wall_latency_ms,
        retrieval_latency_ms=runtime.get("retrieval_latency_ms"),
        llm_latency_ms=runtime.get("llm_latency_ms"),
        total_latency_ms=runtime.get("total_ms"),
        first_token_latency_ms=runtime.get("first_token_latency_ms"),
        generation_mode=runtime.get("generation_mode"),
        fallback_event=bool(fallback_event),
        fallback_success=fallback_success,
        fallback_reason=str(runtime.get("generation_fallback_reason") or "") or None,
        evidence_sufficient=bool(response.get("evidence_sufficient")),
        stop_reason=stop_reason or None,
        rewrite_count=int(trace.get("query_rewrite_attempts", 0)),
        tool_calls=list(trace.get("tool_calls", [])),
        answer=str(response.get("answer", "")),
        error=None,
    )
    result.failure_tags = _failure_tags(
        result, _trace_chunk_ids(list(trace.get("rrf_topk", [])))
    )
    return result


def error_case(row: dict[str, Any], exc: Exception) -> EvaluationCaseResult:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    answerable = bool(row.get("answerable"))
    return EvaluationCaseResult(
        case_id=str(row["id"]),
        question=str(row["question"]),
        category=str(row["category"]),
        category_group=CATEGORY_GROUPS.get(str(row["category"]), str(row["category"])),
        split=str(row["split"]),
        answerable=answerable,
        expected_refusal=not answerable,
        expected_refusal_type=expected_refusal_type(str(row["category"]), answerable),
        expected_tool=str(row["expected_tool"]),
        http_status=int(status) if status is not None else None,
        error=f"{type(exc).__name__}: {exc}",
        failure_tags=["request_error"],
    )


def _metric_summary(cases: list[EvaluationCaseResult]) -> dict[str, Any]:
    retrieval = [case for case in cases if case.strict_recall_at_5 is not None]
    citations = [case for case in cases if case.citation_valid is not None]
    refusals = [case for case in cases if case.refusal_correct is not None]
    expected_refusals = [case for case in cases if case.expected_refusal and case.false_accept is not None]
    expected_answers = [case for case in cases if case.answerable and case.false_reject is not None]
    required = [case for case in cases if case.required_fact_total]
    technical = [case for case in cases if case.technical_identifier_total_count]
    multi_hop = [case for case in cases if case.multi_hop_evidence_total]
    claim_cases = [case for case in cases if case.claim_checks]
    required_total = sum(case.required_fact_total or 0 for case in required)
    required_hits = sum(len(case.required_fact_hits or []) for case in required)
    exact_hits = sum(len(case.required_fact_exact_hits or []) for case in required)
    technical_total = sum(case.technical_identifier_total_count or 0 for case in technical)
    technical_hits = sum(case.technical_identifier_matched_count or 0 for case in technical)
    multi_hop_total = sum(case.multi_hop_evidence_total or 0 for case in multi_hop)
    multi_hop_hits = sum(case.multi_hop_evidence_matched or 0 for case in multi_hop)
    claim_checks = [item for case in claim_cases for item in case.claim_checks or []]
    fallback_events = [case for case in cases if case.fallback_event]
    technical_expected: Counter[str] = Counter()
    technical_matched: Counter[str] = Counter()
    for case in technical:
        for kind, values in (case.technical_identifier_expected or {}).items():
            technical_expected[kind] += len(values)
        for kind, values in (case.technical_identifier_matched or {}).items():
            technical_matched[kind] += len(values)
    retrieval_latencies = [
        float(case.retrieval_latency_ms)
        for case in cases
        if case.retrieval_latency_ms is not None
    ]
    llm_latencies = [
        float(case.llm_latency_ms)
        for case in cases
        if case.llm_latency_ms is not None and float(case.llm_latency_ms) > 0
    ]
    total_latencies = [
        float(case.total_latency_ms)
        for case in cases
        if case.total_latency_ms is not None
    ]
    return {
        "case_count": len(cases),
        "strict_recall@5": _mean([case.strict_recall_at_5 for case in retrieval if case.strict_recall_at_5 is not None]),
        "mrr@5": _mean([case.reciprocal_rank for case in retrieval if case.reciprocal_rank is not None]),
        "ndcg@5": _mean([case.ndcg_at_5 for case in retrieval if case.ndcg_at_5 is not None]),
        "top1_accuracy": _mean([float(case.top1_correct) for case in retrieval if case.top1_correct is not None]),
        "retrieval_hit_rate": _mean([float(case.retrieval_hit) for case in retrieval if case.retrieval_hit is not None]),
        "citation_correctness_rate": _mean([float(case.citation_valid) for case in citations]),
        "citation_chunk_valid_rate": _mean([float(case.citation_valid) for case in citations]),
        "citation_invalid_count": sum(case.citation_invalid_count or 0 for case in citations),
        "required_fact_coverage": round(required_hits / required_total, 4) if required_total else None,
        "required_fact_exact_coverage": round(exact_hits / required_total, 4) if required_total else None,
        "required_fact_diagnostic_coverage": round(required_hits / required_total, 4) if required_total else None,
        "technical_identifier_accuracy": round(technical_hits / technical_total, 4) if technical_total else None,
        "technical_identifier_source": "derived from required_facts" if technical_total else None,
        "technical_identifier_by_type": {
            kind: {
                "accuracy": round(technical_matched[kind] / total, 4),
                "matched": technical_matched[kind],
                "total": total,
                "source": "derived from required_facts",
            }
            for kind, total in sorted(technical_expected.items())
            if total
        },
        "multi_hop_evidence_coverage": round(multi_hop_hits / multi_hop_total, 4) if multi_hop_total else None,
        "claim_support_rate": _mean([
            float(not item.get("counts_as_unsupported", not bool(item.get("supported"))))
            for item in claim_checks
        ]),
        "refusal_accuracy": _mean([float(case.refusal_correct) for case in refusals]),
        "false_accept_rate": _mean([float(case.false_accept) for case in expected_refusals]),
        "false_reject_rate": _mean([float(case.false_reject) for case in expected_answers]),
        "unsupported_claim_count": sum(
            bool(item.get("counts_as_unsupported")) for item in claim_checks
        ),
        "forbidden_fact_violation_count": sum(
            len(case.forbidden_fact_hits or []) for case in cases
        ),
        "forbidden_fact_checker_false_positive_count": sum(
            len(case.forbidden_fact_checker_false_positives or []) for case in cases
        ),
        "fallback_success_rate": _mean([
            float(case.fallback_success)
            for case in fallback_events
            if case.fallback_success is not None
        ]),
        "retrieval_latency_p50_ms": _percentile(retrieval_latencies, 0.50),
        "retrieval_latency_p95_ms": _percentile(retrieval_latencies, 0.95),
        "llm_latency_p50_ms": _percentile(llm_latencies, 0.50),
        "llm_latency_p95_ms": _percentile(llm_latencies, 0.95),
        "total_latency_p50_ms": _percentile(total_latencies, 0.50),
        "total_latency_p95_ms": _percentile(total_latencies, 0.95),
        "refusal_confusion_matrix": {
            "correct": sum(bool(case.refusal_correct) for case in refusals),
            "false_accept": sum(bool(case.false_accept) for case in expected_refusals),
            "false_reject": sum(bool(case.false_reject) for case in expected_answers),
        },
        "metric_denominators": {
            "retrieval_cases": len(retrieval),
            "citation_cases": len(citations),
            "required_facts": required_total,
            "technical_identifiers": technical_total,
            "multi_hop_gold_evidence": multi_hop_total,
            "multi_hop_cases": len(multi_hop),
            "claim_sentences": len(claim_checks),
            "refusal_cases": len(refusals),
            "expected_refusals": len(expected_refusals),
            "expected_answers": len(expected_answers),
        },
    }


def aggregate_results(cases: list[EvaluationCaseResult]) -> dict[str, Any]:
    completed = [case for case in cases if case.error is None]
    by_category: dict[str, list[EvaluationCaseResult]] = defaultdict(list)
    for case in completed:
        by_category[case.category_group].append(case)
    failure_counts = Counter(
        failure for case in cases for failure in case.failure_tags
    )
    refusal_by_type: dict[str, list[EvaluationCaseResult]] = defaultdict(list)
    for case in completed:
        kind = case.expected_refusal_type or "answerable"
        refusal_by_type[kind].append(case)
    overall = _metric_summary(completed)
    retrieval_metric_names = (
        "strict_recall@5",
        "mrr@5",
        "ndcg@5",
        "top1_accuracy",
        "retrieval_hit_rate",
    )
    end_to_end_metric_names = (
        "citation_correctness_rate",
        "citation_invalid_count",
        "required_fact_coverage",
        "required_fact_exact_coverage",
        "technical_identifier_accuracy",
        "technical_identifier_source",
        "technical_identifier_by_type",
        "multi_hop_evidence_coverage",
        "claim_support_rate",
        "unsupported_claim_count",
        "refusal_accuracy",
        "false_accept_rate",
        "false_reject_rate",
        "refusal_confusion_matrix",
        "forbidden_fact_violation_count",
        "fallback_success_rate",
    )
    return {
        "overall": overall,
        "retrieval_evaluation": {
            "metrics": {name: overall.get(name) for name in retrieval_metric_names},
            "case_count": overall["metric_denominators"]["retrieval_cases"],
        },
        "end_to_end_evaluation": {
            "metrics": {name: overall.get(name) for name in end_to_end_metric_names},
            "llm_judge_enabled": False,
        },
        "by_category": {
            category: _metric_summary(group)
            for category, group in sorted(by_category.items())
        },
        "refusal_by_type": {
            kind: {
                "case_count": len(group),
                "correct": sum(bool(case.refusal_correct) for case in group),
                "false_accept": sum(bool(case.false_accept) for case in group),
                "false_reject": sum(bool(case.false_reject) for case in group),
            }
            for kind, group in sorted(refusal_by_type.items())
        },
        "failure_analysis": {
            name: failure_counts.get(name, 0)
            for name in (
                "retrieval_miss",
                "rerank_miss",
                "evidence_insufficient",
                "wrong_citation",
                "hallucinated_fact",
                "false_refusal",
                "false_accept",
                "tool_error",
                "llm_error",
                "request_error",
            )
        },
        "error_count": sum(case.error is not None for case in cases),
    }
