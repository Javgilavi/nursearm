# NurseArm — an assistive robot arm you talk to

> An SO-101 robot arm that helps a person with physical tasks — feeding, dispensing
> medication, picking things up, handing things over. You ask in plain language; an LLM
> **judge** orchestrates fast, specialized **skills** and watches each one through an
> Intel RealSense RGB-D camera, recovering when something goes wrong.

Built for a 24-hour hackathon. Healthcare for Hong Kong. The architecture (a slow,
smart LLM planner orchestrating fast, dumb sub-policies with recovery behaviours
between them) is the pattern that took runner-up at Physical AI Hack 2026 — adapted
here to assistive care.

- **[PLAN.md](./PLAN.md)** — the 24-hour build plan, scope control, and owner split.
- **[AGENT.md](./AGENT.md)** — how the LLM judge drives the robot (the heart of the project).

---

## What it does

| Kind | Skill | What it does | Status |
|---|---|---|---|
| Primitive | `move_up`, `move_down` | Emit a direct fixed-step movement command | scaffolded |
| VLA | `dispense_pills` | Picks the requested pill and places it in the cup | **build first** |
| VLA | `feed_person` | Scoops food and brings the spoon toward the person's mouth | **build first** |
| VLA | `gaze_pick` | Picks up whatever the person is looking at | stretch |
| VLA | `hand_handoff` | Places an object safely into an open palm | stretch |

You talk to it from a web UI (chat + mic) and watch the judge's reasoning and every
robot action stream into a live **audit log** — the healthcare safety story, built in
from minute one.

---

## Architecture (one screen)

```
  speech / text  ─▶  INTERFACE (FastAPI + web UI, optional WhatsApp/Telegram via MCP)
                          │  user intent
                          ▼
                     JUDGE  (Claude, tool-calling)   ◀── the only thing that "thinks"
                          │  picks a skill, watches, recovers, reports
            ┌─────────────┼──────────────┐
            ▼                            ▼
      PRIMITIVES           VLA SKILLS              PERCEPTION
      move up/down         prompt → policy         hands / mouth
            │                   │                         │
            └───────────────────┴──────────┬──────────────┘
                                          ▼
     ROBOT LAYER (LeRobot: ACT/SmolVLA policies, joint + gripper control)
            │
        SO-101 arm

  External: Google Calendar (today's meds) · append-only Audit Log (every action)
```

**The one design rule that keeps this buildable in 24h:** the robot policies stay
*dumb and reliable* (one trained skill each); all the intelligence lives in the
orchestrator and perception. Never push reasoning into the policy. See **AGENT.md**.

---

## How this repo relates to LeRobot

**We depend on [LeRobot](https://github.com/huggingface/lerobot) — we do not fork or
vendor it.** NurseArm is the orchestration/perception/interface layer on top; LeRobot
provides the robot drivers, the ACT/SmolVLA policies, and the record/train/rollout
CLIs. Reasons: forking means maintaining a divergent copy during a 24h sprint; vendoring
a clone bloats the repo and pins us to one commit. A clean dependency keeps NurseArm
small and lets us pull LeRobot fixes for free.

The robot is touched in exactly one file — [`nursearm/robot/controller.py`](./nursearm/robot/controller.py)
— which either (A) imports LeRobot in-process for low-latency servoing, or (B) shells
out to `lerobot-rollout` for a full trained-skill rollout. Swap LeRobot for another
robot stack by rewriting only that file.

### Installing LeRobot

You already have a working LeRobot checkout at `../lerobot`. The painless path is to
**install NurseArm into LeRobot's existing venv** (torch + CUDA are already resolved
there):

```bash
# 1) activate the lerobot venv and make sure the motor stack is present
cd ../lerobot
source .venv/bin/activate
uv pip install -e ".[feetech]"          # SO-101 motors (not installed by default)

# 2) install NurseArm + its vision deps into that same venv
cd ../nursearm
uv pip install -e ".[robot,calendar]"   # add ,voice or ,mcp if you use them
```

Standalone alternative (separate venv): `uv venv --python 3.12 && uv pip install -e ".[robot,calendar]"`,
then install LeRobot separately with `pip install 'lerobot[feetech]'`.

---

## Quickstart

### Laptop, no hardware (verify the brain first)

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY; leave NURSEARM_MOCK=1
NURSEARM_MOCK=1 nursearm-serve
# open http://localhost:8000  →  type "give me my morning pills"
```

In mock mode the robot and camera are stubbed, so the **judge loop, the skill
selection, the calendar tool, and the audit log all run on a laptop** — perfect for
building and demoing the orchestration before the hardware is ready. Skills will report
"not implemented" until their policies are trained, which is exactly what the judge's
recovery/ask-human logic is there to handle.

### With the robot

```bash
# 0) one-time: calibrate the SO-101 (LeRobot CLIs)
lerobot-find-port
lerobot-setup-motors --robot.type=so101_follower --robot.port=<PORT>
lerobot-calibrate    --robot.type=so101_follower --robot.port=<PORT> --robot.id=follower
python scripts/calibrate.py        # then fill config/robot.yaml (ports, ids, hand-eye)

# 1) ALWAYS verify perception before any skill (README §hard rule)
python scripts/test_perception.py  # live mouth / hand / object / gaze 3D points

# 2) record + train a skill (prints the exact lerobot commands)
python scripts/record_demos.py dispense_pills --episodes 60
python scripts/train_skill.py  dispense_pills --steps 60000
#    → set the printed policy_path in config/skills.yaml

# 3) run for real
NURSEARM_MOCK=0 nursearm-serve
```

---

## Repository guide

There are two directories named `nursearm`:

- The outer `nursearm/` is the Git repository: documentation, configuration, scripts, and source code.
- The inner `nursearm/` is the importable Python package. For example,
  `nursearm/interface/server.py` is imported as `nursearm.interface.server`.

### Request flow

A normal text request follows this path:

1. `interface/web/index.html` sends text to `POST /chat`.
2. `interface/server.py` owns the long-lived robot, camera, registry, audit log, and judge objects, and serves `GET /state`, `GET /scene`, `GET /frame`, and `WS /audit`.
3. `orchestrator/judge.py` sends the request to Claude with a bounded tool list.
4. The judge can inspect `perception`, query `integrations/calendar.py`, or invoke a named skill through `skill_registry.py`.
5. A primitive skill calls a direct method such as `robot.jog()`. A VLA skill calls `robot.run_policy()` with its configured prompt and checkpoint.
6. The skill returns `SkillResult`; the judge may report success or invoke `recovery.py`.
7. Every tool call is written by `audit/log.py` and streamed back to the UI over `/audit`.

```text
Web UI -> FastAPI server -> Judge -> Skill registry -> Primitive or VLA skill
                              |                |              |
                              |                |              +-> RobotController -> LeRobot/SO-101
                              |                +-> Perception -> RealSense/CV
                              +-> Calendar / Recovery / Audit
```

### Top-level files

| Path | Purpose |
|---|---|
| `README.md` | Setup, architecture, and repository guide |
| `PLAN.md` | Build order, team ownership, milestones, and demo checklist |
| `AGENT.md` | Detailed judge/tool/recovery design |
| `pyproject.toml` | Python package metadata, dependencies, extras, and CLI entry point |
| `.env.example` | Environment variable template; copy to `.env` and never commit secrets |
| `config/robot.yaml` | SO-101 ports, calibration IDs, camera settings, safety limit, and hand-eye transform |
| `config/skills.yaml` | Enabled skills, primitive/VLA type, Python class, prompt, and policy checkpoint |
| `scripts/` | Operator commands for calibration, perception testing, demo recording, and training |
| `data/` | Runtime audit logs and local data; generated contents are gitignored |

### Python package

| Module | Responsibility | Main files |
|---|---|---|
| `interface/` | User-facing HTTP/WebSocket boundary | `server.py`, `voice.py`, `web/index.html` |
| `orchestrator/` | Agent reasoning and bounded tool dispatch | `judge.py`, `prompts.py`, `skill_registry.py`, `recovery.py` |
| `skills/` | Executable robot capabilities | `base.py`, `primitives.py`, and one file per VLA task |
| `robot/` | The only layer allowed to communicate with LeRobot/SO-101 | `controller.py`, `policies.py` |
| `perception/` | Camera capture and scene/body/object observations | `realsense.py`, `face.py`, `hands.py`, `gaze.py`, `objects.py` |
| `integrations/` | External non-robot services | `calendar.py` |
| `audit/` | Append-only JSONL event history and UI subscribers | `log.py` |
| `mcp/` | Optional future MCP exposure of the same bounded tools | `robot_server.py` |
| `types.py` | Shared data contracts used across layers | `SkillResult`, `SceneObservation`, `DetectedObject`, `Medication` |
| `config.py` | Loads `.env`, `robot.yaml`, and `skills.yaml` | Cached configuration accessors |

### Skill model

`config/skills.yaml` is the source of truth for what the agent may run.
`SkillRegistry` imports the configured class and verifies that its declared kind matches:

- `PrimitiveSkill`: deterministic direct command, currently `move_up` and `move_down`.
- `VLASkill`: learned manipulation behavior driven by a prompt and policy checkpoint.

All skills implement `run()`, `check_success()`, and `reset()`, and return the same
`SkillResult` contract. This lets the judge invoke both kinds through one `run_skill` tool.

### Current team ownership

| Workstream | Primary area | Integration boundary |
|---|---|---|
| Diffusion + camera | `nursearm/perception/` | Produce observations or targets consumed by a skill |
| VLA + robot | `nursearm/skills/`, `nursearm/robot/`, `config/skills.yaml` | Accept a prompt/target and return `SkillResult` |
| UI | `nursearm/interface/` | Use `POST /chat`, `GET /health`, and WebSocket `/audit` |
| Agentic connection | `nursearm/orchestrator/` | Select and invoke registry skills without raw joint access |

Shared contracts belong in `types.py`. Hardware-specific code stays in `robot/`; camera-specific code stays in `perception/`. This keeps parallel work from colliding.

### What is implemented versus stubbed

Implemented now: package/config loading, FastAPI wiring, Claude tool loop, skill registry,
mock robot/perception mode, primitive mock moves, audit logging, and the basic web UI.

Still requiring real implementation or trained artifacts: Cartesian robot jogging, home/gripper/servo commands, VLA checkpoints, camera landmark/object detectors, visual success checks, and the optional MCP server.

---

## Safety & deployment story (for the pitch)

- **Bounded tools.** The LLM can only call a fixed set of skills — there is no path from
  the model to arbitrary joint commands. That fixed toolset *is* the safety boundary.
- **Confidence gating.** Every skill returns a confidence; below threshold the judge must
  recover or ask the person — it may never report an unverified success. A wrong pill is
  treated as a serious error.
- **Safe-stop near humans.** `feed_person` and `hand_handoff` halt instantly if the
  tracked mouth/palm point jumps between frames (the person moved).
- **Audit trail.** Every judge decision and robot action is logged with a timestamp,
  the skill, and the confidence — required for healthcare, built in from day one.
- **Open & swappable.** MCP-standard tools; swap Claude for any compliant model; swap the
  SO-101 for a clinical-grade arm by rewriting one file. Total hardware cost < US$1000.

---

## Tech stack

LeRobot (SO-101 + ACT/SmolVLA) · Intel RealSense + MediaPipe (RGB-D perception) ·
Claude via the Anthropic API (orchestrator) · FastAPI + a single-file web UI · Google
Calendar API · optional Deepgram/ElevenLabs voice and an MCP gateway for phone access ·
`uv` for packaging.
