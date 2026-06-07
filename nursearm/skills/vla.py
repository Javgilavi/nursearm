"""NurseArm VLA skill — runs a lerobot policy rollout for open-ended manipulation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController


class NurseArmVLA(VLASkill):
    """Language-conditioned policy for any physical manipulation task.

    Set policy_path in skills.yaml to the trained lerobot checkpoint.
    When policy_path is None, returns an informative error (no hardware moved).
    """

    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        task = args.get("task") or self.prompt or "perform the requested task"
        if self.policy_path is None:
            return SkillResult(
                False, 0.0,
                note="VLA policy not loaded — set policy_path in skills.yaml to the trained checkpoint",
            )
        try:
            robot.run_policy(self.policy_path, task=task)
            return SkillResult(True, 0.9, note=f"VLA completed: {task!r}")
        except Exception as exc:
            return SkillResult(False, 0.0, note=f"VLA error: {exc}")

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return perception.has_real_camera, 0.9
