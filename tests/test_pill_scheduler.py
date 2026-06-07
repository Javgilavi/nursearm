from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nursearm.integrations.google_calendar import FakeCalendarClient
from nursearm.integrations.models import CalendarEvent
from nursearm.integrations.scheduler import PillScheduler

BASE = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)

CONFIG: dict[str, Any] = {
    "poll_interval_s": 30,
    "grace_min": 5,
    "countdown_s": 15,
    "auto_pilot": True,
    "calendar_id": "primary",
    "lookahead_hours": 24,
    "triggers": {
        "green": {
            "color_ids": ["10"],
            "keywords": ["green"],
            "skill": "handover_pill",
            "args": {"color": "green"},
            "label": "Green pill",
            "color_hex": "#0b8043",
        },
        "black": {
            "color_ids": ["8"],
            "keywords": ["black"],
            "skill": "handover_pill",
            "args": {"color": "black"},
            "label": "Black pill",
            "color_hex": "#3c4043",
        },
    },
}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


class Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, skill: str, args: dict) -> dict:
        self.calls.append((skill, args))
        return {"success": False, "note": f"ran {skill}"}


def _green(minutes_from_base: int, eid: str = "green-1") -> CalendarEvent:
    return CalendarEvent(
        id=eid,
        title="Green pill",
        color_id="10",
        start=BASE + timedelta(minutes=minutes_from_base),
    )


def make_scheduler(
    clock: Clock,
    runner: Runner,
    events: list[CalendarEvent],
    state_path: Path,
    *,
    busy: Any = None,
    auto_pilot: bool = True,
) -> PillScheduler:
    config = {**CONFIG, "auto_pilot": auto_pilot}
    return PillScheduler(
        calendar=FakeCalendarClient(events=events),
        config=config,
        runner=runner,
        now_fn=clock,
        robot_busy=busy or (lambda: False),
        state_path=state_path,
    )


def test_due_event_creates_pending_with_countdown(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(0)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.tick()

    asyncio.run(go())
    assert sched.pending is not None
    assert sched.pending.event_id == "green-1"
    assert sched.pending.fires_at == BASE + timedelta(seconds=15)
    assert runner.calls == []


def test_fires_after_countdown(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(0)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.tick()
        clock.advance(seconds=15)
        await sched.tick()

    asyncio.run(go())
    assert runner.calls == [("handover_pill", {"color": "green"})]
    assert "green-1" in sched.fired
    assert sched.pending is None


def test_does_not_double_fire(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(0)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.tick()
        clock.advance(seconds=15)
        await sched.tick()
        clock.advance(seconds=5)
        await sched.tick()

    asyncio.run(go())
    assert len(runner.calls) == 1


def test_auto_pilot_off_notifies_only(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(0)], tmp_path / "s.json", auto_pilot=False)

    async def go() -> None:
        await sched.poll()
        await sched.tick()
        clock.advance(seconds=60)
        await sched.tick()

    asyncio.run(go())
    assert runner.calls == []
    assert sched.pending is not None
    assert sched.pending.fires_at is None


def test_robot_busy_defers_then_fires(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    busy = {"value": True}
    sched = make_scheduler(
        clock, runner, [_green(0)], tmp_path / "s.json", busy=lambda: busy["value"]
    )

    async def go() -> None:
        await sched.poll()
        await sched.tick()
        clock.advance(seconds=15)
        await sched.tick()  # still busy -> defer
        assert runner.calls == []
        busy["value"] = False
        await sched.tick()  # free -> fire

    asyncio.run(go())
    assert runner.calls == [("handover_pill", {"color": "green"})]


def test_missed_event_not_fired(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(-10)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.tick()

    asyncio.run(go())
    assert runner.calls == []
    statuses = {e["id"]: e["status"] for e in sched.schedule_payload()["events"]}
    assert statuses["green-1"] == "missed"


def test_skip_prevents_fire(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(0)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.tick()
        sched.skip("green-1")
        clock.advance(seconds=20)
        await sched.tick()

    asyncio.run(go())
    assert runner.calls == []
    statuses = {e["id"]: e["status"] for e in sched.schedule_payload()["events"]}
    assert statuses["green-1"] == "skipped"


def test_fire_now_runs_immediately(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    sched = make_scheduler(clock, runner, [_green(60)], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()
        await sched.fire_now("green-1")

    asyncio.run(go())
    assert runner.calls == [("handover_pill", {"color": "green"})]
    assert "green-1" in sched.fired


def test_only_triggered_events_in_schedule(tmp_path: Path) -> None:
    clock, runner = Clock(BASE), Runner()
    lunch = CalendarEvent(id="lunch", title="Lunch", color_id="5", start=BASE + timedelta(hours=2))
    sched = make_scheduler(clock, runner, [_green(30), lunch], tmp_path / "s.json")

    async def go() -> None:
        await sched.poll()

    asyncio.run(go())
    ids = [e["id"] for e in sched.schedule_payload()["events"]]
    assert ids == ["green-1"]


def test_persistence_prevents_refire_after_restart(tmp_path: Path) -> None:
    state = tmp_path / "s.json"
    clock, runner1 = Clock(BASE), Runner()
    sched1 = make_scheduler(clock, runner1, [_green(0)], state)

    async def first() -> None:
        await sched1.poll()
        await sched1.tick()
        clock.advance(seconds=15)
        await sched1.tick()

    asyncio.run(first())
    assert len(runner1.calls) == 1

    # Fresh scheduler, same state file, same event still "due" — must not re-fire.
    runner2 = Runner()
    sched2 = make_scheduler(clock, runner2, [_green(0)], state)

    async def second() -> None:
        await sched2.poll()
        await sched2.tick()

    asyncio.run(second())
    assert runner2.calls == []
    statuses = {e["id"]: e["status"] for e in sched2.schedule_payload()["events"]}
    assert statuses["green-1"] == "done"
