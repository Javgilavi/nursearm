"""Thin wrapper over the SO-101 robot hardware.

Motor positions are normalized to [-100, 100] for arm joints, [0, 100] for the gripper.
In mock mode all operations are no-ops that log to stdout.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from nursearm import config

logger = logging.getLogger(__name__)

# Home pose — measured from the physical robot at its rest position.
_HOME_POSE: dict[str, float] = {
    "shoulder_pan":  16.74,
    "shoulder_lift": -96.69,
    "elbow_flex":    99.02,
    "wrist_flex":    69.80,
    "wrist_roll":    -0.02,
    "gripper":        4.84,
}

_GRIP_CLOSED = 80.0   # gripper closed (% of range)
_GRIP_OPEN   = 0.0    # gripper fully open


class RobotController:
    def __init__(self, mock: bool = False) -> None:
        self.mock = mock
        rc = config.robot_config()
        self.port = rc.get("follower_port", "/dev/ttyACM0")
        self.robot_id = rc.get("follower_id", "follower")
        self.camera_arg = rc.get("camera_arg", "")
        # Policy rollout settings (must match how the policy was trained).
        self.fps = rc.get("fps", 15)
        self.policy_device = rc.get("policy_device", "cuda")
        self.temporal_ensemble_coeff = rc.get("policy_temporal_ensemble_coeff")
        self.rollout_duration_s = rc.get("rollout_duration_s", 30)
        self.rollout_executable = os.getenv("NURSEARM_LEROBOT_ROLLOUT", "lerobot-rollout")
        self._bus = None
        self._current_pose: dict[str, float] = dict(_HOME_POSE)
        if not mock:
            self._connect()

    # ── connection ────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        from nursearm.robot.motor_bus import FeetechBus  # noqa: PLC0415

        try:
            bus = FeetechBus(self.port)
            bus.connect()
            self._bus = bus
            logger.info("SO-101 follower connected on %s.", self.port)
        except Exception as exc:
            permission_denied = (
                isinstance(exc, PermissionError)
                or getattr(exc, "errno", None) == 13
                or "Permission denied" in str(exc)
            )
            if permission_denied:
                logger.error(
                    "Permission denied opening %s. Add the current user to the device group "
                    "(usually `sudo usermod -aG dialout $USER`), then log out and back in.",
                    self.port,
                    exc_info=True,
                )
            else:
                logger.exception("Could not connect SO-101 on %s — running in degraded mode.", self.port)

    # ── state reading ─────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, float]:
        """Return current motor positions (normalized).  Falls back to last known on error."""
        if self.mock or self._bus is None:
            return dict(self._current_pose)
        try:
            import math  # noqa: PLC0415

            positions = self._bus.read_positions()
            for k, v in positions.items():
                if not math.isnan(v):
                    self._current_pose[k] = v
            return dict(self._current_pose)
        except Exception as exc:
            logger.warning("get_state failed: %s", exc)
            return dict(self._current_pose)

    # ── primitive skills ──────────────────────────────────────────────────────

    def _move_then_relax(self, positions: dict[str, float], settle_s: float = 0.8) -> None:
        """Write goal positions, wait for motion to settle, then disable torque."""
        self._bus.set_torque(True)
        self._bus.write_positions(positions)
        time.sleep(settle_s)
        self._bus.set_torque(False)

    def home(self) -> None:
        """Move all joints to the neutral home pose."""
        if self.mock:
            logger.info("[mock] home()")
            self._current_pose = dict(_HOME_POSE)
            return
        if self._bus is None:
            logger.warning("home(): not connected")
            return
        self._move_then_relax(_HOME_POSE, settle_s=1.2)
        self._current_pose = dict(_HOME_POSE)
        logger.info("home() done — torque off.")

    def grip(self) -> None:
        """Close the gripper."""
        if self.mock:
            logger.info("[mock] grip()")
            self._current_pose["gripper"] = _GRIP_CLOSED
            return
        if self._bus is None:
            return
        self._move_then_relax({"gripper": _GRIP_CLOSED}, settle_s=0.6)
        self._current_pose["gripper"] = _GRIP_CLOSED

    def release(self) -> None:
        """Open the gripper fully."""
        if self.mock:
            logger.info("[mock] release()")
            self._current_pose["gripper"] = _GRIP_OPEN
            return
        if self._bus is None:
            return
        self._move_then_relax({"gripper": _GRIP_OPEN}, settle_s=0.6)
        self._current_pose["gripper"] = _GRIP_OPEN

    def jog(self, joint: str, delta: float) -> None:
        """Move a single joint by `delta` normalized units.

        Valid joint names: shoulder_pan, shoulder_lift, elbow_flex,
                           wrist_flex, wrist_roll, gripper.
        """
        from nursearm.robot.motor_bus import MOTOR_NAMES  # noqa: PLC0415

        if joint not in MOTOR_NAMES:
            raise ValueError(f"Unknown joint: {joint!r}. Valid: {MOTOR_NAMES}")
        if self.mock:
            logger.info("[mock] jog(joint=%s, delta=%.1f)", joint, delta)
            lo, hi = (0.0, 100.0) if joint == "gripper" else (-100.0, 100.0)
            self._current_pose[joint] = max(lo, min(hi, self._current_pose.get(joint, 0.0) + delta))
            return
        if self._bus is None:
            return
        current = self.get_state()
        lo, hi = (0.0, 100.0) if joint == "gripper" else (-100.0, 100.0)
        target = max(lo, min(hi, current.get(joint, 0.0) + delta))
        self._move_then_relax({joint: target}, settle_s=0.6)
        self._current_pose[joint] = target

    def move_direction(self, direction: str, step_m: float = 0.02) -> None:
        """Move the end-effector by `step_m` metres in a Cartesian direction.

        Valid directions: up, down, forward, back, left, right.
        Uses analytical FK + numerical IK from nursearm.robot.kinematics.
        """
        from nursearm.robot.kinematics import step_direction  # noqa: PLC0415

        if self.mock:
            logger.info("[mock] move_direction(%s, step=%.3f m)", direction, step_m)
            new_joints = step_direction(self._current_pose, direction, step_m)
            self._current_pose.update(new_joints)
            return
        if self._bus is None:
            return
        current = self.get_state()
        new_joints = step_direction(current, direction, step_m)
        self._move_then_relax(new_joints, settle_s=0.6)
        self._current_pose.update(new_joints)

    def run_policy(
        self,
        policy_path: str | None,
        task: str,
        duration_s: float | None = None,
        camera_arg: str | None = None,
        fps: float | None = None,
    ) -> None:
        """Run a full trained-skill rollout (Option B: lerobot-rollout subprocess).

        Frees the in-process serial connection first so lerobot-rollout can own the arm,
        then reconnects afterwards. Passes the camera/fps config and only enables
        temporal ensembling when explicitly configured for a compatible checkpoint.
        """
        duration_s = self.rollout_duration_s if duration_s is None else duration_s
        camera_arg = self.camera_arg if camera_arg is None else camera_arg
        fps = self.fps if fps is None else fps
        if self.mock or not policy_path:
            logger.info("[mock] run_policy(%s, task=%r)", policy_path, task)
            return

        # lerobot-rollout opens the arm itself — release our in-process handle first,
        # otherwise both fight for the serial port.
        reconnect = self._bus is not None
        if reconnect:
            try:
                self._bus.disconnect()
            except Exception:
                logger.exception("disconnect before rollout failed")
            self._bus = None

        cmd = [
            self.rollout_executable, "--strategy.type=base",
            f"--policy.path={policy_path}",
            f"--policy.device={self.policy_device}",
            "--robot.type=so101_follower",
            f"--robot.port={self.port}", f"--robot.id={self.robot_id}",
            f"--robot.cameras={camera_arg}",
            f"--task={task}",
            f"--fps={fps}",
            f"--duration={duration_s}",
        ]
        if self.temporal_ensemble_coeff is not None:
            cmd.insert(
                4,
                f"--policy.temporal_ensemble_coeff={self.temporal_ensemble_coeff}",
            )
        logger.info("Running: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)  # noqa: S603
        finally:
            if reconnect:
                self._connect()

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
