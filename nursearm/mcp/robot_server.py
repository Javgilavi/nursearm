"""Backward-compatible entry point for the NurseArm MCP server."""

from nursearm.mcp.server import main, mcp

__all__ = ["main", "mcp"]


if __name__ == "__main__":
    main()
