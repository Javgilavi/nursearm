"""sort_pills — run the trained ACT policy that sorts the two pills into their cups.

Unlike dispense_pills (which needs a perception pill-classifier to choose a target),
this skill is a single self-contained behaviour: the ACT policy was trained on the
full sort (locate both pills, pick, place in the matching cup) and does it end-to-end
from the camera. So the skill just hands the policy + task to the controller and lets
``lerobot-rollout`` drive the arm.

The policy path and task string come from ``config/skills.yaml`` and MUST match the
training run (camera config + task string), which they do via ``config/robot.yaml``.
"""

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
            return SkillResult(False, 0.0, note="sort_pills has no policy_path set in skills.yaml")

        task = args.get("task") or self.prompt or "Sort the pills into the cups"
        duration_s = args.get("duration_s")  # optional override

        # Runs lerobot-rollout (ACT + temporal ensembling) for the configured duration.
        # Raises on subprocess failure -> the SkillRegistry turns that into success=False.
        robot.run_policy(self.policy_path, task=task, duration_s=duration_s)

        ok, conf = self.check_success(perception)
        note = "ran ACT sort policy" if ok else "sort policy ran but success not verified"
        frame = None
        try:
            frame = perception.observe().frame
        except Exception:
            pass
        return SkillResult(ok, conf, note=note, frame=frame)

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # The rollout completed without error. Visual verification (both pills in the
        # correct cups) is not implemented yet, so report moderate confidence rather
        # than a false certainty. Wire a perception check here to trust it fully.
        return True, 0.6
