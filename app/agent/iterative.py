from __future__ import annotations

import re
import time
from typing import Any

from app.models import SearchHit
from app.retrieval.query_expansion import technical_terms


POLICY_INTENTS = frozenset({"safety_risk", "out_of_scope"})


def _config(config: Any, name: str, default: Any) -> Any:
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def assess_evidence(
    query: str,
    evidence: list[SearchHit],
    *,
    round_count: int,
    intent: str = "",
    identifiers_supported: bool | None = None,
) -> dict[str, Any]:
    """Wrap the existing gate conditions in an auditable assessment."""
    top_score = (
        float(evidence[0].rerank_score or evidence[0].score) if evidence else 0.0
    )
    query_terms = technical_terms(query) - {"1200", "1500"}
    evidence_terms = (
        set().union(*(technical_terms(hit.chunk.text) for hit in evidence))
        if evidence
        else set()
    )
    missing_terms = sorted(query_terms - evidence_terms)
    if identifiers_supported is None:
        identifiers_supported = (
            True
            if not query_terms
            else len(query_terms & evidence_terms) / len(query_terms) >= 0.75
        )

    if intent == "out_of_scope":
        reason = "out_of_scope"
        sufficient = False
        next_action = "refuse"
    elif not evidence:
        reason = "no_evidence"
        sufficient = False
        next_action = "rewrite_and_retry"
    elif not identifiers_supported:
        reason = "missing_identifier"
        sufficient = False
        next_action = "rewrite_and_retry"
    elif top_score <= 0.01:
        reason = "low_relevance"
        sufficient = False
        next_action = "rewrite_and_retry"
    else:
        reason = "sufficient"
        sufficient = True
        next_action = "generate"

    return {
        "round": round_count,
        "sufficient": sufficient,
        "reason": reason,
        "score": round(top_score, 8),
        "evidence_count": len(evidence),
        "missing_terms": missing_terms,
        "identifiers_supported": identifiers_supported,
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
        "tool_calls_used": len(state.get("tool_calls", [])),
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
    if len(state.get("tool_calls", [])) >= int(
        _config(config, "max_tool_calls", 4)
    ):
        return False
    current = time.monotonic() if now is None else now
    started = float(state.get("agent_started_at", current))
    if current - started >= float(_config(config, "agent_timeout_seconds", 60.0)):
        return False
    return True


def retry_stop_reason(
    state: dict[str, Any], config: Any, *, now: float | None = None
) -> str:
    intent = state.get("intent", {})
    intent_name = intent.get("intent", "") if isinstance(intent, dict) else str(intent)
    if intent_name == "safety_risk" or state.get("refusal_kind") == "unsafe_request":
        return "safety_blocked"
    if intent_name == "out_of_scope" or state.get("refusal_kind") == "unanswerable_scope":
        return "out_of_scope"
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
    if len(state.get("tool_calls", [])) >= int(
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
        *assessment.get("missing_terms", []),
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
