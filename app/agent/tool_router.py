from __future__ import annotations

from app.agent.intent import IntentName


TOOL_CANDIDATES: dict[IntentName, tuple[str, ...]] = {
    "alarm_diagnosis": ("lookup_fault_code", "search_manual"),
    "parameter_lookup": ("lookup_parameter", "search_manual"),
    "table_lookup": ("search_manual", "get_document_page"),
    "cross_section_procedure": ("search_manual", "get_document_page"),
    "version_resolution": ("search_manual", "get_document_page"),
    "general_manual_search": ("search_manual", "get_document_page"),
    "safety_risk": (),
    "out_of_scope": (),
}


def candidate_tools(
    intent: IntentName,
    *,
    registered_tools: tuple[str, ...] | list[str] | set[str] | None = None,
) -> list[str]:
    """Return intent candidates filtered by the current Registry when supplied."""
    candidates = TOOL_CANDIDATES.get(intent, ("search_manual",))
    if registered_tools is None:
        return list(candidates)
    available = set(registered_tools)
    return [name for name in candidates if name in available]


def should_execute_planner(
    intent: IntentName,
    *,
    fixed_tool: str,
    has_policy_refusal: bool,
) -> bool:
    """Keep stable rules first and opt in only ambiguous evidence workflows."""
    if has_policy_refusal or intent in {"safety_risk", "out_of_scope"}:
        return False
    if fixed_tool in {"lookup_fault_code", "lookup_parameter"}:
        return False
    return intent in {
        "table_lookup",
        "cross_section_procedure",
        "version_resolution",
    }
