"""Loads the skill registry from ``config/skills.yaml`` and exposes skills to the judge.

A skill name maps to a Python class (the behavior) plus a trained policy checkpoint
and a natural-language description. The judge reads the descriptions to choose.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from carearm import config
from carearm.types import SkillInfo, SkillResult

if TYPE_CHECKING:
    from carearm.perception.realsense import Perception
    from carearm.robot.controller import RobotController
    from carearm.skills.base import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Holds instantiated skills keyed by name."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._load()

    def _load(self) -> None:
        for name, spec in config.skills_config().get("skills", {}).items():
            if not spec.get("enabled", True):
                continue
            module_path, _, cls_name = spec["class"].rpartition(".")
            cls = getattr(importlib.import_module(module_path), cls_name)
            self._skills[name] = cls(
                name=name,
                description=spec["description"],
                policy_path=spec.get("policy_path"),
            )
            logger.info("Registered skill: %s", name)

    def info(self) -> list[SkillInfo]:
        return [SkillInfo(name=s.name, description=s.description) for s in self._skills.values()]

    def run(
        self,
        name: str,
        args: dict[str, Any],
        robot: RobotController,
        perception: Perception,
    ) -> SkillResult:
        skill = self._skills.get(name)
        if skill is None:
            return SkillResult(success=False, confidence=0.0, note=f"no such skill: {name}")
        try:
            return skill.run(args, robot, perception)
        except Exception as exc:  # never let a skill crash the judge loop
            logger.exception("Skill %s failed", name)
            return SkillResult(success=False, confidence=0.0, note=f"skill error: {exc}")
