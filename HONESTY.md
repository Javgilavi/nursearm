# HONESTY

This document describes what NurseArm started with, what the team built during the
hackathon, what comes from third parties, and what is and is not currently verified.
It is based on the Git history through June 7, 2026 and the current working tree.

## Before The Hackathon

There was no completed NurseArm application before the hackathon. The repository's
first commit was created on June 6, 2026 at 14:30 CEST.

The team did not build the following foundations:

- The SO-101 robot arm, its firmware, and its physical components.
- [LeRobot](https://github.com/huggingface/lerobot), including SO-101 drivers and the
  ACT recording, training, and rollout tooling.
- Ollama and the Qwen models it runs.
- Anthropic Claude and the Anthropic Python SDK.
- FastAPI, MCP, MediaPipe, OpenCV, Faster-Whisper, Intel RealSense SDK, and the other
  open-source dependencies declared in `pyproject.toml`.
- OpenClaw and Telegram's bot platform.

Robot calibration files, datasets, and trained checkpoint files are runtime artifacts.
They are not included in this Git repository. The application expects the operator to
provide compatible local artifacts and paths.

## Initial Hackathon Scaffold

The first two commits (`5f2bb95` and `a4630db`) created the project structure and a
proposed architecture. This scaffold was not a completed robot product. It included
mock behavior, TODOs, unimplemented robot methods, placeholder perception modules, and
untrained skills such as feeding, gaze picking, dispensing pills, and hand handoff.

Those placeholder capabilities must not be presented as completed work. They were
later removed from the active project when they could not be supported honestly.

## Built During The Hackathon

The Git history records the following project-specific work during June 6-7, 2026:

- A FastAPI application serving the browser UI, HTTP endpoints, camera streams, audio
  transcription, robot state, and live audit events.
- A responsive operator UI with text and voice input, camera views, robot controls,
  a digital arm view, prompt shortcuts, and remote-access support.
- A bounded MCP skill server and local MCP client used by the LLM orchestration layer.
- Local Ollama/Qwen and Anthropic Claude agent backends that select only registered
  tools rather than producing arbitrary motor commands.
- An append-only JSONL audit trail for agent decisions and skill execution.
- Webcam and Intel RealSense capture paths plus MediaPipe hand openness and palm-up
  detection.
- Direct SO-101 primitives for home, grip, release, and Cartesian step directions,
  including motor-bus and kinematics code.
- ACT policy rollout wiring for the `sort_pills` skill through `lerobot-rollout`.
- ACT checkpoint selection and MCP wiring for `handover_pill`, with explicit green or
  black requests and optional separate checkpoints for each color.
- Optional Telegram integration through an isolated OpenClaw Docker container.
- Setup, operation, checkpoint-transfer, MCP, safety, and limitation documentation.
- Unit and smoke tests for the LLM tool loop, robot controller command construction,
  handover checkpoint selection, and MCP exposure.

Contributors visible in Git history are Javier Gil, MxguelTech (Miguel), and
SimoneUtili. Git remains the source of truth for individual commits and authorship.

## Third-Party And AI Assistance

This project integrates third-party libraries and models rather than implementing
robot drivers, ACT, speech recognition, hand landmark estimation, or foundation
language models from scratch.

Generative AI assistants, including Claude and OpenAI Codex, were used during the
hackathon for scaffolding, implementation assistance, debugging, repository review,
cleanup, tests, and documentation. The team selected the architecture, supplied the
robot/task requirements, integrated teammate work, trained or supplied runtime
artifacts, and remains responsible for reviewing and operating the resulting code.

## Current Functional Status

| Area | Status | Honest boundary |
|---|---|---|
| Server and browser UI | Functional | Runs as one FastAPI process and supports mock or hardware configuration. |
| Ollama/Claude chat | Functional when configured | Requires a running Ollama model or a valid Anthropic API key. |
| MCP tool discovery and dispatch | Functional | Unit and smoke tested without requiring physical hardware. |
| Audit logging | Functional | Records software events; it is not a certified medical audit system. |
| Camera streaming | Functional when compatible cameras are present | Device indexes and permissions are machine-specific. |
| Hand/palm perception | Functional prototype | MediaPipe/geometric detection is not clinically validated. |
| Voice transcription | Functional when dependencies/model are available | Uses Faster-Whisper; accuracy is environment-dependent. |
| Robot primitives | Implemented prototype | Commands are not closed-loop verified and require correct calibration. |
| `sort_pills` ACT integration | Implemented, checkpoint required | The rollout path exists; task success is not automatically visually verified. |
| `handover_pill` ACT integration | Implemented, checkpoint required | Step 35000 is configured externally; physical success was not verified during the latest repository audit. |
| Telegram/OpenClaw bridge | Implemented, optional | Requires Docker, tokens, network access, and a reachable NurseArm server. |
| Mock mode | Functional development mode | It prevents hardware access; it does not pretend learned tasks succeeded. |

## Mocked, Unverified, Or Incomplete

- Mock mode uses in-memory primitive state and synthetic camera frames when no camera
  is available. Learned policy skills do not report fake success.
- ACT checkpoint weights are excluded from Git. A reviewer cannot reproduce the learned
  behavior from this repository alone without the matching checkpoint and training
  dataset.
- Standard ACT policies generally consume images and robot state, not natural-language
  instructions. One shared handover checkpoint can choose green versus black only if
  its training pipeline actually conditioned that behavior. Otherwise separate
  per-color checkpoints are required.
- `sort_pills` and `handover_pill` currently return an unverified result after rollout
  because automatic visual outcome verification is not implemented.
- Primitive completion is not confirmed by an independent perception or force-feedback
  loop.
- Cartesian IK does not yet enforce complete workspace or convergence limits.
- The interface and its MCP subprocess can own separate robot controller instances;
  concurrent physical commands must be avoided.
- Direct robot HTTP actions are not authenticated.
- This is a hackathon prototype, not a medical device, certified assistive system, or
  production safety controller.

## Repository Hygiene

- Secrets and local `.env` files are ignored.
- Virtual environments, caches, logs, datasets, model outputs, and checkpoints are
  ignored.
- The repository does not vendor LeRobot or model weights.
- Removed placeholder skills are not advertised as supported capabilities.

For the most current setup instructions and operational limitations, see `README.md`.
