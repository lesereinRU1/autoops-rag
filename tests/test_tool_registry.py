from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.graph import build_graph
from app.agent.memory import MemoryStore
from app.agent.tool_registry import ToolRegistry
from app.document_service import DocumentPageService
from app.models import (
    Chunk,
    GetDocumentPageInput,
    LookupFaultCodeInput,
    LookupParameterInput,
    SearchHit,
    SearchManualInput,
    ToolCallTrace,
    ToolResult,
)


class FakeRetriever:
    def __init__(self, hit: SearchHit) -> None:
        self.hit = hit
        self.calls: list[dict] = []

    def search_with_trace(self, query, top_k, model, version):
        self.calls.append(
            {"query": query, "top_k": top_k, "model": model, "version": version}
        )
        traced = [{"rank": 1, "chunk_id": self.hit.chunk.chunk_id}]
        return [self.hit], {
            "dense_topk": traced,
            "bm25_topk": traced,
            "rrf_topk": traced,
            "final_evidence": traced,
        }

    @staticmethod
    def _trace_hits(hits):
        return [
            {"rank": index, "chunk_id": hit.chunk.chunk_id}
            for index, hit in enumerate(hits, start=1)
        ]


def _hit() -> SearchHit:
    return SearchHit(
        chunk=Chunk(
            chunk_id="manual-1-page-12",
            doc_id="manual-1",
            doc_name="manual-one.pdf",
            text="16#80C8 and RD_MB_DATA_LEN are documented on this page.",
            page=12,
            model="S7-1200",
            version="V4.6",
        ),
        score=1.0,
        rerank_score=1.0,
    )


@pytest.fixture
def registry(tmp_path):
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "registry.db", seed)
    hit = _hit()
    retriever = FakeRetriever(hit)
    document_pages = DocumentPageService(
        {hit.chunk.chunk_id: hit.chunk}, tmp_path / "raw"
    )
    value = ToolRegistry(
        memory=memory,
        retriever=retriever,
        document_pages=document_pages,
        timeout_seconds=0.2,
        max_tool_calls=4,
        max_workers=2,
    )
    try:
        yield value, retriever
    finally:
        value.close()


def test_four_tools_are_registered_with_independent_input_models(registry):
    tools, _ = registry

    assert set(tools.names) == {
        "search_manual",
        "lookup_fault_code",
        "lookup_parameter",
        "get_document_page",
    }
    assert tools.input_model("search_manual") is SearchManualInput
    assert tools.input_model("lookup_fault_code") is LookupFaultCodeInput
    assert tools.input_model("lookup_parameter") is LookupParameterInput
    assert tools.input_model("get_document_page") is GetDocumentPageInput
    assert tools.input_model("lookup_alarm_code") is LookupFaultCodeInput


def test_pydantic_inputs_reject_empty_invalid_and_ambiguous_values(registry):
    with pytest.raises(ValidationError):
        SearchManualInput(query="   ")
    with pytest.raises(ValidationError):
        SearchManualInput(query="ok", top_k=21)
    with pytest.raises(ValidationError):
        LookupFaultCodeInput(code="")
    with pytest.raises(ValidationError):
        LookupParameterInput(name="")
    with pytest.raises(ValidationError):
        GetDocumentPageInput(page=0, document_id="manual-1")
    with pytest.raises(ValidationError):
        GetDocumentPageInput(page=1)

    tools, retriever = registry
    result = tools.execute("search_manual", {"query": "", "top_k": 99})
    assert result.success is False
    assert result.error == "tool_arguments_invalid"
    assert result.call_trace is not None
    assert result.call_trace.executed is False
    assert retriever.calls == []


def test_fault_and_parameter_tools_return_structured_found_and_empty_results(registry):
    tools, _ = registry

    fault = tools.execute("lookup_fault_code", {"code": "16#80C8"})
    missing_fault = tools.execute("lookup_fault_code", {"code": "16#FFFF"})
    parameter = tools.execute(
        "lookup_parameter", {"name": "RD_MB_DATA_LEN 的范围"}
    )
    missing_parameter = tools.execute(
        "lookup_parameter", {"name": "NOT_A_REAL_PARAMETER"}
    )

    assert fault.success and fault.result_count == 1
    assert fault.data["record"]["code"] == "16#80C8"
    assert fault.data["record"]["causes"]
    assert missing_fault.success and missing_fault.result_count == 0
    assert missing_fault.data == {"record": None}
    assert parameter.success and parameter.result_count == 1
    assert parameter.data["record"]["name"] == "Read Holding Registers quantity"
    assert missing_parameter.success and missing_parameter.result_count == 0


def test_search_manual_reuses_existing_retriever_once(registry):
    tools, retriever = registry

    result = tools.execute(
        "search_manual",
        {"query": "MB_CLIENT", "model": "S7-1200", "version": "V4.6", "top_k": 3},
    )

    assert result.success is True
    assert result.result_count == 1
    assert result.evidence[0].chunk.chunk_id == "manual-1-page-12"
    assert result.data["hits"][0]["chunk"]["chunk_id"] == "manual-1-page-12"
    assert len(retriever.calls) == 1
    assert retriever.calls[0] == {
        "query": "MB_CLIENT",
        "top_k": 3,
        "model": "S7-1200",
        "version": "V4.6",
    }


def test_get_document_page_resolves_processed_page_and_reports_missing(registry):
    tools, _ = registry

    found = tools.execute(
        "get_document_page", {"document_id": "manual-1", "page": 12}
    )
    missing = tools.execute(
        "get_document_page", {"document_name": "manual-one.pdf", "page": 999}
    )

    assert found.success is True
    assert found.result_count == 1
    assert found.data["page"] == 12
    assert found.data["chunks"][0]["chunk_id"] == "manual-1-page-12"
    assert missing.success is False
    assert missing.result_count == 0
    assert missing.error == "document_page_not_found"


def test_unknown_tool_result_and_trace_are_complete(registry):
    tools, _ = registry

    result = tools.execute("not_registered", {"query": "test", "api_key": "secret"})
    payload = result.model_dump(mode="json")

    assert result.success is False
    assert result.error == "unknown_tool"
    assert result.tool_name == result.tool == "not_registered"
    assert {
        "tool_name",
        "success",
        "data",
        "result_count",
        "error",
        "latency_ms",
    }.issubset(payload)
    assert result.call_trace is not None
    trace = result.call_trace.model_dump(mode="json")
    assert {
        "tool_name",
        "arguments",
        "started_at",
        "latency_ms",
        "success",
        "result_count",
        "error",
    }.issubset(trace)
    assert "api_key" not in trace["arguments"]


def test_registry_normalizes_timeout_and_handler_exception(registry):
    tools, _ = registry

    def slow(_payload):
        time.sleep(0.05)
        return ToolResult(tool_name="slow", success=True, result_count=1)

    def broken(_payload):
        raise RuntimeError("database unavailable")

    tools.register("slow", SearchManualInput, slow)
    tools.register("broken", SearchManualInput, broken)

    timed_out = tools.execute(
        "slow", {"query": "test"}, timeout_seconds=0.001
    )
    failed = tools.execute("broken", {"query": "test"})

    assert timed_out.success is False
    assert timed_out.error == "tool_timeout"
    assert timed_out.call_trace is not None and timed_out.call_trace.executed is True
    assert failed.success is False
    assert failed.error == "tool_execution_failed"
    assert failed.metadata["error_type"] == "RuntimeError"


def test_max_tool_calls_rejects_without_executing_handler(registry):
    tools, retriever = registry

    result = tools.execute(
        "search_manual",
        {"query": "test"},
        tool_calls=[{"tool_name": "lookup_fault_code", "executed": True}],
        max_tool_calls=1,
    )

    assert result.success is False
    assert result.error == "max_tool_calls_reached"
    assert result.call_trace is not None
    assert result.call_trace.executed is False
    assert retriever.calls == []


def test_fixed_graph_stops_before_search_when_tool_budget_is_exhausted(registry):
    tools, retriever = registry
    outcome = SimpleNamespace(
        answer="当前证据不足。",
        mode="local_extractive",
        external_calls=0,
        model="local",
        attempted_models=[],
        final_model="",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        token_usage_available=False,
        token_usage_missing_reason="evidence_insufficient",
        first_token_latency_ms=None,
        total_latency_ms=0.0,
        fallback_reason="evidence_insufficient",
    )
    service = SimpleNamespace(
        settings=SimpleNamespace(
            llm_model="local",
            llm_primary_model="local",
            enable_query_expansion=False,
            enable_agentic_routing=False,
            enable_agentic_planner=False,
            enable_iterative_retrieval=False,
            max_agent_rounds=2,
            max_tool_calls=1,
            max_llm_calls=2,
            agent_timeout_seconds=60.0,
            max_rewrites=1,
        ),
        memory=tools._sqlite.memory,
        tool_registry=tools,
        retriever=retriever,
        generator=SimpleNamespace(generate=lambda *_args, **_kwargs: outcome),
        scope_refusal=lambda *_args: None,
        evidence_supports_query=lambda *_args: False,
    )

    result = build_graph(service).invoke(
        {
            "question": "故障码 16#80C8 表示什么",
            "original_question": "故障码 16#80C8 表示什么",
            "model": "S7-1200",
            "version": "",
            "session_id": "registry-budget-test",
        }
    )

    assert result["stop_reason"] == "max_tool_calls_reached"
    assert result["budget"]["tool_calls_used"] == 1
    assert result["tool_calls"][0]["tool_name"] == "lookup_fault_code"
    assert result["tool_calls"][0]["executed"] is True
    assert result["tool_calls"][1]["tool_name"] == "search_manual"
    assert result["tool_calls"][1]["executed"] is False
    assert retriever.calls == []


class GraphMemory:
    def expand_knowledge_graph(self, _question):
        return {"matched_entities": [], "expansion_terms": [], "relations": []}

    def find_verified_solution(self, _question, _model):
        return None

    def lookup_alarm(self, *_args):
        raise AssertionError("Graph bypassed ToolRegistry for fault lookup")

    def find_parameter_in_text(self, *_args):
        raise AssertionError("Graph bypassed ToolRegistry for parameter lookup")


class SpyRegistry:
    def __init__(self, hit: SearchHit) -> None:
        self.hit = hit
        self.calls: list[str] = []

    def execute(self, tool_name, arguments, **_kwargs):
        self.calls.append(tool_name)
        evidence = [self.hit] if tool_name == "search_manual" else []
        result_count = len(evidence) if evidence else 1
        result = ToolResult(
            tool_name=tool_name,
            success=True,
            content=f"{tool_name} structured result" if not evidence else "",
            data={},
            result_count=result_count,
            evidence=evidence,
            metadata={
                "retrieval_trace": {
                    "dense_topk": [],
                    "bm25_topk": [],
                    "rrf_topk": [],
                    "final_evidence": [],
                }
            }
            if evidence
            else {},
        )
        result.call_trace = ToolCallTrace(
            tool_name=tool_name,
            arguments=arguments.model_dump(mode="json"),
            started_at=datetime.now(timezone.utc),
            latency_ms=0.1,
            success=True,
            result_count=result_count,
        )
        result.latency_ms = 0.1
        return result


def _graph_service():
    hit = _hit()
    registry = SpyRegistry(hit)
    outcome = SimpleNamespace(
        answer="结论 [来源1：manual-one.pdf，第12页]",
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
    service = SimpleNamespace(
        settings=SimpleNamespace(
            llm_model="local",
            llm_primary_model="local",
            enable_query_expansion=False,
            enable_agentic_routing=False,
            enable_agentic_planner=False,
            enable_iterative_retrieval=False,
            max_agent_rounds=2,
            max_tool_calls=4,
            max_llm_calls=2,
            agent_timeout_seconds=60.0,
            max_rewrites=1,
        ),
        memory=GraphMemory(),
        tool_registry=registry,
        retriever=SimpleNamespace(
            _trace_hits=lambda hits: [
                {"rank": index, "chunk_id": hit.chunk.chunk_id}
                for index, hit in enumerate(hits, start=1)
            ]
        ),
        generator=SimpleNamespace(generate=lambda *_args, **_kwargs: outcome),
        scope_refusal=lambda *_args: None,
        evidence_supports_query=lambda *_args: True,
    )
    return service, registry


@pytest.mark.parametrize(
    ("question", "expected_tool"),
    [
        ("故障码 16#80C8 表示什么", "lookup_fault_code"),
        ("RD_MB_DATA_LEN 参数范围是多少", "lookup_parameter"),
    ],
)
def test_fixed_structured_paths_execute_through_registry(question, expected_tool):
    service, registry = _graph_service()

    result = build_graph(service).invoke(
        {
            "question": question,
            "original_question": question,
            "model": "S7-1200",
            "version": "",
            "session_id": "registry-graph-test",
        }
    )

    assert result["execution_tool"] == expected_tool
    assert result["selected_tool"] == {
        "lookup_fault_code": "lookup_alarm_code",
        "lookup_parameter": "check_parameter_range",
    }[expected_tool]
    assert registry.calls == [expected_tool, "search_manual"]
    assert [item["tool_name"] for item in result["tool_calls"]] == registry.calls
    assert result["evidence_sufficient"] is True
