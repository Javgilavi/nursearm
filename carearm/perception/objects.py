"""Object detection + pill classification -> DetectedObject list with 3D positions.

Two responsibilities:
  - Detect graspable objects on the table (a general detector: YOLO / OWL-ViT, or for
    the hackathon a simple colour/contour segmenter on the table plane).
  - Classify PILLS specifically (colour + shape, or a small CNN / a CLIP zero-shot call,
    or a VLM). dispense_pills relies on the `label` matching the medication name.

For each detection: take the bbox centre pixel, read aligned depth, deproject to a 3D
base-frame position with ``perception.deproject``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from carearm.types import DetectedObject

if TYPE_CHECKING:
    from carearm.perception.realsense import Perception


def detect(perception: Perception) -> list[DetectedObject]:
    """Return detected objects with labels, confidences and 3D base-frame positions."""
    color, depth = perception.frames()
    # TODO: run the detector on `color`. For each detection:
    #   cx, cy = bbox centre; d = depth[cy, cx]; pos = perception.deproject((cx, cy), d)
    #   label = classify_pill(crop) for pill-like detections, else the detector's class.
    #   append DetectedObject(label, confidence, pos, bbox).
    return []


def classify_pill(crop) -> tuple[str, float]:
    """Classify a single pill crop -> (label, confidence).

    Hackathon options, simplest first:
      1. Colour + size heuristic (e.g. "white round", "red capsule").
      2. CLIP zero-shot against the day's medication names.
      3. A small CNN fine-tuned on a few photos of the actual pills.
    """
    # TODO: implement. Start with option 1, upgrade to 2/3 if time allows.
    return ("unknown", 0.0)
