#!/usr/bin/env python
"""Offline MCP smoke test: discover tools and execute all dummy skills."""

from __future__ import annotations

import asyncio

from nursearm.mcp.client import NurseArmMCPClient


async def run() -> None:
    client = NurseArmMCPClient()
    await client.connect()
    try:
        tools = {tool.name for tool in await client.list_tools()}
        expected = {
            "list_skills",
            "run_skill",
            "skill1_check_environment",
            "skill2_prepare_assistance",
            "skill3_confirm_handoff",
        }
        missing = expected - tools
        if missing:
            raise AssertionError(f"missing MCP tools: {sorted(missing)}")

        cases = {
            "skill1_check_environment": "skill1 completed",
            "skill2_prepare_assistance": "skill2 completed",
            "skill3_confirm_handoff": "skill3 completed",
        }
        for tool_name, expected_note in cases.items():
            result = await client.call_tool(tool_name, {"request": "offline smoke test"})
            if not result.get("success") or result.get("note") != expected_note:
                raise AssertionError(f"{tool_name} returned {result!r}")
            print(f"PASS {tool_name}: {result['note']}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run())
