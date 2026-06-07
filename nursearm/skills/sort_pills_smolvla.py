"""Run the SmolVLA policy that classifies and sorts pills into matching containers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nursearm.skills.base import VLASkill
from nursearm.types import SkillResult

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception
    from nursearm.robot.controller import RobotController

# Used as --policy.path when no local checkpoint is configured.
# lerobot-rollout passes this to PreTrainedConfig.from_pretrained(), which
# accepts both local directories and HuggingFace repo IDs.
HF_REPO_ID = "psarikas/task1_smolvla_base_step45k"


class SortPillsSmolVLA(VLASkill):
    def run(self, args: dict[str, Any], robot: RobotController, perception: Perception) -> SkillResult:
        task = args.get("task") or self.prompt or "Sort the pills into the matching containers"
        duration_s = args.get("duration_s")
        camera_arg = os.getenv("NURSEARM_SORT_SMOLVLA_CAMERA_ARG") or os.getenv("NURSEARM_HANDOVER_CAMERA_ARG")

        # Use local path if set and valid, otherwise fall back to the HF repo ID.
        policy_path = self.policy_path
        if policy_path:
            resolved = Path(policy_path).expanduser()
            if not resolved.is_dir():
                return SkillResult(
                    False,
                    0.0,
                    note=f"SmolVLA checkpoint not found at {resolved}. "
                         "Fix NURSEARM_SORT_SMOLVLA_POLICY or leave it unset to pull from HuggingFace.",
                )
            policy_path = str(resolved)
        else:
            policy_path = HF_REPO_ID

        robot.run_policy(
            policy_path=policy_path,
            task=task,
            duration_s=duration_s,
            camera_arg=camera_arg,
            temporal_ensemble=False,  # SmolVLA does not support temporal ensembling
        )

        frame = None
        try:
            frame = perception.observe().frame
        except Exception:
            pass
        return SkillResult(
            False,
            0.0,
            note="SmolVLA sort rollout completed; physical outcome is not visually verified",
            frame=frame,
        )

    def check_success(self, perception: Perception) -> tuple[bool, float]:
        return False, 0.0
