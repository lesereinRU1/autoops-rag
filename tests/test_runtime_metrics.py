from __future__ import annotations

import asyncio
import copy
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import app.api as api
from app.agent.tool_registry import ToolRegistry
from app.document_service import DocumentPageService
from app.mcp.server import MCPToolAdapter
from app.metrics import MetricsCollector, RuntimeMetricsMiddleware
from app.models import LookupParameterInput, SearchManualInput, ToolResult


def test_request_outcomes_are_settled_once_with_active_request_cleanup():
    collector = MetricsCollector()
    app = FastAPI()
    app.add_middleware(RuntimeMetricsMiddleware, collector=collector)

    @app.get("/ok")
    def ok():
        return {"active": collector.active_requests}

    @app.get("/invalid")
    def invalid():
        raise HTTPException(status_code=422, detail="invalid")

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/ok").json() == {"active": 1}
    assert client.get("/invalid").status_code == 422

    request = collector.snapshot()["request"]
    assert request["request_total"] == 2
    assert request["request_success_total"] == 1
    assert request["request_error_total"] == 1
    assert request["request_timeout_total"] == 0
    assert request["active_requests"] == 0
    assert request["error_events_by_category"]["validation"] == 1
    assert collector.snapshot()["latency"]["request_ms"]["lifetime_count"] == 2


def test_streaming_body_chunks_and_timeout_marker_each_settle_one_request():
    collector = MetricsCollector()
    app = FastAPI()
    app.add_middleware(RuntimeMetricsMiddleware, collector=collector)

    @app.get("/stream")
    def stream():
        async def body():
            yield b"one"
            yield b"two"

        return StreamingResponse(body())

    @app.get("/stream-timeout")
    def stream_timeout(request: Request):
        async def body():
            yield b"one"
            request.state.metrics_error_category = "timeout"
            yield b"two"

        return StreamingResponse(body())

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/stream").status_code == 200
    assert client.get("/stream-timeout").status_code == 200

    request = collector.snapshot()["request"]
    assert request["request_total"] == 2
    assert request["request_success_total"] == 1
    assert request["request_error_total"] == 1
    assert request["request_timeout_total"] == 1
    assert request["active_requests"] == 0


def test_latency_percentiles_use_only_the_latest_1000_samples():
    collector = MetricsCollector(latency_window_size=1000)
    for latency_ms in range(1, 1002):
        collector.request_started()
        collector.settle_request(latency_ms=latency_ms, status_code=200)

    snapshot = collector.snapshot()
    values = snapshot["latency"]["request_ms"]
    assert snapshot["window"] == {
        "latency_sample_limit": 1000,
        "percentile_scope": "most_recent_samples",
        "percentile_method": "nearest_rank",
        "percentiles_are_lifetime": False,
    }
    assert values["lifetime_count"] == 1001
    assert values["rolling_window_count"] == 1000
    assert values["rolling_p50_ms"] == 501.0
    assert values["rolling_p95_ms"] == 951.0
    assert values["rolling_p99_ms"] == 991.0


def test_rag_llm_and_token_metrics_use_explicit_trace_facts_without_mutation():
    collector = MetricsCollector()
    trace = {
        "original_question": "private user query",
        "llm_api_key": "must-not-appear",
        "query_rewrite_attempts": 2,
        "stop_reason": "insufficient_evidence",
    }
    agent_trace = [
        {"node": "safe_refusal", "category": "unanswerable_version"},
        {"node": "citation_guard", "action": "fallback_local_extractive"},
    ]
    generation = {
        "mode": "local_extractive",
        "external_calls": 2,
        "attempted_models": ["primary", "fallback"],
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "total_latency_ms": 25.0,
        "fallback_reason": "llm_timeout",
    }
    original_trace = copy.deepcopy(trace)
    original_generation = copy.deepcopy(generation)

    collector.observe_rag_trace(trace, generation, agent_trace=agent_trace)
    collector.observe_rag_trace(
        {"query_rewrite_attempts": 0, "stop_reason": "evidence_sufficient"},
        {"mode": "llm_grounded", "external_calls": 0, "fallback_reason": ""},
    )

    snapshot = collector.snapshot()
    assert snapshot["rag"]["rag_request_total"] == 2
    assert snapshot["rag"]["rewrite_total"] == 2
    assert snapshot["rag"]["rewrite_rate"] == 0.5
    assert snapshot["rag"]["refusal_total"] == 1
    assert snapshot["rag"]["refusal_rate"] == 0.5
    assert snapshot["rag"]["evidence_insufficient_total"] == 1
    assert snapshot["rag"]["citation_guard_failure_total"] == 1
    assert snapshot["rag"]["fallback_total"] == 1
    assert snapshot["llm"]["llm_call_total"] == 2
    assert snapshot["llm"]["llm_error_total"] == 1
    assert snapshot["llm"]["llm_fallback_total"] == 1
    assert snapshot["llm"]["input_tokens_total"] == 10
    assert snapshot["llm"]["output_tokens_total"] == 5
    assert snapshot["llm"]["total_tokens"] == 15
    assert snapshot["llm"]["average_tokens_per_observed_request"] == 15.0
    assert trace == original_trace
    assert generation == original_generation


class _Retriever:
    def __init__(self) -> None:
        self.calls = 0

    def search_with_trace(self, *_args, **_kwargs):
        self.calls += 1
        return [], {
            "dense_topk": [{"chunk_id": "dense"}],
            "bm25_topk": [{"chunk_id": "sparse"}],
            "rrf_topk": [{"chunk_id": "fused"}],
            "final_evidence": [],
            "dense_latency_ms": 1.0,
            "bm25_latency_ms": 2.0,
            "fusion_latency_ms": 3.0,
            "rerank_latency_ms": 4.0,
            "candidate_count": 1,
            "final_evidence_count": 0,
        }


def _registry(tmp_path: Path, collector: MetricsCollector):
    retriever = _Retriever()
    registry = ToolRegistry(
        memory=SimpleNamespace(),
        retriever=retriever,
        document_pages=DocumentPageService({}, tmp_path),
        timeout_seconds=0.2,
        max_tool_calls=10,
        max_workers=2,
        metrics=collector,
    )
    return registry, retriever


def test_registry_is_the_only_tool_completion_point_and_retrieval_counts_once_per_search(
    tmp_path,
):
    collector = MetricsCollector()
    registry, retriever = _registry(tmp_path, collector)
    try:
        for query in ("first query", "rewritten query"):
            result = registry.execute("search_manual", SearchManualInput(query=query))
            assert result.success is True

        snapshot = collector.snapshot()
        assert retriever.calls == 2
        assert snapshot["tools"]["tool_call_total"] == 2
        assert snapshot["rag"]["retrieval"]["retrieval_request_total"] == 2
        for name in ("dense_ms", "bm25_ms", "fusion_ms", "rerank_ms"):
            assert snapshot["latency"][name]["lifetime_count"] == 2
        assert snapshot["rag"]["retrieval"]["retrieved_candidate_count"][
            "lifetime_count"
        ] == 2
    finally:
        registry.close()


def test_tool_success_error_timeout_and_unbounded_names_are_handled_at_registry(
    tmp_path,
):
    collector = MetricsCollector()
    registry, _ = _registry(tmp_path, collector)

    def slow(_payload):
        time.sleep(0.03)
        return ToolResult(success=True)

    def broken(_payload):
        raise RuntimeError("database details must not become a metric label")

    registry.register("lookup_parameter", LookupParameterInput, slow)
    registry.execute(
        "lookup_parameter",
        {"name": "parameter"},
        timeout_seconds=0.001,
    )
    registry.register("lookup_parameter", LookupParameterInput, broken)
    registry.execute("lookup_parameter", {"name": "parameter"})
    registry.register(
        "arbitrary-user-tool-name",
        SearchManualInput,
        lambda _payload: ToolResult(success=True),
    )
    registry.execute("arbitrary-user-tool-name", {"query": "ignored label"})
    registry.close()

    tools = collector.snapshot()["tools"]
    assert tools["tool_call_total"] == 2
    assert tools["tool_success_total"] == 0
    assert tools["tool_error_total"] == 2
    assert tools["tool_timeout_total"] == 1
    assert set(tools["by_tool"]) == {
        "search_manual",
        "lookup_fault_code",
        "lookup_parameter",
        "get_document_page",
    }


def test_mcp_passes_source_without_incrementing_http_or_duplicate_tool_counters(
    tmp_path,
):
    collector = MetricsCollector()
    registry, retriever = _registry(tmp_path, collector)
    try:
        result = asyncio.run(
            MCPToolAdapter(registry).call_tool(
                "search_manual", {"query": "MCP query", "top_k": 5}
            )
        )
        assert result.is_error is False
        snapshot = collector.snapshot()
        assert retriever.calls == 1
        assert snapshot["request"]["request_total"] == 0
        assert snapshot["tools"]["tool_call_total"] == 1
        assert snapshot["tools"]["mcp_tool_call_total"] == 1
        assert snapshot["rag"]["retrieval"]["retrieval_request_total"] == 1
    finally:
        registry.close()


class _Memory:
    @staticmethod
    def business_metrics():
        return {
            "feedback_total": 1,
            "helpful": 1,
            "unhelpful": 0,
            "helpful_rate": 1.0,
            "verified_solutions": 2,
            "verified_solution_reuse": 3,
        }


class _StreamService:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.memory = _Memory()

    def chat(self, _request, request_id, workflow_event_callback=None):
        if self.mode == "error":
            raise RuntimeError("private-api-key-value")
        if self.mode == "timeout":
            time.sleep(0.03)
        if workflow_event_callback is not None:
            for stage in ("analyzing", "retrieving", "reranking", "generating"):
                workflow_event_callback(stage, stage, {"event": stage})
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "request_id": request_id,
                "answer": "completed",
                "evidence": [],
            }
        )

    def close(self):
        return None


def _post_actual_stream(monkeypatch, service):
    monkeypatch.setattr(api, "get_service", lambda: service)
    return TestClient(api.app, raise_server_exceptions=False).post(
        "/api/chat/stream",
        headers={"X-Request-ID": "metrics-stream-request"},
        json={"query": "private query text", "session_id": "metrics-test"},
    )


def test_actual_sse_success_counts_one_http_request_for_many_events(monkeypatch):
    api.RUNTIME_METRICS.reset()
    response = _post_actual_stream(monkeypatch, _StreamService())
    assert response.status_code == 200
    assert response.text.count("event: ") > 2

    request = api.RUNTIME_METRICS.snapshot()["request"]
    assert request["request_total"] == 1
    assert request["request_success_total"] == 1
    assert request["request_error_total"] == 0
    assert request["active_requests"] == 0


def test_actual_sse_error_and_timeout_are_settled_by_http_boundary(monkeypatch):
    api.RUNTIME_METRICS.reset()
    error = _post_actual_stream(monkeypatch, _StreamService("error"))
    assert error.status_code == 200
    request = api.RUNTIME_METRICS.snapshot()["request"]
    assert request["request_total"] == 1
    assert request["request_error_total"] == 1
    assert request["request_timeout_total"] == 0
    assert request["active_requests"] == 0

    api.RUNTIME_METRICS.reset()
    monkeypatch.setattr(api.SETTINGS, "request_timeout_seconds", 0.001)
    timeout = _post_actual_stream(monkeypatch, _StreamService("timeout"))
    assert timeout.status_code == 200
    request = api.RUNTIME_METRICS.snapshot()["request"]
    assert request["request_total"] == 1
    assert request["request_error_total"] == 1
    assert request["request_timeout_total"] == 1
    assert request["active_requests"] == 0


def test_metrics_endpoints_are_excluded_safe_and_business_api_stays_compatible(
    monkeypatch,
):
    api.RUNTIME_METRICS.reset()
    api.RUNTIME_METRICS.observe_rag_trace(
        {
            "original_question": "private query text",
            "llm_api_key": "sk-must-not-appear",
            "query_rewrite_attempts": 0,
            "stop_reason": "evidence_sufficient",
        },
        {"external_calls": 0, "fallback_reason": "", "mode": "local_extractive"},
    )
    monkeypatch.setattr(api, "get_service", lambda: _StreamService())
    client = TestClient(api.app, raise_server_exceptions=False)

    runtime = client.get("/api/metrics/runtime")
    prometheus = client.get("/metrics")
    business = client.get("/api/metrics/business")

    assert runtime.status_code == 200
    assert set(runtime.json()) == {"window", "request", "latency", "rag", "llm", "tools"}
    assert runtime.json()["window"]["latency_sample_limit"] == 1000
    assert runtime.json()["window"]["percentiles_are_lifetime"] is False
    assert prometheus.status_code == 200
    assert prometheus.headers["content-type"].startswith("text/plain")
    assert "autoops_request_total" in prometheus.text
    assert "private query text" not in runtime.text + prometheus.text
    assert "sk-must-not-appear" not in runtime.text + prometheus.text
    assert business.json() == _Memory.business_metrics()
    assert api.RUNTIME_METRICS.snapshot()["request"]["request_total"] == 0
