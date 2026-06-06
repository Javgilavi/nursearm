"""Anthropic Claude agent that executes NurseArm tools through MCP."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import anthropic

from nursearm import config
from nursearm.mcp.client import NurseArmMCPClient
from nursearm.orchestrator.ollama_agent import SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12


class ClaudeUnavailableError(RuntimeError):
    """Raised when the Anthropic API is unreachable or the key is invalid."""


class ClaudeMCPAgent:
    """Run Claude as the NurseArm task agent via MCP tools."""

    def __init__(self, mcp_client: NurseArmMCPClient, audit: Any | None = None) -> None:
        self.mcp = mcp_client
        self.audit = audit
        self.model = config.env("CLAUDE_MODEL", DEFAULT_MODEL)
        api_key = config.env("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ClaudeUnavailableError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._chat_lock = asyncio.Lock()
        self._history: list[dict[str, Any]] = []

    async def close(self) -> None:
        await self._client.close()

    async def handle(self, user_intent: str) -> str:
        async with self._chat_lock:
            return await self._handle_locked(user_intent)

    async def _handle_locked(self, user_intent: str) -> str:
        self._log({"event": "user_intent", "text": user_intent})
        self._history.append({"role": "user", "content": user_intent})

        mcp_tools = await self.mcp.list_tools()
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            }
            for t in mcp_tools
        ]

        for _ in range(MAX_TURNS):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=self._history,
                    tools=tools,
                )
            except anthropic.AuthenticationError as exc:
                raise ClaudeUnavailableError(f"Invalid Anthropic API key: {exc}") from exc
            except anthropic.APIConnectionError as exc:
                raise ClaudeUnavailableError(f"Cannot reach Anthropic API: {exc}") from exc
            except anthropic.APIStatusError as exc:
                raise ClaudeUnavailableError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc

            # Append assistant turn to history
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    name = block.name
                    args = block.input or {}
                    self._log({"event": "mcp_tool", "tool": name, "args": args})
                    try:
                        result = await self.mcp.call_tool(name, args)
                    except Exception as exc:
                        result = {"error": str(exc)}
                    self._log({"event": "mcp_tool_result", "tool": name, "result": result})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
                self._history.append({"role": "user", "content": tool_results})
                continue

            # Final text reply
            reply = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            ).strip()
            self._log({"event": "report", "text": reply})
            self._trim_history()
            return reply or "No reply from Claude."

        self._trim_history()
        return "Stopped after reaching the agent turn limit."

    def _trim_history(self) -> None:
        if len(self._history) > 40:
            self._history = self._history[-40:]

    def _log(self, event: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.log(event)

    async def model_status(self) -> dict[str, Any]:
        try:
            # Lightweight check — just verify the key works
            await self._client.models.retrieve(self.model)
            return {"available": True, "model": self.model, "backend": "claude"}
        except Exception as exc:
            return {"available": False, "model": self.model, "backend": "claude", "error": str(exc)}
