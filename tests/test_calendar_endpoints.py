"""Integration tests for the /calendar REST endpoints.

These exercise the real FastAPI handlers against a real ``AppState`` in mock mode
(so the offline ``FakeCalendarClient`` backs the scheduler). The scheduler's
persistence path, audit sink, and skill runner are redirected to test doubles so
no rollout subprocess runs and nothing is written to the repo's ``data/`` dir.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from nursearm.interface import server


@pytest.fixture
def app_state(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MOCK", True)
    # Redirect persistence to a tmp dir BEFORE constructing AppState, so the scheduler
    # starts from clean state instead of loading the repo's data/calendar_state.json.
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    state = server.AppState()
    state.scheduler._audit = None
    runs: list[tuple[str, dict]] = []

    async def runner(skill: str, args: dict) -> dict:
        runs.append((skill, args))
        return {"success": True}

    state.scheduler._runner = runner
    state.runs = runs  # type: ignore[attr-defined]
    monkeypatch.setattr(server, "state", state)
    return state


def test_schedule_lists_seeded_events_with_trigger_options(app_state) -> None:
    asyncio.run(app_state.scheduler.poll())  # the background watcher polls in production
    payload = asyncio.run(server.calendar_schedule())

    assert payload["connection"]["backend"] == "fake"
    assert payload["auto_pilot"] is True
    labels = {event["label"] for event in payload["events"]}
    assert {"Green pill", "Black pill"} <= labels

    trigger_keys = {trigger["key"] for trigger in payload["triggers"]}
    assert {"green", "black", "sort"} <= trigger_keys
    # Every trigger option carries the swatch colour the UI renders.
    assert all(trigger["color_hex"] for trigger in payload["triggers"])


def test_status_reports_fake_backend(app_state) -> None:
    status = asyncio.run(server.calendar_status())

    assert status["backend"] == "fake"
    assert status["configured"] is True
    assert status["auto_pilot"] is True


def test_auto_pilot_toggle_updates_scheduler(app_state) -> None:
    result = asyncio.run(server.calendar_auto_pilot(server.AutoPilotIn(enabled=False)))

    assert result == {"ok": True, "auto_pilot": False}
    assert app_state.scheduler.auto_pilot is False


def test_create_event_appears_in_schedule(app_state) -> None:
    start_iso = (datetime.now() + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%S")
    body = server.NewEventIn(trigger="green", start_iso=start_iso, daily=False)

    created = asyncio.run(server.calendar_create_event(body))
    assert created["ok"] is True
    assert created["label"] == "Green pill"

    payload = asyncio.run(server.calendar_schedule())
    assert any(event["id"] == created["id"] for event in payload["events"])


def test_create_event_unknown_trigger_returns_400(app_state) -> None:
    body = server.NewEventIn(trigger="purple", start_iso="2026-06-07T09:00:00", daily=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.calendar_create_event(body))
    assert excinfo.value.status_code == 400


def test_delete_event_removes_it_from_schedule(app_state) -> None:
    start_iso = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    created = asyncio.run(
        server.calendar_create_event(server.NewEventIn(trigger="black", start_iso=start_iso, daily=False))
    )

    asyncio.run(server.calendar_delete_event(created["id"]))

    payload = asyncio.run(server.calendar_schedule())
    assert all(event["id"] != created["id"] for event in payload["events"])


def test_fire_now_runs_the_mapped_skill(app_state) -> None:
    asyncio.run(app_state.scheduler.poll())  # populate the in-memory schedule

    result = asyncio.run(server.calendar_fire_event("seed-green"))

    assert result["ok"] is True
    assert app_state.runs == [("handover_pill", {"color": "green"})]


def test_skip_marks_event_skipped(app_state) -> None:
    asyncio.run(app_state.scheduler.poll())

    result = asyncio.run(server.calendar_skip_event("seed-green"))
    assert result["ok"] is True

    payload = asyncio.run(server.calendar_schedule())
    statuses = {event["id"]: event["status"] for event in payload["events"]}
    assert statuses["seed-green"] == "skipped"
