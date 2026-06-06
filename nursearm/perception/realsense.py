"""RealSense RGB-D capture + the unified Perception service.

Perception is a SHARED service: both the judge (situational awareness via get_scene)
and the skills (targeting) call it. The core RGB-D pattern (see README §6) is:

    1. MediaPipe on the COLOR frame -> 2D landmarks (mouth, palm, eyes).
    2. rs.align depth->color so every color pixel has a depth value.
    3. rs.rs2_deproject_pixel_to_point(pixel, depth) -> 3D point in CAMERA frame.
    4. apply the hand-eye transform (config/robot.yaml) -> ROBOT BASE frame.
    5. hand that 3D target to the skill / servo loop.

This module owns steps 1-4. The face/gaze/hands/objects sub-modules implement the
landmark extraction; this class wires them together into a SceneObservation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from nursearm import config
from nursearm.types import DetectedObject, Point3D, SceneObservation

logger = logging.getLogger(__name__)


@dataclass
class FaceObservation:
    mouth_point: Point3D | None


@dataclass
class HandObservation:
    is_open: bool
    palm_point: Point3D | None


class Perception:
    """Wraps a RealSense pipeline and the landmark extractors.

    For development without hardware, construct with ``mock=True`` to return empty/
    canned observations so the judge loop and UI can run on a laptop.  When mock=True,
    a laptop webcam (index 0) is opened automatically if one is available so the camera
    tile in the UI shows a real feed rather than a synthetic placeholder.
    """

    def __init__(self, mock: bool = False) -> None:
        self.mock = mock
        self._pipeline = None
        self._align = None
        self._intrinsics = None
        self._cap = None  # cv2.VideoCapture for laptop webcam in mock mode
        self._hand_eye = np.array(config.robot_config().get("hand_eye_transform", np.eye(4).tolist()))
        if not mock:
            self._start()
        else:
            self._start_webcam()

    def _start_webcam(self) -> None:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            self._cap = cap
            logger.info("Laptop webcam (index 0) opened for mock-mode camera feed.")
        else:
            cap.release()
            logger.info("No webcam found on index 0; using synthetic frames.")

    def _start(self) -> None:
        import pyrealsense2 as rs  # lazy import — only needed with real hardware

        self._pipeline = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        cfg.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        profile = self._pipeline.start(cfg)
        self._align = rs.align(rs.stream.color)
        self._intrinsics = (
            profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        )
        logger.info("RealSense started (color+depth, aligned).")

    @property
    def has_real_camera(self) -> bool:
        """True when we have an open webcam (mock mode) or RealSense (real mode)."""
        if self.mock:
            return self._cap is not None and self._cap.isOpened()
        return self._pipeline is not None

    # -- raw capture -------------------------------------------------------------
    def frames(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (color_bgr, depth_m) with depth aligned to color."""
        if self.mock:
            if self._cap is not None and self._cap.isOpened():
                ok, frame = self._cap.read()
                if ok:
                    return frame, np.zeros((frame.shape[0], frame.shape[1]), np.float32)
            return np.zeros((480, 640, 3), np.uint8), np.zeros((480, 640), np.float32)
        import pyrealsense2 as rs  # noqa: F401

        frames = self._align.process(self._pipeline.wait_for_frames())
        color = np.asanyarray(frames.get_color_frame().get_data())
        depth = np.asanyarray(frames.get_depth_frame().get_data()).astype(np.float32) * 0.001
        return color, depth

    def deproject(self, pixel: tuple[int, int], depth_m: float) -> Point3D:
        """Pixel + depth -> 3D point in CAMERA frame, then transform to BASE frame."""
        if self.mock or self._intrinsics is None:
            return (0.0, 0.0, 0.0)
        import pyrealsense2 as rs

        x, y, z = rs.rs2_deproject_pixel_to_point(self._intrinsics, list(pixel), depth_m)
        cam = np.array([x, y, z, 1.0])
        base = self._hand_eye @ cam
        return (float(base[0]), float(base[1]), float(base[2]))

    # -- high-level observations -------------------------------------------------
    def observe(self) -> SceneObservation:
        """Full scene understanding for the judge's get_scene tool."""
        color, _ = self.frames()
        face = self.face()
        hand = self.hands()
        objects = self.objects()
        gaze = self.gaze_target(objects)
        return SceneObservation(
            objects=objects,
            face_visible=face is not None and face.mouth_point is not None,
            mouth_point=face.mouth_point if face else None,
            hand_open=hand.is_open if hand else None,
            palm_point=hand.palm_point if hand else None,
            gaze_target=gaze,
            frame=color,
        )

    # The following delegate to the sub-modules. Imported lazily to keep this file light.
    def face(self) -> FaceObservation | None:
        from nursearm.perception import face as face_mod

        return face_mod.detect(self)

    def hands(self) -> HandObservation | None:
        from nursearm.perception import hands as hands_mod

        return hands_mod.detect(self)

    def objects(self) -> list[DetectedObject]:
        from nursearm.perception import objects as objects_mod

        return objects_mod.detect(self)

    def gaze_target(self, objects: list[DetectedObject] | None = None) -> DetectedObject | None:
        from nursearm.perception import gaze as gaze_mod

        return gaze_mod.target(self, objects if objects is not None else self.objects())

    def close(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
