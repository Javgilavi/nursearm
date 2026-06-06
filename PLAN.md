# PLAN.md — the 24-hour build plan

The goal is **one skill working end-to-end through the judge, demoed live**, with a
second skill and the safety/audit story on top. A judge that reliably orchestrates two
skills beats four skills that only run standalone. Cut scope ruthlessly toward a
working demo.

---

## North star (what "done" looks like)

A hackathon judge types or says *"give me my morning pills"* into the web UI. NurseArm:
1. calls `get_today_medication` → today's pill from the (mock or real) calendar,
2. calls `get_scene` → sees the pills on the table, classifies them,
3. calls `run_skill("dispense_pills", {pill: ...})` → the SO-101 picks the right pill
   and drops it in the cup,
4. verifies from the camera, and if unsure, **recovers or asks** instead of guessing,
5. reports back — and every step is visible in the live audit log.

If feeding is also working, *"I'm hungry"* triggers `feed_person` with a safe standoff.

---

## Three build levels

1. **VLA** - get a language-conditioned policy executing a robot skill from a prompt.
2. **Text/voice agent** - let the agent choose primitive or VLA skills from user input.
3. **CV inputs** - add RealSense hand and mouth tracking for visual targets.

Within Level 1, build `dispense_pills` first and `feed_person` second. The existing
mock server remains useful for developing the UI and agent while VLA work proceeds.

Hard rule: **collect data and verify RealSense alignment in the first 3 hours** — every
skill depends on both. If perception 3D points are wrong, nothing downstream works.

---

## Current team split

| Workstream | Current focus | Integration deliverable |
|---|---|---|
| Diffusion + camera | Test the diffusion model with camera observations and establish its input/output format | A callable inference path with one recorded camera example and measured latency |
| VLA + robot | Test language-conditioned VLA execution on the SO-101 | One prompt reliably produces one recorded robot behavior |
| UI | Build the text/voice interface and display system status/results | UI can submit a request to the backend and render its response |
| Agentic connection | Connect user requests to primitive and VLA skills through the judge | Agent lists skills, chooses one, invokes it, and returns the result |

Integration order: first agree on the backend request/result contract, then connect
the UI to the agent, the agent to the VLA, and finally add camera-derived targets.
Each workstream should keep a mock path so integration is not blocked by hardware.

---

## Hour-by-hour (4 engineers: E1 robot, E2 perception/ML, E3 orchestrator, E4 interface)

| Hours | Goal | Owner |
|---|---|---|
| 0–2  | Repo + venv (install into lerobot venv), SO-101 calibration, RealSense streaming + `rs.align` verified | E1 |
| 0–2  | **Mock end-to-end**: `NURSEARM_MOCK=1` server runs, judge selects a skill, audit log streams to UI | E3 + E4 |
| 0–3  | Perception MVP: mouth + hand + object 3D points visualized in `test_perception.py` | E2 |
| 2–6  | Record demos + train ACT for `dispense_pills` (pick&place) and `feed_person` (scoop) | E1 + E2 |
| 3–8  | Judge loop hardening: recovery behaviours, confidence gate, prompts | E3 |
| 4–9  | Interface: voice in/out, live camera tile, polished audit log UI | E4 |
| 6–10 | Real Google Calendar for `dispense_pills` | E4 |
| 8–14 | Wire skills ↔ judge ↔ robot; **first real end-to-end run of dispense + feed** | all |
| 14–18| `gaze_pick` stretch; recovery tuning on real failures | E2 + E3 |
| 16–20| Reliability hardening; `hand_handoff` safe-stop; edge cases | all |
| 20–23| Demo polish: on-screen judge reasoning + audit log; record a backup video | E4 + E1 |
| 23–24| Presentation + dry runs | all |

---

## The pitch (4 minutes)

**General (2 min)** — Why we're here; who we are (4 robotics engineers, prior builds).
The problem: Hong Kong's ageing population, medication errors, pharmacist/carer load,
and assistive care that doesn't scale. Our bet: cheap open-source arms + an LLM
orchestrator + real APIs = a *deployable, safe* assistive tool, not a one-off demo.

**Tech (2 min)** — The slow-judge / fast-skills architecture and why it beats one big
policy (recovery from failure). The safety boundary (bounded tools, confidence gate,
safe-stop, audit trail). The live demo: speak to it → it reads the calendar → picks the
right pill → logs everything. Show the GitHub. If the MCP gateway is up: a judge
messages the robot from their own phone — "API in the real world."

---

## Demo-day checklist

- [ ] `.env` has a real `ANTHROPIC_API_KEY`; `ANTHROPIC_API_KEY` quota checked.
- [ ] `config/robot.yaml`: ports, ids, and a **non-identity hand-eye transform** set.
- [ ] At least one skill's `policy_path` set in `config/skills.yaml` and loads.
- [ ] `test_perception.py` shows correct 3D points under demo lighting.
- [ ] Pills + bowl + cup at fixed, rehearsed positions; lighting fixed.
- [ ] Backup video recorded in case hardware misbehaves live.
- [ ] Audit log visible on the projector — it's half the story.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hardware/serial flakiness eats hours | Mock end-to-end first; backup video; one engineer owns hardware only |
| RealSense alignment / hand-eye wrong | Verify in first 3h with `test_perception.py`; this gates everything |
| ACT policy underperforms on pick | ≥50–80 clean episodes, fixed object positions, single operator (see LeRobot AGENT_GUIDE §5) |
| Pill misclassification (safety) | Confidence gate + ask-human; start with colour/shape, upgrade to CLIP only if time |
| Judge loops or stalls | `MAX_TURNS` cap + capped retries in recovery |
| Voice setup rabbit-holes | Browser Web Speech API works key-free; treat Deepgram/ElevenLabs as optional |
