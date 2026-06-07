"""Run the Laniakea2002/act_sort ACT policy that sorts pills into matching cups."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

# Published Hub model (warm-start + augmentation, 107 episodes, 30k steps).
HF_REPO_ID = "Laniakea2002/act_sort"
TASK = "Sort two mock pills, green to green cup and black to black cup"
TEMPORAL_ENSEMBLE_COEFF = 0.01  # as used in infer_two_pills_cups.sh


class SortPillsACT(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        task = args.get("task") or self.prompt or TASK
        duration_s = args.get("duration_s")
        camera_arg = os.getenv("NURSEARM_SORT_ACT_CAMERA_ARG") or os.getenv("NURSEARM_HANDOVER_CAMERA_ARG")

        # Use configured local path if valid, otherwise pull from HuggingFace Hub.
        policy_path = self.policy_path
        if policy_path:
            resolved = Path(policy_path).expanduser()
            if not resolved.is_dir():
                return SkillResult(
                    False,
                    0.0,
                    note=f"ACT sort checkpoint not found at {resolved}. "
                         "Fix NURSEARM_SORT_ACT_POLICY or leave unset to pull from HuggingFace.",
                )
            policy_path = str(resolved)
        else:
            policy_path = HF_REPO_ID

        robot.run_policy(
            policy_path=policy_path,
            task=task,
            duration_s=duration_s,
            camera_arg=camera_arg,
            temporal_ensemble=True,
            temporal_ensemble_coeff=TEMPORAL_ENSEMBLE_COEFF,
        )

        frame = None
        try:
            frame = perception.observe().frame
        except Exception:
            pass
        return SkillResult(
            False,
            0.0,
            note="ACT sort rollout completed; physical outcome is not visually verified",
            frame=frame,
        )

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return False, 0.0
