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
import os
from dataclasses import dataclass

import cv2
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
    palm_up: bool = False
    palm_up_confidence: float = 0.0


class Perception:
    """Wraps a RealSense pipeline and the landmark extractors.

    For development without hardware, construct with ``mock=True`` to return empty/
    canned observations so the judge loop and UI can run on a laptop. When
    ``mock=True``, a laptop webcam is opened automatically if one is available so the
    UI can show a real feed rather than a synthetic placeholder.
    """

    def __init__(self, mock: bool = False) -> None:
        self.mock = mock
        self.source = os.getenv("NURSEARM_CAMERA_SOURCE", "realsense").strip().lower()
        self.webcam_index = int(os.getenv("NURSEARM_WEBCAM_INDEX", "0"))
        self._pipeline = None
        self._align = None
        self._intrinsics = None
        self._video_capture: cv2.VideoCapture | None = None
        self._video_capture_mode: str | None = None
        self._hand_eye = np.array(config.robot_config().get("hand_eye_transform", np.eye(4).tolist()))
        if not mock and self.source == "realsense":
            self._start()
        else:
            self._start_webcam(allow_failure=mock)

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

    def _start_webcam(self, *, allow_failure: bool = False) -> None:
        # Use explicit V4L2 backend on Linux for reliable RealSense access
        cap = cv2.VideoCapture(self.webcam_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            if allow_failure:
                logger.info("No webcam found on index %s; using synthetic frames.", self.webcam_index)
                return
            raise RuntimeError(f"failed to open webcam index {self.webcam_index}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        # Discard ~30 frames so RealSense auto-exposure settles before we stream
        logger.info("Warming up camera %s (discarding 30 frames for auto-exposure)…", self.webcam_index)
        for _ in range(30):
            cap.grab()
        self._video_capture = cap
        self._video_capture_mode = "mock" if self.mock else "webcam"
        logger.info("Webcam started (index=%s, mode=%s).", self.webcam_index, self._video_capture_mode)

    @property
    def has_real_camera(self) -> bool:
        """True when we have an open webcam or RealSense device."""
        if self.mock or self.source == "webcam":
            return self._video_capture is not None and self._video_capture.isOpened()
        return self._pipeline is not None

    # -- raw capture -------------------------------------------------------------
    def frames(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (color_bgr, depth_m) with depth aligned to color."""
        if self.mock:
            if self._video_capture is not None and self._video_capture.isOpened():
                ok, frame = self._video_capture.read()
                if ok:
                    return frame, np.zeros((frame.shape[0], frame.shape[1]), np.float32)
            return np.zeros((480, 640, 3), np.uint8), np.zeros((480, 640), np.float32)

        if self.source == "webcam":
            if self._video_capture is None:
                self._start_webcam(allow_failure=False)
            assert self._video_capture is not None
            ok, color = self._video_capture.read()
            if not ok or color is None:
                raise RuntimeError(f"failed to read webcam frame from index {self.webcam_index}")
            depth = np.zeros(color.shape[:2], np.float32)
            return color, depth

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
            palm_up=hand.palm_up if hand else None,
            palm_up_confidence=hand.palm_up_confidence if hand else None,
            gaze_target=gaze,
            frame=color,
        )

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
        if self._video_capture is not None:
            self._video_capture.release()
            self._video_capture = None
            self._video_capture_mode = None
