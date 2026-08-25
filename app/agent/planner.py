from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.intent import IntentName


POLICY_INTENTS = frozenset({"safety_risk", "out_of_scope"})
ALARM_PATTERN = re.compile(r"(?:16#|0x)?([0-9A-Fa-f]{4})", re.I)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)
    expected_evidence: str = Field(min_length=1, max_length=200)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: IntentName
    steps: list[PlanStep] = Field(default_factory=list)
    allow_generation: bool
    need_evidence_gate: bool
    max_rounds: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_linear_bounds(self) -> "Plan":
        expected_ids = list(range(1, len(self.steps) + 1))
        if [step.step_id for step in self.steps] != expected_ids:
            raise ValueError("plan step_id values must be sequential")
        if len(self.steps) > self.max_tool_calls:
            raise ValueError("plan steps exceed max_tool_calls")
        return self


def _non_negative_int(value: int, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class BoundedQueryPlanner:
    """Build deterministic, schema-validated plans without calling an LLM."""

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
        model: str = "S7-1200",
        version: str = "",
        known_document_pages: list[dict[str, Any]] | None = None,
    ) -> Plan:
        policy_blocked = intent in POLICY_INTENTS
        candidates = set(candidate_tools)
        step_limit = min(self.MAX_STEPS, self.max_tool_calls)
        steps: list[PlanStep] = []

        def add_step(
            tool_name: str,
            arguments: dict[str, Any],
            reason: str,
            expected_evidence: str,
        ) -> None:
            if tool_name not in candidates or len(steps) >= step_limit:
                return
            steps.append(
                PlanStep(
                    step_id=len(steps) + 1,
                    tool_name=tool_name,
                    arguments=arguments,
                    reason=reason,
                    expected_evidence=expected_evidence,
                )
            )

        if not policy_blocked and intent == "alarm_diagnosis":
            match = ALARM_PATTERN.search(query)
            add_step(
                "lookup_fault_code",
                {
                    "code": match.group(1) if match else query,
                    "model": model,
                    "version": version,
                },
                "先查询结构化故障码线索",
                "structured_hint",
            )
        elif not policy_blocked and intent == "parameter_lookup":
            add_step(
                "lookup_parameter",
                {"name": query, "model": model, "version": version},
                "先查询结构化参数线索",
                "structured_hint",
            )

        if not policy_blocked:
            reason = {
                "table_lookup": "检索表格相关的官方手册证据",
                "cross_section_procedure": "检索跨章节流程的官方手册证据",
                "version_resolution": "检索匹配版本的官方手册证据",
            }.get(intent, "检索相关官方手册证据")
            add_step(
                "search_manual",
                {"query": query, "model": model, "version": version, "top_k": 5},
                reason,
                "manual_evidence",
            )

        for reference in known_document_pages or []:
            if len(steps) >= step_limit or "get_document_page" not in candidates:
                break
            arguments = {
                key: reference[key]
                for key in ("document_id", "document_name", "page")
                if reference.get(key) is not None
            }
            add_step(
                "get_document_page",
                arguments,
                "补读已有证据明确指向的原始文档页",
                "document_page_evidence",
            )

        return Plan(
            intent=intent,
            steps=steps,
            allow_generation=not policy_blocked,
            need_evidence_gate=not policy_blocked,
            max_rounds=0 if policy_blocked else min(1, self.max_agent_rounds),
            max_tool_calls=len(steps),
        )
