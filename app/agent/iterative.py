from __future__ import annotations

import re
import time
from typing import Any

from app.agent.evidence_terms import (
    filter_retry_identifiers,
    generic_terms_in_text,
    normalize_technical_terms,
)
from app.models import SearchHit
from app.retrieval.query_expansion import technical_terms


POLICY_INTENTS = frozenset({"safety_risk", "out_of_scope"})
NON_RETRY_REASONS = frozenset({"out_of_scope", "version_conflict", "safety"})
EXPLICIT_REPAIRABLE_REASONS = frozenset({"missing_subtopic"})


def _config(config: Any, name: str, default: Any) -> Any:
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def _tool_calls_used(state: dict[str, Any]) -> int:
    return sum(
        bool(item.get("executed", True)) for item in state.get("tool_calls", [])
    )


def assess_evidence(
    query: str,
    evidence: list[SearchHit],
    *,
    round_count: int,
    intent: str = "",
    identifiers_supported: bool | None = None,
    apply_retry_filter: bool = True,
) -> dict[str, Any]:
    """Wrap the existing gate conditions in an auditable assessment."""
    top_score = (
        float(evidence[0].rerank_score or evidence[0].score) if evidence else 0.0
    )
    query_terms = technical_terms(query)
    evidence_terms = (
        set().union(*(technical_terms(hit.chunk.text) for hit in evidence))
        if evidence
        else set()
    )
    query_candidates = {
        *normalize_technical_terms(list(query_terms)),
        *generic_terms_in_text(query),
    }
    evidence_candidates: set[str] = set()
    for hit in evidence:
        evidence_candidates.update(
            normalize_technical_terms(list(technical_terms(hit.chunk.text)))
        )
        evidence_candidates.update(generic_terms_in_text(hit.chunk.text))
    evidence_candidate_keys = {term.casefold() for term in evidence_candidates}
    raw_missing_terms = normalize_technical_terms(
        sorted(
            term
            for term in query_candidates
            if term.casefold() not in evidence_candidate_keys
        )
    )
    filtered_missing_terms = filter_retry_identifiers(raw_missing_terms)
    filtered_keys = {term.casefold() for term in filtered_missing_terms}
    generic_terms_ignored = [
        term for term in raw_missing_terms if term.casefold() not in filtered_keys
    ]
    if identifiers_supported is None:
        legacy_query_terms = query_terms - {"1200", "1500"}
        identifiers_supported = (
            True
            if not legacy_query_terms
            else len(legacy_query_terms & evidence_terms) / len(legacy_query_terms)
            >= 0.75
        )

    sufficient_before_filter = bool(evidence) and top_score > 0.01 and bool(
        identifiers_supported
    )
    generic_only_gap = bool(raw_missing_terms) and not filtered_missing_terms
    effective_identifiers_supported = bool(identifiers_supported)
    if apply_retry_filter and generic_only_gap:
        effective_identifiers_supported = True

    if intent == "safety_risk":
        reason = "safety"
        sufficient = False
    elif intent == "out_of_scope":
        reason = "out_of_scope"
        sufficient = False
    elif not evidence:
        reason = "no_evidence"
        sufficient = False
    elif not effective_identifiers_supported:
        reason = "missing_identifier"
        sufficient = False
    elif top_score <= 0.01:
        reason = "low_relevance"
        sufficient = False
    else:
        reason = "sufficient"
        sufficient = True

    retry_eligible = bool(
        not sufficient
        and filtered_missing_terms
        and reason not in NON_RETRY_REASONS
    )
    if sufficient:
        next_action = "generate"
    elif retry_eligible:
        next_action = "rewrite_and_retry"
    else:
        next_action = "refuse"

    retry_would_trigger_before_filter = bool(
        not sufficient_before_filter
        and reason not in NON_RETRY_REASONS
        and (raw_missing_terms or reason in {"no_evidence", "low_relevance"})
    )
    retry_blocked_by_generic_terms = bool(
        retry_would_trigger_before_filter
        and generic_only_gap
        and not retry_eligible
    )

    return {
        "round": round_count,
        "sufficient": sufficient,
        "reason": reason,
        "score": round(top_score, 8),
        "evidence_count": len(evidence),
        "missing_terms": filtered_missing_terms,
        "raw_missing_terms": raw_missing_terms,
        "filtered_missing_terms": filtered_missing_terms,
        "generic_terms_ignored": generic_terms_ignored,
        "identifiers_supported": effective_identifiers_supported,
        "identifiers_supported_before_filter": bool(identifiers_supported),
        "sufficient_before_filter": sufficient_before_filter,
        "retry_eligible": retry_eligible,
        "retry_would_trigger_before_filter": retry_would_trigger_before_filter,
        "retry_blocked_by_generic_terms": retry_blocked_by_generic_terms,
        "recommended_next_action": next_action,
    }


def budget_snapshot(
    state: dict[str, Any],
    config: Any,
    *,
    now: float | None = None,
    llm_calls_used: int | None = None,
) -> dict[str, Any]:
    current = time.monotonic() if now is None else now
    started = float(state.get("agent_started_at", current))
    return {
        "max_rounds": int(_config(config, "max_agent_rounds", 2)),
        "max_tool_calls": int(_config(config, "max_tool_calls", 4)),
        "max_llm_calls": int(_config(config, "max_llm_calls", 2)),
        "timeout_seconds": float(_config(config, "agent_timeout_seconds", 60.0)),
        "max_rewrites": int(_config(config, "max_rewrites", 1)),
        "rounds_used": int(state.get("round_count", 0)),
        "tool_calls_used": _tool_calls_used(state),
        "llm_calls_used": int(
            state.get("budget", {}).get("llm_calls_used", 0)
            if llm_calls_used is None
            else llm_calls_used
        ),
        "rewrites_used": int(state.get("retry_count", 0)),
        "elapsed_ms": round(max(0.0, current - started) * 1000, 2),
    }


def should_retry_retrieval(
    state: dict[str, Any],
    assessment: dict[str, Any],
    config: Any,
    *,
    now: float | None = None,
) -> bool:
    if not bool(_config(config, "enable_iterative_retrieval", False)):
        return False
    if assessment.get("sufficient"):
        return False
    if assessment.get("recommended_next_action") != "rewrite_and_retry":
        return False
    if assessment.get("generic_terms_ignored") and not assessment.get(
        "filtered_missing_terms"
    ):
        return False
    if not assessment.get("retry_eligible", False) and assessment.get(
        "reason"
    ) not in EXPLICIT_REPAIRABLE_REASONS:
        return False
    if assessment.get("reason") in NON_RETRY_REASONS:
        return False
    intent = state.get("intent", {})
    intent_name = intent.get("intent", "") if isinstance(intent, dict) else str(intent)
    if intent_name in POLICY_INTENTS or state.get("refusal_reason"):
        return False
    if int(state.get("round_count", 0)) >= int(
        _config(config, "max_agent_rounds", 2)
    ):
        return False
    if int(state.get("retry_count", 0)) >= int(
        _config(config, "max_rewrites", 1)
    ):
        return False
    if _tool_calls_used(state) >= int(
        _config(config, "max_tool_calls", 4)
    ):
        return False
    current = time.monotonic() if now is None else now
    started = float(state.get("agent_started_at", current))
    if current - started >= float(_config(config, "agent_timeout_seconds", 60.0)):
        return False
    return True


def retry_stop_reason(
    state: dict[str, Any],
    config: Any,
    *,
    assessment: dict[str, Any] | None = None,
    now: float | None = None,
) -> str:
    intent = state.get("intent", {})
    intent_name = intent.get("intent", "") if isinstance(intent, dict) else str(intent)
    if intent_name == "safety_risk" or state.get("refusal_kind") == "unsafe_request":
        return "safety_blocked"
    if intent_name == "out_of_scope" or state.get("refusal_kind") == "unanswerable_scope":
        return "out_of_scope"
    if assessment and assessment.get("generic_terms_ignored") and not assessment.get(
        "filtered_missing_terms"
    ):
        return "generic_terms_only"
    current = time.monotonic() if now is None else now
    started = float(state.get("agent_started_at", current))
    if current - started >= float(_config(config, "agent_timeout_seconds", 60.0)):
        return "timeout_reached"
    if int(state.get("round_count", 0)) >= int(
        _config(config, "max_agent_rounds", 2)
    ):
        return "max_rounds_reached"
    if int(state.get("retry_count", 0)) >= int(
        _config(config, "max_rewrites", 1)
    ):
        return "max_rewrites_reached"
    if _tool_calls_used(state) >= int(
        _config(config, "max_tool_calls", 4)
    ):
        return "max_tool_calls_reached"
    return "insufficient_evidence"


def build_retry_query(
    original_query: str,
    state: dict[str, Any],
    assessment: dict[str, Any],
) -> str:
    query = re.sub(r"(请问|麻烦|一下|应该如何|怎么办)", " ", original_query)
    context = [
        state.get("model", ""),
        state.get("version", ""),
        *assessment.get("filtered_missing_terms", assessment.get("missing_terms", [])),
        "故障诊断",
        "参数",
        "手册",
    ]
    values = (
        value.strip()
        for value in [query.strip(), *context]
        if value and value.strip()
    )
    return " ".join(dict.fromkeys(values))


def merge_evidence_rounds(
    old_evidence: list[SearchHit],
    new_evidence: list[SearchHit],
    *,
    limit: int = 5,
) -> list[SearchHit]:
    """Deduplicate by chunk_id and rank only by scores already produced by retrieval."""
    by_id: dict[str, SearchHit] = {}
    for hit in [*old_evidence, *new_evidence]:
        chunk_id = hit.chunk.chunk_id
        current = by_id.get(chunk_id)
        hit_score = float(hit.rerank_score or hit.score)
        current_score = float(current.rerank_score or current.score) if current else -1.0
        if current is None or hit_score > current_score:
            by_id[chunk_id] = hit
    ordered = sorted(
        by_id.values(),
        key=lambda hit: float(hit.rerank_score or hit.score),
        reverse=True,
    )
    return ordered[: max(1, int(limit))]
