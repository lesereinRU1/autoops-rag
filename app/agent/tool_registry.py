from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.agent.memory import MemoryStore
from app.agent.tools import SQLiteToolbox
from app.document_service import DocumentPageService
from app.metrics import MetricsCollector
from app.models import (
    GetDocumentPageInput,
    LookupFaultCodeInput,
    LookupParameterInput,
    SearchManualInput,
    ToolCallTrace,
    ToolResult,
)
from app.tracing import sanitize_trace


ToolHandler = Callable[[BaseModel], ToolResult]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    input_model: type[BaseModel]
    handler: ToolHandler


class ToolRegistry:
    """Validated, bounded execution boundary shared by the fixed workflow."""

    ALIASES = {
        "lookup_alarm_code": "lookup_fault_code",
        "check_parameter_range": "lookup_parameter",
    }

    def __init__(
        self,
        *,
        memory: MemoryStore,
        retriever: Any,
        document_pages: DocumentPageService,
        timeout_seconds: float = 30.0,
        max_tool_calls: int = 4,
        max_workers: int = 8,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.timeout_seconds = max(float(timeout_seconds), 0.001)
        self.max_tool_calls = max(int(max_tool_calls), 0)
        self._executor = ThreadPoolExecutor(
            max_workers=max(int(max_workers), 1),
            thread_name_prefix="autoops-tool",
        )
        self._tools: dict[str, RegisteredTool] = {}
        self._sqlite = SQLiteToolbox(memory)
        self._retriever = retriever
        self._document_pages = document_pages
        self._metrics = metrics
        self.register("search_manual", SearchManualInput, self._search_manual)
        self.register("lookup_fault_code", LookupFaultCodeInput, self._lookup_fault_code)
        self.register("lookup_parameter", LookupParameterInput, self._lookup_parameter)
        self.register("get_document_page", GetDocumentPageInput, self._get_document_page)

    @classmethod
    def from_service(cls, service: Any) -> "ToolRegistry":
        settings = service.settings
        document_pages = getattr(service, "document_pages", None) or DocumentPageService(
            getattr(service, "_chunk_by_id", {}),
            Path(getattr(settings, "raw_dir", ".")),
        )
        return cls(
            memory=service.memory,
            retriever=service.retriever,
            document_pages=document_pages,
            timeout_seconds=getattr(settings, "tool_timeout_seconds", 30.0),
            max_tool_calls=getattr(settings, "max_tool_calls", 4),
            max_workers=getattr(settings, "max_concurrent_queries", 8),
            metrics=getattr(service, "metrics", None),
        )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def register(
        self,
        name: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
    ) -> None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("tool name cannot be empty")
        self._tools[normalized] = RegisteredTool(normalized, input_model, handler)

    def input_model(self, name: str) -> type[BaseModel] | None:
        requested_name = name.strip()
        canonical = self.ALIASES.get(requested_name, requested_name)
        definition = self._tools.get(canonical)
        return definition.input_model if definition else None

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return max((time.perf_counter() - started) * 1000, 0.001)

    @staticmethod
    def _trace_arguments(arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, BaseModel):
            value = arguments.model_dump(mode="json")
        elif isinstance(arguments, dict):
            value = dict(arguments)
        else:
            value = {"value": str(arguments)[:500]}
        clean = sanitize_trace(value)
        return clean if isinstance(clean, dict) else {}

    @staticmethod
    def _executed_calls(tool_calls: list[Any] | None) -> int:
        return sum(
            bool(
                item.get("executed", True)
                if isinstance(item, dict)
                else getattr(item, "executed", True)
            )
            for item in (tool_calls or [])
        )

    def _finish(
        self,
        result: ToolResult,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        started_at: datetime,
        started: float,
        executed: bool,
        source: str,
    ) -> ToolResult:
        latency_ms = self._elapsed_ms(started)
        result.tool_name = tool_name
        result.tool = tool_name
        result.latency_ms = latency_ms
        result.call_trace = ToolCallTrace(
            tool_name=tool_name,
            arguments=arguments,
            started_at=started_at,
            latency_ms=latency_ms,
            executed=executed,
            success=result.success,
            result_count=result.result_count,
            error=result.error,
        )
        if self._metrics is not None:
            try:
                self._metrics.observe_tool_result(result, source=source)
            except Exception:
                # Observability must never alter a tool result or workflow decision.
                pass
        return result

    def execute(
        self,
        tool_name: str,
        arguments: BaseModel | dict[str, Any],
        *,
        tool_calls: list[Any] | None = None,
        max_tool_calls: int | None = None,
        timeout_seconds: float | None = None,
        allow_aliases: bool = True,
        source: str = "workflow",
    ) -> ToolResult:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        requested_name = tool_name.strip()
        canonical = (
            self.ALIASES.get(requested_name, requested_name)
            if allow_aliases
            else requested_name
        )
        trace_arguments = self._trace_arguments(arguments)
        definition = self._tools.get(canonical)
        if definition is None:
            return self._finish(
                ToolResult(success=False, error="unknown_tool"),
                tool_name=canonical,
                arguments=trace_arguments,
                started_at=started_at,
                started=started,
                executed=False,
                source=source,
            )

        call_limit = (
            self.max_tool_calls
            if max_tool_calls is None
            else max(int(max_tool_calls), 0)
        )
        if self._executed_calls(tool_calls) >= call_limit:
            return self._finish(
                ToolResult(success=False, error="max_tool_calls_reached"),
                tool_name=canonical,
                arguments=trace_arguments,
                started_at=started_at,
                started=started,
                executed=False,
                source=source,
            )

        try:
            payload = (
                arguments.model_dump(mode="python")
                if isinstance(arguments, BaseModel)
                else arguments
            )
            validated = definition.input_model.model_validate(payload)
        except ValidationError as exc:
            return self._finish(
                ToolResult(
                    success=False,
                    error="tool_arguments_invalid",
                    metadata={"validation_errors": exc.errors(include_input=False)},
                ),
                tool_name=canonical,
                arguments=trace_arguments,
                started_at=started_at,
                started=started,
                executed=False,
                source=source,
            )

        trace_arguments = self._trace_arguments(validated)
        future = self._executor.submit(definition.handler, validated)
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else max(float(timeout_seconds), 0.001)
        )
        try:
            result = future.result(timeout=timeout)
            if not isinstance(result, ToolResult):
                raise TypeError("tool handler must return ToolResult")
        except FutureTimeoutError:
            future.cancel()
            result = ToolResult(success=False, error="tool_timeout")
        except Exception as exc:
            result = ToolResult(
                success=False,
                error="tool_execution_failed",
                metadata={"error_type": type(exc).__name__},
            )
        return self._finish(
            result,
            tool_name=canonical,
            arguments=trace_arguments,
            started_at=started_at,
            started=started,
            executed=True,
            source=source,
        )

    def _search_manual(self, payload: BaseModel) -> ToolResult:
        arguments = SearchManualInput.model_validate(payload)
        evidence, retrieval_trace = self._retriever.search_with_trace(
            arguments.query,
            top_k=arguments.top_k,
            model=arguments.model,
            version=arguments.version,
        )
        return ToolResult(
            tool_name="search_manual",
            success=True,
            data={"hits": [hit.model_dump(mode="json") for hit in evidence]},
            result_count=len(evidence),
            evidence=evidence,
            metadata={"retrieval_trace": retrieval_trace},
        )

    def _lookup_fault_code(self, payload: BaseModel) -> ToolResult:
        arguments = LookupFaultCodeInput.model_validate(payload)
        result = self._sqlite.lookup_fault_code(arguments.code, arguments.model)
        result.metadata["requested_version"] = arguments.version
        return result

    def _lookup_parameter(self, payload: BaseModel) -> ToolResult:
        arguments = LookupParameterInput.model_validate(payload)
        result = self._sqlite.lookup_parameter(
            arguments.name, arguments.model, arguments.value
        )
        result.metadata["requested_version"] = arguments.version
        return result

    def _get_document_page(self, payload: BaseModel) -> ToolResult:
        return self._document_pages.get_page(
            GetDocumentPageInput.model_validate(payload)
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
