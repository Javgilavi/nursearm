"""Trainable palm-up classifier over hand landmarks.

The goal is not to ship a giant vision model into this repo. MediaPipe already solves
the expensive part (finding the 21 hand landmarks). This module turns those landmarks
into a small feature vector and trains a lightweight binary classifier:

    1 => open palm facing upward
    0 => any other pose/orientation

That keeps iteration fast, works well with small datasets, and is practical for a
RealSense-based robotics stack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from nursearm import config

MODEL_PATH = config.ROOT / "data" / "models" / "palm_up_model.json"

WRIST = 0
INDEX_MCP = 5
MIDDLE_MCP = 9
PINKY_MCP = 17
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_TIP = 20


def handedness_sign(label: str | None) -> float:
    if not label:
        return 0.0
    return 1.0 if label.lower() == "right" else -1.0


def normalize_landmarks(landmarks_xyz: np.ndarray) -> np.ndarray:
    """Center on the wrist and normalize by palm width."""
    centered = landmarks_xyz - landmarks_xyz[WRIST]
    scale = np.linalg.norm(landmarks_xyz[INDEX_MCP] - landmarks_xyz[PINKY_MCP])
    if not np.isfinite(scale) or scale < 1e-6:
        scale = 1.0
    return centered / scale


def feature_vector(
    landmarks_xyz: np.ndarray,
    *,
    handedness: str | None,
    base_palm_normal: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """Flatten normalized geometry plus a few orientation summary features."""
    norm = normalize_landmarks(landmarks_xyz)
    wrist = norm[WRIST]
    index = norm[INDEX_MCP]
    middle = norm[MIDDLE_MCP]
    pinky = norm[PINKY_MCP]
    palm_normal = np.cross(index - wrist, pinky - wrist)
    palm_norm = np.linalg.norm(palm_normal)
    if palm_norm > 1e-6:
        palm_normal = palm_normal / palm_norm
    else:
        palm_normal = np.zeros(3, dtype=np.float32)

    fingertip_distances = np.array(
        [
            np.linalg.norm(norm[THUMB_TIP] - wrist),
            np.linalg.norm(norm[INDEX_TIP] - wrist),
            np.linalg.norm(norm[MIDDLE_TIP] - wrist),
            np.linalg.norm(norm[RING_TIP] - wrist),
            np.linalg.norm(norm[PINKY_TIP] - wrist),
        ],
        dtype=np.float32,
    )
    finger_axis = middle - wrist
    finger_axis_norm = np.linalg.norm(finger_axis)
    if finger_axis_norm > 1e-6:
        finger_axis = finger_axis / finger_axis_norm
    else:
        finger_axis = np.zeros(3, dtype=np.float32)

    base_normal = np.array(base_palm_normal if base_palm_normal is not None else (0.0, 0.0, 0.0), dtype=np.float32)
    features = np.concatenate(
        [
            norm.astype(np.float32).reshape(-1),
            fingertip_distances,
            palm_normal.astype(np.float32),
            finger_axis.astype(np.float32),
            base_normal,
            np.array([handedness_sign(handedness)], dtype=np.float32),
        ]
    )
    return features.astype(np.float32)


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))


@dataclass
class PalmUpModel:
    weights: np.ndarray
    bias: float
    mean: np.ndarray
    std: np.ndarray

    def predict_proba(self, features: np.ndarray) -> float:
        x = ((features - self.mean) / self.std).astype(np.float32)
        score = float(x @ self.weights + self.bias)
        return float(sigmoid(np.array([score], dtype=np.float32))[0])

    def predict(self, features: np.ndarray, threshold: float = 0.5) -> tuple[bool, float]:
        prob = self.predict_proba(features)
        return prob >= threshold, prob

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "weights": self.weights.tolist(),
            "bias": self.bias,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
        }
        path.write_text(json.dumps(payload))

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> PalmUpModel:
        payload = json.loads(path.read_text())
        return cls(
            weights=np.array(payload["weights"], dtype=np.float32),
            bias=float(payload["bias"]),
            mean=np.array(payload["mean"], dtype=np.float32),
            std=np.array(payload["std"], dtype=np.float32),
        )


@lru_cache(maxsize=1)
def load_default_model() -> PalmUpModel | None:
    if not MODEL_PATH.exists():
        return None
    return PalmUpModel.load(MODEL_PATH)


def train_from_jsonl(
    dataset_path: Path,
    *,
    output_path: Path = MODEL_PATH,
    epochs: int = 600,
    lr: float = 0.08,
    l2: float = 1e-4,
) -> PalmUpModel:
    rows = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"Dataset is empty: {dataset_path}")

    x = np.array([row["features"] for row in rows], dtype=np.float32)
    y = np.array([row["label"] for row in rows], dtype=np.float32)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-6] = 1.0
    xn = (x - mean) / std

    weights = np.zeros(x.shape[1], dtype=np.float32)
    bias = 0.0
    n = float(len(x))
    for _ in range(epochs):
        logits = xn @ weights + bias
        probs = sigmoid(logits)
        error = probs - y
        grad_w = (xn.T @ error) / n + l2 * weights
        grad_b = float(error.mean())
        weights -= lr * grad_w
        bias -= lr * grad_b

    model = PalmUpModel(weights=weights, bias=bias, mean=mean, std=std)
    model.save(output_path)
    load_default_model.cache_clear()
    return model


def evaluate(model: PalmUpModel, dataset_path: Path) -> dict[str, float]:
    rows = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"Dataset is empty: {dataset_path}")
    correct = 0
    probs: list[float] = []
    labels: list[int] = []
    for row in rows:
        prob = model.predict_proba(np.array(row["features"], dtype=np.float32))
        pred = int(prob >= 0.5)
        correct += int(pred == int(row["label"]))
        probs.append(prob)
        labels.append(int(row["label"]))
    preds = np.array([p >= 0.5 for p in probs], dtype=np.int32)
    ys = np.array(labels, dtype=np.int32)
    tp = int(np.sum((preds == 1) & (ys == 1)))
    fp = int(np.sum((preds == 1) & (ys == 0)))
    fn = int(np.sum((preds == 0) & (ys == 1)))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return {
        "samples": float(len(rows)),
        "accuracy": correct / len(rows),
        "precision": precision,
        "recall": recall,
    }
