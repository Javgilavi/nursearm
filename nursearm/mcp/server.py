"""MCP server exposing NurseArm's bounded skill interface."""

from __future__ import annotations

import argparse
import os
from functools import lru_cache
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from nursearm.orchestrator.skill_registry import SkillRegistry
from nursearm.perception.realsense import Perception
from nursearm.robot.controller import RobotController

mcp = FastMCP(
    "NurseArm",
    instructions=(
        "Use only the exposed task-level tools. Primitive skills move the robot directly; "
        "VLA skills run learned policies. Discover all capabilities with list_skills."
    ),
    stateless_http=True,
    json_response=True,
)


class Runtime:
    """Own the registry and hardware services used by MCP tools."""

    def __init__(self) -> None:
        mock = os.getenv("NURSEARM_MOCK", "1") == "1"
        self.skills = SkillRegistry()
        self.robot = RobotController(mock=mock)
        self.perception = Perception(mock=mock)

    def run_skill(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.skills.run(name, args or {}, self.robot, self.perception)
        return result.summary()

    def close(self) -> None:
        self.robot.disconnect()
        self.perception.close()


@lru_cache
def runtime() -> Runtime:
    return Runtime()


@mcp.tool()
def list_skills() -> list[dict[str, str]]:
    """List every enabled NurseArm skill with its kind and usage description."""
    return [vars(skill) for skill in runtime().skills.info()]


@mcp.tool()
def get_scene() -> dict[str, Any]:
    """Read the current camera-derived scene without moving the robot."""
    return runtime().perception.observe().summary()


@mcp.tool()
def run_skill(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one enabled skill by registry name.

    Use list_skills first when the correct name or arguments are uncertain. This is
    the generic entry point for future primitive and VLA capabilities.
    """
    return runtime().run_skill(name, args)


@mcp.tool()
def handover_pill(
    color: Literal["green", "black"],
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Pick up the requested green or black pill and present it to the person's hand.

    Use only when the user explicitly requests one of the supported pill colors.
    """
    args: dict[str, Any] = {"color": color}
    if duration_s is not None:
        args["duration_s"] = duration_s
    result = runtime().run_skill("handover_pill", args)
    return {"skill": "handover_pill", "color": color, **result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NurseArm MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio for local agent clients; streamable-http for Inspector/OpenClaw.",
    )
    args = parser.parse_args()
    try:
        mcp.run(transport=args.transport)
    finally:
        if runtime.cache_info().currsize:
            runtime().close()


if __name__ == "__main__":
    main()
