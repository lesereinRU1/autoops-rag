from __future__ import annotations

from typing import Any

from app.agent.intent import IntentName
from app.agent.tool_router import TOOL_WHITELIST


PLAN_TEMPLATES: dict[IntentName, tuple[tuple[str, str], ...]] = {
    "alarm_diagnosis": (
        ("lookup_fault_code", "查询结构化故障码记录"),
        ("search_manual", "检索官方手册证据"),
    ),
    "parameter_lookup": (
        ("lookup_parameter", "查询结构化参数记录"),
        ("search_manual", "检索官方手册证据"),
    ),
    "table_lookup": (
        ("lookup_table_rows", "查询结构化表格行记录"),
        ("search_manual", "检索官方手册证据"),
    ),
    "cross_section_procedure": (("search_manual", "检索跨章节流程证据"),),
    "version_resolution": (("search_manual", "检索匹配版本的手册证据"),),
    "general_manual_search": (("search_manual", "检索相关手册证据"),),
    "safety_risk": (),
    "out_of_scope": (),
}
POLICY_INTENTS = frozenset({"safety_risk", "out_of_scope"})


def _non_negative_int(value: int, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class BoundedQueryPlanner:
    """Build deterministic shadow plans from allowlisted intent templates."""

    MAX_STEPS = 3

    def __init__(self, *, max_agent_rounds: int = 2, max_tool_calls: int = 4) -> None:
        self.max_agent_rounds = _non_negative_int(max_agent_rounds, 2)
        self.max_tool_calls = _non_negative_int(max_tool_calls, 4)

    def build_plan(
        self,
        *,
        query: str,
        intent: IntentName,
        candidate_tools: list[str],
    ) -> dict[str, Any]:
        del query  # Reserved for later evidence-aware planning; no free-form generation here.
        policy_blocked = intent in POLICY_INTENTS
        candidates = {
            tool for tool in candidate_tools if tool in TOOL_WHITELIST
        }
        template = PLAN_TEMPLATES.get(intent, ())
        step_limit = min(self.MAX_STEPS, self.max_tool_calls)
        selected = [
            (tool, purpose)
            for tool, purpose in template
            if tool in candidates and tool in TOOL_WHITELIST
        ][:step_limit]
        steps = [
            {
                "step_id": index,
                "action": tool,
                "tool": tool,
                "purpose": purpose,
            }
            for index, (tool, purpose) in enumerate(selected, start=1)
        ]
        return {
            "intent": intent,
            "steps": steps,
            "allow_generation": not policy_blocked,
            "need_evidence_gate": not policy_blocked,
            "max_rounds": (
                0 if policy_blocked else min(1, self.max_agent_rounds)
            ),
            "max_tool_calls": len(steps),
            "routing_mode": "shadow",
            "applied": False,
        }
