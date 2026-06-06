"""Skill contract. Every skill implements the same interface so the judge can treat
them uniformly: run one rollout, verify success from the camera, reset to home.

A skill is FAST and DUMB — it knows how to do exactly one thing (a trained ACT/SmolVLA
policy plus its perception) and reports whether it succeeded. All planning/recovery
intelligence lives in the judge, never here. See AGENT.md §4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from carearm.types import SkillResult

if TYPE_CHECKING:
    from carearm.perception.realsense import Perception
    from carearm.robot.controller import RobotController


class Skill(ABC):
    def __init__(self, name: str, description: str, policy_path: str | None = None) -> None:
        self.name = name
        self.description = description
        self.policy_path = policy_path

    @abstractmethod
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        """Execute ONE rollout of the policy. Return success + confidence + final frame."""
        ...

    @abstractmethod
    def check_success(self, perception: Perception) -> tuple[bool, float]:
        """Verify from the camera whether the goal state is reached. Returns (ok, confidence)."""
        ...

    def reset(self, robot: RobotController) -> None:
        """Return the arm to a safe home pose between attempts."""
        robot.home()
