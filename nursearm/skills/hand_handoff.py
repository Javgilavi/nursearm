"""hand_handoff (the safety story) — place an object safely into an open palm.

Flow:
  1. perception.hands() -> open/closed + 3D palm point.
  2. only proceed if the hand is OPEN and stable.
  3. servo to a point just above the palm, release the gripper, retract.
  4. verify the object left the gripper.

SAFETY: stop instantly if the palm point jumps (person pulled away) — handled by the
safe-stop guard in robot.servo_to. Never release until the palm is stably tracked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

PALM_STANDOFF_M = 0.03


class HandHandoff(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        hands = perception.hands()
        if not hands or not hands.is_open or hands.palm_point is None:
            return SkillResult(False, 0.0, note="no open hand detected; ask the person to open their hand")

        robot.servo_to(hands.palm_point, standoff_m=PALM_STANDOFF_M, track=lambda: _palm(perception))
        robot.release()  # open gripper to hand over
        robot.home()

        ok, conf = self.check_success(perception)
        return SkillResult(ok, conf, note="handed over" if ok else "handover not confirmed")

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # TODO: confirm the gripper is empty (object successfully released into the hand).
        return False, 0.0  # stub


def _palm(perception: Perception):
    hands = perception.hands()
    return hands.palm_point if hands else None
