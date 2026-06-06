# NurseArm — an assistive robot arm you talk to

> An SO-101 robot arm that helps a person with physical tasks — feeding, dispensing
> medication, picking things up, handing things over. You ask in plain language (or
> speak into the mic); an LLM **agent** orchestrates fast, specialized **skills**
> and watches each one through an Intel RealSense RGB-D camera, recovering when
> something goes wrong.

Built for a 24-hour hackathon. Healthcare for Hong Kong.

- **[PLAN.md](./PLAN.md)** — the 24-hour build plan, scope control, and owner split.
- **[AGENT.md](./AGENT.md)** — how the LLM agent drives the robot.
- **[MCP.md](./MCP.md)** — install, test, and connect the MCP server to an LLM.

---

## Running the project (laptop, no hardware)

### Prerequisites

```bash
# 1. Install Ollama (only needed if using the Ollama backend)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:4b          # default model
# or
ollama pull qwen2.5:3b        # smaller, faster, better at following instructions
ollama pull qwen2.5:7b        # best quality, needs ~5 GB RAM

# 2. Install Python dependencies
uv sync --extra dev

# 3. (Optional) Install and authenticate ngrok for phone access
#    Get a free token at https://ngrok.com
sudo apt install ngrok
ngrok config add-authtoken <your-token>
```

Faster-Whisper models download automatically on first use. The `base` model (~150 MB)
is recommended to start — it is fast and already covers short clinical commands.

### Start the server

```bash
# Ollama backend (default) — uses qwen3:4b
WHISPER_MODEL=base NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload --host 0.0.0.0

# Claude backend — uses claude-sonnet-4-6 via Anthropic API (requires ANTHROPIC_API_KEY in .env)
AGENT_BACKEND=claude WHISPER_MODEL=base NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload --host 0.0.0.0
```

Open **http://localhost:8000** in a browser.

The server automatically:
- Starts `ollama serve` if Ollama is not already running (Ollama backend only)
- Loads the Faster-Whisper model in the background (first voice request may be slow)
- Starts an ngrok HTTPS tunnel if `ngrok` is installed and authenticated

> **Note:** `--host 0.0.0.0` is required if you want the Telegram bot (OpenClaw
> Docker container) to be able to reach the server. Without it the server only
> accepts connections from `localhost` and the bot will report "server offline."

---

## Environment variables

Copy `.env.example` to `.env` to persist these without setting them each run.

### Agent backend

| Variable | Default | Description |
|---|---|---|
| `AGENT_BACKEND` | `ollama` | `ollama` or `claude` — which LLM backend to use |

### Ollama backend

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:4b` | Ollama model name. See [Ollama model options](#ollama-model-options) below. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama API base URL |

### Claude backend

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key. Get one at [console.anthropic.com](https://console.anthropic.com). |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model ID. |

### Other

| Variable | Default | Description |
|---|---|---|
| `NURSEARM_MOCK` | `0` | Set to `1` to run without robot and RealSense hardware |
| `WHISPER_MODEL` | `small` | Faster-Whisper model: `base`, `small`, `medium`, `large-v3` |

---

## LLM agent backends

### Ollama (local, no API key)

Runs fully on your laptop. No internet required for inference, no API cost.

```bash
OLLAMA_MODEL=qwen3:4b WHISPER_MODEL=base NURSEARM_MOCK=1 \
  uvicorn nursearm.interface.server:app --reload --host 0.0.0.0
```

#### Ollama model options

| Model | Pull command | RAM | Quality | Notes |
|---|---|---|---|---|
| `qwen3:4b` | `ollama pull qwen3:4b` | ~3 GB | Good | Default. Has a thinking mode that can leak verbose reasoning. |
| `qwen2.5:3b` | `ollama pull qwen2.5:3b` | ~2 GB | Good | **Recommended.** No thinking mode, follows system prompt reliably, small download. |
| `qwen2.5:7b` | `ollama pull qwen2.5:7b` | ~5 GB | Best local | Best instruction-following and tool-use among 7B models. |

To use a different model without changing code:

```bash
OLLAMA_MODEL=qwen2.5:3b WHISPER_MODEL=base NURSEARM_MOCK=1 \
  uvicorn nursearm.interface.server:app --reload --host 0.0.0.0
```

### Claude via Anthropic API

Uses `claude-sonnet-4-6` by default. Clean replies, reliable tool-use, no local GPU needed.
Requires an `ANTHROPIC_API_KEY` in your `.env` file.

```bash
AGENT_BACKEND=claude WHISPER_MODEL=base NURSEARM_MOCK=1 \
  uvicorn nursearm.interface.server:app --reload --host 0.0.0.0
```

The startup log will confirm which backend is active:

```
INFO  Agent backend: Claude (claude-sonnet-4-6)
# or
INFO  Agent backend: Ollama
```

---

## Accessing from a phone

If ngrok is installed and authenticated, the server prints the public URL at startup:

```
========================================================
  Phone / remote access:  https://abc123.ngrok-free.app
========================================================
```

The same URL also appears as a clickable link and QR code in the sidebar of the UI.
Open it on any device — the full UI including voice input works because ngrok provides
HTTPS (required by browsers for microphone access).

Without ngrok, phones on the same WiFi can reach the server at
`http://<laptop-local-ip>:8000`. Check your laptop IP with `hostname -I`.

---

## Telegram bot (OpenClaw)

NurseArm can be controlled via Telegram. The bot runs in a Docker container that is
fully isolated — it has no access to the host filesystem, shell, or browser.

### What you need

1. A Telegram bot token — create one with [@BotFather](https://t.me/BotFather) on Telegram.
2. An Anthropic API key (OpenClaw uses Claude as its reasoning engine inside the bot).
3. Docker and Docker Compose installed on the laptop.

### Setup

Create a `.env` file in the repo root (if you do not have one already):

```bash
cp .env.example .env
```

Add these two lines:

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456789:AAF...
```

### Run the bot

Start the NurseArm server first (with `--host 0.0.0.0`), then:

```bash
docker compose up --build openclaw
```

The container:
1. Generates an isolated OpenClaw config (no shell, no file, no browser access).
2. Registers the Telegram bot token via `openclaw channels add`.
3. Connects to your bot and starts listening for messages.

You will see in the logs:

```
[telegram] [default] starting provider (@YourBotName)
[gateway] ready
```

### First-time pairing

The first time you message the bot on Telegram it will reply with a pairing command,
for example:

```
openclaw pairing approve telegram U2LJC7D3
```

Run that in a separate terminal while the container is running:

```bash
docker exec nursearm-openclaw openclaw pairing approve telegram U2LJC7D3
```

This is a one-time step. After approval, your Telegram account can talk to the bot
freely.

### How it works

```
Telegram message
    → OpenClaw (Claude inside container)
    → MCP bridge (Python, inside container)
    → POST /chat on NurseArm server (host, port 8000)
    → NurseArm agent (Ollama or Claude)
    → reply back to Telegram
```

OpenClaw uses Claude to understand the Telegram message and decides to call the
`robot_command` MCP tool, which forwards the request to the NurseArm server. The
NurseArm server handles all robot logic and replies in plain text.

### Isolation

The container has no access to:
- The host filesystem (no volume mounts)
- A shell (`shell`, `exec` blocked)
- A browser (`browser`, `computer` blocked)
- Files (`read`, `write`, `edit`, `glob`, `grep`, `ls` blocked)

The only thing it can do is call `robot_command`, which POSTs to port 8000 on the host.

---

## Cameras and palm detection

The UI shows two camera panels:

| Panel | Stream | Description |
|---|---|---|
| Camera 1 | `/stream/palm` | Live feed with hand skeleton overlay and open/closed detection |
| Camera 2 | `/stream` | Raw camera feed, no processing |

A floating badge on Camera 1 shows the current palm state (`✋ open`, `✊ closed`,
or `— no hand`). The server logs palm status at INFO level every ~2 seconds.

---

## Accessing from a phone

If ngrok is installed and authenticated, the server prints the public URL at startup:

```
========================================================
  Phone / remote access:  https://abc123.ngrok-free.app
========================================================
```

The URL also appears as a QR code in the sidebar of the UI.

---

## Current UI — Clinical Console

```
┌─────────────┬───────────────────────────────────────────────────┐
│  NurseArm   │  Camera 1 — Palm detection             [Live]     │
│  Clinical   │                                    [✋ open badge] │
│  console    │  [MJPEG stream with hand skeleton overlay]        │
│             │                                                   │
│  System     ├───────────────────────────────────────────────────┤
│  Cameras    │  Camera 2 — Raw feed                   [Live]     │
│  Audit      │                                                   │
│             │  [MJPEG stream — laptop webcam or RealSense]      │
│  Remote URL ├───────────────────────────────────────────────────┤
│  (ngrok)    │  Chat — Operator instructions       [Audit on]    │
│  [QR code]  │                                                   │
│             │  [Morning pills] [Scene check] [Feeding help]     │
│  Focus tip  │  ─────────────────────────────────────────────── │
│             │  [input field]              [🎤 mic]  [Send]      │
└─────────────┴───────────────────────────────────────────────────┘
```

**Key features:**

- **Live cameras** — Camera 1 shows the palm detection overlay; Camera 2 is the raw
  feed. Both stream at 25–30 fps via MJPEG with no JS polling.

- **Palm detection badge** — floating pill on Camera 1 that updates every second:
  `✋ open`, `✊ closed`, or `— no hand`. Driven by MediaPipe Hand Landmarker.

- **Voice input** — click the mic button to record, click again to stop. Audio is sent
  to the server, transcribed locally by Faster-Whisper, and the text fills the input
  field.

- **Prompt chips** — quick-action buttons pre-fill the input with common commands.

- **Chat** — user messages appear immediately. A spinner shows while the agent works.
  Every agent decision streams to the audit log via WebSocket.

- **Resizable panels** — drag splitters to resize cameras vs chat. Layout persists to
  `localStorage`.

- **QR code** — the ngrok URL appears as a scannable QR code in the sidebar.

---

## Models

### LLM agent

Two backends are available. Switch with `AGENT_BACKEND`.

**Ollama (default):** runs locally, no API key. The agent uses `think: false` to
suppress chain-of-thought tokens and includes a recovery path for models that emit
tool calls as plain-text JSON. See [Ollama model options](#ollama-model-options).

**Claude:** calls the Anthropic API. Reliable tool-use, clean replies, no local GPU
required. Uses `claude-sonnet-4-6` by default; override with `CLAUDE_MODEL`.

### Speech-to-text — Faster-Whisper

[Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) runs fully locally.

| Model | Size | Speed on GPU | Recommended for |
|---|---|---|---|
| `base` | ~150 MB | ~0.5 s | Quick demo |
| `small` | ~460 MB | ~1 s | Good default |
| `medium` | ~1.5 GB | ~2 s | High accuracy |
| `large-v3` | ~3 GB | ~3–4 s | Best quality |

Set `WHISPER_MODEL=base` (or any size above) before starting the server. The model
downloads from Hugging Face to `~/.cache/huggingface/hub/` automatically.

---

## Skills and MCP tools

The agent calls skills through a local MCP server that runs as a stdio subprocess
managed by the FastAPI server. The MCP server exposes these tools:

| Tool | Purpose |
|---|---|
| `run_vla` | **Main physical tool.** Runs the VLA policy with a natural-language task description. Currently a dummy that echoes the task and simulates success. Replace with a real policy checkpoint in `config/skills.yaml`. |
| `run_skill` | Generic skill runner by registry name — for primitive moves and integration tests. |
| `list_skills` | Lists every enabled skill with kind and description. |
| `get_scene` | Reads the current camera-derived scene observation without moving the robot. |

---

## Architecture

```
  voice / text  ─▶  INTERFACE (FastAPI + clinical web UI)
                         │  user intent
                         ▼
                    AGENT  (Ollama local  ─or─  Claude API)
                         │  picks a tool, reads result, reports
              ┌──────────┴──────────┐
              ▼                     ▼
         MCP TOOLS             PRIMITIVES
         run_vla               move_up / move_down
         (VLA policy)
              │
              ▼
       SKILL REGISTRY  ──▶  RobotController  ──▶  SO-101 (LeRobot)
                       ──▶  Perception       ──▶  RealSense / webcam

  Side services:
    Faster-Whisper (STT) · ngrok (remote HTTPS) · Audit log (JSONL)
    OpenClaw Docker bot  (Telegram → /chat bridge, isolated container)
```

---

## With the robot (hardware path)

```bash
# 0) calibrate the SO-101 (one-time)
lerobot-find-port
lerobot-setup-motors --robot.type=so101_follower --robot.port=<PORT>
lerobot-calibrate    --robot.type=so101_follower --robot.port=<PORT> --robot.id=follower
python scripts/calibrate.py        # fill config/robot.yaml afterwards

# 1) verify perception before any skill
python scripts/test_perception.py  # live mouth / hand / object / gaze 3D points

# 2) record demos and train
python scripts/record_demos.py dispense_pills --episodes 60
python scripts/train_skill.py  dispense_pills --steps 60000
#    set the printed policy_path in config/skills.yaml

# 3) run for real
NURSEARM_MOCK=0 uvicorn nursearm.interface.server:app --host 0.0.0.0
```

For quick laptop-only testing, you can use the built-in webcam instead of the Intel
RealSense:

```bash
NURSEARM_MOCK=0 NURSEARM_CAMERA_SOURCE=webcam NURSEARM_WEBCAM_INDEX=0 python scripts/test_perception.py
```

This webcam mode is RGB-only. It is good for validating hand detection and `palm_up`,
but not for any task that depends on reliable 3D palm position.

### Train palm-up hand detection for the Intel RealSense

The repo now includes a lightweight AI pipeline for `palm_up / not_palm_up`:
MediaPipe extracts the 21 hand landmarks, and a small classifier is trained over the
3D hand geometry. This is the right level of model for this task: fast, cheap to label,
and easy to deploy in a robotics loop.

```bash
# 1) collect labeled examples with the RealSense
python scripts/collect_palm_up_dataset.py
#    press `u` when the visible hand is palm-up
#    press `n` for any other orientation

# 2) train the classifier
python scripts/train_palm_up_model.py

# 3) verify live inference
python scripts/test_perception.py
```

The trained model is written to `data/models/palm_up_model.json`. At runtime,
`perception/hands.py` will load it automatically if it exists; otherwise it falls back
to a simple geometric heuristic based on the 3D palm normal.

---

## Repository guide

There are two directories named `nursearm`:

- The outer `nursearm/` is the Git repository: documentation, configuration, scripts, and source code.
- The inner `nursearm/` is the importable Python package.

### Python package

| Module | Responsibility |
|---|---|
| `interface/` | FastAPI server, MJPEG stream, voice transcription endpoint, web UI |
| `orchestrator/` | Ollama agent, Claude agent, skill registry, MCP client |
| `mcp/` | MCP server (tools) and client (discovery + invocation) |
| `skills/` | Skill implementations: dummy VLA, primitive stubs |
| `robot/` | LeRobot adapter — the only layer that touches the arm |
| `perception/` | RealSense / webcam capture, landmark and object detection |
| `audit/` | Append-only JSONL event log, WebSocket broadcast |
| `types.py` | Shared data contracts: `SkillResult`, `SceneObservation`, etc. |
| `config.py` | Loads `.env`, `robot.yaml`, `skills.yaml` |

### `bot/` directory

| File | Purpose |
|---|---|
| `Dockerfile` | Node 24 + Python 3 image; installs OpenClaw and the MCP bridge |
| `entrypoint.sh` | Generates OpenClaw config, registers Telegram channel, starts gateway |
| `mcp_bridge.py` | FastMCP server with one `robot_command` tool; POSTs to `/chat` |
| `workspace/SOUL.md` | OpenClaw agent persona — brief, safety-first, one tool only |
| `requirements.txt` | Python deps for the MCP bridge (`mcp`, `httpx`) |

### What is working now

| Feature | Status |
|---|---|
| Clinical web UI (rail sidebar, cameras, chat, chips) | Working |
| Live MJPEG camera stream (webcam in mock mode) | Working |
| Palm detection overlay on Camera 1 with badge | Working |
| Voice input via Faster-Whisper (local, English) | Working |
| Ollama agent (qwen3:4b, qwen2.5:3b, qwen2.5:7b) | Working |
| Claude agent (claude-sonnet-4-6 via Anthropic API) | Working |
| MCP tool calling (`run_vla`, `list_skills`, `get_scene`) | Working |
| Dummy VLA skill (echoes task, simulates success) | Working |
| Primitive mock moves (`move_up`, `move_down`) | Working |
| Audit log + WebSocket stream to UI | Working |
| ngrok HTTPS tunnel with sidebar URL + QR code | Working |
| Resizable panel layout (persisted to localStorage) | Working |
| Telegram bot via OpenClaw Docker container | Working |
| Real VLA policy execution | Needs trained checkpoint |
| RealSense RGB-D pipeline | Needs hardware |
| Cartesian robot jogging + gripper | Needs hardware |
| Visual success checking | Needs perception implementation |

---

## Safety (for the pitch)

- **Bounded tools.** The LLM calls a fixed skill set — no path to arbitrary joint commands.
- **Confidence gating.** Every skill returns a confidence score; below threshold the agent must recover or ask.
- **Safe-stop near humans.** `feed_person` halts if the tracked mouth point jumps unexpectedly.
- **Audit trail.** Every agent decision and robot action is timestamped and logged — required for healthcare, built in from day one.
- **Bot isolation.** The Telegram bot runs in a Docker container with no shell, no filesystem, and no browser access — it can only call `robot_command`.
- **Open and swappable.** MCP-standard tools; swap the local model or arm by rewriting one file. Total hardware cost < US$1,000.

---

## Tech stack

Ollama + Qwen2.5 / Qwen3 (local agent) · Claude Sonnet 4.6 (cloud agent) ·
Faster-Whisper (local STT) · FastAPI + MJPEG streaming (interface) ·
MCP (tool protocol) · LeRobot + ACT/SmolVLA (robot + policies) ·
Intel RealSense + MediaPipe (perception) · ngrok (remote HTTPS) ·
OpenClaw (Telegram/WhatsApp gateway) · Docker (bot isolation) · `uv` (packaging)
