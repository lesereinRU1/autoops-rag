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
    refusal_reason: str
    refusal_kind: str
    query_expansion_terms: list[str]
    generation_usage: dict[str, Any]
    retrieval_trace: dict[str, Any]
