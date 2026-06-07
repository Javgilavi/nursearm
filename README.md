# NurseArm

NurseArm connects an SO-101 robot arm to a browser interface and an LLM agent. The
agent discovers a bounded set of MCP tools, selects a configured skill, executes it,
and reports the structured result.

See [HONESTY.md](HONESTY.md) for the project provenance, hackathon contributions,
third-party foundations, AI assistance, functional status, mocks, and limitations.

The current project supports:

- Direct primitives: home, grip, release, and six Cartesian step directions
- A trained ACT `sort_pills` policy through `lerobot-rollout`
- An ACT `handover_pill` policy for green or black pill requests
- A calendar-driven medication schedule that auto-runs the matching pill skill at each event's time
- Intel RealSense or V4L2 webcam streaming
- MediaPipe hand openness and palm-up detection
- Text and Faster-Whisper voice input
- Ollama or Anthropic Claude as the task-level agent
- JSONL audit events and a live browser console
- An optional Telegram bridge through OpenClaw

There are no simulated-success or placeholder skills in the registry.

## Setup

Requirements:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/) for the default local agent, or an Anthropic API key
- LeRobot installed in the same environment for ACT policy execution
- SO-101 and camera hardware for real operation

Clone the repository, enter its root directory, and install the application:

```bash
uv sync --extra dev
cp .env.example .env
```

NurseArm automatically reads `.env` from the repository root. Do not commit that
file because it can contain API keys and local hardware paths.

For the default local agent:

```bash
ollama pull qwen3:4b
```

Alternatively, edit `.env` to use Claude:

```dotenv
AGENT_BACKEND=claude
ANTHROPIC_API_KEY=your-real-key
```

### Start The UI And Server

The FastAPI process serves the API, browser UI, camera streams, and LLM agent together.
You do not need to start a separate frontend development server.

For a complete local test without robot or camera hardware, set this in `.env`:

```dotenv
NURSEARM_MOCK=1
AGENT_BACKEND=ollama
WHISPER_MODEL=base
```

Then start the application from the repository root:

```bash
uv run nursearm-serve
```

Open `http://127.0.0.1:8000` in a browser. Verify startup from another terminal:

```bash
curl http://127.0.0.1:8000/health
```

The response should contain `"ok": true` and `"mock": true`. The first startup can
take longer while Faster-Whisper downloads the selected model.

Mock mode is a development mode, not a simulated task-success mode. Primitive state is
updated in memory, while `sort_pills` still fails clearly if no policy checkpoint is
configured. Stop the server with `Ctrl+C`.

## Run With Hardware

Install camera support and LeRobot into the same `uv` environment:

```bash
uv sync --extra dev --extra robot
uv pip install -e "/absolute/path/to/lerobot[core_scripts]"
uv run lerobot-rollout --help
```

The `robot` extra installs Intel RealSense support. It is optional when every camera
uses OpenCV/V4L2. LeRobot supplies the SO-101 runtime and policy deployment commands.

On Linux, give your user permanent access to SO-101 serial devices:

```bash
sudo usermod -aG dialout "$USER"
```

Log out completely and log back in, then verify:

```bash
groups
ls -l /dev/ttyACM0 /dev/ttyACM1
test -r /dev/ttyACM1 && test -w /dev/ttyACM1 && echo "serial access OK"
```

`groups` must include `dialout`. For an immediate fix that lasts only until the device
is unplugged or the machine restarts, use:

```bash
sudo setfacl -m "u:$USER:rw" /dev/ttyACM1
```

Before startup:

1. Calibrate the follower arm with LeRobot and confirm its calibration file exists.
2. Review [config/robot.yaml](config/robot.yaml). Set the follower serial port, robot
   ID, camera definitions, FPS, policy device, and rollout duration.
3. Make the serial and camera devices accessible to the current Linux user.
4. Edit `.env` and set `NURSEARM_MOCK=0`, the camera source/indexes, agent backend,
   and checkpoint paths.
5. Confirm that each checkpoint's camera names, image sizes, FPS, task label, and
   robot calibration match the training dataset.

Example `.env` values:

```dotenv
NURSEARM_MOCK=0
NURSEARM_CAMERA_SOURCE=webcam
NURSEARM_WEBCAM_INDEX=8
NURSEARM_CAMERA2_INDEX=2
NURSEARM_SORT_PILLS_POLICY=/absolute/path/to/sort/pretrained_model
NURSEARM_HANDOVER_PILLS_POLICY=/absolute/path/to/handover/pretrained_model
```

Then start the server:

```bash
uv run nursearm-serve
```

Open `http://127.0.0.1:8000` and check `http://127.0.0.1:8000/health` before moving
the arm. `nursearm-serve` listens on port `8000`; the browser UI is part of this same
server.

The ACT rollout temporarily releases the in-process motor bus, runs
`lerobot-rollout`, and reconnects after the subprocess exits.

## Configuration

Important environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_BACKEND` | `ollama` | `ollama` or `claude` |
| `OLLAMA_MODEL` | `qwen3:4b` | Local Ollama model |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `ANTHROPIC_API_KEY` | unset | Required for the Claude backend |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Anthropic model ID |
| `NURSEARM_MOCK` | `0` | Set to `1` to prevent hardware access |
| `NURSEARM_CAMERA_SOURCE` | `realsense` | `realsense` or `webcam` |
| `NURSEARM_WEBCAM_INDEX` | `0` | Primary V4L2 camera index |
| `NURSEARM_CAMERA2_INDEX` | `2` | Secondary camera index |
| `NURSEARM_LEROBOT_ROLLOUT` | `lerobot-rollout` | Rollout executable, optionally from a separate LeRobot environment |
| `NURSEARM_SORT_PILLS_POLICY` | unset | ACT checkpoint directory |
| `NURSEARM_HANDOVER_PILLS_POLICY` | unset | Shared handover checkpoint |
| `NURSEARM_HANDOVER_GREEN_POLICY` | unset | Optional green-only checkpoint override |
| `NURSEARM_HANDOVER_BLACK_POLICY` | unset | Optional black-only checkpoint override |
| `NURSEARM_HANDOVER_TASK_TEMPLATE` | `Give the {color} pill to the hand` | Handover task label |
| `NURSEARM_HANDOVER_CAMERA_ARG` | unset | Handover training camera config override |
| `NURSEARM_HANDOVER_FPS` | unset | Handover training FPS override |
| `WHISPER_MODEL` | `small` | Faster-Whisper model size |

## Skills

Enabled skills are defined in [config/skills.yaml](config/skills.yaml):

| Skill | Type | Behavior |
|---|---|---|
| `home` | primitive | Move to the calibrated rest pose |
| `grip` | primitive | Close the gripper |
| `release` | primitive | Open the gripper |
| `move_up`, `move_down` | primitive | Cartesian vertical step through IK |
| `move_forward`, `move_back` | primitive | Cartesian depth step through IK |
| `move_left`, `move_right` | primitive | Cartesian lateral step through IK |
| `sort_pills` | ACT policy | Sort green and black pills into matching cups |
| `handover_pill` | ACT policy | Pick a requested green or black pill and present it to a hand |

The MCP server exposes:

- `list_skills`
- `get_scene`
- `run_skill`
- `handover_pill`
- `list_pill_schedule`, `schedule_pill`, `cancel_pill` (see [Medication Schedule](#medication-schedule))

`get_scene` reports the implemented hand/palm fields only. Object, face, mouth, and
gaze detection are not advertised because they are not implemented.

### Connect The Handover Checkpoint

Send the complete `pretrained_model` directory, not `training_state`:

```bash
tar -czf act_handover_pills_step35000.tar.gz \
  -C outputs/train/act_handover_pills/checkpoints/035000 pretrained_model
sha256sum act_handover_pills_step35000.tar.gz \
  > act_handover_pills_step35000.tar.gz.sha256
```

The recipient should extract it to a stable absolute path:

```bash
mkdir -p ~/nursearm-models/act_handover_pills_step35000
tar -xzf act_handover_pills_step35000.tar.gz \
  -C ~/nursearm-models/act_handover_pills_step35000

export NURSEARM_HANDOVER_PILLS_POLICY="$HOME/nursearm-models/act_handover_pills_step35000/pretrained_model"
```

The directory must contain at least:

```text
pretrained_model/
├── config.json
└── model.safetensors
```

Keep the processor and normalization files generated in the directory as well.

Call it directly through MCP:

```bash
NURSEARM_MOCK=0 uv run nursearm-mcp-client \
  --call handover_pill \
  --arguments '{"color":"green"}'
```

Or ask the browser agent: `Hand me the black pill.` The LLM should select
`handover_pill` and pass `{"color":"black"}`.

The installed LeRobot version uses `lerobot-rollout` for policy deployment.
`lerobot-record --policy.path=...` is not valid in this version because
`lerobot-record` is teleoperation data collection only. Install LeRobot's core script
dependencies in the same environment used to run NurseArm:

```bash
uv pip install -e "/absolute/path/to/lerobot[core_scripts]"
```

Verify before connecting the robot:

```bash
uv run lerobot-rollout --help
```

If this fails with `ModuleNotFoundError: draccus`, the LeRobot environment is
incomplete.

**ACT color selection:** standard ACT consumes robot state and images, not the MCP task
text. A shared checkpoint can select green versus black only if your training pipeline
actually conditioned the policy on that instruction. Otherwise train/export separate
checkpoints and configure:

```bash
export NURSEARM_HANDOVER_GREEN_POLICY=/path/to/green/pretrained_model
export NURSEARM_HANDOVER_BLACK_POLICY=/path/to/black/pretrained_model
```

Those color-specific variables take precedence over the shared path.

If the handover dataset used different cameras or FPS from `config/robot.yaml`, set
the exact training values:

```bash
export NURSEARM_HANDOVER_CAMERA_ARG='{...the exact LeRobot camera config...}'
export NURSEARM_HANDOVER_FPS=15
export NURSEARM_HANDOVER_TASK_TEMPLATE='Give the {color} pill to the hand'
```

Camera keys such as `wrist` and `front` must match the checkpoint's input feature
names. Do not rename or omit a trained camera.

## Medication Schedule

A calendar event whose label is a pill colour automatically runs the matching skill at
the event's scheduled time. A green-labelled event at 09:00 hands over the green pill; a
black-labelled event hands over the black pill; a `sort`-labelled event runs `sort_pills`.
This is just a convenient way to require a robot skill, automated by a calendar entry.

A background watcher in the server polls the calendar, resolves each event to a trigger,
and fires the mapped skill once. Firing is serialized with the rest of the robot through a
shared lock, so a scheduled pill never stacks a rollout on top of a live movement.

### Launching

There is **no separate command** — the medication scheduler starts inside `nursearm-serve`
alongside the UI. The same command you already use to launch NurseArm also launches the
calendar:

```bash
uv run nursearm-serve
```

Open `http://127.0.0.1:8000`; the **Today's medication** card is at the top of the left
rail. Which calendar it reads depends only on how the server is started:

| How you start the server | Calendar backend | Card chip |
|---|---|---|
| `NURSEARM_MOCK=1 uv run nursearm-serve` | offline demo (seeded sample pills) | **Demo** |
| `uv run nursearm-serve` (full hardware, `NURSEARM_MOCK=0`) | your real Google Calendar | **Connected** once authorized |
| `NURSEARM_MOCK=1 NURSEARM_CALENDAR_REAL=1 uv run nursearm-serve` | real Google Calendar, mocked robot | **Connected** once authorized |

The scheduler always starts; if the real calendar is not authorized yet the card simply
shows **Offline** and the rest of NurseArm runs normally. To connect the real calendar, do
the one-time setup in [Connect A Real Google Calendar](#connect-a-real-google-calendar) —
after that, the same `uv run nursearm-serve` picks it up automatically on every launch.

### Triggers And Timing

Triggers live in [config/calendar.yaml](config/calendar.yaml). Each trigger maps a calendar
event to a skill by **colour swatch** (Google `colorId`) **or** by a **keyword** in the event
title (case-insensitive substring). The first trigger in file order that matches wins.

```yaml
triggers:
  green: { color_ids: ["10", "2"], keywords: ["green"], skill: handover_pill, args: { color: green }, label: "Green pill", color_hex: "#0b8043" }
  black: { color_ids: ["8"],       keywords: ["black"], skill: handover_pill, args: { color: black }, label: "Black pill", color_hex: "#3c4043" }
  sort:  { color_ids: [],          keywords: ["sort"],  skill: sort_pills,    args: {},               label: "Sort pills", color_hex: "#b8860b" }
```

Timing knobs in the same file:

| Key | Default | Purpose |
|---|---|---|
| `calendar_id` | `primary` | Which calendar to watch |
| `poll_interval_s` | `30` | How often the watcher reloads events |
| `countdown_s` | `15` | Auto-pilot cancel window before a due pill runs |
| `grace_min` | `5` | How long after the scheduled time an event stays runnable |
| `lookahead_hours` | `24` | How far ahead events are loaded |
| `auto_pilot` | `true` | Run due pills automatically (see below) |

### How It Behaves

With **Auto-pilot on**, a due pill shows a banner with a `countdown_s` cancel window, then
runs automatically if the robot is free (it defers while the robot is busy, within the grace
window). With **Auto-pilot off**, the banner is notify-only — you press **Give now** or
**Skip**. Each event fires at most once per day; fired and skipped ids are persisted to
`data/calendar_state.json` so an event never double-fires across a restart, and the record
resets the next day for daily medications.

In the browser, the **Today's medication** card at the top of the status rail shows the
connection state, the Auto-pilot switch, today's pill timeline, and an **Add pill** form. A
global banner appears when a pill is due. On phones the schedule has its own bottom-bar tab.

**Anticipate a pill:** any upcoming (or missed) pill has a **Give now** button on its row —
press it to run that pill immediately, ahead of its scheduled time. A due pill instead shows
**Give** / **Skip**, and the `×` removes an event entirely.

**Daily medications:** tick **Repeat daily** in the Add form (or ask the agent to repeat
daily) to create a recurring event. Each day's instance is tracked separately, so it fires
once per day and the per-day state resets automatically. Daily events expand into one dated
instance per day in both the real Google backend and the offline demo.

### Demo Mode (No Calendar Required)

In mock mode (`NURSEARM_MOCK=1`) or whenever Google credentials are absent, an in-memory
calendar seeds two sample events (a green pill a couple of minutes out and a black pill later
in the day) so the card, banner, and auto-run flow all work offline. The connection chip
reads **Demo**.

### Connect A Real Google Calendar

1. Install the optional dependencies:

   ```bash
   uv sync --extra calendar
   ```

2. In the Google Cloud Console, enable the **Google Calendar API**, create an **OAuth client
   ID** of type **Desktop app**, download the JSON, and save it at the repository root as
   `credentials.json`.

3. Run the one-time consent flow (opens a browser, writes `token.json`):

   ```bash
   uv run nursearm-calendar-auth
   ```

4. Start the server with the real calendar. To test against your live Google Calendar
   **without** any robot or camera hardware, keep the robot mocked and force the real
   calendar backend:

   ```bash
   NURSEARM_MOCK=1 NURSEARM_CALENDAR_REAL=1 uv run nursearm-serve
   ```

   (On a full hardware deployment, `NURSEARM_MOCK=0` already uses the real calendar.) The
   connection chip now reads **Connected**.

5. In Google Calendar, create an event that matches a trigger — title it `green`/`black`/`sort`,
   or colour it (Basil/Sage = green, Graphite = black) — at a time a few minutes out. It
   appears in the card and fires at its start time (in mock-robot mode the "give" runs the
   in-memory skill, so you see the full due → banner → done flow with no hardware).

`credentials.json` and `token.json` are secrets. They are git-ignored — never commit them.

> `NURSEARM_CALENDAR_REAL=1` forces the real Google client even while `NURSEARM_MOCK=1`
> keeps the robot/cameras mocked — handy for testing or demoing the schedule on a laptop.

### Follow A Patient's Calendar From A Caregiver's Machine

NurseArm reads **one** calendar: the one named in `config/calendar.yaml` → `calendar_id`,
through whichever Google account ran `nursearm-calendar-auth` on the host. `calendar_id`
ships set to the patient's address (`simoutili@gmail.com`) so the robot follows the
patient's schedule no matter who runs it. To let a caregiver's machine read the patient's
calendar **without sharing the patient's login**:

1. **Patient** shares the calendar: Google Calendar → **Settings → [their calendar] →
   Share with specific people or groups → Add people →** enter the caregiver's Gmail →
   permission **"See all event details"** (or "Make changes to events" to let the robot
   add/cancel pills) → **Send**.
2. **Caregiver** accepts the share (email link or it appears under "Other calendars").
3. On the caregiver's machine, the caregiver runs `nursearm-calendar-auth` with **their
   own** Google account.
4. Confirm `config/calendar.yaml` has `calendar_id: simoutili@gmail.com` (the patient's
   address — already set). Restart `nursearm-serve`.

The robot now fires pills from the patient's shared calendar; the caregiver never handles
the patient's credentials. (Alternatively, run `nursearm-calendar-auth` signed in as the
patient and leave `calendar_id` as the patient's address or `primary` — simpler, but the
patient's `token.json` then lives on that machine.)

### Control It Through The Agent

The agent can read and manage the schedule with the `list_pill_schedule`, `schedule_pill`,
and `cancel_pill` MCP tools. Ask in chat, for example, "What pills are scheduled today?",
"Schedule the green pill at 9am every day", or "Cancel the 9am pill." The agent confirms the
pill, time, and repeat before creating or cancelling an event; scheduled pills still auto-run
at their time, so it does not hand them over itself.

## ACT Data And Training

The helper scripts print LeRobot commands using the repository configuration:

```bash
python scripts/record_demos.py sort_pills --episodes 60 --hf-user YOUR_NAME
python scripts/train_skill.py sort_pills --steps 60000 --hf-user YOUR_NAME
```

The rollout camera configuration and task text must match training.

## Palm Detection

```bash
python scripts/collect_palm_up_dataset.py
python scripts/train_palm_up_model.py
python scripts/test_perception.py
```

The optional trained classifier is stored at
`data/models/palm_up_model.json`. If it is absent, hand analysis uses the geometric
palm-normal heuristic.

## MCP

The browser server automatically starts its own local MCP subprocess for the LLM
agent. Do not start the standalone MCP server just to use the browser UI.

List tools or call a skill without an LLM:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp-client --list-tools
NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --call run_skill \
  --arguments '{"name":"move_up","args":{"step_m":0.02}}'
```

Run the standalone HTTP MCP server only when an external MCP client needs to connect
directly:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp --transport streamable-http
```

See [MCP.md](MCP.md) for client configuration.

## Telegram

Set `ANTHROPIC_API_KEY` and `TELEGRAM_BOT_TOKEN`, start the NurseArm server on an
address reachable from Docker, then run:

```bash
docker compose up --build openclaw
```

The container receives Telegram messages and forwards supported requests to `/chat`
through one MCP bridge tool. It also sends a heartbeat every 3 seconds; the UI marks
the OpenClaw bot offline after roughly 8-9 seconds without a heartbeat. Rebuild the
container after updating the bot files so this status signal is included.

## Tests

```bash
uv run pytest -q
uv run ruff check .
NURSEARM_MOCK=1 uv run python scripts/test_mcp.py
```

## Repository Layout

| Path | Purpose |
|---|---|
| `nursearm/interface/` | FastAPI server and browser UI |
| `nursearm/orchestrator/` | Ollama and Claude MCP agents |
| `nursearm/mcp/` | MCP server and stdio client |
| `nursearm/skills/` | Configured primitives and ACT skill |
| `nursearm/robot/` | Motor bus, controller, and kinematics |
| `nursearm/perception/` | Camera and hand/palm detection |
| `nursearm/audit/` | JSONL event logging |
| `scripts/` | Calibration, data, training, and smoke-test utilities |
| `bot/` | Isolated OpenClaw Telegram bridge |

## Current Limitations

- Cartesian IK does not yet enforce workspace or convergence limits.
- Direct `/robot/action` requests are not authenticated.
- The interface and MCP subprocess currently own separate controller instances in
  real mode; do not issue concurrent UI and agent movements.
- Primitive success means the command was sent; there is no closed-loop completion
  verification.
- `sort_pills` runs the policy but reports `success=false` until visual outcome
  verification is implemented.
- `handover_pill` also reports `success=false` after rollout until handover verification
  is implemented.
- Torque is disabled after primitive motion, including gripper commands.

Operate the physical arm only in a controlled workspace with an accessible emergency
stop.
