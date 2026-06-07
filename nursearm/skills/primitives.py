"""Primitive command skills — direct, deterministic robot commands.

No policy, no perception. Fast and reliable; the agent fires these when a small
deterministic action is needed instead of paying for a slow VLA rollout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import PrimitiveSkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

STEP_M = 0.03  # default Cartesian step distance (metres)


class HomeSkill(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        robot.home()
        return SkillResult(True, 1.0, note="moved to home position")


class GripSkill(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        robot.grip()
        return SkillResult(True, 1.0, note="gripper closed")


class ReleaseSkill(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        robot.release()
        return SkillResult(True, 1.0, note="gripper opened")


class MoveUp(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("up", step)
        return SkillResult(True, 1.0, note=f"moved up {step:.3f} m")


class MoveDown(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("down", step)
        return SkillResult(True, 1.0, note=f"moved down {step:.3f} m")


class MoveForward(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("forward", step)
        return SkillResult(True, 1.0, note=f"moved forward {step:.3f} m")


class MoveBack(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("back", step)
        return SkillResult(True, 1.0, note=f"moved back {step:.3f} m")


class MoveLeft(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("left", step)
        return SkillResult(True, 1.0, note=f"moved left {step:.3f} m")


class MoveRight(PrimitiveSkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        step = float(args.get("step_m", STEP_M))
        robot.move_direction("right", step)
        return SkillResult(True, 1.0, note=f"moved right {step:.3f} m")
