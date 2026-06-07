"""Google Calendar access for the medication scheduler, with an offline fake.

The real client (:class:`GoogleCalendarClient`) lazily imports the optional Google
libraries so the base install and the tests never require the ``calendar`` extra.
When NurseArm runs in mock mode — or has no ``credentials.json`` — the scheduler uses
:class:`FakeCalendarClient`, an in-memory calendar seeded with sample pill events so the
whole feature demos offline.
"""

from __future__ import annotations

import itertools
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nursearm.integrations.models import CalendarEvent

logger = logging.getLogger(__name__)

# Read + write events on the user's calendars.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_PATH = _ROOT / "credentials.json"
TOKEN_PATH = _ROOT / "token.json"


class CalendarUnavailableError(RuntimeError):
    """Raised when the calendar cannot be reached or is not authorized."""


class CalendarClient(ABC):
    """Interface shared by the real Google client and the offline fake."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Report configuration/authorization without raising."""

    @abstractmethod
    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        """Return events starting within ``[time_min, time_max)``, sorted by start."""

    @abstractmethod
    def create_event(
        self,
        summary: str,
        start: datetime,
        *,
        duration_min: int = 5,
        color_id: str | None = None,
        daily: bool = False,
    ) -> CalendarEvent:
        """Create an event and return it."""

    @abstractmethod
    def delete_event(self, event_id: str) -> None:
        """Delete an event by id (no error if it is already gone)."""


class FakeCalendarClient(CalendarClient):
    """In-memory calendar used in mock mode and tests. No network, no Google libs."""

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events: dict[str, CalendarEvent] = {}
        self._ids = itertools.count(1)
        for event in self._seed() if events is None else events:
            self._events[event.id] = event

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "authorized": True,
            "calendar_id": "mock",
            "account": "mock@nursearm.local",
            "backend": "fake",
        }

    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for event in self._events.values():
            if event.recurring:
                events.extend(self._expand_daily(event, time_min, time_max))
            elif time_min <= event.start < time_max:
                events.append(event)
        return sorted(events, key=lambda e: e.start)

    @staticmethod
    def _expand_daily(
        base: CalendarEvent, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        """One dated instance per day within the window, mirroring Google's singleEvents."""
        duration = (base.end - base.start) if base.end else timedelta(minutes=5)
        day = base.start
        if day < time_min:  # fast-forward to the first instance inside the window
            day += timedelta(days=(time_min - day).days)
            while day < time_min:
                day += timedelta(days=1)
        instances: list[CalendarEvent] = []
        while day < time_max:
            instance_id = f"{base.id}_{day.astimezone().strftime('%Y%m%d')}"
            instances.append(replace(base, id=instance_id, start=day, end=day + duration))
            day += timedelta(days=1)
        return instances

    def create_event(
        self,
        summary: str,
        start: datetime,
        *,
        duration_min: int = 5,
        color_id: str | None = None,
        daily: bool = False,
    ) -> CalendarEvent:
        event_id = f"mock-{next(self._ids)}"
        event = CalendarEvent(
            id=event_id,
            title=summary,
            color_id=color_id,
            start=start,
            end=start + timedelta(minutes=duration_min),
            status="confirmed",
            recurring=daily,
        )
        self._events[event_id] = event
        return event

    def delete_event(self, event_id: str) -> None:
        # An expanded daily instance ("base_YYYYMMDD") deletes the whole series.
        base_id = re.sub(r"_\d{8}$", "", event_id)
        self._events.pop(base_id, None)
        self._events.pop(event_id, None)

    @staticmethod
    def _seed() -> list[CalendarEvent]:
        """Two sample events so the panel and banner demo without a real calendar."""
        now = datetime.now(UTC)
        return [
            CalendarEvent(
                id="seed-green",
                title="Green pill",
                color_id="10",
                start=now + timedelta(minutes=2),
                end=now + timedelta(minutes=7),
            ),
            CalendarEvent(
                id="seed-black",
                title="Black pill",
                color_id="8",
                start=now + timedelta(hours=4),
                end=now + timedelta(hours=4, minutes=5),
            ),
        ]


class GoogleCalendarClient(CalendarClient):
    """Real Google Calendar client. Google libraries are imported lazily."""

    def __init__(
        self,
        calendar_id: str = "primary",
        credentials_path: Path | str = CREDENTIALS_PATH,
        token_path: Path | str = TOKEN_PATH,
    ) -> None:
        self.calendar_id = calendar_id
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any | None = None

    # -- configuration / auth ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        configured = self._credentials_path.exists()
        authorized = self._token_path.exists()
        result: dict[str, Any] = {
            "configured": configured,
            "authorized": authorized,
            "calendar_id": self.calendar_id,
            "account": None,
            "backend": "google",
        }
        if not (configured and authorized):
            return result
        try:
            service = self._ensure_service()
            # Verify access through the Events API because SCOPES intentionally grants
            # event access only. calendarList.get requires an additional calendar-list
            # scope and would incorrectly mark a valid event token as unauthorized.
            (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    maxResults=1,
                    singleEvents=True,
                )
                .execute()
            )
            result["account"] = self.calendar_id
        except Exception as exc:  # noqa: BLE001 — status must never raise
            logger.warning("Calendar status check failed: %s", exc)
            result["authorized"] = False
            result["error"] = str(exc)
        return result

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self) -> Any:
        try:
            from google.auth.transport.requests import Request  # noqa: PLC0415
            from google.oauth2.credentials import Credentials  # noqa: PLC0415
            from googleapiclient.discovery import build  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise CalendarUnavailableError(
                "Google libraries missing. Install with: uv sync --extra calendar"
            ) from exc

        if not self._token_path.exists():
            raise CalendarUnavailableError(
                "Not authorized. Run: uv run nursearm-calendar-auth"
            )
        creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._token_path.write_text(creds.to_json())
            else:
                raise CalendarUnavailableError(
                    "Calendar token invalid. Re-run: uv run nursearm-calendar-auth"
                )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # -- reads / writes ----------------------------------------------------------

    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        service = self._ensure_service()
        try:
            response = (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min.astimezone(UTC).isoformat(),
                    timeMax=time_max.astimezone(UTC).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — surface as a typed error
            raise CalendarUnavailableError(f"Calendar read failed: {exc}") from exc
        events = [self._parse(item) for item in response.get("items", [])]
        return [e for e in events if e is not None]

    def create_event(
        self,
        summary: str,
        start: datetime,
        *,
        duration_min: int = 5,
        color_id: str | None = None,
        daily: bool = False,
    ) -> CalendarEvent:
        service = self._ensure_service()
        start = start.astimezone(UTC)
        end = start + timedelta(minutes=duration_min)
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if color_id:
            body["colorId"] = str(color_id)
        if daily:
            body["recurrence"] = ["RRULE:FREQ=DAILY"]
        try:
            created = service.events().insert(calendarId=self.calendar_id, body=body).execute()
        except Exception as exc:  # noqa: BLE001
            raise CalendarUnavailableError(f"Calendar create failed: {exc}") from exc
        parsed = self._parse(created)
        if parsed is None:  # pragma: no cover - insert always returns a dated event
            raise CalendarUnavailableError("Calendar returned an unparseable event")
        return parsed

    def delete_event(self, event_id: str) -> None:
        service = self._ensure_service()
        try:
            service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        except Exception as exc:  # noqa: BLE001
            raise CalendarUnavailableError(f"Calendar delete failed: {exc}") from exc

    @staticmethod
    def _parse(item: dict[str, Any]) -> CalendarEvent | None:
        start = _parse_dt(item.get("start", {}))
        if start is None:
            return None
        return CalendarEvent(
            id=item.get("id", ""),
            title=item.get("summary", "(no title)"),
            color_id=item.get("colorId"),
            start=start,
            end=_parse_dt(item.get("end", {})),
            status=item.get("status", "confirmed"),
            html_link=item.get("htmlLink"),
            recurring=bool(item.get("recurringEventId")),
        )


def _parse_dt(value: dict[str, Any]) -> datetime | None:
    """Parse a Google start/end object (``dateTime`` or all-day ``date``) to aware UTC."""
    raw = value.get("dateTime") or value.get("date")
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:  # all-day events have no time/zone
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_client(*, mock: bool, calendar_id: str = "primary") -> CalendarClient:
    """Return the offline fake in mock mode, else the real Google client."""
    if mock:
        return FakeCalendarClient()
    return GoogleCalendarClient(calendar_id=calendar_id)
