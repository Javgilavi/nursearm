"""Load primitive and VLA skills from ``config/skills.yaml``."""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING, Any

from nursearm import config
from nursearm.types import SkillInfo, SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController
    from nursearm.skills.base import Skill

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
            policy_path = spec.get("policy_path")
            if policy_env := spec.get("policy_env"):
                policy_path = os.getenv(policy_env) or policy_path
            skill = cls(
                name=name,
                description=spec["description"],
                policy_path=policy_path,
                prompt=spec.get("prompt", spec.get("task")),
            )
            configured_kind = spec.get("type", "vla")
            if configured_kind != skill.kind:
                raise ValueError(
                    f"skill {name!r} is configured as {configured_kind!r}, "
                    f"but {spec['class']} declares {skill.kind!r}"
                )
            self._skills[name] = skill
            logger.info("Registered %s skill: %s", skill.kind, name)

    def info(self) -> list[SkillInfo]:
        return [
            SkillInfo(name=s.name, description=s.description, kind=s.kind)
            for s in self._skills.values()
        ]

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
