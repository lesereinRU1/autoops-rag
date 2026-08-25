from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path

import pytest
from mcp import Client

from app.agent.memory import MemoryStore
from app.agent.tool_registry import ToolRegistry
from app.document_service import DocumentPageService
from app.mcp.server import (
    MCP_TOOL_NAMES,
    MCPToolAdapter,
    create_server,
    tool_result_to_mcp,
)
from app.models import (
    Chunk,
    LookupFaultCodeInput,
    SearchHit,
    ToolResult,
)


class FakeRetriever:
    def __init__(self, hit: SearchHit) -> None:
        self.hit = hit
        self.calls: list[dict[str, object]] = []

    def search_with_trace(self, query, top_k, model, version):
        self.calls.append(
            {"query": query, "top_k": top_k, "model": model, "version": version}
        )
        trace_hit = {"rank": 1, "chunk_id": self.hit.chunk.chunk_id}
        return [self.hit], {
            "dense_topk": [trace_hit],
            "bm25_topk": [trace_hit],
            "rrf_topk": [trace_hit],
            "final_evidence": [trace_hit],
        }


class TestService:
    __test__ = False

    def __init__(self, registry: ToolRegistry) -> None:
        self.tool_registry = registry
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.tool_registry.close()


@pytest.fixture
def mcp_service(tmp_path):
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    memory = MemoryStore(tmp_path / "mcp.db", seed)
    chunk = Chunk(
        chunk_id="manual-1-page-12",
        doc_id="manual-1",
        doc_name="manual-one.pdf",
        text="16#80C8 and RD_MB_DATA_LEN are documented on this page.",
        page=12,
        model="S7-1200",
        version="V4.6",
    )
    retriever = FakeRetriever(SearchHit(chunk=chunk, score=1.0, rerank_score=1.0))
    registry = ToolRegistry(
        memory=memory,
        retriever=retriever,
        document_pages=DocumentPageService({chunk.chunk_id: chunk}, tmp_path / "raw"),
        timeout_seconds=0.2,
        max_tool_calls=4,
        max_workers=2,
    )
    return TestService(registry), retriever


async def _with_client(service: TestService, operation):
    server = create_server(lambda: service)
    async with Client(server, mode="legacy") as client:
        return await operation(client)


def _run(service: TestService, operation):
    return asyncio.run(_with_client(service, operation))


def test_server_initializes_and_discovers_exact_registry_tools_with_pydantic_schema(
    mcp_service,
):
    service, _ = mcp_service

    async def operation(client):
        return await client.list_tools()

    discovered = _run(service, operation)
    assert tuple(tool.name for tool in discovered.tools) == MCP_TOOL_NAMES
    assert set(MCP_TOOL_NAMES) == set(service.tool_registry.names)

    by_name = {tool.name: tool for tool in discovered.tools}
    for name in MCP_TOOL_NAMES:
        input_model = service.tool_registry.input_model(name)
        assert input_model is not None
        assert by_name[name].input_schema == input_model.model_json_schema()
        assert by_name[name].description
        assert by_name[name].output_schema == ToolResult.model_json_schema(
            mode="serialization"
        )

    search_schema = by_name["search_manual"].input_schema
    assert search_schema["required"] == ["query"]
    assert search_schema["properties"]["top_k"]["minimum"] == 1
    assert search_schema["properties"]["top_k"]["maximum"] == 20
    assert search_schema["properties"]["query"]["description"]
    page_schema = by_name["get_document_page"].input_schema
    assert page_schema["required"] == ["page"]
    assert page_schema["properties"]["page"]["minimum"] == 1
    assert service.close_calls == 1


def test_lookup_fault_code_found_and_empty_results(mcp_service):
    service, _ = mcp_service

    async def operation(client):
        found = await client.call_tool("lookup_fault_code", {"code": "16#80C8"})
        missing = await client.call_tool("lookup_fault_code", {"code": "16#FFFF"})
        return found, missing

    found, missing = _run(service, operation)
    assert found.is_error is False
    assert found.structured_content["success"] is True
    assert found.structured_content["result_count"] == 1
    assert found.structured_content["data"]["record"]["code"] == "16#80C8"
    assert missing.is_error is False
    assert missing.structured_content["success"] is True
    assert missing.structured_content["result_count"] == 0
    assert missing.structured_content["data"] == {"record": None}


def test_lookup_parameter_returns_structured_result(mcp_service):
    service, _ = mcp_service

    async def operation(client):
        return await client.call_tool(
            "lookup_parameter", {"name": "RD_MB_DATA_LEN 的范围"}
        )

    result = _run(service, operation)
    assert result.is_error is False
    assert result.structured_content["tool_name"] == "lookup_parameter"
    assert result.structured_content["result_count"] == 1
    assert (
        result.structured_content["data"]["record"]["name"]
        == "Read Holding Registers quantity"
    )


def test_search_manual_calls_the_existing_registry_and_retriever_once(mcp_service):
    service, retriever = mcp_service
    registry_calls: list[str] = []
    original_execute = service.tool_registry.execute

    def execute(name, arguments, **kwargs):
        registry_calls.append(name)
        return original_execute(name, arguments, **kwargs)

    service.tool_registry.execute = execute

    async def operation(client):
        return await client.call_tool(
            "search_manual",
            {"query": "MB_CLIENT", "model": "S7-1200", "version": "V4.6", "top_k": 3},
        )

    result = _run(service, operation)
    assert result.is_error is False
    assert result.structured_content["evidence"][0]["chunk"]["chunk_id"] == "manual-1-page-12"
    assert registry_calls == ["search_manual"]
    assert retriever.calls == [
        {
            "query": "MB_CLIENT",
            "top_k": 3,
            "model": "S7-1200",
            "version": "V4.6",
        }
    ]


def test_get_document_page_found_and_missing(mcp_service):
    service, _ = mcp_service

    async def operation(client):
        found = await client.call_tool(
            "get_document_page", {"document_id": "manual-1", "page": 12}
        )
        missing = await client.call_tool(
            "get_document_page", {"document_name": "manual-one.pdf", "page": 999}
        )
        return found, missing

    found, missing = _run(service, operation)
    assert found.is_error is False
    assert found.structured_content["data"]["page"] == 12
    assert found.structured_content["provenance"][0]["page"] == 12
    assert missing.is_error is True
    assert missing.structured_content["error"] == "document_page_not_found"


def test_parameter_validation_error_remains_a_business_tool_result(mcp_service):
    service, retriever = mcp_service

    async def operation(client):
        return await client.call_tool("search_manual", {"query": "", "top_k": 99})

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["success"] is False
    assert result.structured_content["error"] == "tool_arguments_invalid"
    assert result.structured_content["call_trace"]["executed"] is False
    assert retriever.calls == []


def test_handler_exception_is_normalized_by_registry(mcp_service):
    service, _ = mcp_service

    def broken(_payload):
        raise RuntimeError("database unavailable")

    service.tool_registry.register(
        "lookup_fault_code", LookupFaultCodeInput, broken
    )

    async def operation(client):
        return await client.call_tool("lookup_fault_code", {"code": "16#80C8"})

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["error"] == "tool_execution_failed"
    assert result.structured_content["metadata"]["error_type"] == "RuntimeError"


def test_registry_budget_is_not_bypassed_by_mcp(mcp_service):
    service, retriever = mcp_service
    service.tool_registry.max_tool_calls = 0

    async def operation(client):
        return await client.call_tool("search_manual", {"query": "MB_CLIENT"})

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["error"] == "max_tool_calls_reached"
    assert result.structured_content["call_trace"]["executed"] is False
    assert retriever.calls == []


def test_registry_timeout_is_returned_through_mcp(mcp_service):
    service, _ = mcp_service

    def slow(_payload):
        time.sleep(0.05)
        return ToolResult(tool_name="search_manual", success=True)

    service.tool_registry.register(
        "search_manual",
        service.tool_registry.input_model("search_manual"),
        slow,
    )
    service.tool_registry.timeout_seconds = 0.001

    async def operation(client):
        return await client.call_tool("search_manual", {"query": "MB_CLIENT"})

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["error"] == "tool_timeout"
    assert result.structured_content["call_trace"]["executed"] is True


def test_unadvertised_legacy_alias_is_not_callable_over_mcp(mcp_service):
    service, _ = mcp_service

    async def operation(client):
        return await client.call_tool("lookup_alarm_code", {"code": "16#80C8"})

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["error"] == "unknown_tool"
    assert result.structured_content["call_trace"]["executed"] is False


def test_document_page_cannot_escape_the_allowed_raw_directory(mcp_service):
    service, _ = mcp_service
    raw_dir = service.tool_registry._document_pages.raw_dir
    raw_dir.mkdir(parents=True)
    (raw_dir.parent / "outside.pdf").write_bytes(b"outside the allowed corpus")

    async def operation(client):
        return await client.call_tool(
            "get_document_page",
            {"document_name": "../outside.pdf", "page": 1},
        )

    result = _run(service, operation)
    assert result.is_error is True
    assert result.structured_content["error"] == "document_page_not_found"
    assert result.structured_content["metadata"]["found"] is False


def test_tool_result_conversion_preserves_structured_and_text_payload():
    source = ToolResult(
        tool_name="lookup_fault_code",
        success=True,
        data={"record": {"code": "16#80C8"}},
        result_count=1,
        evidence=[],
        provenance=[{"document_name": "manual.pdf", "page": 12}],
        latency_ms=1.25,
    )

    converted = tool_result_to_mcp(source)
    assert converted.is_error is False
    assert converted.structured_content == source.model_dump(mode="json")
    assert json.loads(converted.content[0].text) == converted.structured_content
    assert converted.structured_content["provenance"][0]["page"] == 12


def test_one_server_lifecycle_reuses_one_service_for_multiple_calls(mcp_service):
    service, _ = mcp_service
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return service

    async def scenario():
        server = create_server(factory)
        async with Client(server, mode="legacy") as client:
            await client.list_tools()
            await client.call_tool("lookup_fault_code", {"code": "16#80C8"})
            await client.call_tool("lookup_parameter", {"name": "RD_MB_DATA_LEN"})

    asyncio.run(scenario())
    assert factory_calls == 1
    assert service.close_calls == 1


def test_mcp_module_is_only_a_registry_protocol_adapter():
    source = inspect.getsource(__import__("app.mcp.server", fromlist=["server"]))
    prohibited = (
        "search_with_trace",
        "SELECT ",
        "fitz.",
        "EvidenceGate",
        "CitationGuard",
        "build_graph",
        "/api/chat",
        "/api/search",
    )
    assert all(pattern not in source for pattern in prohibited)
    assert ".registry.execute" in source
    assert "AutoOpsService" in source


def test_adapter_rejects_a_registry_missing_one_required_tool(mcp_service):
    service, _ = mcp_service
    service.tool_registry._tools.pop("get_document_page")

    with pytest.raises(RuntimeError, match="get_document_page"):
        MCPToolAdapter(service.tool_registry).list_tools()

    service.close()
