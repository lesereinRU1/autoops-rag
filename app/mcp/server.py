from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Protocol

import anyio
import mcp.server.stdio
import mcp.types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server

from app import __version__
from app.agent.tool_registry import ToolRegistry
from app.models import ToolResult
from app.service import AutoOpsService


MCP_TOOL_NAMES = (
    "search_manual",
    "lookup_fault_code",
    "lookup_parameter",
    "get_document_page",
)

_TOOL_DESCRIPTIONS = {
    "search_manual": (
        "Search the industrial manual corpus with the shared hybrid retriever and "
        "return ranked evidence."
    ),
    "lookup_fault_code": (
        "Look up an exact equipment fault or alarm code in the shared structured store."
    ),
    "lookup_parameter": (
        "Look up a device parameter or table field in the shared structured store."
    ),
    "get_document_page": (
        "Read one page from an allowed indexed document by its known ID or filename."
    ),
}


class ServiceWithTools(Protocol):
    tool_registry: ToolRegistry

    def close(self) -> None: ...


ServiceFactory = Callable[[], ServiceWithTools]


def tool_result_to_mcp(result: ToolResult) -> types.CallToolResult:
    """Preserve one ToolResult in MCP structured and text-compatible forms."""
    payload = result.model_dump(mode="json")
    return types.CallToolResult(
        content=[
            types.TextContent(
                text=json.dumps(payload, ensure_ascii=False, sort_keys=True)
            )
        ],
        structuredContent=payload,
        isError=not result.success,
    )


class MCPToolAdapter:
    """Thin MCP schema/response adapter; all execution stays in ToolRegistry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def list_tools(self) -> list[types.Tool]:
        registered = set(self.registry.names)
        missing = set(MCP_TOOL_NAMES) - registered
        if missing:
            raise RuntimeError(
                f"ToolRegistry is missing MCP tools: {', '.join(sorted(missing))}"
            )

        tools: list[types.Tool] = []
        output_schema = ToolResult.model_json_schema(mode="serialization")
        for name in MCP_TOOL_NAMES:
            input_model = self.registry.input_model(name)
            if input_model is None:  # Guard against a registry changed mid-lifecycle.
                raise RuntimeError(f"ToolRegistry input model is unavailable: {name}")
            tools.append(
                types.Tool(
                    name=name,
                    description=_TOOL_DESCRIPTIONS[name],
                    inputSchema=input_model.model_json_schema(),
                    outputSchema=output_schema,
                )
            )
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, object] | None
    ) -> types.CallToolResult:
        # Registry owns validation, timeout, budget, sanitization, and business errors.
        result = await anyio.to_thread.run_sync(
            partial(
                self.registry.execute,
                name,
                arguments or {},
                allow_aliases=False,
                source="mcp",
            )
        )
        return tool_result_to_mcp(result)


@dataclass(frozen=True)
class MCPServerContext:
    service: ServiceWithTools
    adapter: MCPToolAdapter


def create_server(
    service_factory: ServiceFactory = AutoOpsService,
) -> Server[MCPServerContext]:
    """Build a server without initializing retriever/database resources on import."""

    @asynccontextmanager
    async def lifespan(_server: Server[MCPServerContext]) -> AsyncIterator[MCPServerContext]:
        service = service_factory()
        try:
            yield MCPServerContext(
                service=service,
                adapter=MCPToolAdapter(service.tool_registry),
            )
        finally:
            service.close()

    async def list_tools(
        context: ServerRequestContext[MCPServerContext],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=context.lifespan_context.adapter.list_tools())

    async def call_tool(
        context: ServerRequestContext[MCPServerContext],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        return await context.lifespan_context.adapter.call_tool(
            params.name, params.arguments
        )

    return Server(
        "autoops-rag",
        version=__version__,
        title="AutoOps RAG local tools",
        description="Local MCP adapter over the shared AutoOps ToolRegistry.",
        instructions=(
            "Use only the advertised industrial manual tools. Tool results are "
            "evidence-oriented and do not authorize equipment control actions."
        ),
        lifespan=lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def run_stdio(service_factory: ServiceFactory = AutoOpsService) -> None:
    server = create_server(service_factory)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
