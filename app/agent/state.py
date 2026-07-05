from __future__ import annotations

from typing import Any, TypedDict

from app.models import SearchHit


class AgentState(TypedDict, total=False):
    question: str
    original_question: str
    model: str
    version: str
    session_id: str
    rewritten_query: str
    evidence: list[SearchHit]
    selected_tool: str
    tool_result: str
    answer: str
    evidence_sufficient: bool
    retry_count: int
    route_reason: str
    knowledge_graph: dict[str, Any]
    agent_trace: list[dict[str, Any]]
    verified_solution_used: bool
    verified_source_chunk_ids: list[str]
    refusal_reason: str
    refusal_kind: str
    citation_warnings: list[str]
    query_expansion_terms: list[str]
    generation_usage: dict[str, Any]
    retrieval_trace: dict[str, Any]
    intent: dict[str, Any]
    plan: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    round_count: int
    budget: dict[str, Any]
    stop_reason: str
    evidence_assessments: list[dict[str, Any]]
    agentic_enabled: bool


def agentic_state_defaults(*, enabled: bool = False) -> AgentState:
    """Return fresh stage-1 Agentic fields without changing graph behavior."""
    return {
        "intent": {},
        "plan": [],
        "tool_calls": [],
        "round_count": 0,
        "budget": {},
        "stop_reason": "",
        "evidence_assessments": [],
        "agentic_enabled": enabled,
    }
