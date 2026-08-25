from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def print_result(name: str, result) -> None:
    payload = result.structured_content
    if payload is None:
        text_blocks = [
            block.text for block in result.content if getattr(block, "type", "") == "text"
        ]
        payload = json.loads(text_blocks[0]) if text_blocks else {}
    print(f"\n{name}:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result.is_error:
        print(f"MCP tool call failed: {payload.get('error', 'unknown_error')}")


async def run() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        cwd=PROJECT_ROOT,
    )
    try:
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                discovered = await session.list_tools()
                print("Available tools:")
                for tool in discovered.tools:
                    print(f"- {tool.name}: {tool.description}")

                fault = await session.call_tool(
                    "lookup_fault_code",
                    {"code": "16#80C8", "model": "S7-1200"},
                )
                print_result("lookup_fault_code", fault)

                search = await session.call_tool(
                    "search_manual",
                    {"query": "MB_CLIENT 16#80C8", "model": "S7-1200", "top_k": 3},
                )
                print_result("search_manual", search)
    except Exception as exc:
        raise SystemExit(
            f"MCP client failed ({type(exc).__name__}): {exc}. "
            "Run this command from an initialized AutoOps repository."
        ) from exc


if __name__ == "__main__":
    asyncio.run(run())
