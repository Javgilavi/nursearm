"""Primitive command skills — the sketch's /move up and /move down.

These emit a direct, hardcoded movement command to the robot (no policy, no
perception). Fast and reliable; the judge fires them when a small deterministic nudge
is all that's needed, instead of paying for a slow VLA rollout.

Each jogs the end-effector a fixed step along one axis via ``robot.jog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import PrimitiveSkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

STEP_M = 0.03  # fixed jog distance per call (metres)


class MoveUp(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.jog("z", +step)
        return SkillResult(True, 1.0, note=f"moved up {step:.3f}m")


class MoveDown(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.jog("z", -step)
        return SkillResult(True, 1.0, note=f"moved down {step:.3f}m")
