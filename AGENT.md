# AGENT.md — the orchestrator (the Judge)

This is the heart of CareArm. It specifies how the LLM drives the robot. The pattern
(Physical AI Hack 2026 runner-up): **a slow, high-level LLM planner — the "judge" —
orchestrating a collection of fast, specialized, language-conditioned sub-policies —
"skills" — with recovery behaviours between them.**

Implemented in [`carearm/orchestrator/`](./carearm/orchestrator/): `judge.py` (the
loop + tool schemas), `skill_registry.py`, `recovery.py`, `prompts.py`.

---

## 1. Mental model

- **The judge is slow and smart.** It runs at the pace of *decisions*, not control. It
  never moves a joint. It picks a skill, watches what happens, and decides what's next.
- **Skills are fast and dumb.** Each is a self-contained, reliable behaviour (a trained
  ACT/SmolVLA policy + its perception). It does exactly one thing and reports whether it
  succeeded.
- **Perception is shared.** RGB-D understanding (mouth, hand, gaze, objects, pills) is a
  service both the judge (situational awareness) and the skills (targeting) call.

The loop the judge runs:

```
parse user intent
  └─▶ decompose into an ordered plan of skill calls
        └─▶ for each step:
              run_skill(...)
              observe result (success + confidence + camera verification)
              success and confidence ≥ SAFE_CONF ?
                 ├─ yes → advance to next step
                 └─ no  → run_recovery(retry | reposition | reperceive | abort)
                          or speak(...) to ask the person
        └─▶ report outcome to the person (text + optional speech)
        └─▶ every decision + action already logged to the audit trail
```

---

## 2. The judge is a tool-calling agent

The judge is Claude with a **small, fixed set of tools** (defined in `judge.py` as
`TOOLS`). It never emits raw joint commands — only these tools. **This fixed toolset is
the safety boundary and the "API in the real world" story.**

| Tool | Purpose |
|---|---|
| `list_skills()` | Each skill's name + natural-language description, so the judge can choose. |
| `get_scene()` | Current RGB-D understanding: objects (+3D positions), face/mouth, hand open?, gaze target. |
| `get_today_medication()` | Google Calendar → `[{name, dose, time}]` for `dispense_pills`. |
| `run_skill(name, args)` | Run ONE rollout of a skill; blocks; returns success + confidence + final frame. |
| `run_recovery(behavior, args)` | `retry` \| `reposition` \| `reperceive` \| `abort`. |
| `speak(text)` | TTS reply / question to the person. |

`log(...)` is called automatically around every tool use — the judge doesn't have to
remember to audit.

### Why a separate judge instead of one big policy

A single end-to-end policy can't reliably do long-horizon, multi-step tasks ("get my
pills, then feed me") and can't recover from its own failures. Splitting slow planning
(judge) from fast acting (skills) is what makes long rollouts work: the judge can look
at a failed rollout, reason about *why*, and choose a recovery — a flat policy cannot.

---

## 3. The judge loop (reference — see `judge.py`)

```python
def handle(self, user_intent: str) -> str:
    messages = [{"role": "user", "content": user_intent}]
    for _ in range(MAX_TURNS):
        resp = claude.messages.create(model=MODEL, system=SYSTEM_PROMPT,
                                      tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return final_text(resp)              # judge is done → report to the person
        results = [self.dispatch(b.name, b.input) for b in tool_use_blocks(resp)]
        messages.append({"role": "user", "content": tool_results(results)})  # + audit each
```

The judge's intelligence is mostly in the **system prompt** (`prompts.py`): which skills
exist and when to use each, how to read a `SkillResult`, the confidence threshold below
which it must recover or ask, and the hard rule that it must never claim a success it
cannot verify from `get_scene`.

---

## 4. Skill contract (see `skills/base.py`)

Every skill implements the same interface so the judge treats them uniformly:

```python
class Skill(ABC):
    name: str
    description: str                       # natural language — the judge reads this to choose

    def run(self, args, robot, perception) -> SkillResult:   # ONE rollout
        ...
    def check_success(self, perception) -> tuple[bool, float]:  # verify from the camera
        ...
    def reset(self, robot) -> None:        # return to a safe home pose between attempts
        ...

SkillResult = {success: bool, confidence: float, note: str, frame: image}
```

**`feed_person.run()`**: mouth 3D point (MediaPipe + depth, base frame) → run ACT scoop
policy → servo to the mouth, stopping ~5cm short (safe-stop) → verify spoon at mouth /
bowl emptier.

**`dispense_pills.run()`**: judge supplies the target pill → classify pills on the table
→ run ACT pick&place at the matching pill's 3D position → verify the pill is in the cup.

**`gaze_pick.run()`**: gaze ray from the eyes → intersect with detected objects → run ACT
pick at the nearest hit → verify object in gripper.

---

## 5. Recovery behaviours (see `recovery.py`)

The judge picks one when a skill reports failure or low confidence:

| Behavior | When | Action |
|---|---|---|
| `retry` | transient failure, scene unchanged | reset to home, re-run the same skill once |
| `reposition` | target moved / out of reach | move to a better vantage, re-perceive, retry |
| `reperceive` | detection was uncertain | grab fresh frames, re-run detection before acting |
| `ask_human` | confidence stays low after a recovery | `speak()` a question, wait for the next turn |
| `abort` | unsafe or repeated failure | return to home pose, report failure honestly |

Retries are capped (default **2 per step**) so the robot never loops forever, and the
arm is always `reset()` to a safe home before a retry.

---

## 6. Safety rules (enforced in code, not just prompt)

1. **Confidence gate** — below `SAFE_CONF` (default 0.9) the judge may not report
   success; it must recover or ask. Set in `prompts.py` and checked in the skills.
2. **Body-part safe-stop** — in `feed_person` and `hand_handoff`, if the tracked 3D
   point jumps more than `safe_stop_max_jump_m` (config/robot.yaml) between frames, the
   arm halts immediately (guard in `robot.servo_to`).
3. **Bounded tools** — the judge can call only the tools in §2. No arbitrary joint-control
   path exists from the LLM.
4. **Audit everything** — every tool call + result is logged with a timestamp before the
   next step. The audit log is the source of truth for the demo and the clinical record.
5. **Human-in-the-loop** — asking is always available and is the default when uncertain.
   Prefer asking over guessing near a person's face or hand.

---

## 7. Model & connectivity choices

- **Brain:** Claude — strongest for robot tool-calling in the SO-101 community's own
  testing. `judge.py` uses `claude-opus-4-8`; switch to `claude-sonnet-4-6` for
  lower latency/cost during iteration. Use the Anthropic API directly for tight control
  of the loop (what we do), or the Claude Agent SDK for a ready-made agent harness.
- **Connect from anywhere (optional):** wrap the same tools behind an MCP gateway
  ([`carearm/mcp/robot_server.py`](./carearm/mcp/robot_server.py)) to get WhatsApp /
  Telegram / Slack for free — a strong live moment (a judge messages the robot from
  their phone). Bind to loopback, require auth, pair only known users. The model on the
  far side still can't send raw joint commands — only the bounded tools.
- **Voice:** browser Web Speech API works key-free in the UI; Deepgram Nova-3 for the
  low-latency hot path; ElevenLabs/Cartesia for natural TTS.

---

## 8. What to build first

1. `skills/base.py` + one real skill (`dispense_pills`) with the registry wired.
2. The judge loop in **mock mode** (`CAREARM_MOCK=1`) choosing that skill from text —
   no robot, no camera. Confirm the audit log streams to the UI.
3. Perception for the skill (pills → 3D points) verified live with `test_perception.py`.
4. Train the ACT policy, set `policy_path`, run the skill for real through the judge.
5. Add `feed_person` + the calendar tool; let the judge choose between the two.
6. Add `gaze_pick`, then `hand_handoff`, then tighten the safety gates.

Get one skill working end-to-end through the judge before adding more.
