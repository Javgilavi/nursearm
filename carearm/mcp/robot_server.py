"""OPTIONAL: expose CareArm's skills as MCP tools.

Why: lets any MCP client (Claude Desktop, an OpenClaw WhatsApp/Telegram gateway, etc.)
drive the robot through the SAME bounded toolset the judge uses — a strong live-demo
moment (a hackathon judge messages the robot from their phone). It is the literal
"API in the real world" requirement.

The tools mirror the judge's toolset exactly (the safety boundary). This is a stretch
goal — the FastAPI web UI is enough for the core build. Only wire this once the judge
loop works end-to-end.

SECURITY: bind to loopback, require an auth token, and only pair known users. The LLM
on the far side still cannot send raw joint commands — only these fixed tools.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Pseudocode using the `mcp` Python SDK (install the [mcp] extra):
#
#   from mcp.server.fastmcp import FastMCP
#   from carearm.interface.server import App
#
#   server = FastMCP("carearm")
#   state = App()
#
#   @server.tool()
#   def list_skills() -> list[dict]: ...
#   @server.tool()
#   def get_scene() -> dict: ...
#   @server.tool()
#   def get_today_medication() -> list[dict]: ...
#   @server.tool()
#   def run_skill(name: str, args: dict | None = None) -> dict: ...
#   @server.tool()
#   def run_recovery(behavior: str, args: dict | None = None) -> dict: ...
#
#   if __name__ == "__main__":
#       server.run()  # bind to loopback; front with an auth-checking gateway.


def main() -> None:
    raise NotImplementedError("Stretch goal — see module docstring. Build the judge loop first.")


if __name__ == "__main__":
    main()
