"""Hand landmarks -> open/closed state + 3D palm point + palm-up classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from nursearm.perception.palm_up_model import feature_vector, load_default_model

if TYPE_CHECKING:
    from nursearm.perception.realsense import HandObservation, Perception

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_MCP = 13
RING_TIP = 16
PINKY_MCP = 17
PINKY_TIP = 20
FINGER_MCPS = (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
FINGER_TIPS = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)

_HAND_BONES = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

_MP_HANDS = None
_MP_HANDS_KIND = None
_TASK_MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "hand_landmarker.task"


@dataclass
class HandDebug:
    landmarks_xyz: np.ndarray
    landmarks_px: np.ndarray
    handedness: str | None
    is_open: bool
    openness_score: float
    palm_pixel: tuple[int, int]
    palm_point: tuple[float, float, float] | None
    palm_up: bool
    palm_up_confidence: float
    base_palm_normal: tuple[float, float, float] | None


def detect(perception: Perception) -> HandObservation | None:
    """Return a HandObservation (open?, 3D palm point, palm-up?), or None if no hand is visible."""
    from nursearm.perception.realsense import HandObservation

    debug = analyze(perception)
    if debug is None:
        return None
    return HandObservation(
        is_open=debug.is_open,
        palm_point=debug.palm_point,
        palm_up=debug.palm_up,
        palm_up_confidence=debug.palm_up_confidence,
    )


def analyze(
    perception: Perception,
    *,
    color: np.ndarray | None = None,
    depth: np.ndarray | None = None,
) -> HandDebug | None:
    """Full hand analysis for scripts and runtime inference."""
    if color is None or depth is None:
        color, depth = perception.frames()
    result = _run_mediapipe(color)
    if result is None:
        return None

    landmarks_xyz, landmarks_px, handedness = result
    is_open = _is_hand_open(landmarks_xyz)
    openness_score = _openness_score(landmarks_xyz)
    palm_pixel = _palm_pixel(landmarks_px, depth.shape[1], depth.shape[0])
    palm_depth = _depth_at(depth, palm_pixel)
    palm_point = perception.deproject(palm_pixel, palm_depth) if palm_depth is not None else None
    base_palm_normal = _base_palm_normal(perception, depth, landmarks_px)
    palm_up, conf = _classify_palm_up(
        landmarks_xyz,
        handedness,
        base_palm_normal,
        is_open=is_open,
        openness_score=openness_score,
        source=perception.source,
    )
    return HandDebug(
        landmarks_xyz=landmarks_xyz,
        landmarks_px=landmarks_px,
        handedness=handedness,
        is_open=is_open,
        openness_score=openness_score,
        palm_pixel=palm_pixel,
        palm_point=palm_point,
        palm_up=palm_up,
        palm_up_confidence=conf,
        base_palm_normal=base_palm_normal,
    )


def _run_mediapipe(color_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, str | None] | None:
    hands = _hands_solution()
    rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
    height, width = color_bgr.shape[:2]

    if _MP_HANDS_KIND == "solutions":
        results = hands.process(rgb)
        if not results.multi_hand_landmarks:
            return None
        hand = results.multi_hand_landmarks[0]
        xyz = np.array([(lm.x, lm.y, lm.z) for lm in hand.landmark], dtype=np.float32)
        px = np.array(
            [
                (
                    int(np.clip(round(lm.x * (width - 1)), 0, width - 1)),
                    int(np.clip(round(lm.y * (height - 1)), 0, height - 1)),
                )
                for lm in hand.landmark
            ],
            dtype=np.int32,
        )
        handedness = None
        if results.multi_handedness:
            handedness = results.multi_handedness[0].classification[0].label
        return xyz, px, handedness

    import mediapipe as mp

    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    results = hands.detect(image)
    if not results.hand_landmarks:
        return None
    hand = results.hand_landmarks[0]
    xyz = np.array([(lm.x, lm.y, lm.z) for lm in hand], dtype=np.float32)
    px = np.array(
        [
            (
                int(np.clip(round(lm.x * (width - 1)), 0, width - 1)),
                int(np.clip(round(lm.y * (height - 1)), 0, height - 1)),
            )
            for lm in hand
        ],
        dtype=np.int32,
    )
    handedness = None
    if results.handedness and results.handedness[0]:
        handedness = results.handedness[0][0].category_name
    return xyz, px, handedness


def _hands_solution():
    global _MP_HANDS, _MP_HANDS_KIND
    if _MP_HANDS is None:
        try:
            import mediapipe as mp

            hands_module = mp.solutions.hands
            _MP_HANDS = hands_module.Hands(
                static_image_mode=False,
                model_complexity=1,
                max_num_hands=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            _MP_HANDS_KIND = "solutions"
        except AttributeError as exc:
            from mediapipe.tasks.python import BaseOptions, vision

            if not _TASK_MODEL_PATH.exists():
                raise RuntimeError(
                    f"missing hand landmarker model bundle: {_TASK_MODEL_PATH}"
                ) from exc
            options = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(_TASK_MODEL_PATH)),
                num_hands=1,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            _MP_HANDS = vision.HandLandmarker.create_from_options(options)
            _MP_HANDS_KIND = "tasks"
    return _MP_HANDS


def _is_hand_open(landmarks_xyz: np.ndarray) -> bool:
    return bool(_openness_score(landmarks_xyz) > 1.65)


def _openness_score(landmarks_xyz: np.ndarray) -> float:
    wrist = landmarks_xyz[WRIST]
    spread = [float(np.linalg.norm(landmarks_xyz[idx] - wrist)) for idx in FINGER_TIPS]
    mcp_spread = [float(np.linalg.norm(landmarks_xyz[idx] - wrist)) for idx in FINGER_MCPS]
    if not mcp_spread:
        return 0.0
    return float(np.mean(spread) / max(np.mean(mcp_spread), 1e-6))


def _palm_pixel(landmarks_px: np.ndarray, width: int, height: int) -> tuple[int, int]:
    centroid = landmarks_px[[WRIST, *FINGER_MCPS]].mean(axis=0)
    px = int(np.clip(round(float(centroid[0])), 0, width - 1))
    py = int(np.clip(round(float(centroid[1])), 0, height - 1))
    return px, py


def _depth_at(depth_m: np.ndarray, pixel: tuple[int, int], radius: int = 3) -> float | None:
    px, py = pixel
    y0 = max(py - radius, 0)
    y1 = min(py + radius + 1, depth_m.shape[0])
    x0 = max(px - radius, 0)
    x1 = min(px + radius + 1, depth_m.shape[1])
    patch = depth_m[y0:y1, x0:x1]
    valid = patch[np.isfinite(patch) & (patch > 0.0)]
    if valid.size == 0:
        return None
    return float(np.median(valid))


def _base_palm_normal(
    perception: Perception,
    depth_m: np.ndarray,
    landmarks_px: np.ndarray,
) -> tuple[float, float, float] | None:
    points: list[np.ndarray] = []
    for idx in (WRIST, INDEX_MCP, PINKY_MCP):
        pixel = tuple(int(v) for v in landmarks_px[idx])
        depth = _depth_at(depth_m, pixel)
        if depth is None:
            return None
        points.append(np.array(perception.deproject(pixel, depth), dtype=np.float32))

    wrist, index, pinky = points
    normal = np.cross(index - wrist, pinky - wrist)
    norm = np.linalg.norm(normal)
    if not np.isfinite(norm) or norm < 1e-6:
        return None
    normal = normal / norm
    return float(normal[0]), float(normal[1]), float(normal[2])


def _classify_palm_up(
    landmarks_xyz: np.ndarray,
    handedness: str | None,
    base_palm_normal: tuple[float, float, float] | None,
    *,
    is_open: bool,
    openness_score: float,
    source: str,
) -> tuple[bool, float]:
    model = load_default_model()
    features = feature_vector(
        landmarks_xyz,
        handedness=handedness,
        base_palm_normal=base_palm_normal,
    )
    if model is not None and base_palm_normal is not None:
        return model.predict(features)
    return _heuristic_palm_up(
        landmarks_xyz,
        handedness,
        base_palm_normal,
        is_open=is_open,
        openness_score=openness_score,
        source=source,
    )


def _heuristic_palm_up(
    landmarks_xyz: np.ndarray,
    handedness: str | None,
    base_palm_normal: tuple[float, float, float] | None,
    *,
    is_open: bool,
    openness_score: float,
    source: str,
) -> tuple[bool, float]:
    if base_palm_normal is not None:
        upness = float(base_palm_normal[2])
        confidence = float(np.clip((upness + 1.0) / 2.0, 0.0, 1.0))
        return upness > 0.25, confidence

    # Webcam mode has no reliable depth, so treat a clear open-palm presentation as
    # a proxy signal for "palm visible" to make laptop testing practical.
    if source == "webcam":
        confidence = float(np.clip((openness_score - 1.25) / 0.75, 0.0, 1.0))
        return is_open, confidence

    palm_normal = np.cross(
        landmarks_xyz[INDEX_MCP] - landmarks_xyz[WRIST],
        landmarks_xyz[PINKY_MCP] - landmarks_xyz[WRIST],
    )
    norm = float(np.linalg.norm(palm_normal))
    if norm < 1e-6:
        return False, 0.0
    palm_normal = palm_normal / norm
    z_score = float(abs(palm_normal[2]))
    confidence = float(np.clip(z_score, 0.0, 1.0))
    return is_open and z_score > 0.35, confidence


def draw_debug(frame: np.ndarray, debug: HandDebug) -> np.ndarray:
    rendered = frame.copy()
    pts = debug.landmarks_px

    # skeleton bones
    for a, b in _HAND_BONES:
        cv2.line(rendered, (int(pts[a][0]), int(pts[a][1])), (int(pts[b][0]), int(pts[b][1])),
                 (255, 255, 255), 2, cv2.LINE_AA)

    # joint dots
    for px, py in pts:
        cv2.circle(rendered, (int(px), int(py)), 5, (40, 220, 140), -1, cv2.LINE_AA)
        cv2.circle(rendered, (int(px), int(py)), 5, (255, 255, 255), 1, cv2.LINE_AA)

    # palm centroid
    cv2.circle(rendered, debug.palm_pixel, 10, (0, 220, 255), -1, cv2.LINE_AA)
    cv2.circle(rendered, debug.palm_pixel, 12, (255, 255, 255), 2, cv2.LINE_AA)

    # text with dark background
    hand_str = debug.handedness or "hand"
    state_str = "open" if debug.is_open else "closed"
    up_str = f"palm-up: {'yes' if debug.palm_up else 'no'} ({debug.palm_up_confidence:.0%})"
    label = f"{hand_str}  {state_str}  {up_str}"
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.58, 1
    (tw, th), baseline = cv2.getTextSize(label, font, scale, thick)
    y = rendered.shape[0] - 10
    cv2.rectangle(rendered, (8, y - th - baseline - 4), (12 + tw, y + 4), (0, 0, 0), -1)
    cv2.putText(rendered, label, (10, y - baseline), font, scale, (40, 220, 140), thick, cv2.LINE_AA)

    return rendered
