#!/usr/bin/env python
"""SO-101 calibration + hand-eye reminder.

Robot calibration is done with LeRobot's own CLI (most reliable):

    lerobot-find-port
    lerobot-setup-motors --robot.type=so101_follower --robot.port=<PORT>
    lerobot-calibrate     --robot.type=so101_follower --robot.port=<PORT> --robot.id=follower

After that, fill config/robot.yaml with the port, the id, and the HAND-EYE TRANSFORM
(4x4, camera->base). The hand-eye transform is what turns a 3D camera point into a
robot-frame target for future camera-guided motion.

This script just prints the steps and checks config/robot.yaml is populated.
"""

from __future__ import annotations

import numpy as np

from nursearm import config


def main() -> None:
    print(__doc__)
    rc = config.robot_config()
    print("\nConfigured:")
    print("  follower_port:", rc.get("follower_port"))
    print("  follower_id:  ", rc.get("follower_id"))
    T = np.array(rc.get("hand_eye_transform", np.eye(4).tolist()))
    if np.allclose(T, np.eye(4)):
        print("  hand_eye_transform: NOT SET (still identity) — run hand-eye calibration!")
    else:
        print("  hand_eye_transform: set")


if __name__ == "__main__":
    main()
