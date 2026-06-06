# NurseArm — an assistive robot arm you talk to

> An SO-101 robot arm that helps a person with physical tasks — feeding, dispensing
> medication, picking things up, handing things over. You ask in plain language (or
> speak into the mic); a local LLM **agent** orchestrates fast, specialized **skills**
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
# 1. Install Ollama and pull the model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:4b

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
WHISPER_MODEL=base NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload
```

Open **http://localhost:8000** in a browser.

The server automatically:
- Starts `ollama serve` if Ollama is not already running
- Loads the Faster-Whisper model in the background (first voice request may be slow)
- Starts an ngrok HTTPS tunnel if `ngrok` is installed and authenticated

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `NURSEARM_MOCK` | `0` | Set to `1` to run without robot and RealSense hardware |
| `OLLAMA_MODEL` | `qwen3:4b` | Ollama model used by the agent |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama API base URL |
| `WHISPER_MODEL` | `small` | Faster-Whisper model: `base`, `small`, `medium`, `large-v3` |

Copy `.env.example` to `.env` to persist these without setting them each run.

### Accessing from a phone

If ngrok is installed and authenticated, the server prints the public URL at startup:

```
========================================================
  Phone / remote access:  https://abc123.ngrok-free.app
========================================================
```

The same URL also appears as a clickable link in the sidebar of the UI. Open it on any
device — the full UI including voice input works because ngrok provides HTTPS (required
by browsers for microphone access).

Without ngrok, phones on the same WiFi can reach the server at
`http://<laptop-local-ip>:8000`, but the mic button will be blocked by the browser
(HTTP only). Check your laptop IP with `hostname -I`.

---

## Current UI — Clinical Console

The operator interface is a full-screen clinical console built with vanilla HTML/CSS/JS.

```
┌─────────────┬───────────────────────────────────────────────────┐
│  NurseArm   │  Camera 1 — Overhead view              [Live]     │
│  Clinical   │                                                   │
│  console    │  [MJPEG stream — laptop webcam or RealSense]      │
│             │                                                   │
│  System     ├───────────────────────────────────────────────────┤
│  Cameras    │  Camera 2 — Side view                  [Live]     │
│  Audit      │                                                   │
│             │  [MJPEG stream]                                   │
│  Remote URL ├───────────────────────────────────────────────────┤
│  (ngrok)    │  Chat — Operator instructions       [Audit on]    │
│             │                                                   │
│  Focus tip  │  [Morning pills] [Scene check] [Feeding help]     │
│             │  ─────────────────────────────────────────────── │
│             │  [input field]              [🎤 mic]  [Send]      │
└─────────────┴───────────────────────────────────────────────────┘
```

**Key features:**

- **Live camera** — MJPEG stream pushed at 25 fps; no JS polling loop. Both camera
  panels connect to the same stream, updated at 30 fps by a background capture task.
  In mock mode the laptop webcam is used automatically; a synthetic frame is shown
  if no webcam is found.

- **Voice input** — click the mic button to record, click again to stop. Audio is sent
  to the server, transcribed locally by Faster-Whisper, and the text fills the input
  field. The input and send button are disabled during transcription with a
  "Transcribing…" placeholder. Language is fixed to English.

- **Prompt chips** — three quick-action buttons pre-fill the input with common commands
  (`Morning pills`, `Scene check`, `Feeding help`). Click a chip then Send.

- **Chat** — user messages appear immediately. A spinner ("Thinking…") shows while the
  agent is working. Input and send are disabled during a response. Every agent decision
  is streamed to the audit log via WebSocket.

- **Resizable panels** — drag the horizontal splitter to resize the two camera panels;
  drag the vertical splitter to resize cameras vs chat. Layout is persisted to
  `localStorage`.

- **Sidebar rail** — system status cards (System, Cameras, Audit) and, when ngrok is
  active, a clickable remote-access URL.

---

## Models

### LLM agent — Qwen3:4b (Ollama)

The agent runs locally via Ollama. It receives the user's message, the list of
available MCP tools, and the conversation history. It decides which tool to call,
calls it, reads the result, and produces a plain-language reply.

**Why Qwen3:4b:** fast tool-calling, runs well on a laptop GPU, no API key needed.
Swap to any Ollama-hosted model by setting `OLLAMA_MODEL`. The agent uses `think: false`
to suppress chain-of-thought tokens and includes a recovery path that handles the case
where the model emits a tool call as plain-text JSON instead of the proper
function-call wire format.

Ollama is started automatically by the server if it is not already running.

### Speech-to-text — Faster-Whisper

[Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) is a CTranslate2
reimplementation of OpenAI Whisper. It runs fully locally — no API key, no network
request for transcription.

| Model | Size | Speed on GPU | Recommended for |
|---|---|---|---|
| `base` | ~150 MB | ~0.5 s | Quick demo, already downloaded |
| `small` | ~460 MB | ~1 s | Better accuracy, good default |
| `medium` | ~1.5 GB | ~2 s | High accuracy |
| `large-v3` | ~3 GB | ~3–4 s | Best quality |

The model is loaded on first voice request. On an RTX 5070 (Blackwell) the server
forces `compute_type=float16` — INT8 crashes on that architecture.

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

The single `run_vla` tool covers all physical assistance tasks — dispensing medication,
feeding, picking up objects, handing things over. The VLA model receives the task
description in natural language and decides the arm motions internally. When a real
policy checkpoint is ready, set `policy_path` in `config/skills.yaml` and replace
`DummyVLASkill` with the real implementation — the MCP interface does not change.

Primitive skills (`move_up`, `move_down`) and dummy integration skills are accessible
via `run_skill`. The dummy skills always return success and never move hardware.

---

## Architecture

```
  voice / text  ─▶  INTERFACE (FastAPI + clinical web UI)
                         │  user intent
                         ▼
                    AGENT  (Ollama + Qwen3:4b, tool-calling via MCP)
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

  Side services: Faster-Whisper (STT) · ngrok (remote HTTPS) · Audit log (JSONL)
```

**The one design rule that keeps this buildable in 24h:** robot policies stay dumb and
reliable (one trained skill each); all intelligence lives in the orchestrator. Never
push reasoning into the policy. See **AGENT.md**.

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
NURSEARM_MOCK=0 uvicorn nursearm.interface.server:app
```

---

## Repository guide

There are two directories named `nursearm`:

- The outer `nursearm/` is the Git repository: documentation, configuration, scripts, and source code.
- The inner `nursearm/` is the importable Python package.

### Python package

| Module | Responsibility |
|---|---|
| `interface/` | FastAPI server, MJPEG stream, voice transcription endpoint, web UI |
| `orchestrator/` | Local Ollama agent, skill registry, MCP client |
| `mcp/` | MCP server (tools) and client (discovery + invocation) |
| `skills/` | Skill implementations: dummy VLA, primitive stubs |
| `robot/` | LeRobot adapter — the only layer that touches the arm |
| `perception/` | RealSense / webcam capture, landmark and object detection |
| `audit/` | Append-only JSONL event log, WebSocket broadcast |
| `types.py` | Shared data contracts: `SkillResult`, `SceneObservation`, etc. |
| `config.py` | Loads `.env`, `robot.yaml`, `skills.yaml` |

### What is working now

| Feature | Status |
|---|---|
| Clinical web UI (rail sidebar, cameras, chat, chips) | Working |
| Live MJPEG camera stream (webcam in mock mode) | Working |
| Voice input via Faster-Whisper (local, English) | Working |
| Local Qwen3:4b agent via Ollama | Working |
| MCP tool calling (`run_vla`, `list_skills`, `get_scene`) | Working |
| Dummy VLA skill (echoes task, simulates success) | Working |
| Primitive mock moves (`move_up`, `move_down`) | Working |
| Audit log + WebSocket stream to UI | Working |
| ngrok HTTPS tunnel with sidebar URL | Working |
| Resizable panel layout (persisted to localStorage) | Working |
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
- **Open and swappable.** MCP-standard tools; swap the local model or arm by rewriting one file. Total hardware cost < US$1,000.

---

## Tech stack

Ollama + Qwen3:4b (local agent) · Faster-Whisper (local STT) ·
FastAPI + MJPEG streaming (interface) · MCP (tool protocol) ·
LeRobot + ACT/SmolVLA (robot + policies) · Intel RealSense + MediaPipe (perception) ·
ngrok (remote HTTPS access) · `uv` (packaging)
