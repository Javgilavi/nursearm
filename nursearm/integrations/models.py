"""Plain data contracts for the calendar integration.

Kept free of any Google dependency so triggers, the scheduler, and the tests can
import these without the optional ``calendar`` extra installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class CalendarEvent:
    """A normalized calendar event, independent of the Google API response shape."""

    id: str
    title: str
    color_id: str | None
    start: datetime
    end: datetime | None = None
    status: str = "confirmed"
    html_link: str | None = None
    recurring: bool = False
