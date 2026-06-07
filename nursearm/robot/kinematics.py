"""SO-101 forward and inverse kinematics.

Joint space  : normalized values (-100..+100 for arm joints, 0..100 gripper).
World frame  : X = forward, Y = left, Z = up, origin at base centre on the table.

SO-101 geometry (from SO-ARM100 design):
  L1 = 0.100 m   base height  (table → shoulder joint)
  L2 = 0.100 m   upper arm    (shoulder → elbow)
  L3 = 0.096 m   forearm      (elbow → wrist)
  L4 = 0.160 m   hand         (wrist → gripper tip)

Joint convention (all angles measured from arm-horizontal at norm=0):
  q1  shoulder_pan   rotates about Z  (positive = left)
  q2  shoulder_lift  rotates about Y  (positive = up)
  q3  elbow_flex     rotates about Y  (positive = flex up, i.e. bend the elbow)
  q4  wrist_flex     rotates about Y  (positive = flex up)
  q5  wrist_roll     rotates about X  (ignored for position IK)

Calibration-derived scale (each motor's normalized range ÷ physical range):
  shoulder_pan  : range 709–3188  → 217.9 ° total → ±108.9 ° from zero
  shoulder_lift : range 793–3210  → 212.4 °        → ±106.2 °
  elbow_flex    : range 666–3123  → 216.1 °        → ±108.0 °
  wrist_flex    : range 755–3258  → 220.0 °        → ±110.0 °
  wrist_roll    : range   0–4095  → 360.0 °        → ±180.0 °
"""

from __future__ import annotations

import math

import numpy as np

# ── link lengths (metres) ─────────────────────────────────────────────────────
L1 = 0.100  # base → shoulder
L2 = 0.100  # shoulder → elbow
L3 = 0.096  # elbow → wrist
L4 = 0.160  # wrist → gripper tip

# ── norm-to-radian scale for each joint ──────────────────────────────────────
# 1 norm unit = this many radians
_SCALE: dict[str, float] = {
    "shoulder_pan":  math.radians(108.9) / 100.0,
    "shoulder_lift": math.radians(106.2) / 100.0,
    "elbow_flex":    math.radians(108.0) / 100.0,
    "wrist_flex":    math.radians(110.0) / 100.0,
    "wrist_roll":    math.radians(180.0) / 100.0,
}

_IK_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex"]
_LIMITS = {n: (-100.0, 100.0) for n in _IK_JOINTS}


def _n2r(name: str, norm: float) -> float:
    return norm * _SCALE[name]


def forward_kinematics(joints: dict[str, float]) -> np.ndarray:
    """Return end-effector [x, y, z] position in metres."""
    q1 = _n2r("shoulder_pan",  joints.get("shoulder_pan",  0.0))
    q2 = _n2r("shoulder_lift", joints.get("shoulder_lift", 0.0))
    q3 = _n2r("elbow_flex",    joints.get("elbow_flex",    0.0))
    q4 = _n2r("wrist_flex",    joints.get("wrist_flex",    0.0))

    # Horizontal reach in the arm's sagittal plane
    reach = (
        L2 * math.cos(q2)
        + L3 * math.cos(q2 + q3)
        + L4 * math.cos(q2 + q3 + q4)
    )
    z = (
        L1
        + L2 * math.sin(q2)
        + L3 * math.sin(q2 + q3)
        + L4 * math.sin(q2 + q3 + q4)
    )
    x = reach * math.cos(q1)
    y = reach * math.sin(q1)
    return np.array([x, y, z], dtype=float)


def _jacobian(joints: dict[str, float], eps: float = 0.5) -> np.ndarray:
    """3×4 numerical Jacobian: ∂(xyz)/∂(norm_i) for the 4 IK joints."""
    p0 = forward_kinematics(joints)
    J = np.zeros((3, 4))
    for i, name in enumerate(_IK_JOINTS):
        jh = dict(joints)
        jh[name] = joints.get(name, 0.0) + eps
        J[:, i] = (forward_kinematics(jh) - p0) / eps
    return J


def inverse_kinematics(
    joints: dict[str, float],
    target_xyz: np.ndarray,
    max_iter: int = 200,
    tol_m: float = 0.003,
) -> dict[str, float]:
    """Damped-least-squares IK.

    Moves shoulder_pan, shoulder_lift, elbow_flex, wrist_flex to reach
    `target_xyz`.  Gripper and wrist_roll are preserved unchanged.

    Returns updated joints dict (still in normalised units).
    """
    q = dict(joints)
    for _ in range(max_iter):
        ee = forward_kinematics(q)
        err = target_xyz - ee
        norm_err = float(np.linalg.norm(err))
        if norm_err < tol_m:
            break
        J = _jacobian(q)
        # Auto-scale damping: 0.1% of the largest singular value squared
        sigma_max = float(np.linalg.svd(J, compute_uv=False)[0])
        damping = max(1e-9, (sigma_max ** 2) * 1e-2)
        A = J @ J.T + damping * np.eye(3)
        dq = J.T @ np.linalg.solve(A, err)
        for i, name in enumerate(_IK_JOINTS):
            lo, hi = _LIMITS[name]
            q[name] = max(lo, min(hi, q.get(name, 0.0) + float(dq[i])))
    return q


# ── Cartesian step helpers ────────────────────────────────────────────────────

_STEP_M = 0.02  # 2 cm per directional move

_DIRECTION_DELTA: dict[str, np.ndarray] = {
    "up":      np.array([0.0,  0.0,  _STEP_M]),
    "down":    np.array([0.0,  0.0, -_STEP_M]),
    "forward": np.array([_STEP_M,  0.0, 0.0]),
    "back":    np.array([-_STEP_M, 0.0, 0.0]),
    "left":    np.array([0.0,  _STEP_M, 0.0]),
    "right":   np.array([0.0, -_STEP_M, 0.0]),
}


def step_direction(
    joints: dict[str, float],
    direction: str,
    step_m: float = _STEP_M,
) -> dict[str, float]:
    """Return new joints after moving the EE by `step_m` in `direction`.

    Valid directions: up, down, forward, back, left, right.
    """
    if direction not in _DIRECTION_DELTA:
        raise ValueError(f"Unknown direction {direction!r}. Valid: {list(_DIRECTION_DELTA)}")
    delta = _DIRECTION_DELTA[direction] * (step_m / _STEP_M)
    current_ee = forward_kinematics(joints)
    target_ee = current_ee + delta
    return inverse_kinematics(joints, target_ee)
