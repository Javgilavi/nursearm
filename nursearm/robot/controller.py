"""Thin wrapper over LeRobot. The ONLY module that talks to the SO-101.

It exposes a tiny, safe vocabulary the skills use: home(), jog(), run_policy(),
servo_to(), grip()/release(). Everything else (the judge, skills) goes through this. Keeping the
LeRobot surface in one place means the rest of the codebase has no hard dependency on
LeRobot internals and can run in mock mode on a laptop.

LeRobot integration choice (see README §LeRobot): we DEPEND on lerobot (installed in
the same venv), we do not fork it. Two ways to drive the arm:
  A. In-process: import lerobot's SO101Follower + a loaded policy and step the control
     loop here (lowest latency, most control). Preferred for servo_to.
  B. Subprocess: shell out to `lerobot-rollout --policy.path=... --task=...` for a full
     trained-skill rollout. Simplest; good enough for run_policy.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Callable

from nursearm import config
from nursearm.types import Point3D

logger = logging.getLogger(__name__)


class RobotController:
    def __init__(self, mock: bool = False) -> None:
        self.mock = mock
        rc = config.robot_config()
        self.port = rc.get("follower_port", "/dev/ttyACM0")
        self.robot_id = rc.get("follower_id", "follower")
        self.camera_arg = rc.get("camera_arg", "{ front: {type: opencv, index_or_path: 0, "
                                               "width: 640, height: 480, fps: 30}}")
        self.max_jump_m = rc.get("safe_stop_max_jump_m", 0.08)
        self._robot = None
        if not mock:
            self._connect()

    def _connect(self) -> None:
        # Option A wiring (in-process). Imported lazily so mock mode needs no lerobot.
        try:
            from lerobot.robots.so_follower.so_follower import SO101Follower  # type: ignore
            from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig  # type: ignore

            self._robot = SO101Follower(SO101FollowerConfig(port=self.port, id=self.robot_id))
            self._robot.connect()
            logger.info("SO-101 follower connected on %s (id=%s).", self.port, self.robot_id)
        except Exception:
            logger.exception("Could not connect SO-101 in-process; run_policy will use subprocess.")

    # -- primitives skills use ---------------------------------------------------
    def home(self) -> None:
        """Move to a safe home pose. Called between attempts and on abort."""
        if self.mock:
            logger.info("[mock] home()")
            return
        # TODO: send the configured home joint pose via self._robot.send_action(...).
        raise NotImplementedError("set home pose in config/robot.yaml and implement send_action")

    def jog(self, axis: str, distance_m: float) -> None:
        """Move the end effector by a fixed Cartesian offset."""
        if axis not in {"x", "y", "z"}:
            raise ValueError(f"unsupported jog axis: {axis}")
        if self.mock:
            logger.info("[mock] jog(axis=%s, distance_m=%.3f)", axis, distance_m)
            return
        # TODO: convert the Cartesian offset to a joint command with the selected
        # LeRobot kinematics implementation.
        raise NotImplementedError("implement Cartesian jog with LeRobot kinematics")

    def run_policy(self, policy_path: str | None, task: str, target: Point3D | None = None) -> None:
        """Run a full trained-skill rollout (Option B: lerobot-rollout subprocess)."""
        if self.mock or not policy_path:
            logger.info("[mock] run_policy(%s, task=%r, target=%s)", policy_path, task, target)
            return
        cmd = [
            "lerobot-rollout", "--strategy.type=base",
            f"--policy.path={policy_path}",
            "--robot.type=so101_follower", f"--robot.port={self.port}", f"--robot.id={self.robot_id}",
            f"--robot.cameras={self.camera_arg}", f"--task={task}", "--duration=30",
        ]
        logger.info("Running: %s", " ".join(cmd))
        subprocess.run(cmd, check=True)  # noqa: S603

    def servo_to(self, point: Point3D, standoff_m: float = 0.05,
                 track: Callable[[], Point3D | None] | None = None) -> None:
        """Move the end-effector toward `point`, stopping `standoff_m` short.

        SAFE-STOP: if a `track` callback is given, re-read the target each step; if it
        jumps more than `max_jump_m`, halt immediately (person moved). This is the
        hard safety guard for feed_person and hand_handoff.
        """
        if self.mock:
            logger.info("[mock] servo_to(%s, standoff=%.3f)", point, standoff_m)
            return
        # TODO: implement a small IK/Jacobian servo loop using lerobot's kinematics
        #       (see src/lerobot/robots/so_follower/robot_kinematic_processor.py).
        #       Each step: read track() -> if |new - last| > self.max_jump_m: STOP.
        raise NotImplementedError("implement servo loop with safe-stop guard")

    def grip(self) -> None:
        if self.mock:
            logger.info("[mock] grip()")
            return
        raise NotImplementedError

    def release(self) -> None:
        if self.mock:
            logger.info("[mock] release()")
            return
        raise NotImplementedError

    def disconnect(self) -> None:
        if self._robot is not None:
            self._robot.disconnect()
