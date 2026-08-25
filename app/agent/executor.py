from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.iterative import budget_snapshot
from app.agent.planner import Plan, PlanStep
from app.models import SearchHit, ToolCallTrace, ToolResult
from app.tracing import sanitize_trace


@dataclass
class ExecutorOutcome:
    applied: bool = False
    fallback: bool = False
    fallback_reason: str = ""
    planner_round: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_result_cache: dict[str, ToolResult] = field(default_factory=dict)
    tool_call_signatures: list[str] = field(default_factory=list)
    evidence: list[SearchHit] = field(default_factory=list)
    result_parts: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)


class ControlledAgentExecutor:
    """Request-scoped validation, budget, deduplication, and Registry execution."""

    def __init__(self, registry: Any, settings: Any) -> None:
        self.registry = registry
        self.settings = settings

    @staticmethod
    def _normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): ControlledAgentExecutor._normalize(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, list):
            return [ControlledAgentExecutor._normalize(item) for item in value]
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @classmethod
    def signature(cls, tool_name: str, arguments: BaseModel | dict[str, Any]) -> str:
        payload = (
            arguments.model_dump(mode="json")
            if isinstance(arguments, BaseModel)
            else arguments
        )
        normalized = json.dumps(
            cls._normalize(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{tool_name}:{digest}"

    def _validated_step(
        self,
        step: PlanStep,
        *,
        evidence: list[SearchHit],
    ) -> tuple[str, BaseModel]:
        try:
            canonical, arguments = self.registry.validate_arguments(
                step.tool_name,
                step.arguments,
                agent_only=True,
                allow_aliases=False,
            )
        except ValidationError as exc:
            raise ValueError("invalid_arguments") from exc
        if canonical == "get_document_page":
            known = {
                (hit.chunk.doc_id.casefold(), hit.chunk.page)
                for hit in evidence
                if hit.chunk.doc_id
            }
            known.update(
                (hit.chunk.doc_name.casefold(), hit.chunk.page)
                for hit in evidence
                if hit.chunk.doc_name
            )
            references = {
                value.casefold()
                for value in (
                    getattr(arguments, "document_id", None),
                    getattr(arguments, "document_name", None),
                )
                if value
            }
            page = int(getattr(arguments, "page"))
            if not references or not any((reference, page) in known for reference in references):
                raise ValueError("document_page_not_grounded_in_evidence")
        return canonical, arguments

    def validate_plan(
        self,
        candidate: Plan | dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[Plan, list[tuple[PlanStep, str, BaseModel]]]:
        plan = Plan.model_validate(candidate)
        max_rounds = max(int(getattr(self.settings, "max_agent_rounds", 2)), 0)
        max_calls = max(int(getattr(self.settings, "max_tool_calls", 4)), 0)
        if plan.max_rounds > max_rounds:
            raise ValueError("max_rounds_exceeded")
        if plan.max_tool_calls > max_calls or len(plan.steps) > max_calls:
            raise ValueError("max_tool_calls_exceeded")
        evidence = list(state.get("evidence", []))
        validated = [
            (step, *self._validated_step(step, evidence=evidence))
            for step in plan.steps
        ]
        if not evidence and not any(name == "search_manual" for _, name, _ in validated):
            raise ValueError("evidence_retrieval_required")
        return plan, validated

    @staticmethod
    def _fallback_reason(exc: BaseException) -> str:
        if isinstance(exc, ValidationError):
            return "plan_validation_failure"
        if isinstance(exc, KeyError):
            return "unknown_tool"
        message = str(exc)
        if "document_page_not_grounded" in message:
            return "invalid_document_page"
        if "invalid_arguments" in message:
            return "invalid_arguments"
        if "max_rounds" in message:
            return "max_rounds_reached"
        if "max_tool_calls" in message:
            return "max_tool_calls_reached"
        if "evidence_retrieval_required" in message:
            return "evidence_retrieval_required"
        return "plan_validation_failure"

    @staticmethod
    def _result_error_reason(error: str) -> str:
        return {
            "unknown_tool": "unknown_tool",
            "tool_arguments_invalid": "invalid_arguments",
            "tool_timeout": "tool_timeout",
            "max_tool_calls_reached": "max_tool_calls_reached",
        }.get(error, "executor_tool_error")

    def _remaining_timeout(self, state: dict[str, Any]) -> float:
        budget = budget_snapshot(state, self.settings)
        remaining_seconds = float(budget.get("remaining_ms", 0.0)) / 1000
        tool_timeout = max(
            float(getattr(self.settings, "tool_timeout_seconds", 30.0)), 0.001
        )
        return min(tool_timeout, remaining_seconds) if remaining_seconds > 0 else 0.0

    def call_or_reuse(
        self,
        tool_name: str,
        arguments: BaseModel | dict[str, Any],
        state: dict[str, Any],
        *,
        planner_round: int,
    ) -> tuple[ToolResult, dict[str, Any], str]:
        canonical, validated = self.registry.validate_arguments(
            tool_name,
            arguments,
            agent_only=True,
            allow_aliases=False,
        )
        signature = self.signature(canonical, validated)
        existing_cache = state.get("tool_result_cache", {})
        cache = existing_cache if isinstance(existing_cache, dict) else {}
        cached = cache.get(signature)
        if cached is not None:
            result = cached.model_copy(deep=True)
            original_latency = result.latency_ms
            trace_arguments = sanitize_trace(validated.model_dump(mode="json"))
            result.call_trace = ToolCallTrace(
                tool_name=canonical,
                arguments=trace_arguments if isinstance(trace_arguments, dict) else {},
                started_at=datetime.now(timezone.utc),
                latency_ms=0.0,
                executed=False,
                reused=True,
                deduplicated=True,
                planner_round=planner_round,
                remaining_budget=budget_snapshot(state, self.settings),
                success=result.success,
                result_count=result.result_count,
                error=result.error,
            )
            result.latency_ms = original_latency
            return result, cache, signature

        timeout = self._remaining_timeout(state)
        if timeout <= 0:
            return ToolResult(
                tool_name=canonical,
                success=False,
                error="agent_timeout",
            ), cache, signature
        result = self.registry.execute(
            canonical,
            validated,
            tool_calls=list(state.get("tool_calls", [])),
            max_tool_calls=getattr(self.settings, "max_tool_calls", 4),
            timeout_seconds=timeout,
            allow_aliases=False,
            source="workflow",
        )
        # Publish the completed Registry result to the request-scoped cache before
        # any trace enrichment. If later executor bookkeeping fails, the Graph can
        # still reuse this exact result during fixed-workflow fallback.
        cache[signature] = result
        if result.call_trace is not None:
            result.call_trace.planner_round = planner_round
            result.call_trace.remaining_budget = budget_snapshot(
                {
                    **state,
                    "tool_calls": [
                        *state.get("tool_calls", []),
                        result.call_trace.model_dump(mode="json"),
                    ],
                },
                self.settings,
            )
        # Cache failures too: an identical timeout/error must not start a loop or
        # duplicate a real Registry call during fixed-workflow fallback.
        cache[signature] = result.model_copy(deep=True)
        return result, cache, signature

    def execute_plan(
        self,
        candidate: Plan | dict[str, Any],
        state: dict[str, Any],
    ) -> ExecutorOutcome:
        existing_tool_calls = state.get("tool_calls", [])
        existing_cache = state.get("tool_result_cache", {})
        existing_signatures = state.get("tool_call_signatures", [])
        outcome = ExecutorOutcome(
            planner_round=int(state.get("planner_round", 0)) + 1,
            tool_calls=(
                existing_tool_calls if isinstance(existing_tool_calls, list) else []
            ),
            tool_result_cache=(existing_cache if isinstance(existing_cache, dict) else {}),
            tool_call_signatures=(
                existing_signatures if isinstance(existing_signatures, list) else []
            ),
            evidence=list(state.get("evidence", [])),
        )
        working = {**state, "planner_round": outcome.planner_round}
        try:
            if outcome.planner_round > int(
                getattr(self.settings, "max_agent_rounds", 2)
            ):
                raise ValueError("max_rounds_exceeded")
            plan, validated_steps = self.validate_plan(candidate, working)
        except Exception as exc:
            outcome.fallback = True
            outcome.fallback_reason = self._fallback_reason(exc)
            outcome.budget = budget_snapshot(working, self.settings)
            return outcome

        seen_this_round: set[str] = set()
        for _step, canonical, validated in validated_steps:
            call_state = {
                **working,
                "tool_calls": outcome.tool_calls,
                "tool_result_cache": outcome.tool_result_cache,
                "tool_call_signatures": outcome.tool_call_signatures,
            }
            if self._remaining_timeout(call_state) <= 0:
                outcome.fallback = True
                outcome.fallback_reason = "agent_timeout"
                break
            result, cache, signature = self.call_or_reuse(
                canonical,
                validated,
                call_state,
                planner_round=outcome.planner_round,
            )
            outcome.tool_result_cache = cache
            if result.call_trace is not None:
                outcome.tool_calls.append(result.call_trace.model_dump(mode="json"))
            if signature in seen_this_round and not (
                result.call_trace and result.call_trace.reused
            ):
                outcome.fallback = True
                outcome.fallback_reason = "duplicate_loop"
                break
            seen_this_round.add(signature)
            outcome.tool_call_signatures.append(signature)
            if not result.success:
                outcome.fallback = True
                outcome.fallback_reason = (
                    "agent_timeout"
                    if result.error == "agent_timeout"
                    else self._result_error_reason(result.error)
                )
                break
            if result.content:
                outcome.result_parts.append(result.content)
            if result.evidence:
                known_ids = {hit.chunk.chunk_id for hit in outcome.evidence}
                outcome.evidence.extend(
                    hit for hit in result.evidence if hit.chunk.chunk_id not in known_ids
                )

        outcome.applied = not outcome.fallback and bool(plan.steps)
        final_state = {
            **working,
            "tool_calls": outcome.tool_calls,
            "tool_result_cache": outcome.tool_result_cache,
        }
        outcome.budget = budget_snapshot(final_state, self.settings)
        return outcome
