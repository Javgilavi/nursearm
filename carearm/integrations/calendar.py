"""Google Calendar -> today's medication schedule.

The judge calls ``today()`` (via the get_today_medication tool) to learn which
medications are scheduled for the current day. We model each medication as a calendar
event whose title encodes the pill and dose, e.g. "Aspirin 100mg" at 09:00.

For the hackathon you can start with ``MockCalendarClient`` (no Google setup needed)
and swap to ``GoogleCalendarClient`` once OAuth credentials are in place.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Protocol

from carearm import config
from carearm.types import Medication

logger = logging.getLogger(__name__)


class CalendarClient(Protocol):
    def today(self) -> list[Medication]: ...


class MockCalendarClient:
    """Zero-setup stand-in. Reads a static schedule from config or returns a default."""

    def today(self) -> list[Medication]:
        schedule = config.skills_config().get("mock_medication_schedule") or [
            {"name": "Aspirin", "dose": "100mg", "time": "09:00"},
            {"name": "Vitamin D", "dose": "1000IU", "time": "09:00"},
        ]
        return [Medication(**m) for m in schedule]


class GoogleCalendarClient:
    """Real Google Calendar integration.

    Setup:
      1. Create an OAuth client (Desktop) in Google Cloud Console, enable Calendar API.
      2. Download credentials.json to the repo root.
      3. First run opens a browser to authorize; token is cached to token.json.
      4. Tag medication events in a dedicated calendar, title = "<Name> <Dose>".
    """

    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

    def __init__(self, calendar_id: str = "primary") -> None:
        self.calendar_id = config.env("GOOGLE_CALENDAR_ID", calendar_id)
        self._service = None  # lazy — only build when first used

    def _build_service(self):
        # Imported lazily so the mock path needs no Google deps installed.
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        from pathlib import Path

        token = Path("token.json")
        creds = Credentials.from_authorized_user_file(str(token), self.SCOPES) if token.exists() else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", self.SCOPES)
                creds = flow.run_local_server(port=0)
            token.write_text(creds.to_json())
        return build("calendar", "v3", credentials=creds)

    def today(self) -> list[Medication]:
        if self._service is None:
            self._service = self._build_service()
        start = datetime.combine(datetime.now().date(), time.min, tzinfo=timezone.utc).isoformat()
        end = datetime.combine(datetime.now().date(), time.max, tzinfo=timezone.utc).isoformat()
        events = (
            self._service.events()
            .list(calendarId=self.calendar_id, timeMin=start, timeMax=end,
                  singleEvents=True, orderBy="startTime")
            .execute()
            .get("items", [])
        )
        meds: list[Medication] = []
        for e in events:
            title = e.get("summary", "").strip()
            if not title:
                continue
            name, _, dose = title.partition(" ")
            when = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
            meds.append(Medication(name=name, dose=dose or "as labelled", time=when[11:16] if "T" in when else when))
        return meds


def make_calendar_client() -> CalendarClient:
    """Factory: real client if USE_GOOGLE_CALENDAR=1 in .env, else the mock."""
    if config.env("USE_GOOGLE_CALENDAR", "0") == "1":
        return GoogleCalendarClient()
    logger.info("Using MockCalendarClient (set USE_GOOGLE_CALENDAR=1 to use Google).")
    return MockCalendarClient()
