"""The Judge — a slow, smart LLM planner that orchestrates fast, dumb skills.

The judge never moves joints. It picks a skill, watches the rollout through the
camera, and decides what to do next (advance / recover / ask / report). It is
implemented as a Claude tool-calling agent with a small, FIXED set of tools — that
fixed toolset is the safety boundary and the "API in the real world" story.

See AGENT.md for the full design rationale. This module is intentionally close to
runnable: fill in the perception/skill/robot stubs and it drives end-to-end.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from anthropic import Anthropic

from nursearm import config
from nursearm.orchestrator.prompts import SYSTEM_PROMPT
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.audit.log import AuditLog
    from nursearm.integrations.calendar import CalendarClient
    from nursearm.orchestrator.recovery import RecoveryManager
    from nursearm.orchestrator.skill_registry import SkillRegistry
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"  # strongest tool-caller; swap to claude-sonnet-4-6 for speed/cost
MAX_TOKENS = 2048
MAX_TURNS = 24  # hard cap on judge tool-calling turns per user request

# Tool schemas exposed to Claude. The judge can call ONLY these — no raw joint control.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_skills",
        "description": (
            "List the robot's available skills, their primitive or VLA kind, and descriptions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_scene",
        "description": (
            "Get the current RGB-D understanding of the scene: detected objects with 3D "
            "positions, whether a face/mouth is visible, whether a hand is open, gaze target."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_today_medication",
        "description": "Get today's scheduled medication from Google Calendar: name, dose, time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_skill",
        "description": (
            "Run one primitive command or one VLA skill rollout. Returns success, confidence, "
            "and a verification note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name from list_skills."},
                "args": {"type": "object", "description": "Skill-specific args, e.g. {'pill': 'aspirin'}."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "run_recovery",
        "description": "Run a recovery behavior after a failed/low-confidence skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "behavior": {"type": "string", "enum": ["retry", "reposition", "reperceive", "abort"]},
                "args": {"type": "object"},
            },
            "required": ["behavior"],
        },
    },
    {
        "name": "speak",
        "description": "Say something to the person (text-to-speech). Use for questions and updates.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


class Judge:
    """LLM planner loop. One ``handle()`` call services one user request to completion."""

    def __init__(
        self,
        skills: SkillRegistry,
        perception: Perception,
        robot: RobotController,
        audit: AuditLog,
        recovery: RecoveryManager,
        calendar: CalendarClient,
        speak_fn=None,
    ) -> None:
        self.client = Anthropic(api_key=config.env("ANTHROPIC_API_KEY", required=True))
        self.skills = skills
        self.perception = perception
        self.robot = robot
        self.audit = audit
        self.recovery = recovery
        self.calendar = calendar
        self.speak_fn = speak_fn or (lambda text: logger.info("SPEAK: %s", text))

    def handle(self, user_intent: str) -> str:
        """Drive the full plan→act→verify→recover→report loop for one request."""
        self.audit.log({"event": "user_intent", "text": user_intent})
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_intent}]

        for _ in range(MAX_TURNS):
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                final = _text_of(resp.content)
                self.audit.log({"event": "report", "text": final})
                return final

            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = self.dispatch(block.name, block.input or {})
                self.audit.log({"event": "tool", "tool": block.name, "args": block.input,
                                "result": _jsonable(result)})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(_jsonable(result)),
                })
            messages.append({"role": "user", "content": tool_results})

        msg = "Reached the planning step limit without finishing. Stopping for safety."
        self.audit.log({"event": "abort", "reason": "max_turns"})
        return msg

    def dispatch(self, name: str, args: dict[str, Any]) -> Any:
        """Execute one tool call. This is the only place tools map to real actions."""
        match name:
            case "list_skills":
                return [vars(s) for s in self.skills.info()]
            case "get_scene":
                return self.perception.observe().summary()
            case "get_today_medication":
                return [vars(m) for m in self.calendar.today()]
            case "run_skill":
                return self.skills.run(args["name"], args.get("args", {}), self.robot, self.perception)
            case "run_recovery":
                return self.recovery.run(args["behavior"], args.get("args", {}), self.robot, self.perception)
            case "speak":
                self.speak_fn(args["text"])
                return {"spoken": True}
            case _:
                return SkillResult(success=False, confidence=0.0, note=f"unknown tool {name}")


def _text_of(content: list[Any]) -> str:
    return " ".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, SkillResult):
        return obj.summary()
    if hasattr(obj, "summary"):
        return obj.summary()
    return obj
