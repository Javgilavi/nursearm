"""Safe dummy skills used to validate agent and MCP integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import PrimitiveSkill, VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController


class _DummySkill(PrimitiveSkill):
    completion_message = "skill completed"

    def run(
        self,
        args: dict[str, Any],
        robot: RobotController,
        perception: Perception,
    ) -> SkillResult:
        return SkillResult(success=True, confidence=1.0, note=self.completion_message)


class DummySkill1(_DummySkill):
    completion_message = "skill1 completed"


class DummySkill2(_DummySkill):
    completion_message = "skill2 completed"


class DummySkill3(_DummySkill):
    completion_message = "skill3 completed"


class DummyVLASkill(VLASkill):
    """Stand-in for the real VLA policy. Echoes the task and reports simulated success."""

    def run(
        self,
        args: dict[str, Any],
        robot: RobotController,
        perception: Perception,
    ) -> SkillResult:
        task = args.get("task") or self.prompt or "(no task given)"
        return SkillResult(
            success=True,
            confidence=1.0,
            note=f"[DUMMY] skill=vla | task={task!r} | policy not loaded — simulated success, no hardware moved",
        )

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return True, 1.0
