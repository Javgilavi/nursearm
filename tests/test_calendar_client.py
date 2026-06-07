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


def test_google_status_unconfigured_when_no_credentials(tmp_path: Path) -> None:
    client = GoogleCalendarClient(
        calendar_id="primary",
        credentials_path=tmp_path / "nope.json",
        token_path=tmp_path / "tok.json",
    )
    status = client.status()
    assert status["configured"] is False
    assert status["authorized"] is False
