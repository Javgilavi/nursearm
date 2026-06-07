"""Run an ACT policy that picks a requested pill and presents it to a hand."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

SUPPORTED_COLORS = {"green", "black"}


class HandoverPill(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        color = str(args.get("color", "")).strip().lower()
        if color not in SUPPORTED_COLORS:
            return SkillResult(
                False,
                0.0,
                note="color must be 'green' or 'black'",
            )

        policy_path = self._policy_for_color(color)
        if not policy_path:
            return SkillResult(
                False,
                0.0,
                note=(
                    "set NURSEARM_HANDOVER_PILLS_POLICY, or set the matching "
                    f"NURSEARM_HANDOVER_{color.upper()}_POLICY"
                ),
            )

        checkpoint = Path(policy_path).expanduser()
        if not checkpoint.is_dir():
            return SkillResult(
                False,
                0.0,
                note=f"handover checkpoint directory not found: {checkpoint}",
            )
        missing = [
            name
            for name in ("config.json", "model.safetensors")
            if not (checkpoint / name).is_file()
        ]
        if missing:
            return SkillResult(
                False,
                0.0,
                note=(
                    f"invalid handover checkpoint {checkpoint}: "
                    f"missing {', '.join(missing)}"
                ),
            )

        task_template = (
            os.getenv("NURSEARM_HANDOVER_TASK_TEMPLATE")
            or self.prompt
            or "Give the {color} pill to the hand"
        )
        task = task_template.format(color=color)
        duration_s = args.get("duration_s")
        camera_arg = os.getenv("NURSEARM_HANDOVER_CAMERA_ARG")
        fps_value = os.getenv("NURSEARM_HANDOVER_FPS")
        try:
            fps = float(fps_value) if fps_value else None
        except ValueError:
            return SkillResult(False, 0.0, note="NURSEARM_HANDOVER_FPS must be numeric")
        robot.run_policy(
            str(checkpoint),
            task=task,
            duration_s=duration_s,
            camera_arg=camera_arg,
            fps=fps,
        )

        frame = None
        try:
            frame = perception.observe().frame
        except Exception:
            pass
        return SkillResult(
            False,
            0.0,
            note=(
                f"ACT rollout completed for the {color} pill; "
                "handover outcome is not visually verified"
            ),
            frame=frame,
        )

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return False, 0.0

    def _policy_for_color(self, color: str) -> str | None:
        override = os.getenv(f"NURSEARM_HANDOVER_{color.upper()}_POLICY")
        return override or self.policy_path
