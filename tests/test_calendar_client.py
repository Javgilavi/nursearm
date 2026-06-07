from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nursearm.integrations.google_calendar import FakeCalendarClient, GoogleCalendarClient
from nursearm.integrations.models import CalendarEvent

BASE = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)


def _ev(eid: str, minutes: int, title: str = "Green pill", color: str = "10") -> CalendarEvent:
    return CalendarEvent(id=eid, title=title, color_id=color, start=BASE + timedelta(minutes=minutes))


def test_fake_status_is_authorized() -> None:
    status = FakeCalendarClient(events=[]).status()
    assert status["configured"] is True
    assert status["authorized"] is True


def test_fake_list_events_filters_window_and_sorts() -> None:
    client = FakeCalendarClient(events=[_ev("b", 30), _ev("a", 10), _ev("late", 10_000)])
    got = client.list_events(BASE, BASE + timedelta(hours=24))
    assert [e.id for e in got] == ["a", "b"]


def test_fake_create_then_listed_then_delete() -> None:
    client = FakeCalendarClient(events=[])
    created = client.create_event("Black pill", BASE + timedelta(minutes=5), color_id="8")
    assert created.title == "Black pill"
    assert created.color_id == "8"

    listed = client.list_events(BASE, BASE + timedelta(hours=1))
    assert [e.id for e in listed] == [created.id]

    client.delete_event(created.id)
    assert client.list_events(BASE, BASE + timedelta(hours=1)) == []


def test_fake_daily_event_expands_into_per_day_instances() -> None:
    client = FakeCalendarClient(events=[])
    client.create_event("Green pill", BASE + timedelta(minutes=30), color_id="10", daily=True)

    listed = client.list_events(BASE, BASE + timedelta(days=3))

    assert len(listed) == 3  # one instance per day in the window
    assert {e.start for e in listed} == {
        BASE + timedelta(minutes=30),
        BASE + timedelta(days=1, minutes=30),
        BASE + timedelta(days=2, minutes=30),
    }
    assert len({e.id for e in listed}) == 3  # distinct, stable per-day ids
    assert all(e.recurring for e in listed)


def test_fake_delete_daily_series_removes_all_instances() -> None:
    client = FakeCalendarClient(events=[])
    client.create_event("Green pill", BASE + timedelta(minutes=30), color_id="10", daily=True)
    listed = client.list_events(BASE, BASE + timedelta(days=3))

    client.delete_event(listed[0].id)  # deleting any instance removes the whole series

    assert client.list_events(BASE, BASE + timedelta(days=3)) == []


def test_google_status_unconfigured_when_no_credentials(tmp_path: Path) -> None:
    client = GoogleCalendarClient(
        calendar_id="primary",
        credentials_path=tmp_path / "nope.json",
        token_path=tmp_path / "tok.json",
    )
    status = client.status()
    assert status["configured"] is False
    assert status["authorized"] is False
