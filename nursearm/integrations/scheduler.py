"""Background watcher that fires robot skills from labelled calendar events.

The scheduler is deliberately split into small, injectable pieces so its decision
logic can be tested with a fake clock, a fake calendar, and a recording runner:

- ``poll()``     — load events from the calendar client and resolve their triggers.
- ``tick()``     — evaluate the due/pending/firing lifecycle against ``now``.
- ``run()``      — the production loop: poll on ``poll_interval_s``, tick every second.

A due event becomes ``pending`` with a ``fires_at`` countdown; once the countdown
elapses (and the robot is free, and Auto-pilot is on) the mapped skill runs exactly
once. Fired/skipped event ids are persisted per-day so an event never double-fires
across a restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nursearm.integrations.google_calendar import CalendarClient, CalendarUnavailableError
from nursearm.integrations.models import CalendarEvent
from nursearm.integrations.triggers import Trigger, load_trigger_map, resolve_trigger

logger = logging.getLogger(__name__)

Runner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class Pending:
    """The single in-flight due event awaiting (or undergoing) execution."""

    event_id: str
    trigger_key: str
    label: str
    color_hex: str
    skill: str
    args: dict[str, Any]
    fires_at: datetime | None  # None when Auto-pilot is off (notify only)
    firing: bool = False


class PillScheduler:
    def __init__(
        self,
        calendar: CalendarClient,
        config: dict[str, Any],
        runner: Runner,
        *,
        now_fn: Callable[[], datetime] | None = None,
        robot_busy: Callable[[], bool] | None = None,
        state_path: Path | str | None = None,
        audit: Any | None = None,
    ) -> None:
        self._calendar = calendar
        self._runner = runner
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._robot_busy = robot_busy or (lambda: False)
        self._audit = audit

        self._triggers: dict[str, Trigger] = load_trigger_map(config)
        self.poll_interval_s: int = int(config.get("poll_interval_s", 30))
        self.grace = timedelta(minutes=float(config.get("grace_min", 5)))
        self.countdown_s: int = int(config.get("countdown_s", 15))
        self.lookahead = timedelta(hours=float(config.get("lookahead_hours", 24)))
        self.lookback = timedelta(hours=12)
        self.auto_pilot: bool = bool(config.get("auto_pilot", True))

        self._state_path = Path(state_path) if state_path else None
        self._items: list[tuple[CalendarEvent, Trigger]] = []
        self.pending: Pending | None = None
        self.error: str | None = None
        self.fired: set[str] = set()
        self.skipped: set[str] = set()
        self._task: asyncio.Task | None = None
        self._load_state()

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        """Production loop: poll the calendar periodically, evaluate every second."""
        ticks_per_poll = max(1, self.poll_interval_s)
        counter = 0
        await self.poll()
        while True:
            try:
                if counter % ticks_per_poll == 0:
                    await self.poll()
                await self.tick()
            except Exception:  # a bad tick must never kill the loop
                logger.exception("pill scheduler tick failed")
            counter += 1
            await asyncio.sleep(1)

    # -- calendar polling --------------------------------------------------------

    async def poll(self) -> None:
        now = self._now()
        time_min = now - self.lookback
        time_max = now + self.lookahead
        try:
            events = await asyncio.to_thread(self._calendar.list_events, time_min, time_max)
            self.error = None
        except CalendarUnavailableError as exc:
            self.error = str(exc)
            logger.debug("calendar poll unavailable: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 — keep last-known schedule on error
            self.error = str(exc)
            logger.warning("calendar poll failed: %s", exc)
            return
        self.set_events(events)

    def set_events(self, events: list[CalendarEvent]) -> None:
        """Keep only events that resolve to a trigger, paired with that trigger."""
        items: list[tuple[CalendarEvent, Trigger]] = []
        for event in events:
            trigger = resolve_trigger(event, self._triggers)
            if trigger is not None:
                items.append((event, trigger))
        items.sort(key=lambda pair: pair[0].start)
        self._items = items

    # -- firing lifecycle --------------------------------------------------------

    async def tick(self) -> None:
        now = self._now()

        # Drop a pending whose event vanished or was already resolved.
        if self.pending is not None and self.pending.event_id in self.fired | self.skipped:
            self.pending = None

        due = self._due_item(now)

        if self.pending is None and due is not None:
            event, trigger = due
            fires_at = now + timedelta(seconds=self.countdown_s) if self.auto_pilot else None
            self.pending = Pending(
                event_id=event.id,
                trigger_key=trigger.key,
                label=trigger.label,
                color_hex=trigger.color_hex,
                skill=trigger.skill,
                args=dict(trigger.args),
                fires_at=fires_at,
            )

        pending = self.pending
        if pending is None or pending.firing:
            return
        if pending.fires_at is None or now < pending.fires_at:
            return  # notify-only, or countdown still running
        if self._robot_busy():
            logger.info("Scheduled %s deferred: robot busy", pending.label)
            return
        await self._fire(pending)

    def _due_item(self, now: datetime) -> tuple[CalendarEvent, Trigger] | None:
        """The first event whose start is within the live grace window and unresolved."""
        for event, trigger in self._items:
            if event.id in self.fired or event.id in self.skipped:
                continue
            if event.start <= now < event.start + self.grace:
                return event, trigger
        return None

    async def _fire(self, pending: Pending) -> None:
        pending.firing = True
        self.fired.add(pending.event_id)  # mark first so a retry never double-fires
        self._save_state()
        self._log({
            "event": "calendar_fire",
            "trigger": pending.trigger_key,
            "skill": pending.skill,
            "args": pending.args,
            "label": pending.label,
        })
        try:
            result = await self._runner(pending.skill, pending.args)
            self._log({"event": "calendar_fire_result", "label": pending.label, "result": result})
        except Exception as exc:  # noqa: BLE001 — log and move on; never re-fire
            logger.exception("scheduled skill %s failed", pending.skill)
            self._log({"event": "calendar_fire_error", "label": pending.label, "error": str(exc)})
        finally:
            if self.pending is pending:
                self.pending = None

    # -- manual controls (UI buttons / MCP tools) --------------------------------

    async def fire_now(self, event_id: str) -> dict[str, Any]:
        """Run a scheduled event's skill immediately, skipping the countdown."""
        match = next((pair for pair in self._items if pair[0].id == event_id), None)
        if match is None:
            return {"ok": False, "error": f"no scheduled event {event_id!r}"}
        event, trigger = match
        if self.pending is not None and self.pending.event_id == event_id:
            self.pending.firing = True
        self.fired.add(event_id)
        self.skipped.discard(event_id)
        self._save_state()
        self._log({
            "event": "calendar_fire_now",
            "trigger": trigger.key,
            "skill": trigger.skill,
            "label": trigger.label,
        })
        try:
            result = await self._runner(trigger.skill, dict(trigger.args))
        except Exception as exc:  # noqa: BLE001
            logger.exception("manual scheduled skill %s failed", trigger.skill)
            result = {"success": False, "error": str(exc)}
        if self.pending is not None and self.pending.event_id == event_id:
            self.pending = None
        return {"ok": True, "label": trigger.label, "result": result}

    def skip(self, event_id: str) -> dict[str, Any]:
        """Mark an event as skipped so it never fires."""
        self.skipped.add(event_id)
        if self.pending is not None and self.pending.event_id == event_id:
            self.pending = None
        self._save_state()
        self._log({"event": "calendar_skip", "event_id": event_id})
        return {"ok": True, "event_id": event_id}

    def set_auto_pilot(self, enabled: bool) -> None:
        self.auto_pilot = enabled
        if not enabled and self.pending is not None and not self.pending.firing:
            self.pending.fires_at = None  # demote a live countdown to notify-only
        self._log({"event": "calendar_auto_pilot", "enabled": enabled})

    # -- views -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        info = self._calendar.status()
        info["auto_pilot"] = self.auto_pilot
        if self.error:
            info["error"] = self.error
        return info

    def schedule_payload(self) -> dict[str, Any]:
        now = self._now()
        events = [self._event_view(event, trigger, now) for event, trigger in self._items]
        return {
            "auto_pilot": self.auto_pilot,
            "connection": self.status(),
            "pending": self._pending_view(),
            "events": events,
            "error": self.error,
            "server_time": now.isoformat(),
        }

    def _event_view(self, event: CalendarEvent, trigger: Trigger, now: datetime) -> dict[str, Any]:
        return {
            "id": event.id,
            "label": trigger.label,
            "trigger": trigger.key,
            "color_hex": trigger.color_hex,
            "skill": trigger.skill,
            "start_iso": event.start.isoformat(),
            "start_human": event.start.astimezone().strftime("%H:%M"),
            "status": self._event_status(event, now),
        }

    def _event_status(self, event: CalendarEvent, now: datetime) -> str:
        if event.id in self.fired:
            return "done"
        if event.id in self.skipped:
            return "skipped"
        if self.pending is not None and self.pending.event_id == event.id:
            return "due"
        if now < event.start:
            return "scheduled"
        if event.start <= now < event.start + self.grace:
            return "due"
        return "missed"

    def _pending_view(self) -> dict[str, Any] | None:
        if self.pending is None:
            return None
        return {
            "event_id": self.pending.event_id,
            "label": self.pending.label,
            "color_hex": self.pending.color_hex,
            "trigger": self.pending.trigger_key,
            "fires_at": self.pending.fires_at.isoformat() if self.pending.fires_at else None,
            "firing": self.pending.firing,
            "auto": self.pending.fires_at is not None,
        }

    # -- persistence -------------------------------------------------------------

    def _today_key(self) -> str:
        return self._now().astimezone().strftime("%Y-%m-%d")

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("date") != self._today_key():
            return  # a new day resets daily medication firings
        self.fired = set(data.get("fired", []))
        self.skipped = set(data.get("skipped", []))

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": self._today_key(),
            "fired": sorted(self.fired),
            "skipped": sorted(self.skipped),
        }
        try:
            self._state_path.write_text(json.dumps(payload))
        except OSError as exc:
            logger.warning("could not persist calendar state: %s", exc)

    def _log(self, event: dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.log(event)
            except Exception:  # noqa: BLE001
                logger.exception("audit log failed")
