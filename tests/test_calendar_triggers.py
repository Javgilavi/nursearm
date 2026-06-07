from __future__ import annotations

from datetime import UTC, datetime

from nursearm.integrations.models import CalendarEvent
from nursearm.integrations.triggers import load_trigger_map, resolve_trigger

SAMPLE_CONFIG = {
    "triggers": {
        "green": {
            "color_ids": ["10", "2"],
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
        "sort": {
            "color_ids": [],
            "keywords": ["sort"],
            "skill": "sort_pills",
            "args": {},
            "label": "Sort pills",
            "color_hex": "#b8860b",
        },
    }
}


def _event(title: str = "", color_id: str | None = None) -> CalendarEvent:
    return CalendarEvent(
        id="e1",
        title=title,
        color_id=color_id,
        start=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        end=None,
        status="confirmed",
    )


def test_load_trigger_map_preserves_order_and_fields() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    assert list(triggers) == ["green", "black", "sort"]
    assert triggers["green"].skill == "handover_pill"
    assert triggers["green"].args == {"color": "green"}
    assert triggers["green"].color_ids == ["10", "2"]
    assert triggers["green"].label == "Green pill"


def test_resolve_by_color_swatch() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    matched = resolve_trigger(_event(title="Pill", color_id="10"), triggers)
    assert matched is not None
    assert matched.key == "green"


def test_resolve_by_title_keyword() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    matched = resolve_trigger(_event(title="Morning green pill"), triggers)
    assert matched is not None
    assert matched.key == "green"


def test_keyword_match_is_case_insensitive() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    matched = resolve_trigger(_event(title="BLACK PILL"), triggers)
    assert matched is not None
    assert matched.key == "black"


def test_black_via_graphite_color() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    matched = resolve_trigger(_event(title="Pill", color_id="8"), triggers)
    assert matched is not None
    assert matched.key == "black"


def test_no_match_returns_none() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    assert resolve_trigger(_event(title="Lunch", color_id="5"), triggers) is None


def test_definition_order_is_precedence() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    # Title contains both 'green' and 'sort'; green is defined first, so it wins.
    matched = resolve_trigger(_event(title="green sort run"), triggers)
    assert matched is not None
    assert matched.key == "green"


def test_color_match_when_keyword_absent() -> None:
    triggers = load_trigger_map(SAMPLE_CONFIG)
    matched = resolve_trigger(_event(title="Take medicine", color_id="2"), triggers)
    assert matched is not None
    assert matched.key == "green"
