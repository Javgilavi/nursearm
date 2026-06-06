"""Hand landmarks -> open/closed state + 3D palm point in the robot base frame.

MediaPipe Hands gives 21 landmarks. Open vs closed: compare fingertip-to-palm
distances (open hand = fingertips far from the wrist/MCP joints). Palm point: the
centroid of the wrist + finger-MCP landmarks, deprojected with its depth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nursearm.perception.realsense import HandObservation, Perception

WRIST = 0
FINGER_MCPS = (5, 9, 13, 17)  # index/middle/ring/pinky knuckles


def detect(perception: Perception) -> HandObservation | None:
    """Return a HandObservation (open?, 3D palm point), or None if no hand is visible."""
    from nursearm.perception.realsense import HandObservation

    color, depth = perception.frames()
    # TODO: run MediaPipe Hands on `color`. Compute open/closed from fingertip spread.
    #       Palm pixel = mean of WRIST + FINGER_MCPS landmarks -> deproject with depth.
    return HandObservation(is_open=False, palm_point=None)
