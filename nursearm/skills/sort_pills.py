"""Run the trained ACT policy that sorts two pills into matching cups."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController


class SortPills(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        if not self.policy_path:
            return SkillResult(
                False,
                0.0,
                note="set NURSEARM_SORT_PILLS_POLICY to the trained checkpoint",
            )

        task = args.get("task") or self.prompt or "Sort the pills into the cups"
        duration_s = args.get("duration_s")  # optional override

        # Runs lerobot-rollout (ACT + temporal ensembling) for the configured duration.
        # Raises on subprocess failure -> the SkillRegistry turns that into success=False.
        robot.run_policy(self.policy_path, task=task, duration_s=duration_s)

        ok, conf = self.check_success(perception)
        note = "ACT rollout completed; physical outcome is not visually verified"
        frame = None
        try:
            frame = perception.observe().frame
        except Exception:
            pass
        return SkillResult(ok, conf, note=note, frame=frame)

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return False, 0.0
