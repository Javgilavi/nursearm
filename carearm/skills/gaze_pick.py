"""gaze_pick (stretch / wow-factor) — pick whatever the person is looking at.

Flow (see AGENT.md §4):
  1. perception.gaze() -> a ray from the person's eyes.
  2. perception.objects() -> detected objects with 3D positions.
  3. intersect the ray with the objects; target = nearest hit.
  4. run the ACT "pick" policy at the target's 3D position.
  5. verify the object is in the gripper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from carearm.skills.base import Skill
from carearm.types import SkillResult

if TYPE_CHECKING:
    from carearm.perception.realsense import Perception
    from carearm.robot.controller import RobotController


class GazePick(Skill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        target = perception.gaze_target()  # ray-cast handled in perception
        if target is None:
            return SkillResult(False, 0.0, note="could not resolve a gaze target")

        # TODO: run the trained ACT pick policy at target.position.
        robot.run_policy(self.policy_path, task=f"pick the {target.label}", target=target.position)

        ok, conf = self.check_success(perception)
        return SkillResult(ok, conf, note=f"picked {target.label}" if ok else "pick failed")

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # TODO: confirm the object is in the gripper (gripper closed on object / object gone from table).
        return False, 0.0  # stub
