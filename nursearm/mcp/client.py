"""Local MCP client and Claude agent loop for NurseArm."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nursearm import config

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12
SYSTEM_PROMPT = """You are the NurseArm task-level agent.
Use the available MCP tools to satisfy robot-assistance requests.
For testing requests, select the most semantically appropriate dummy skill.
Never claim a skill succeeded unless its MCP result reports success.
Never invent tools or raw motor commands. Keep the final reply concise.
"""


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

    async def claude_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in await self.list_tools()
        ]

    def _require_session(self) -> ClientSession:
        if self.session is None:
            raise RuntimeError("MCP client is not connected")
        return self.session


class ClaudeMCPAgent:
    """Let Claude discover and execute NurseArm capabilities exclusively via MCP."""

    def __init__(self, mcp_client: NurseArmMCPClient, audit: Any | None = None) -> None:
        self.mcp = mcp_client
        self.audit = audit
        self.client = AsyncAnthropic(api_key=config.env("ANTHROPIC_API_KEY", required=True))
        self.model = config.env("NURSEARM_MODEL", DEFAULT_MODEL)

    async def handle(self, user_intent: str) -> str:
        self._log({"event": "user_intent", "text": user_intent})
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_intent}]
        tools = await self.mcp.claude_tools()

        for _ in range(MAX_TURNS):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if not tool_uses:
                reply = " ".join(
                    block.text for block in response.content if block.type == "text"
                ).strip()
                self._log({"event": "report", "text": reply})
                return reply

            results = []
            for tool_use in tool_uses:
                result = await self.mcp.call_tool(tool_use.name, tool_use.input)
                self._log(
                    {
                        "event": "mcp_tool",
                        "tool": tool_use.name,
                        "args": tool_use.input,
                        "result": result,
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result),
                    }
                )
            messages.append({"role": "user", "content": results})

        return "Stopped after reaching the agent turn limit."

    def _log(self, event: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.log(event)


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
        elif args.chat:
            print(await ClaudeMCPAgent(client).handle(args.chat))
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the local NurseArm MCP client.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-tools", action="store_true")
    group.add_argument("--call", metavar="TOOL")
    group.add_argument("--chat", metavar="MESSAGE")
    parser.add_argument("--arguments", default="{}", help="JSON object for --call.")
    asyncio.run(_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
