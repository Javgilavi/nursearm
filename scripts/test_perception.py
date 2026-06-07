#!/usr/bin/env python
"""Verify camera capture and MediaPipe hand/palm detection.

    python scripts/test_perception.py            # real RealSense
    NURSEARM_MOCK=1 python scripts/test_perception.py   # no hardware (sanity only)
"""

from __future__ import annotations

import os

import cv2
import numpy as np

from nursearm.perception import hands as hands_mod
from nursearm.perception.realsense import Perception


def main() -> None:
    mock = os.getenv("NURSEARM_MOCK", "0") == "1"
    perception = Perception(mock=mock)
    print("Streaming. Press 'q' to quit." + (" [MOCK]" if mock else ""))
    try:
        while True:
            scene = perception.observe()
            frame = scene.frame.copy()
            debug = hands_mod.analyze(
                perception,
                color=frame,
                depth=np.zeros(frame.shape[:2], dtype=np.float32),
            )
            if debug is not None:
                frame = hands_mod.draw_debug(frame, debug)
            y = 24
            for line in (
                f"hand_open={scene.hand_open} palm={scene.palm_point}",
                f"palm_up={scene.palm_up} palm_up_conf={scene.palm_up_confidence}",
            ):
                cv2.putText(frame, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                y += 22
            cv2.imshow("NurseArm perception", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        perception.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
