from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from typing import Any


TOOL_NAMES = (
    "search_manual",
    "lookup_fault_code",
    "lookup_parameter",
    "get_document_page",
)
ERROR_CATEGORIES = (
    "timeout",
    "validation",
    "retrieval_error",
    "tool_error",
    "llm_error",
    "citation_error",
    "database_error",
    "client_disconnect",
    "internal_error",
)
LLM_FAILURE_REASONS = {
    "llm_timeout",
    "llm_api_error",
    "llm_invalid_response",
    "llm_empty_response",
    "llm_rate_limited",
    "llm_quota_exceeded",
    "llm_model_forbidden",
    "llm_model_unavailable",
}
LATENCY_NAMES = (
    "request",
    "retrieval",
    "dense",
    "bm25",
    "fusion",
    "rerank",
    "llm",
    "tool",
)


def _non_negative_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _non_negative_int(value: Any) -> int:
    number = _non_negative_number(value)
    return max(int(number or 0), 0)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


class _RollingSamples:
    """Lifetime count/sum plus bounded samples for window-only percentiles."""

    def __init__(self, window_size: int) -> None:
        self.window_size = max(int(window_size), 1)
        self.values: deque[float] = deque(maxlen=self.window_size)
        self.lifetime_count = 0
        self.lifetime_sum = 0.0

    def add(self, value: Any) -> None:
        number = _non_negative_number(value)
        if number is None:
            return
        self.lifetime_count += 1
        self.lifetime_sum += number
        self.values.append(number)

    @staticmethod
    def _percentile(ordered: list[float], ratio: float) -> float | None:
        if not ordered:
            return None
        index = max(0, math.ceil(len(ordered) * ratio) - 1)
        return ordered[index]

    def snapshot(self, *, unit: str = "") -> dict[str, int | float | None]:
        ordered = sorted(self.values)
        rolling_sum = sum(ordered)
        suffix = f"_{unit}" if unit else ""
        return {
            "lifetime_count": self.lifetime_count,
            f"lifetime_sum{suffix}": round(self.lifetime_sum, 6),
            f"lifetime_average{suffix}": (
                round(self.lifetime_sum / self.lifetime_count, 6)
                if self.lifetime_count
                else None
            ),
            "rolling_window_count": len(ordered),
            f"rolling_average{suffix}": (
                round(rolling_sum / len(ordered), 6) if ordered else None
            ),
            f"rolling_p50{suffix}": self._rounded_percentile(ordered, 0.50),
            f"rolling_p95{suffix}": self._rounded_percentile(ordered, 0.95),
            f"rolling_p99{suffix}": self._rounded_percentile(ordered, 0.99),
        }

    def _rounded_percentile(
        self, ordered: list[float], ratio: float
    ) -> float | None:
        value = self._percentile(ordered, ratio)
        return round(value, 6) if value is not None else None


class MetricsCollector:
    """Thread-safe, process-local runtime aggregates without request payloads."""

    def __init__(self, latency_window_size: int = 1000) -> None:
        self.latency_window_size = max(int(latency_window_size), 1)
        self._lock = threading.RLock()
        self._initialize_state()

    def _initialize_state(self) -> None:
        self._request_total = 0
        self._request_success_total = 0
        self._request_error_total = 0
        self._request_timeout_total = 0
        self._active_requests = 0
        self._error_events = {name: 0 for name in ERROR_CATEGORIES}
        self._latencies = {
            name: _RollingSamples(self.latency_window_size)
            for name in LATENCY_NAMES
        }
        self._rag_request_total = 0
        self._rewrite_total = 0
        self._rewrite_request_total = 0
        self._refusal_total = 0
        self._evidence_insufficient_total = 0
        self._citation_guard_failure_total = 0
        self._fallback_total = 0
        self._planner_attempt_total = 0
        self._planner_applied_total = 0
        self._planner_fallback_total = 0
        self._planner_error_total = 0
        self._agent_round_total = 0
        self._tool_reuse_total = 0
        self._budget_exhausted_total = 0
        self._retrieval_request_total = 0
        self._retrieved_candidates = _RollingSamples(self.latency_window_size)
        self._final_evidence = _RollingSamples(self.latency_window_size)
        self._llm_call_total = 0
        self._llm_error_total = 0
        self._llm_fallback_total = 0
        self._input_tokens_total = 0
        self._output_tokens_total = 0
        self._total_tokens = 0
        self._token_usage_request_total = 0
        self._tool_call_total = 0
        self._tool_success_total = 0
        self._tool_error_total = 0
        self._tool_timeout_total = 0
        self._mcp_tool_call_total = 0
        self._tools = {
            name: {
                "tool_call_total": 0,
                "tool_success_total": 0,
                "tool_error_total": 0,
                "tool_timeout_total": 0,
                "mcp_tool_call_total": 0,
                "latency": _RollingSamples(self.latency_window_size),
            }
            for name in TOOL_NAMES
        }

    def reset(self) -> None:
        """Clear process-local aggregates while retaining the collector object."""
        with self._lock:
            self._initialize_state()

    @property
    def active_requests(self) -> int:
        with self._lock:
            return self._active_requests

    def request_started(self) -> None:
        """Track in-flight work; outcome counters are settled together at finish."""
        with self._lock:
            self._active_requests += 1

    def settle_request(
        self,
        *,
        latency_ms: float,
        status_code: int,
        error_category: str = "",
    ) -> None:
        """Settle total/success/error/timeout exactly once at the HTTP boundary."""
        category = self._normalize_request_error(status_code, error_category)
        with self._lock:
            self._active_requests = max(self._active_requests - 1, 0)
            self._request_total += 1
            self._latencies["request"].add(latency_ms)
            if category:
                self._request_error_total += 1
                if category == "timeout":
                    self._request_timeout_total += 1
                self._record_error_unlocked(category)
            else:
                self._request_success_total += 1

    @staticmethod
    def _normalize_request_error(status_code: int, error_category: str) -> str:
        requested = error_category.strip().lower()
        if requested:
            return requested if requested in ERROR_CATEGORIES else "internal_error"
        if status_code < 400:
            return ""
        if status_code in {408, 504}:
            return "timeout"
        if status_code < 500:
            return "validation"
        return "internal_error"

    def record_error_event(self, category: str) -> None:
        normalized = category if category in ERROR_CATEGORIES else "internal_error"
        with self._lock:
            self._record_error_unlocked(normalized)

    def _record_error_unlocked(self, category: str) -> None:
        self._error_events[category] += 1

    def observe_tool_result(self, result: Any, *, source: str = "workflow") -> None:
        """Observe one Registry call attempt at its unified completion point.

        ``tool_call_total`` includes rejected attempts whose trace has
        ``executed=false``. Retrieval counters remain limited to handlers that
        actually executed ``search_manual``.
        """
        tool_name = str(
            getattr(result, "tool_name", "") or getattr(result, "tool", "")
        )
        if tool_name not in TOOL_NAMES:
            return
        trace = getattr(result, "call_trace", None)
        executed = bool(getattr(trace, "executed", True))
        success = bool(getattr(result, "success", False))
        error = str(getattr(result, "error", "") or "")
        latency_ms = getattr(result, "latency_ms", 0.0)
        metadata = getattr(result, "metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}

        with self._lock:
            tool = self._tools[tool_name]
            self._tool_call_total += 1
            tool["tool_call_total"] += 1
            self._latencies["tool"].add(latency_ms)
            tool["latency"].add(latency_ms)
            if source == "mcp":
                self._mcp_tool_call_total += 1
                tool["mcp_tool_call_total"] += 1
            if success:
                self._tool_success_total += 1
                tool["tool_success_total"] += 1
            else:
                self._tool_error_total += 1
                tool["tool_error_total"] += 1
                if error == "tool_timeout":
                    self._tool_timeout_total += 1
                    tool["tool_timeout_total"] += 1
                self._record_error_unlocked(
                    self._tool_error_category(tool_name, error)
                )

            if tool_name == "search_manual" and executed:
                self._observe_retrieval_unlocked(result, metadata)

    @staticmethod
    def _tool_error_category(tool_name: str, error: str) -> str:
        if error == "tool_timeout":
            return "timeout"
        if error in {"unknown_tool", "tool_arguments_invalid"}:
            return "validation"
        if tool_name == "search_manual" and error:
            return "retrieval_error"
        return "tool_error"

    def _observe_retrieval_unlocked(self, result: Any, metadata: dict[str, Any]) -> None:
        self._retrieval_request_total += 1
        self._latencies["retrieval"].add(getattr(result, "latency_ms", 0.0))
        trace = metadata.get("retrieval_trace", {})
        if not isinstance(trace, dict):
            trace = {}
        for field, latency_name in (
            ("dense_latency_ms", "dense"),
            ("bm25_latency_ms", "bm25"),
            ("fusion_latency_ms", "fusion"),
            ("rerank_latency_ms", "rerank"),
        ):
            self._latencies[latency_name].add(trace.get(field))
        candidate_count = trace.get("candidate_count")
        if candidate_count is None and isinstance(trace.get("rrf_topk"), list):
            candidate_count = len(trace["rrf_topk"])
        final_evidence_count = trace.get("final_evidence_count")
        if final_evidence_count is None:
            final_evidence_count = getattr(result, "result_count", None)
        self._retrieved_candidates.add(candidate_count)
        self._final_evidence.add(final_evidence_count)

    def observe_rag_trace(
        self,
        trace: dict[str, Any],
        generation_usage: dict[str, Any],
        *,
        agent_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        """Aggregate explicit final workflow facts without retaining trace payloads."""
        rewrite_attempts = _non_negative_int(trace.get("query_rewrite_attempts"))
        stop_reason = str(trace.get("stop_reason", "") or "")
        observed_agent_trace: Any = (
            agent_trace if agent_trace is not None else trace.get("agent_trace", [])
        )
        if not isinstance(observed_agent_trace, list):
            observed_agent_trace = []
        safe_refusal = any(
            isinstance(item, dict) and item.get("node") == "safe_refusal"
            for item in observed_agent_trace
        )
        citation_failed = any(
            isinstance(item, dict)
            and item.get("node") == "citation_guard"
            and item.get("action") == "fallback_local_extractive"
            for item in observed_agent_trace
        ) or generation_usage.get("fallback_reason") == "citation_guard_failed"
        fallback_reason = str(generation_usage.get("fallback_reason", "") or "")
        external_calls = _non_negative_int(generation_usage.get("external_calls"))
        attempted_models = generation_usage.get("attempted_models", [])
        if not isinstance(attempted_models, list):
            attempted_models = []
        generation_mode = str(generation_usage.get("mode", "") or "")
        planner_attempted = bool(trace.get("planner_attempted", False))
        planner_applied = bool(trace.get("planner_applied", False))
        planner_fallback = bool(trace.get("planner_fallback", False))
        planner_fallback_reason = str(
            trace.get("planner_fallback_reason", "") or ""
        )
        planner_round = _non_negative_int(trace.get("planner_round"))
        observed_tool_calls = trace.get("tool_calls", [])
        if not isinstance(observed_tool_calls, list):
            observed_tool_calls = []
        tool_reuse_count = sum(
            bool(item.get("reused", False))
            for item in observed_tool_calls
            if isinstance(item, dict)
        )
        planner_error = planner_fallback_reason.startswith(
            ("planner_build_failed", "executor_exception")
        ) or planner_fallback_reason in {
            "plan_validation_failure",
            "unknown_tool",
            "invalid_arguments",
            "invalid_document_page",
            "tool_timeout",
            "executor_tool_error",
            "executor_unavailable",
        }
        budget_exhausted = planner_fallback_reason in {
            "max_tool_calls_reached",
            "max_rounds_reached",
            "agent_timeout",
        } or stop_reason in {
            "max_tool_calls_reached",
            "max_rounds_reached",
            "max_rewrites_reached",
            "timeout_reached",
        }

        with self._lock:
            self._rag_request_total += 1
            self._rewrite_total += rewrite_attempts
            if rewrite_attempts:
                self._rewrite_request_total += 1
            if safe_refusal or stop_reason in {"safety_blocked", "out_of_scope"}:
                self._refusal_total += 1
            if stop_reason == "insufficient_evidence":
                self._evidence_insufficient_total += 1
            if citation_failed:
                self._citation_guard_failure_total += 1
                self._record_error_unlocked("citation_error")
            if fallback_reason:
                self._fallback_total += 1
            if planner_attempted:
                self._planner_attempt_total += 1
            if planner_applied:
                self._planner_applied_total += 1
            if planner_fallback:
                self._planner_fallback_total += 1
            if planner_error:
                self._planner_error_total += 1
            self._agent_round_total += planner_round
            self._tool_reuse_total += tool_reuse_count
            if budget_exhausted:
                self._budget_exhausted_total += 1

            self._llm_call_total += external_calls
            if external_calls:
                self._latencies["llm"].add(
                    generation_usage.get("total_latency_ms")
                )
                if (
                    fallback_reason
                    or len(attempted_models) > 1
                    or generation_mode != "llm_grounded"
                ):
                    self._llm_fallback_total += 1
                if fallback_reason in LLM_FAILURE_REASONS:
                    self._llm_error_total += 1
                    self._record_error_unlocked("llm_error")

            input_tokens = generation_usage.get("input_tokens")
            output_tokens = generation_usage.get("output_tokens")
            total_tokens = generation_usage.get("total_tokens")
            if _non_negative_number(input_tokens) is not None:
                self._input_tokens_total += int(input_tokens)
            if _non_negative_number(output_tokens) is not None:
                self._output_tokens_total += int(output_tokens)
            if _non_negative_number(total_tokens) is not None:
                self._total_tokens += int(total_tokens)
                self._token_usage_request_total += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latency = {
                f"{name}_ms": series.snapshot(unit="ms")
                for name, series in self._latencies.items()
            }
            tools: dict[str, Any] = {}
            for name, values in self._tools.items():
                tools[name] = {
                    key: value
                    for key, value in values.items()
                    if key != "latency"
                }
                tools[name]["latency_ms"] = values["latency"].snapshot(unit="ms")
            return {
                "window": {
                    "latency_sample_limit": self.latency_window_size,
                    "percentile_scope": "most_recent_samples",
                    "percentile_method": "nearest_rank",
                    "percentiles_are_lifetime": False,
                },
                "request": {
                    "request_total": self._request_total,
                    "request_success_total": self._request_success_total,
                    "request_error_total": self._request_error_total,
                    "request_timeout_total": self._request_timeout_total,
                    "active_requests": self._active_requests,
                    "error_events_by_category": dict(self._error_events),
                },
                "latency": latency,
                "rag": {
                    "rag_request_total": self._rag_request_total,
                    "rewrite_total": self._rewrite_total,
                    "rewrite_request_total": self._rewrite_request_total,
                    "rewrite_rate": _rate(
                        self._rewrite_request_total, self._rag_request_total
                    ),
                    "refusal_total": self._refusal_total,
                    "refusal_rate": _rate(
                        self._refusal_total, self._rag_request_total
                    ),
                    "evidence_insufficient_total": self._evidence_insufficient_total,
                    "citation_guard_failure_total": self._citation_guard_failure_total,
                    "fallback_total": self._fallback_total,
                    "fallback_rate": _rate(
                        self._fallback_total, self._rag_request_total
                    ),
                    "retrieval": {
                        "retrieval_request_total": self._retrieval_request_total,
                        "retrieved_candidate_count": self._retrieved_candidates.snapshot(),
                        "final_evidence_count": self._final_evidence.snapshot(),
                    },
                    "agent": {
                        "planner_attempt_total": self._planner_attempt_total,
                        "planner_applied_total": self._planner_applied_total,
                        "planner_fallback_total": self._planner_fallback_total,
                        "planner_error_total": self._planner_error_total,
                        "agent_round_total": self._agent_round_total,
                        "tool_reuse_total": self._tool_reuse_total,
                        "budget_exhausted_total": self._budget_exhausted_total,
                    },
                },
                "llm": {
                    "llm_call_total": self._llm_call_total,
                    "llm_error_total": self._llm_error_total,
                    "llm_fallback_total": self._llm_fallback_total,
                    "input_tokens_total": self._input_tokens_total,
                    "output_tokens_total": self._output_tokens_total,
                    "total_tokens": self._total_tokens,
                    "token_usage_request_total": self._token_usage_request_total,
                    "average_tokens_per_observed_request": (
                        round(
                            self._total_tokens / self._token_usage_request_total, 6
                        )
                        if self._token_usage_request_total
                        else None
                    ),
                },
                "tools": {
                    "tool_call_total": self._tool_call_total,
                    "tool_success_total": self._tool_success_total,
                    "tool_error_total": self._tool_error_total,
                    "tool_timeout_total": self._tool_timeout_total,
                    "mcp_tool_call_total": self._mcp_tool_call_total,
                    "by_tool": tools,
                },
            }

    @staticmethod
    def _format_number(value: int | float) -> str:
        if isinstance(value, int):
            return str(value)
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"

    @classmethod
    def _sample(cls, name: str, value: int | float, labels: str = "") -> str:
        rendered_labels = f"{{{labels}}}" if labels else ""
        return f"{name}{rendered_labels} {cls._format_number(value)}"

    def prometheus_exposition(self) -> str:
        snapshot = self.snapshot()
        request = snapshot["request"]
        rag = snapshot["rag"]
        llm = snapshot["llm"]
        tools = snapshot["tools"]
        lines = [
            "# HELP autoops_request_total Settled application HTTP requests.",
            "# TYPE autoops_request_total counter",
            self._sample("autoops_request_total", request["request_total"]),
            "# HELP autoops_request_success_total Successful application HTTP requests.",
            "# TYPE autoops_request_success_total counter",
            self._sample(
                "autoops_request_success_total", request["request_success_total"]
            ),
            "# HELP autoops_request_error_total Failed application HTTP requests.",
            "# TYPE autoops_request_error_total counter",
            self._sample("autoops_request_error_total", request["request_error_total"]),
            "# HELP autoops_request_timeout_total Timed out application HTTP requests.",
            "# TYPE autoops_request_timeout_total counter",
            self._sample(
                "autoops_request_timeout_total", request["request_timeout_total"]
            ),
            "# HELP autoops_active_requests Application HTTP requests currently in flight.",
            "# TYPE autoops_active_requests gauge",
            self._sample("autoops_active_requests", request["active_requests"]),
            "# HELP autoops_metrics_latency_window_size Maximum recent samples used for latency percentiles.",
            "# TYPE autoops_metrics_latency_window_size gauge",
            self._sample(
                "autoops_metrics_latency_window_size", self.latency_window_size
            ),
        ]
        lines.extend(
            [
                "# HELP autoops_error_events_total Bounded error events by stable category.",
                "# TYPE autoops_error_events_total counter",
            ]
        )
        for category, value in request["error_events_by_category"].items():
            lines.append(
                self._sample(
                    "autoops_error_events_total", value, f'category="{category}"'
                )
            )
        lines.extend(
            [
                "# TYPE autoops_rag_request_total counter",
                self._sample("autoops_rag_request_total", rag["rag_request_total"]),
                "# TYPE autoops_rewrite_total counter",
                self._sample("autoops_rewrite_total", rag["rewrite_total"]),
                "# TYPE autoops_rewrite_rate gauge",
                self._sample("autoops_rewrite_rate", rag["rewrite_rate"] or 0.0),
                "# TYPE autoops_refusal_total counter",
                self._sample("autoops_refusal_total", rag["refusal_total"]),
                "# TYPE autoops_refusal_rate gauge",
                self._sample("autoops_refusal_rate", rag["refusal_rate"] or 0.0),
                "# TYPE autoops_evidence_insufficient_total counter",
                self._sample(
                    "autoops_evidence_insufficient_total",
                    rag["evidence_insufficient_total"],
                ),
                "# TYPE autoops_citation_guard_failure_total counter",
                self._sample(
                    "autoops_citation_guard_failure_total",
                    rag["citation_guard_failure_total"],
                ),
                "# TYPE autoops_fallback_total counter",
                self._sample("autoops_fallback_total", rag["fallback_total"]),
                "# TYPE autoops_fallback_rate gauge",
                self._sample("autoops_fallback_rate", rag["fallback_rate"] or 0.0),
                "# TYPE autoops_planner_attempt_total counter",
                self._sample(
                    "autoops_planner_attempt_total",
                    rag["agent"]["planner_attempt_total"],
                ),
                "# TYPE autoops_planner_applied_total counter",
                self._sample(
                    "autoops_planner_applied_total",
                    rag["agent"]["planner_applied_total"],
                ),
                "# TYPE autoops_planner_fallback_total counter",
                self._sample(
                    "autoops_planner_fallback_total",
                    rag["agent"]["planner_fallback_total"],
                ),
                "# TYPE autoops_planner_error_total counter",
                self._sample(
                    "autoops_planner_error_total",
                    rag["agent"]["planner_error_total"],
                ),
                "# TYPE autoops_agent_round_total counter",
                self._sample(
                    "autoops_agent_round_total",
                    rag["agent"]["agent_round_total"],
                ),
                "# TYPE autoops_tool_reuse_total counter",
                self._sample(
                    "autoops_tool_reuse_total",
                    rag["agent"]["tool_reuse_total"],
                ),
                "# TYPE autoops_budget_exhausted_total counter",
                self._sample(
                    "autoops_budget_exhausted_total",
                    rag["agent"]["budget_exhausted_total"],
                ),
                "# TYPE autoops_retrieval_request_total counter",
                self._sample(
                    "autoops_retrieval_request_total",
                    rag["retrieval"]["retrieval_request_total"],
                ),
                "# TYPE autoops_retrieved_candidate_count_sum counter",
                self._sample(
                    "autoops_retrieved_candidate_count_sum",
                    rag["retrieval"]["retrieved_candidate_count"]["lifetime_sum"],
                ),
                "# TYPE autoops_final_evidence_count_sum counter",
                self._sample(
                    "autoops_final_evidence_count_sum",
                    rag["retrieval"]["final_evidence_count"]["lifetime_sum"],
                ),
                "# TYPE autoops_llm_call_total counter",
                self._sample("autoops_llm_call_total", llm["llm_call_total"]),
                "# TYPE autoops_llm_error_total counter",
                self._sample("autoops_llm_error_total", llm["llm_error_total"]),
                "# TYPE autoops_llm_fallback_total counter",
                self._sample(
                    "autoops_llm_fallback_total", llm["llm_fallback_total"]
                ),
                "# TYPE autoops_input_tokens_total counter",
                self._sample(
                    "autoops_input_tokens_total", llm["input_tokens_total"]
                ),
                "# TYPE autoops_output_tokens_total counter",
                self._sample(
                    "autoops_output_tokens_total", llm["output_tokens_total"]
                ),
                "# TYPE autoops_tokens_total counter",
                self._sample("autoops_tokens_total", llm["total_tokens"]),
                "# TYPE autoops_average_tokens_per_observed_request gauge",
                self._sample(
                    "autoops_average_tokens_per_observed_request",
                    llm["average_tokens_per_observed_request"] or 0.0,
                ),
                "# HELP autoops_tool_calls_total Tool Registry call attempts, including rejected attempts that did not execute a handler.",
                "# TYPE autoops_tool_calls_total counter",
                self._sample("autoops_tool_calls_total", tools["tool_call_total"]),
                "# TYPE autoops_tool_successes_total counter",
                self._sample(
                    "autoops_tool_successes_total", tools["tool_success_total"]
                ),
                "# TYPE autoops_tool_errors_total counter",
                self._sample("autoops_tool_errors_total", tools["tool_error_total"]),
                "# TYPE autoops_tool_timeouts_total counter",
                self._sample(
                    "autoops_tool_timeouts_total", tools["tool_timeout_total"]
                ),
                "# TYPE autoops_mcp_tool_calls_total counter",
                self._sample(
                    "autoops_mcp_tool_calls_total", tools["mcp_tool_call_total"]
                ),
            ]
        )
        for latency_name, values in snapshot["latency"].items():
            metric = f"autoops_{latency_name.removesuffix('_ms')}_latency_ms"
            lines.extend(
                [
                    self._sample(f"{metric}_count", values["lifetime_count"]),
                    self._sample(f"{metric}_sum", values["lifetime_sum_ms"]),
                    self._sample(
                        f"{metric}_rolling_window_count",
                        values["rolling_window_count"],
                    ),
                ]
            )
            for ratio, key in (
                ("0.50", "rolling_p50_ms"),
                ("0.95", "rolling_p95_ms"),
                ("0.99", "rolling_p99_ms"),
            ):
                value = values[key]
                if value is not None:
                    lines.append(
                        self._sample(
                            f"{metric}_rolling_quantile",
                            value,
                            f'quantile="{ratio}"',
                        )
                    )
        for tool_name, values in tools["by_tool"].items():
            label = f'tool="{tool_name}"'
            for field in (
                "tool_call_total",
                "tool_success_total",
                "tool_error_total",
                "tool_timeout_total",
                "mcp_tool_call_total",
            ):
                lines.append(
                    self._sample(f"autoops_{field}", values[field], label)
                )
            latency = values["latency_ms"]
            if latency["lifetime_average_ms"] is not None:
                lines.append(
                    self._sample(
                        "autoops_tool_latency_ms_lifetime_average",
                        latency["lifetime_average_ms"],
                        label,
                    )
                )
            if latency["rolling_p95_ms"] is not None:
                lines.append(
                    self._sample(
                        "autoops_tool_latency_ms_rolling_p95",
                        latency["rolling_p95_ms"],
                        label,
                    )
                )
        return "\n".join(lines) + "\n"


_RUNTIME_METRICS: MetricsCollector | None = None
_RUNTIME_METRICS_LOCK = threading.Lock()


def get_runtime_metrics(latency_window_size: int = 1000) -> MetricsCollector:
    global _RUNTIME_METRICS
    if _RUNTIME_METRICS is None:
        with _RUNTIME_METRICS_LOCK:
            if _RUNTIME_METRICS is None:
                _RUNTIME_METRICS = MetricsCollector(latency_window_size)
    return _RUNTIME_METRICS


class RuntimeMetricsMiddleware:
    """ASGI boundary that settles each included HTTP request exactly once."""

    def __init__(
        self,
        app: Any,
        *,
        collector: MetricsCollector,
        excluded_paths: tuple[str, ...] = (),
        excluded_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.collector = collector
        self.excluded_paths = frozenset(excluded_paths)
        self.excluded_prefixes = tuple(excluded_prefixes)

    def _included(self, path: str) -> bool:
        return path not in self.excluded_paths and not any(
            path.startswith(prefix) for prefix in self.excluded_prefixes
        )

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self._included(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500
        settled = False
        self.collector.request_started()

        def settle(error_category: str = "") -> None:
            nonlocal settled
            if settled:
                return
            settled = True
            self.collector.settle_request(
                latency_ms=(time.perf_counter() - started) * 1000,
                status_code=status_code,
                error_category=error_category,
            )

        async def send_with_metrics(message: dict) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            final_body = (
                message.get("type") == "http.response.body"
                and not message.get("more_body", False)
            )
            await send(message)
            if final_body:
                state = scope.get("state", {})
                category = (
                    str(state.get("metrics_error_category", ""))
                    if isinstance(state, dict)
                    else ""
                )
                settle(category)

        try:
            await self.app(scope, receive, send_with_metrics)
        except asyncio.CancelledError:
            settle("client_disconnect")
            raise
        except BaseException:
            settle("internal_error")
            raise
        finally:
            if not settled:
                state = scope.get("state", {})
                category = (
                    str(state.get("metrics_error_category", ""))
                    if isinstance(state, dict)
                    else ""
                )
                settle(category)
