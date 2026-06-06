"""Recovery behaviors the judge invokes when a skill fails or returns low confidence.

The judge chooses WHICH behavior; this module executes it. Retries are capped so the
robot never loops forever, and the arm is always reset to a safe home pose first.
See AGENT.md §5.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

logger = logging.getLogger(__name__)

MAX_RETRIES_PER_STEP = 2


class RecoveryManager:
    def __init__(self) -> None:
        self._retry_count = 0

    def run(
        self,
        behavior: str,
        args: dict[str, Any],
        robot: RobotController,
        perception: Perception,
    ) -> SkillResult:
        match behavior:
            case "retry":
                return self._retry(robot)
            case "reposition":
                return self._reposition(robot, perception)
            case "reperceive":
                return self._reperceive(perception)
            case "abort":
                return self._abort(robot)
            case _:
                return SkillResult(False, 0.0, note=f"unknown recovery: {behavior}")

    def _retry(self, robot: RobotController) -> SkillResult:
        if self._retry_count >= MAX_RETRIES_PER_STEP:
            return SkillResult(False, 0.0, note="retry budget exhausted; advise abort")
        self._retry_count += 1
        robot.home()  # always reset to a safe pose before retrying
        return SkillResult(True, 1.0, note=f"reset to home, ready for retry #{self._retry_count}")

    def _reposition(self, robot: RobotController, perception: Perception) -> SkillResult:
        # TODO: move the arm to a better vantage point, then re-perceive.
        robot.home()
        return SkillResult(True, 1.0, note="repositioned to home vantage (stub)")

    def _reperceive(self, perception: Perception) -> SkillResult:
        scene = perception.observe()
        return SkillResult(True, 1.0, note="fresh perception captured", frame=scene.frame)

    def _abort(self, robot: RobotController) -> SkillResult:
        robot.home()
        self._retry_count = 0
        return SkillResult(False, 1.0, note="aborted safely; arm at home")

    def reset(self) -> None:
        """Call at the start of each new plan step to reset the retry budget."""
        self._retry_count = 0
