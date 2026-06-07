"""Skill contracts for deterministic primitives and learned policy rollouts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController


class Skill(ABC):
    kind: ClassVar[str] = "vla"

    def __init__(
        self,
        name: str,
        description: str,
        policy_path: str | None = None,
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.policy_path = policy_path
        self.prompt = prompt

    @abstractmethod
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        """Execute ONE rollout / command. Return success + confidence + final frame."""
        ...

    @abstractmethod
    def check_success(self, perception: Perception) -> tuple[bool, float]:
        """Verify whether the goal state is reached. Returns (ok, confidence)."""
        ...

    def reset(self, robot: RobotController) -> None:
        """Return the arm to a safe home pose between attempts."""
        robot.home()


class PrimitiveSkill(Skill):
    """A deterministic command sent directly to the robot controller."""

    kind: ClassVar[str] = "primitive"

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # Primitives are open-loop moves; success is sending the command.
        return True, 1.0


class VLASkill(Skill):
    """A learned policy rollout configured with a checkpoint and task prompt."""

    kind: ClassVar[str] = "vla"
