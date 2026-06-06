"""Face / mouth landmark -> 3D mouth point in the robot base frame.

Pattern: MediaPipe FaceMesh on the color frame gives a mouth landmark (e.g. the
upper-lip centre, landmark 13). Read the aligned depth at that pixel, then call
``perception.deproject(pixel, depth)`` to get the 3D point in the base frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nursearm.perception.realsense import FaceObservation, Perception

# MediaPipe FaceMesh index for the inner upper lip (a good mouth-target proxy).
MOUTH_LANDMARK = 13


def detect(perception: Perception) -> FaceObservation | None:
    """Return a FaceObservation with the 3D mouth point, or None if no face is visible."""
    from nursearm.perception.realsense import FaceObservation

    color, depth = perception.frames()
    # TODO: run MediaPipe FaceMesh on `color`, take landmark MOUTH_LANDMARK,
    #       convert normalized coords -> pixel (px, py), read depth[py, px],
    #       point = perception.deproject((px, py), depth_val).
    # Return FaceObservation(mouth_point=point). For now, no detection:
    return FaceObservation(mouth_point=None)
