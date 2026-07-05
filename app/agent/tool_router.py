from __future__ import annotations

from app.agent.intent import IntentName


TOOL_WHITELIST = frozenset(
    {
        "lookup_fault_code",
        "lookup_parameter",
        "lookup_table_rows",
        "search_manual",
        "lookup_verified_solution",
    }
)


TOOL_CANDIDATES: dict[IntentName, tuple[str, ...]] = {
    "alarm_diagnosis": (
        "lookup_fault_code",
        "search_manual",
        "lookup_verified_solution",
    ),
    "parameter_lookup": (
        "lookup_parameter",
        "search_manual",
        "lookup_verified_solution",
    ),
    "table_lookup": ("lookup_table_rows", "search_manual"),
    "cross_section_procedure": ("search_manual", "lookup_verified_solution"),
    "version_resolution": ("search_manual",),
    "general_manual_search": ("search_manual", "lookup_verified_solution"),
    "safety_risk": (),
    "out_of_scope": (),
}


def candidate_tools(intent: IntentName) -> list[str]:
    """Return a fresh, allowlisted candidate sequence without executing tools."""
    return list(TOOL_CANDIDATES.get(intent, ("search_manual",)))
