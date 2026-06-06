"""feed_person — scoop food and bring the spoon to the person's mouth.

Flow (see AGENT.md §4):
  1. perception.face() -> 3D mouth point (MediaPipe + RealSense depth, base frame).
  2. run the ACT "scoop" policy on the bowl.
  3. servo the end-effector toward the mouth point, stopping ~5cm short (safe-stop).
  4. verify the spoon reached the mouth and the bowl is emptier.

SAFETY: this skill operates next to a person's face. If the tracked mouth point jumps
more than MAX_JUMP between frames, halt immediately (handled in robot.servo_to with a
safe-stop guard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from carearm.skills.base import Skill
from carearm.types import SkillResult

if TYPE_CHECKING:
    from carearm.perception.realsense import Perception
    from carearm.robot.controller import RobotController

MOUTH_STANDOFF_M = 0.05  # stop 5cm short of the mouth


class FeedPerson(Skill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        mouth = perception.face().mouth_point if perception.face() else None
        if mouth is None:
            return SkillResult(False, 0.0, note="no mouth detected; ask the person to face the camera")

        # TODO: run the trained ACT scoop policy on the bowl.
        robot.run_policy(self.policy_path, task=f"scoop {args.get('food', 'food')} from the bowl")

        # Servo toward the mouth with a safe standoff and per-frame safe-stop.
        robot.servo_to(mouth, standoff_m=MOUTH_STANDOFF_M, track=lambda: _mouth(perception))

        ok, conf = self.check_success(perception)
        return SkillResult(ok, conf, note="brought food to mouth" if ok else "did not reach mouth")

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # TODO: confirm the spoon is at the mouth standoff and the bowl is emptier.
        return False, 0.0  # stub


def _mouth(perception: Perception):
    face = perception.face()
    return face.mouth_point if face else None
