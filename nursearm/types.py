"""Shared data contracts used across the orchestrator, skills, perception and robot.

Keeping every cross-module type in one place means the judge, the skills and the
interface all speak the same language. Nothing here imports heavy deps (torch,
pyrealsense2, mediapipe) so it is safe to import anywhere, including the web server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# A camera-relative or base-frame 3D point, in metres.
Point3D = tuple[float, float, float]


@dataclass
class SkillInfo:
    """Natural-language description the judge reads to decide which skill to call."""

    name: str
    description: str
    kind: str = "vla"


@dataclass
class DetectedObject:
    """One object detected on the table, with its 3D position in the robot base frame."""

    label: str
    confidence: float
    position: Point3D
    bbox_xyxy: tuple[int, int, int, int] | None = None


@dataclass
class SceneObservation:
    """Current RGB-D understanding of the scene, exposed to the judge via ``get_scene``."""

    objects: list[DetectedObject] = field(default_factory=list)
    face_visible: bool = False
    mouth_point: Point3D | None = None
    hand_open: bool | None = None
    palm_point: Point3D | None = None
    palm_up: bool | None = None
    palm_up_confidence: float | None = None
    gaze_target: DetectedObject | None = None
    # Optional thumbnail (BGR) for the judge / UI to inspect. Not serialized to JSON.
    frame: np.ndarray | None = None

    def summary(self) -> dict[str, Any]:
        """JSON-safe view for the LLM and the audit log (drops the raw frame)."""
        return {
            "objects": [
                {"label": o.label, "confidence": round(o.confidence, 3), "position": o.position}
                for o in self.objects
            ],
            "face_visible": self.face_visible,
            "mouth_point": self.mouth_point,
            "hand_open": self.hand_open,
            "palm_point": self.palm_point,
            "palm_up": self.palm_up,
            "palm_up_confidence": round(self.palm_up_confidence, 3) if self.palm_up_confidence is not None else None,
            "gaze_target": self.gaze_target.label if self.gaze_target else None,
        }


@dataclass
class Medication:
    """One scheduled medication, from the Google Calendar integration."""

    name: str
    dose: str
    time: str  # ISO 8601 or "HH:MM"


@dataclass
class SkillResult:
    """Returned by every skill rollout and every recovery behavior."""

    success: bool
    confidence: float
    note: str = ""
    frame: np.ndarray | None = None  # final camera frame for the judge to inspect

    def summary(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }
