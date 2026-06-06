#!/usr/bin/env python
"""Collect labeled examples for palm-up classification with the RealSense.

Controls:
  u -> label current visible hand as palm-up
  n -> label current visible hand as not palm-up
  q -> quit
"""

from __future__ import annotations

import json

import cv2

from nursearm import config
from nursearm.perception import hands
from nursearm.perception.palm_up_model import MODEL_PATH, feature_vector
from nursearm.perception.realsense import Perception

DATASET_PATH = config.ROOT / "data" / "datasets" / "palm_up_dataset.jsonl"


def main() -> None:
    dataset_path = DATASET_PATH
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    perception = Perception(mock=False)
    print("u=palm up, n=not palm up, q=quit")
    count = 0
    try:
        while True:
            color, depth = perception.frames()
            debug = hands.analyze(perception, color=color, depth=depth)
            frame = color.copy()
            if debug is not None:
                cv2.circle(frame, debug.palm_pixel, 8, (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    f"open={debug.is_open} up={debug.palm_up} conf={debug.palm_up_confidence:.2f}",
                    (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
            cv2.putText(
                frame,
                f"saved={count} model={MODEL_PATH.exists()}",
                (10, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            cv2.imshow("Collect palm-up dataset", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key not in (ord("u"), ord("n")) or debug is None:
                continue

            label = 1 if key == ord("u") else 0
            features = feature_vector(
                debug.landmarks_xyz,
                handedness=debug.handedness,
                base_palm_normal=debug.base_palm_normal,
            )
            row = {
                "label": label,
                "handedness": debug.handedness,
                "is_open": debug.is_open,
                "palm_point": debug.palm_point,
                "palm_up_confidence": debug.palm_up_confidence,
                "features": features.tolist(),
            }
            with dataset_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            count += 1
    finally:
        perception.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
