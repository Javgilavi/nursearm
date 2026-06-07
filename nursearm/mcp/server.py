"""MCP server exposing NurseArm's bounded skill interface."""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from nursearm.integrations.google_calendar import CalendarUnavailableError
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
        self.mock = mock
        self.skills = SkillRegistry()
        self.robot = RobotController(mock=mock)
        self.perception = Perception(mock=mock)
        self._calendar: Any | None = None
        self._scheduler: Any | None = None

    @property
    def calendar(self) -> Any:
        if self._calendar is None:
            from nursearm.config import calendar_config
            from nursearm.integrations.google_calendar import build_client
            calendar_real = os.getenv("NURSEARM_CALENDAR_REAL", "0") == "1"
            self._calendar = build_client(
                mock=self.mock and not calendar_real,
                calendar_id=calendar_config().get("calendar_id", "primary"),
            )
        return self._calendar

    @property
    def scheduler(self) -> Any:
        """A non-running scheduler used only to read/resolve schedule views.

        Firing happens in the FastAPI server process, never here, so this one's
        loop is never started.
        """
        if self._scheduler is None:
            from nursearm.config import calendar_config
            from nursearm.integrations.scheduler import PillScheduler

            async def _noop(skill: str, args: dict[str, Any]) -> dict[str, Any]:
                return {"note": "scheduled firing is handled by the NurseArm server"}

            self._scheduler = PillScheduler(
                calendar=self.calendar, config=calendar_config(), runner=_noop
            )
        return self._scheduler

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


@mcp.tool()
async def list_pill_schedule() -> dict[str, Any]:
    """List the upcoming medication-schedule events with their time, pill, and status.

    Status is one of scheduled, due, done, skipped, or missed. Scheduled pills auto-run
    at their time; you do not need to run them yourself.
    """
    scheduler = runtime().scheduler
    await scheduler.poll()
    payload = scheduler.schedule_payload()
    return {
        "auto_pilot": payload["auto_pilot"],
        "connection": payload["connection"],
        "events": [
            {
                "id": event["id"],
                "pill": event["label"],
                "time": event["start_human"],
                "status": event["status"],
            }
            for event in payload["events"]
        ],
    }


@mcp.tool()
async def schedule_pill(
    pill: Literal["green", "black", "sort"],
    time: str,
    daily: bool = False,
) -> dict[str, Any]:
    """Create a medication calendar event. Confirm the pill, time, and repeat first.

    ``time`` is an ISO datetime such as ``2026-06-07T09:00``; a bare datetime is treated
    as the server's local time. Set ``daily=true`` to repeat every day.
    """
    rt = runtime()
    trigger = rt.scheduler.triggers.get(pill)
    if trigger is None:
        return {"ok": False, "error": f"unknown pill {pill!r}"}
    try:
        start = datetime.fromisoformat(time)
    except ValueError:
        return {"ok": False, "error": f"invalid time {time!r}; use ISO like 2026-06-07T09:00"}
    if start.tzinfo is None:
        start = start.astimezone()
    color_id = trigger.color_ids[0] if trigger.color_ids else None
    try:
        event = await asyncio.to_thread(
            rt.calendar.create_event, trigger.label, start, color_id=color_id, daily=daily
        )
    except CalendarUnavailableError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "id": event.id,
        "pill": trigger.label,
        "time": event.start.isoformat(),
        "daily": daily,
    }


@mcp.tool()
async def cancel_pill(event_id: str) -> dict[str, Any]:
    """Cancel a scheduled medication event by id (get ids from list_pill_schedule).

    Confirm with the user before cancelling.
    """
    try:
        await asyncio.to_thread(runtime().calendar.delete_event, event_id)
    except CalendarUnavailableError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "id": event_id}


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
