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
    """Load a pretrained LeRobot policy from a local checkpoint dir or a HF Hub repo id.

    Auto-detects the policy type (act / smolvla / ...) from the checkpoint config, so
    the same call works for any trained skill. Returns an eval-mode policy on ``device``.

    Note: this is the *in-process* path (Option A). For stepping the policy yourself you
    also need its pre/post processors and an observation dict shaped like the training
    data (``observation.images.<cam>`` + ``observation.state``); the subprocess path
    (``RobotController.run_policy`` -> ``lerobot-rollout``) handles all of that for you.
    """
    from lerobot.configs.policies import PreTrainedConfig  # type: ignore
    from lerobot.policies.factory import get_policy_class  # type: ignore

    cfg = PreTrainedConfig.from_pretrained(policy_path)
    policy = get_policy_class(cfg.type).from_pretrained(policy_path)
    policy.to(device)
    policy.eval()
    policy.reset()
    logger.info("Loaded %s policy from %s on %s", cfg.type, policy_path, device)
    return policy
