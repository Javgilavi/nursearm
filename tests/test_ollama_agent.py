from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nursearm.orchestrator.ollama_agent import OllamaMCPAgent, OllamaUnavailableError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[Any]:
        return [
            SimpleNamespace(
                name="skill1_check_environment",
                description="Inspect the environment without moving hardware.",
                inputSchema={
                    "type": "object",
                    "properties": {"request": {"type": "string"}},
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return {"success": True, "confidence": 1.0, "note": "skill1 completed"}


@pytest.mark.anyio
async def test_agent_calls_mcp_tool_and_returns_final_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "skill1_check_environment",
                                    "arguments": {"request": "inspect the room"},
                                }
                            }
                        ],
                    }
                },
            )
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Inspection completed."}},
        )

    mcp = FakeMCPClient()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    agent = OllamaMCPAgent(mcp, http_client=http)

    try:
        reply = await agent.handle("Inspect the room")
    finally:
        await http.aclose()

    assert reply == "Inspection completed."
    assert mcp.calls == [
        ("skill1_check_environment", {"request": "inspect the room"})
    ]
    assert requests[0]["model"] == "qwen3:4b"
    assert requests[0]["tools"][0]["function"]["name"] == "skill1_check_environment"
    assert requests[1]["messages"][-1]["content"] == (
        '{"success": true, "confidence": 1.0, "note": "skill1 completed"}'
    )


@pytest.mark.anyio
async def test_agent_reports_unavailable_ollama() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    agent = OllamaMCPAgent(FakeMCPClient(), http_client=http)

    try:
        with pytest.raises(OllamaUnavailableError, match="ollama serve"):
            await agent.handle("Hello")
    finally:
        await http.aclose()
