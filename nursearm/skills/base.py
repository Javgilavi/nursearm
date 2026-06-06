"""Skill contract + the two skill kinds from the whiteboard sketch.

The agent fires SKILLS, and the sketch splits them in two — a real decision the judge
makes every step:

  - PRIMITIVE skills (/move up, /move down) emit a direct, hardcoded movement command
    straight to the robot. Instant and reliable. No policy, no perception needed.
  - VLA skills (/vla 1, /vla 2, ...) are language-conditioned policies: the judge hands
    the skill a PROMPT, the VLA turns it into the actual arm action ("/vla 1 -> prompt
    of vla"). Slower, learned, for the complex manipulation.

Every skill — both kinds — implements the same `run()/check_success()/reset()` so the
judge treats them uniformly; only `kind` tells it which is fast/reliable vs slow/learned.
All planning/recovery intelligence lives in the judge, never here. See AGENT.md §4.
"""

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
    """A hardcoded movement command straight to the robot (the sketch's /move up|down).

    No policy and no perception: it emits a direct CMD and is considered to have
    succeeded once the move is sent (primitives are instant and reliable). Subclasses
    implement ``run()`` with a direct ``robot`` call (e.g. ``robot.jog(...)``).
    """

    kind: ClassVar[str] = "primitive"

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        # Primitives are open-loop moves; success is sending the command.
        return True, 1.0


class VLASkill(Skill):
    """A language-conditioned policy (the sketch's /vla N -> prompt of vla).

    The judge hands it a prompt (or it uses its default ``self.prompt``); the VLA turns
    that into the arm action via ``robot.run_policy(self.policy_path, task=prompt)``.
    Subclasses still implement ``check_success()`` to verify the outcome from the camera.
    """

    kind: ClassVar[str] = "vla"
