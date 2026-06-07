#!/usr/bin/env python
"""Offline MCP smoke test for the current skill registry."""

from __future__ import annotations

import asyncio

from nursearm.mcp.client import NurseArmMCPClient


async def run() -> None:
    client = NurseArmMCPClient()
    await client.connect()
    try:
        tools = {tool.name for tool in await client.list_tools()}
        expected = {"list_skills", "get_scene", "run_skill"}
        missing = expected - tools
        if missing:
            raise AssertionError(f"missing MCP tools: {sorted(missing)}")

        skills = await client.call_tool("list_skills")
        names = {item["name"] for item in skills["result"]}
        expected_skills = {
            "home",
            "grip",
            "release",
            "move_up",
            "move_down",
            "move_forward",
            "move_back",
            "move_left",
            "move_right",
            "sort_pills",
        }
        if names != expected_skills:
            raise AssertionError(f"unexpected skills: {sorted(names)}")

        result = await client.call_tool("run_skill", {"name": "home", "args": {}})
        if not result.get("success"):
            raise AssertionError(f"home returned {result!r}")

        policy_result = await client.call_tool(
            "run_skill",
            {"name": "sort_pills", "args": {}},
        )
        if policy_result.get("success"):
            raise AssertionError("sort_pills must not report success without a checkpoint")

        print("PASS tools, registry, home primitive, and missing-policy failure")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run())
