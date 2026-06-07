"""Resolve a calendar event to the robot skill it should fire.

An event matches a trigger if its Google ``colorId`` is in the trigger's ``color_ids``
*or* any of the trigger's keywords is a case-insensitive substring of the event title.
Trigger definition order is precedence: the first matching trigger wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nursearm.integrations.models import CalendarEvent


@dataclass
class Trigger:
    """One row of the calendar trigger table."""

    key: str
    color_ids: list[str]
    keywords: list[str]
    skill: str
    args: dict[str, Any]
    label: str
    color_hex: str = "#c1272d"


def load_trigger_map(calendar_config: dict[str, Any]) -> dict[str, Trigger]:
    """Build an ordered ``{key: Trigger}`` map from the ``calendar.yaml`` config."""
    triggers: dict[str, Trigger] = {}
    for key, spec in (calendar_config.get("triggers") or {}).items():
        triggers[key] = Trigger(
            key=key,
            color_ids=[str(cid) for cid in (spec.get("color_ids") or [])],
            keywords=[str(kw).lower() for kw in (spec.get("keywords") or [])],
            skill=spec["skill"],
            args=dict(spec.get("args") or {}),
            label=spec.get("label", key),
            color_hex=spec.get("color_hex", "#c1272d"),
        )
    return triggers


def resolve_trigger(event: CalendarEvent, triggers: dict[str, Trigger]) -> Trigger | None:
    """Return the first trigger whose color swatch or title keyword matches ``event``."""
    title = (event.title or "").lower()
    for trigger in triggers.values():
        if event.color_id is not None and event.color_id in trigger.color_ids:
            return trigger
        if any(keyword in title for keyword in trigger.keywords):
            return trigger
    return None
