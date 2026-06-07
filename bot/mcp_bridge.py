#!/usr/bin/env python3
"""Minimal MCP server that bridges OpenClaw → NurseArm /chat endpoint.

This is the ONLY tool OpenClaw gets. It forwards natural-language commands
to the existing FastAPI server, which handles Qwen + MCP + robot logic.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nursearm-bridge")

NURSEARM_URL = os.getenv("NURSEARM_URL", "http://host.docker.internal:8000")


@mcp.tool()
async def robot_command(command: str) -> str:
    """Send a natural-language command to the NurseArm robot assistant.

    Use this for supported robot requests: sorting pills, handing over the green or
    black pill, primitive arm movement, gripper control, hand/palm observation, and
    status checks.

    Examples:
      command="sort the pills into their matching cups"
      command="hand me the green pill"
      command="move the arm up"
      command="open the gripper"
      command="is there an open palm in view?"
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                f"{NURSEARM_URL}/chat",
                json={"text": command},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("reply", str(data))
        except httpx.ConnectError:
            return (
                "Cannot reach the NurseArm server. "
                "Make sure the server is running on the host machine."
            )
        except httpx.HTTPStatusError as e:
            return f"Server error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return f"Error contacting robot: {e}"


if __name__ == "__main__":
    mcp.run()
