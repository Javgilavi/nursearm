# NurseArm

NurseArm connects an SO-101 robot arm to a browser interface and an LLM agent. The
agent discovers a bounded set of MCP tools, selects a configured skill, executes it,
and reports the structured result.

The current project supports:

- Direct primitives: home, grip, release, and six Cartesian step directions
- A trained ACT `sort_pills` policy through `lerobot-rollout`
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
- Ollama for the default local agent, or an Anthropic API key
- LeRobot installed in the same environment for ACT policy execution
- SO-101 and camera hardware for real operation

```bash
uv sync --extra dev
cp .env.example .env
```

For the default local agent:

```bash
ollama pull qwen3:4b
```

## Run Without Hardware

Mock mode keeps camera and robot operations local and prevents hardware access:

```bash
NURSEARM_MOCK=1 WHISPER_MODEL=base \
  uv run uvicorn nursearm.interface.server:app --reload --host 127.0.0.1
```

Open `http://127.0.0.1:8000`.

Mock mode is a development mode, not a simulated task-success mode. Primitive state is
updated in memory, while `sort_pills` still fails clearly if no policy checkpoint is
configured.

## Run With Hardware

Review [config/robot.yaml](config/robot.yaml) first. Its ports, robot IDs, cameras, FPS,
and policy settings must match the calibration and training dataset.

Set the trained checkpoint:

```bash
export NURSEARM_SORT_PILLS_POLICY=/absolute/path/to/pretrained_model
```

Then start the server:

```bash
NURSEARM_MOCK=0 uv run uvicorn nursearm.interface.server:app --host 127.0.0.1
```

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
| `NURSEARM_SORT_PILLS_POLICY` | unset | ACT checkpoint directory |
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

The MCP server exposes:

- `list_skills`
- `get_scene`
- `run_skill`

`get_scene` reports the implemented hand/palm fields only. Object, face, mouth, and
gaze detection are not advertised because they are not implemented.

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

List tools or call a skill without an LLM:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp-client --list-tools
NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --call run_skill \
  --arguments '{"name":"move_up","args":{"step_m":0.02}}'
```

Run the standalone HTTP MCP server:

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
through one MCP bridge tool.

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
- Torque is disabled after primitive motion, including gripper commands.

Operate the physical arm only in a controlled workspace with an accessible emergency
stop.
