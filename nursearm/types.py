"""Shared data contracts used across the agent, skills, perception, and robot."""

from __future__ import annotations

from dataclasses import dataclass
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
class SceneObservation:
    """Current implemented hand/palm observation exposed through ``get_scene``."""

    hand_open: bool | None = None
    palm_point: Point3D | None = None
    palm_up: bool | None = None
    palm_up_confidence: float | None = None
    # Optional thumbnail (BGR) for the UI. Not serialized to JSON.
    frame: np.ndarray | None = None

    def summary(self) -> dict[str, Any]:
        """JSON-safe view for the agent and audit log."""
        return {
            "hand_open": self.hand_open,
            "palm_point": self.palm_point,
            "palm_up": self.palm_up,
            "palm_up_confidence": (
                round(self.palm_up_confidence, 3)
                if self.palm_up_confidence is not None
                else None
            ),
        }


@dataclass
class SkillResult:
    """Returned by every skill execution."""

    success: bool
    confidence: float
    note: str = ""
    frame: np.ndarray | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }
