"""Local Ollama agent that discovers and executes NurseArm tools through MCP."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from nursearm import config
from nursearm.mcp.client import NurseArmMCPClient

DEFAULT_MODEL = "qwen3:4b"
DEFAULT_URL = "http://127.0.0.1:11434"
MAX_TURNS = 12
SYSTEM_PROMPT = """/no_think
You are the NurseArm task-level assistant.
Use the available tools when a request requires a NurseArm capability.
Select only tools relevant to the user's request.
Never claim an action succeeded until its tool result reports success.
Never invent tools, raw motor commands, unsupported capabilities, or completed actions.
After a tool call, state only facts explicitly present in the tool result.
Ask for missing safety-critical information before running a high-risk skill.
You can read and manage a medication schedule backed by the user's calendar:
list_pill_schedule shows today's pills and their status; schedule_pill and cancel_pill
create or cancel a pill event. Always confirm the pill, time, and repeat with the user
before calling schedule_pill or cancel_pill. Scheduled pills auto-run at their time
through the medication scheduler, so you do not need to hand them over yourself.
Do not reveal analysis, chain-of-thought, or <think> content.
Keep final answers concise and clear.
"""


THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
logger = logging.getLogger(__name__)


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama service or configured model is unavailable."""


class OllamaMCPAgent:
    """Run a local model tool loop against the NurseArm MCP server."""

    def __init__(
        self,
        mcp_client: NurseArmMCPClient,
        audit: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.mcp = mcp_client
        self.audit = audit
        self.model = config.env("OLLAMA_MODEL", DEFAULT_MODEL)
        self.base_url = str(config.env("OLLAMA_URL", DEFAULT_URL)).rstrip("/")
        self._owns_http_client = http_client is None
        self.http = http_client or httpx.AsyncClient(timeout=120.0)
        self._chat_lock = asyncio.Lock()
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def close(self) -> None:
        if self._owns_http_client:
            await self.http.aclose()

    async def handle(self, user_intent: str) -> str:
        async with self._chat_lock:
            return await self._handle_locked(user_intent)

    async def _handle_locked(self, user_intent: str) -> str:
        logger.info("Ollama agent handling request with model %s", self.model)
        self._log({"event": "user_intent", "text": user_intent})
        self.messages.append({"role": "user", "content": user_intent})
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in await self.mcp.list_tools()
        ]

        for _ in range(MAX_TURNS):
            logger.info("Waiting for Ollama response")
            message = await self._chat(self.messages, tools)
            self.messages.append(message)
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                content = str(message.get("content") or "")
                # qwen3 sometimes outputs the tool call as plain-text JSON instead
                # of using the proper function-call format — recover and execute it.
                recovered = self._recover_tool_call(content)
                if recovered:
                    name, arguments = recovered
                    logger.info("Ollama selected MCP tool %s", name)
                    result = await self.mcp.call_tool(name, arguments)
                    self._log({"event": "mcp_tool", "tool": name, "args": arguments, "result": result})
                    self.messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result)})
                    continue

                reply = self._clean_reply(content)
                logger.info("Ollama returned final response")
                self._log({"event": "report", "text": reply})
                self._trim_history()
                return reply or "The local model returned an empty response."

            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                logger.info("Ollama selected MCP tool %s", name)
                result = await self.mcp.call_tool(name, arguments)
                self._log(
                    {
                        "event": "mcp_tool",
                        "tool": name,
                        "args": arguments,
                        "result": result,
                    }
                )
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result),
                    }
                )

        self._trim_history()
        return "Stopped after reaching the local agent turn limit."

    def _trim_history(self) -> None:
        if len(self.messages) > 41:
            self.messages = [self.messages[0], *self.messages[-40:]]

    @staticmethod
    def _recover_tool_call(content: str) -> tuple[str, dict] | None:
        """Detect a tool call printed as plain-text JSON and return (name, args).

        qwen3:4b sometimes skips the function-call wire format and just writes
        {"name": "...", "arguments": {...}} (or "args") in the message content.
        """
        cleaned = THINK_BLOCK_RE.sub("", content).strip()
        # Candidates: the whole content, then any {...} substrings found in it.
        candidates = [cleaned] + re.findall(r"\{[^{}]+\}", cleaned, re.DOTALL)
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            name = data.get("name") or data.get("tool")
            if not name or not isinstance(name, str):
                continue
            args = data.get("arguments") or data.get("args") or data.get("parameters") or {}
            if not isinstance(args, dict):
                continue
            return name, args
        return None

    @staticmethod
    def _clean_reply(content: str) -> str:
        cleaned = THINK_BLOCK_RE.sub("", content)
        if "</think>" in cleaned.lower():
            cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1]
        return cleaned.strip()

    async def model_status(self) -> dict[str, Any]:
        try:
            response = await self.http.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
            models = [item.get("name", "") for item in response.json().get("models", [])]
            return {
                "available": True,
                "model": self.model,
                "model_installed": self.model in models,
                "url": self.base_url,
            }
        except (httpx.HTTPError, ValueError):
            return {
                "available": False,
                "model": self.model,
                "model_installed": False,
                "url": self.base_url,
            }

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            response = await self.http.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "think": False,
                },
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                f"Cannot reach Ollama at {self.base_url}. Start it with `ollama serve`."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise OllamaUnavailableError(
                f"Ollama rejected model {self.model!r}. Run `ollama pull {self.model}`. {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(f"Ollama request failed: {exc}") from exc

        try:
            return response.json()["message"]
        except (KeyError, TypeError, ValueError) as exc:
            raise OllamaUnavailableError("Ollama returned an invalid chat response.") from exc

    def _log(self, event: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.log(event)
