# CareArm — an assistive robot arm you talk to

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

| Skill | What it does | Status |
|---|---|---|
| `dispense_pills` | Reads today's meds (Google Calendar), classifies the pills on the table, picks the right one, drops it in the cup | **build first** |
| `feed_person` | Scoops food, brings the spoon to the person's mouth with a safe standoff | **build first** |
| `gaze_pick` | Picks up whatever the person is looking at (gaze ray → object) | stretch / wow |
| `hand_handoff` | Places an object safely into an open palm, with instant safe-stop | stretch / safety story |

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
        SKILLS  ◀───────────────▶  PERCEPTION (RealSense RGB-D:
   feed / dispense / gaze / handoff      mouth · hand · gaze · objects · pills)
            │  policy actions
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
vendor it.** CareArm is the orchestration/perception/interface layer on top; LeRobot
provides the robot drivers, the ACT/SmolVLA policies, and the record/train/rollout
CLIs. Reasons: forking means maintaining a divergent copy during a 24h sprint; vendoring
a clone bloats the repo and pins us to one commit. A clean dependency keeps CareArm
small and lets us pull LeRobot fixes for free.

The robot is touched in exactly one file — [`carearm/robot/controller.py`](./carearm/robot/controller.py)
— which either (A) imports LeRobot in-process for low-latency servoing, or (B) shells
out to `lerobot-rollout` for a full trained-skill rollout. Swap LeRobot for another
robot stack by rewriting only that file.

### Installing LeRobot

You already have a working LeRobot checkout at `../lerobot`. The painless path is to
**install CareArm into LeRobot's existing venv** (torch + CUDA are already resolved
there):

```bash
# 1) activate the lerobot venv and make sure the motor stack is present
cd ../lerobot
source .venv/bin/activate
uv pip install -e ".[feetech]"          # SO-101 motors (not installed by default)

# 2) install CareArm + its vision deps into that same venv
cd ../carearm
uv pip install -e ".[robot,calendar]"   # add ,voice or ,mcp if you use them
```

Standalone alternative (separate venv): `uv venv --python 3.12 && uv pip install -e ".[robot,calendar]"`,
then install LeRobot separately with `pip install 'lerobot[feetech]'`.

---

## Quickstart

### Laptop, no hardware (verify the brain first)

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY; leave CAREARM_MOCK=1
CAREARM_MOCK=1 uvicorn carearm.interface.server:app --reload
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
CAREARM_MOCK=0 uvicorn carearm.interface.server:app
```

---

## Repo layout

```
carearm/
├── README.md  PLAN.md  AGENT.md      # what / when / how-the-judge-works
├── pyproject.toml  .env.example      # deps (uv), secrets template
├── config/
│   ├── robot.yaml                    # ports, calibration id, camera, hand-eye transform
│   └── skills.yaml                   # registry: skill → class + description + policy_path
├── carearm/
│   ├── types.py                      # shared dataclasses (SkillResult, SceneObservation, …)
│   ├── config.py                     # yaml + .env loader
│   ├── orchestrator/                 # THE JUDGE — judge.py, skill_registry.py, recovery.py, prompts.py
│   ├── skills/                       # base.py + feed_person, dispense_pills, gaze_pick, hand_handoff
│   ├── perception/                   # realsense.py + face, hands, gaze, objects (pill classify)
│   ├── robot/                        # controller.py (the only LeRobot wrapper) + policies.py
│   ├── integrations/calendar.py      # Google Calendar → today's medication (mock + real)
│   ├── interface/                    # server.py (FastAPI), voice.py, web/index.html
│   ├── audit/log.py                  # append-only timestamped action log (the safety story)
│   └── mcp/robot_server.py           # OPTIONAL: expose skills as MCP tools (phone → robot)
├── scripts/                          # calibrate, record_demos, train_skill, test_perception
└── data/                            # datasets + checkpoints + audit logs (gitignored)
```

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
