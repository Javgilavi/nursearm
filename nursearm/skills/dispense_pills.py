"""dispense_pills — figure out the right pill, pick it, place it in the cup.

Highest demo value + most reliable, so build this first alongside feed_person.
Flow:
  1. Judge supplies the target pill (it already called get_today_medication).
  2. Classify the pills visible on the table (perception.objects + pill classifier).
  3. Run the ACT "pick & place" policy at the matching pill's 3D position.
  4. Verify the pill landed in the cup before reporting success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController


class DispensePills(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        target = (args.get("pill") or "").lower()
        if not target:
            return SkillResult(False, 0.0, note="no target pill specified by the judge")

        scene = perception.observe()
        match = next((o for o in scene.objects if target in o.label.lower()), None)
        if match is None:
            return SkillResult(False, 0.0, note=f"'{target}' not visible on the table",
                               frame=scene.frame)
        if match.confidence < 0.9:
            return SkillResult(False, match.confidence,
                               note=f"unsure this is '{target}' (conf {match.confidence:.2f})",
                               frame=scene.frame)

        # TODO: run the trained ACT pick&place policy targeting match.position, into the cup.
        robot.run_policy(self.policy_path, task=f"pick the {target} and place it in the cup",
                         target=match.position)

        ok, conf = self.check_success(perception)
        return SkillResult(ok, conf, note=f"dispensed {target}" if ok else "pill not in cup",
                           frame=perception.observe().frame)

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # TODO: verify a pill is now in the cup (object near cup position, gripper empty).
        return False, 0.0  # stub: implement camera verification before trusting this skill
