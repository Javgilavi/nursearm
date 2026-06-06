"""Gaze estimation -> ray from the eyes -> nearest object hit (the gaze target).

Estimate gaze direction from MediaPipe FaceMesh iris + eye landmarks, cast a ray from
the eye midpoint into the scene, and intersect it with the detected objects' 3D
positions. The nearest object within an angular threshold is the gaze target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nursearm.types import DetectedObject

if TYPE_CHECKING:
    from nursearm.perception.realsense import Perception

MAX_ANGLE_DEG = 15.0  # an object must be within this cone of the gaze ray to count


def target(perception: Perception, objects: list[DetectedObject]) -> DetectedObject | None:
    """Return the object the person is looking at, or None."""
    if not objects:
        return None
    # TODO: estimate the gaze ray (origin = eye midpoint in base frame, direction from
    #       iris offset), then pick the object whose bearing from the origin is closest
    #       to the ray direction and within MAX_ANGLE_DEG.
    return None
