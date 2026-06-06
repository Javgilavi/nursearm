"""Local MCP client for NurseArm tool discovery and execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class NurseArmMCPClient:
    """Manage one persistent stdio session with the local NurseArm MCP server."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        if self.session is not None:
            return
        env = os.environ.copy()
        env.setdefault("NURSEARM_MOCK", "1")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "nursearm.mcp.server"],
            env=env,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def close(self) -> None:
        await self._stack.aclose()
        self.session = None

    async def list_tools(self) -> list[Any]:
        return list((await self._require_session().list_tools()).tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self._require_session().call_tool(name, arguments or {})
        if result.isError:
            text = " ".join(getattr(item, "text", "") for item in result.content)
            raise RuntimeError(text or f"MCP tool {name!r} failed")
        if result.structuredContent is not None:
            return result.structuredContent
        text = "\n".join(getattr(item, "text", "") for item in result.content).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _require_session(self) -> ClientSession:
        if self.session is None:
            raise RuntimeError("MCP client is not connected")
        return self.session


async def _cli(args: argparse.Namespace) -> None:
    client = NurseArmMCPClient()
    await client.connect()
    try:
        if args.list_tools:
            for tool in await client.list_tools():
                print(f"{tool.name}: {tool.description}")
        elif args.call:
            arguments = json.loads(args.arguments)
            print(json.dumps(await client.call_tool(args.call, arguments), indent=2))
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the local NurseArm MCP client.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-tools", action="store_true")
    group.add_argument("--call", metavar="TOOL")
    parser.add_argument("--arguments", default="{}", help="JSON object for --call.")
    asyncio.run(_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
