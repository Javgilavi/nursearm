# Calendar-Driven Medication Schedule — Design

**Date:** 2026-06-07
**Status:** Approved
**Branch:** `feat/calendar-medication-schedule`

## Goal

A labelled Google Calendar event auto-fires the matching robot skill at its scheduled
time. A green-labelled event at 09:00 runs `handover_pill {color: "green"}`; a black
one runs `handover_pill {color: "black"}`; a "sort"-labelled event runs `sort_pills`.
The schedule is surfaced in the operator console and is readable/manageable by the chat
AI.

## Locked Decisions

| Dimension | Choice |
|---|---|
| Source | Real Google Calendar API (OAuth, `credentials.json` / `token.json`) |
| Matching | Config map — an event fires if its **color swatch** *or* a **title keyword** matches |
| Firing | Auto-run after a cancel countdown; master **Auto-pilot** toggle |
| UI home | "Today's medication" card atop the status rail + global due-event banner + mobile Schedule tab |
| AI scope | Read + manage (list / add / cancel events); agent confirms before any calendar write |

## Architecture

```
Google Calendar  ⇄  google_calendar client  ⇄  ┬─ PillScheduler (FastAPI bg task) ─ fires skills
                                               ├─ /calendar/* REST endpoints  ─ UI panel + banner
                                               └─ MCP tools (list/schedule/cancel) ─ chat AI
```

### New components

- **`nursearm/integrations/google_calendar.py`** — Google client.
  - OAuth scope `https://www.googleapis.com/auth/calendar.events` (read + write).
  - `status() -> {configured, authorized, calendar_id, account?}`
  - `list_events(time_min, time_max) -> list[CalendarEvent]`
  - `create_event(summary, start, duration_min, color_id?, recurrence?) -> CalendarEvent`
  - `delete_event(event_id)`
  - Lazy/guarded imports; raises typed `CalendarUnavailableError`.
  - `FakeCalendarClient` (same interface, in-memory seeded events) used when
    `NURSEARM_MOCK=1` or credentials are absent — the feature demos fully offline.

- **`config/calendar.yaml`** — loaded via the existing `config.py` pattern
  (`calendar_config()`):
  ```yaml
  poll_interval_s: 30
  grace_min: 5          # do not auto-fire events that became due > 5 min ago
  countdown_s: 15       # cancel window before auto-run
  auto_pilot: true      # default; runtime UI toggle overrides
  calendar_id: primary
  lookahead_hours: 24   # how far ahead the panel lists events
  triggers:
    green: {color_ids: ["10","2"], keywords: ["green"], skill: handover_pill, args: {color: green}, label: "Green pill"}
    black: {color_ids: ["8"],      keywords: ["black"], skill: handover_pill, args: {color: black}, label: "Black pill"}
    sort:  {color_ids: [],          keywords: ["sort"],  skill: sort_pills,    args: {},              label: "Sort pills"}
  ```

- **`nursearm/integrations/triggers.py`** — pure trigger resolution.
  `resolve_trigger(event, trigger_map) -> Trigger | None`. An event matches a trigger
  if its `colorId` is in `color_ids` **or** any keyword is a case-insensitive substring
  of the title. Trigger definition order is precedence; first match wins.

- **`nursearm/integrations/scheduler.py`** — `PillScheduler` async task.
  - Each tick (`poll_interval_s`): `list_events` over `[now, now+lookahead]`, resolve
    triggers, build the schedule model (id, label, trigger, start, status).
  - "Due" = `start <= now < start + grace_min` and not already fired. Sets a `pending`
    record with `fires_at = now + countdown_s`.
  - After the countdown, if not skipped and Auto-pilot on, executes the skill through
    `AppState._run_skill_with_cameras(...)`, marks `done`, logs audit.
  - Fired-event ids persisted to `data/calendar_state.json` (survives restarts so an
    event never double-fires within its grace window).
  - Respects a shared **robot-busy `asyncio.Lock`** so it never stacks movements; if
    busy, leaves `pending` and retries next tick within the grace window.
  - Missed events (`now - start > grace_min`) are shown as `missed`, never fired.
  - Auto-pilot off → due events become `notify`-only cards (Run / Skip), no auto-run.

- **`scripts/google_calendar_auth.py`** (console script `nursearm-calendar-auth`) —
  one-time `InstalledAppFlow` consent that writes `token.json`.

### Wiring into existing code

- **`nursearm/interface/server.py` / `AppState`**:
  - Start/stop `PillScheduler` in `start()`/`close()`.
  - Extract `_run_skill_with_cameras(name, args)` from the current `run_handover`
    (release UI camera tasks → run skill in a thread → restore); `run_handover` and the
    scheduler both call it. Guarded by the shared robot lock.
  - Endpoints: `GET /calendar/status`, `GET /calendar/schedule`,
    `POST /calendar/auto-pilot`, `POST /calendar/events`, `DELETE /calendar/events/{id}`,
    `POST /calendar/fire/{id}`, `POST /calendar/skip/{id}`.

- **`nursearm/mcp/server.py`**: add tools `list_pill_schedule`, `schedule_pill`,
  `cancel_pill` (use the same Google client; instantiated lazily in `Runtime`).
- **`nursearm/orchestrator/ollama_agent.py` `SYSTEM_PROMPT`** (shared with Claude):
  the agent knows the medication schedule exists and **confirms before** creating or
  cancelling calendar events.

### UI (`index.html`, `app.js`, `styles.css`)

- **Rail card** "Today's medication 今日用藥" at the top of the rail stack: connection
  dot, Auto-pilot toggle, timeline of upcoming events (time · color dot · label · status
  chip Scheduled/Due/Done/Skipped/Missed), a "+ Add" mini-form (time + trigger +
  daily-repeat), and a "Connect Google Calendar" CTA when unauthorized.
- **Due-event banner** — global top strip when `pending` is active: color dot +
  "Green pill due now · running in 12s" + Run now / Skip, client-side countdown from
  `fires_at`.
- **Mobile**: a 4th "Schedule" tab in the bottom bar surfaces the panel.
- Reuses the warm/clinical palette and `.rail-card` / `.status-dot` classes. Polls
  `/calendar/schedule` (~3 s), consistent with existing polling.

## Error Handling

- No `credentials.json` → `configured:false`; panel shows Connect CTA; watcher idles
  (mock mode uses the fake calendar).
- Token expired → refresh via stored refresh token; on failure `authorized:false` +
  reconnect CTA.
- API/network error in a tick → logged, retried next tick, last-known schedule kept.
- Skill failure during firing → audit note; event marked attempted, not re-fired.
- Robot busy → defer within grace window.
- Server offline across an event → only fires if within `grace_min`; older = `missed`.

## Dependencies

New optional `calendar` extra in `pyproject.toml`, lazy-imported:
`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`.
New console script `nursearm-calendar-auth`.

## Testing

- `tests/test_calendar_triggers.py` — color/keyword matching + precedence (pure fn).
- `tests/test_pill_scheduler.py` — fake clock + `FakeCalendarClient`: fires once,
  respects grace, countdown, Auto-pilot off, robot-busy deferral, missed events.
- `tests/test_calendar_endpoints.py` — FastAPI `TestClient` in mock mode: status,
  schedule, auto-pilot toggle, create/delete, fire/skip.
- `ruff check .` clean.

## Out of Scope (YAGNI)

- No local-only schedule fallback (Google-only by choice).
- No endpoint authentication (matches the rest of the app).
- No editing of recurring-series exceptions beyond create / delete.
```
