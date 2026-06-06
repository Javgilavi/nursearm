"""Load trained LeRobot policy checkpoints (ACT / SmolVLA) for in-process inference.

Used by RobotController Option A (lowest-latency control). For the simple path
(subprocess `lerobot-rollout`), you don't need this — LeRobot loads the checkpoint
itself. Provided for when you want to step the policy from inside NurseArm (e.g. to
interleave perception/safe-stop between action chunks).
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache
def load_policy(policy_path: str, device: str = "cuda"):
    """Load a pretrained policy from a local checkpoint dir or a HF Hub repo id."""
    from lerobot.policies.factory import get_policy_class  # type: ignore
    from lerobot.policies.pretrained import PreTrainedPolicy  # type: ignore  # noqa: F401

    # TODO: load via the policy's from_pretrained; move to `device`; set eval mode.
    # The exact factory call depends on the policy type recorded in the checkpoint.
    raise NotImplementedError(
        "Use lerobot's from_pretrained for the checkpoint's policy type, then .to(device).eval()."
    )
