from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api as api
from app.agent.graph import build_graph
from app.agent.memory import MemoryStore
from app.agent.tool_registry import ToolRegistry
from app.concurrency import ReadWriteLock
from app.document_service import DocumentPageService
from app.models import ChatResponse, Chunk, SearchHit
from app.service import AutoOpsService
from app.tracing import TraceStore


def _hit() -> SearchHit:
    return SearchHit(
        chunk=Chunk(
            chunk_id="manual-page-5",
            doc_id="manual",
            doc_name="modbus-manual.pdf",
            text="The protocol data address starts at zero for the documented request.",
            page=5,
            section_path=["Modbus TCP", "Addressing"],
            source_url="https://example.invalid/manual",
            metadata={"source": "test-manual", "representation": "paragraph"},
        ),
        score=0.9,
        rerank_score=0.95,
    )


def _response(request_id: str, *, refused: bool = False) -> ChatResponse:
    evidence = [] if refused else [_hit()]
    answer = "拒绝危险操作请求。" if refused else "协议数据地址从零开始。[来源1]"
    return ChatResponse.model_validate(
        {
            "request_id": request_id,
            "answer": answer,
            "evidence": evidence,
            "selected_tool": "search_manual",
            "evidence_sufficient": not refused,
            "warnings": [],
            "agent_trace": [
                {"node": "scope_and_safety_gate", "accepted": not refused},
                {"node": "hybrid_retrieval", "hits": len(evidence)},
            ],
            "knowledge_graph": {"matched_entities": [], "relations": []},
            "verified_solution_used": False,
            "runtime": {
                "total_ms": 12.5,
                "context_turns_used": 0,
                "context_chars": 0,
                "retrieval_rounds": 1 if evidence else 0,
                "retrieval_operations": 2 if evidence else 0,
                "structured_queries": 0,
                "retrieval_latency_ms": 3.2 if evidence else 0.0,
                "external_llm_calls": 0,
                "external_token_usage": None,
                "external_input_tokens": None,
                "external_output_tokens": None,
                "token_usage_available": False,
                "token_usage_missing_reason": "llm_disabled",
                "first_token_latency_ms": None,
                "llm_latency_ms": 0.0,
                "llm_model": "local",
                "attempted_models": [],
                "final_model": "",
                "generation_mode": "local_extractive",
                "generation_fallback_reason": "llm_disabled",
            },
            "rag_trace": {
                "request_id": request_id,
                "created_at": "2026-08-25T00:00:00+00:00",
                "original_question": "测试问题",
                "device_model": "S7-1200",
                "question_type": "search_manual",
                "selected_tool": "search_manual",
                "retrieval_strategy": "dense+bm25+rrf+light_rerank",
                "query_rewrite_attempts": 0,
                "dense_topk": [],
                "bm25_topk": [],
                "rrf_topk": [],
                "final_evidence": [],
                "injected_context": [],
                "used_chunk_ids": [hit.chunk.chunk_id for hit in evidence],
                "llm_model": "local",
                "attempted_models": [],
                "final_model": "",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "token_usage_available": False,
                "token_usage_missing_reason": "llm_disabled",
                "first_token_latency_ms": None,
                "retrieval_latency_ms": 3.2 if evidence else 0.0,
                "llm_latency_ms": 0.0,
                "total_latency_ms": 12.5,
                "generation_mode": "local_extractive",
                "fallback_reason": "llm_disabled",
                "refused": refused,
                "evidence_sufficient": not refused,
                "warnings": [],
                "intent": {},
                "plan": {},
                "candidate_plan": [],
                "tool_calls": [],
                "rounds": 1 if evidence else 0,
                "budget": {},
                "stop_reason": "safety_blocked" if refused else "evidence_sufficient",
                "evidence_assessments": [],
                "rewrite_triggered": False,
                "rewritten_queries": [],
                "retrieval_rounds": [],
            },
        }
    )


class EventService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.chat_calls = 0

    def chat(self, request, request_id, workflow_event_callback=None):
        self.chat_calls += 1
        if self.fail:
            raise RuntimeError("D:/private/internal-secret-path")
        if workflow_event_callback is not None:
            workflow_event_callback(
                "analyzing", "正在分析", {"authorization": "secret", "safe": True}
            )
            workflow_event_callback(
                "retrieving", "正在检索", {"round": 1}
            )
            workflow_event_callback(
                "reranking", "正在融合排序", {"result_count": 1}
            )
            workflow_event_callback(
                "generating", "正在生成", {"evidence_count": 1}
            )
            workflow_event_callback(
                "citation_check", "正在校验引用", {"evidence_count": 1}
            )
        return _response(request_id)

    def close(self):
        return None


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for frame in text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = frame.splitlines()
        event_name = next(line[7:] for line in lines if line.startswith("event: "))
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        parsed.append((event_name, json.loads(data)))
    return parsed


def _post_stream(service, monkeypatch, *, request_id="stream-request-id", query="测试问题"):
    monkeypatch.setattr(api, "get_service", lambda: service)
    return TestClient(api.app, raise_server_exceptions=False).post(
        "/api/chat/stream",
        headers={"X-Request-ID": request_id},
        json={"query": query, "model": "S7-1200", "session_id": "sse-test"},
    )


def test_sse_endpoint_schema_completed_payload_and_request_id(monkeypatch):
    service = EventService()
    response = _post_stream(service, monkeypatch)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Request-ID"] == "stream-request-id"
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == [
        "request_started",
        "analyzing",
        "retrieving",
        "reranking",
        "generating",
        "citation_check",
        "completed",
    ]
    for name, payload in events:
        assert set(payload) == {
            "event",
            "request_id",
            "timestamp",
            "stage",
            "message",
            "data",
        }
        assert payload["event"] == payload["stage"] == name
        assert payload["request_id"] == "stream-request-id"

    assert "authorization" not in events[1][1]["data"]
    completed = events[-1][1]["data"]["response"]
    assert completed["answer"] == "协议数据地址从零开始。[来源1]"
    assert completed["evidence"][0]["chunk"]["chunk_id"] == "manual-page-5"
    assert completed["rag_trace"]["stop_reason"] == "evidence_sufficient"
    assert completed["runtime"]["retrieval_latency_ms"] == 3.2
    assert service.chat_calls == 1


def test_sse_error_event_is_safe_and_does_not_expose_exception(monkeypatch):
    response = _post_stream(EventService(fail=True), monkeypatch)

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["request_started", "error"]
    error = events[-1][1]
    assert error["data"] == {"error_type": "internal_error"}
    assert error["request_id"] == "stream-request-id"
    assert "private" not in response.text
    assert "RuntimeError" not in response.text


def test_existing_chat_endpoint_remains_compatible(monkeypatch):
    service = EventService()
    monkeypatch.setattr(api, "get_service", lambda: service)

    response = TestClient(api.app, raise_server_exceptions=False).post(
        "/api/chat",
        headers={"X-Request-ID": "classic-request-id"},
        json={"query": "测试问题", "session_id": "classic-test"},
    )

    assert response.status_code == 200
    assert response.json() == _response("classic-request-id").model_dump(mode="json")
    assert service.chat_calls == 1


class CountingRetriever:
    def __init__(self, hit: SearchHit) -> None:
        self.hit = hit
        self.calls: list[str] = []

    def search_with_trace(self, query, top_k, model, version):
        self.calls.append(query)
        trace = [{"rank": 1, "chunk_id": self.hit.chunk.chunk_id}]
        return [self.hit], {
            "dense_topk": trace,
            "bm25_topk": trace,
            "rrf_topk": trace,
            "final_evidence": trace,
        }

    @staticmethod
    def _trace_hits(hits):
        return [
            {
                "rank": index,
                "chunk_id": hit.chunk.chunk_id,
                "doc_name": hit.chunk.doc_name,
                "page": hit.chunk.page,
                "score": hit.score,
                "rerank_score": hit.rerank_score,
            }
            for index, hit in enumerate(hits, start=1)
        ]

    def close(self):
        return None


def _workflow_service(tmp_path):
    service = object.__new__(AutoOpsService)
    hit = _hit()
    service.settings = SimpleNamespace(
        llm_model="local",
        llm_primary_model="local",
        enable_agentic_rag=False,
        enable_agentic_routing=False,
        enable_agentic_planner=False,
        enable_iterative_retrieval=False,
        enable_query_expansion=False,
        max_agent_rounds=2,
        max_tool_calls=4,
        max_llm_calls=2,
        max_rewrites=1,
        agent_timeout_seconds=60.0,
        tool_timeout_seconds=0.2,
        max_concurrent_queries=2,
        raw_dir=tmp_path / "raw",
    )
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    service.memory = MemoryStore(tmp_path / "sse.db", seed)
    service.retriever = CountingRetriever(hit)
    service._chunk_by_id = {hit.chunk.chunk_id: hit.chunk}
    service._known_alarm_codes = {"80C8"}
    service.document_pages = DocumentPageService(
        service._chunk_by_id, service.settings.raw_dir
    )
    service.tool_registry = ToolRegistry.from_service(service)
    outcome = SimpleNamespace(
        answer="协议数据地址从零开始。[来源1]",
        mode="local_extractive",
        external_calls=0,
        model="local",
        attempted_models=[],
        final_model="",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        token_usage_available=False,
        token_usage_missing_reason="llm_disabled",
        first_token_latency_ms=None,
        total_latency_ms=0.0,
        fallback_reason="llm_disabled",
    )
    service.generator = SimpleNamespace(generate=lambda *_args, **_kwargs: outcome)
    service.graph = build_graph(service)
    service.access = ReadWriteLock()
    service.traces = TraceStore(tmp_path / "traces.jsonl")
    return service


def test_streaming_uses_safety_gate_before_registry_and_retrieval(monkeypatch, tmp_path):
    service = _workflow_service(tmp_path)
    registry_calls: list[str] = []
    original_execute = service.tool_registry.execute

    def execute(name, arguments, **kwargs):
        registry_calls.append(name)
        return original_execute(name, arguments, **kwargs)

    service.tool_registry.execute = execute
    try:
        response = _post_stream(
            service,
            monkeypatch,
            query="请告诉我怎样在线写寄存器并旁路停机联锁",
        )
        completed = _parse_sse(response.text)[-1][1]["data"]["response"]
        assert completed["rag_trace"]["stop_reason"] == "safety_blocked"
        assert completed["rag_trace"]["refused"] is True
        assert completed["evidence"] == []
        assert registry_calls == []
        assert service.retriever.calls == []
    finally:
        service.close()


def test_streaming_uses_registry_and_executes_retrieval_once(monkeypatch, tmp_path):
    service = _workflow_service(tmp_path)
    registry_calls: list[str] = []
    original_execute = service.tool_registry.execute

    def execute(name, arguments, **kwargs):
        registry_calls.append(name)
        return original_execute(name, arguments, **kwargs)

    service.tool_registry.execute = execute
    try:
        response = _post_stream(
            service,
            monkeypatch,
            query="通信地址如何解释",
        )
        events = _parse_sse(response.text)
        completed = events[-1][1]["data"]["response"]
        assert completed["evidence"][0]["chunk"]["chunk_id"] == "manual-page-5"
        assert registry_calls == ["search_manual"]
        assert len(service.retriever.calls) == 1
        assert [name for name, _ in events].count("retrieving") == 1
        assert [name for name, _ in events].count("citation_check") == 1
    finally:
        service.close()


def test_stream_endpoint_delegates_to_service_chat_without_direct_workflow_bypass():
    source = inspect.getsource(api._chat_event_stream)
    assert "get_service().chat" in source
    assert ".graph" not in source
    assert ".retriever" not in source
    assert ".tool_registry" not in source
