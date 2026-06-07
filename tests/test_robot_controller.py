from __future__ import annotations

from typing import Any

from nursearm.robot.controller import RobotController


class FakeBus:
    def __init__(self) -> None:
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


def test_run_policy_releases_bus_and_reconnects(monkeypatch: Any) -> None:
    controller = RobotController(mock=True)
    controller.mock = False
    bus = FakeBus()
    controller._bus = bus

    commands: list[list[str]] = []
    reconnects: list[bool] = []

    monkeypatch.setattr(
        "nursearm.robot.controller.subprocess.run",
        lambda command, check: commands.append(command),
    )
    monkeypatch.setattr(
        controller,
        "_connect",
        lambda: reconnects.append(True),
    )

    controller.run_policy(
        "/tmp/checkpoint",
        task="sort the pills",
        duration_s=12,
    )

    assert bus.disconnected
    assert reconnects == [True]
    assert commands == [
        [
            controller.rollout_executable,
            "--strategy.type=base",
            "--policy.path=/tmp/checkpoint",
            f"--policy.device={controller.policy_device}",
            "--robot.type=so101_follower",
            f"--robot.port={controller.port}",
            f"--robot.id={controller.robot_id}",
            f"--robot.cameras={controller.camera_arg}",
            "--task=sort the pills",
            f"--fps={controller.fps}",
            "--duration=12",
        ]
    ]


def test_run_policy_adds_temporal_ensemble_when_configured(monkeypatch: Any) -> None:
    controller = RobotController(mock=True)
    controller.mock = False
    controller.temporal_ensemble_coeff = 0.01

    commands: list[list[str]] = []
    monkeypatch.setattr(
        "nursearm.robot.controller.subprocess.run",
        lambda command, check: commands.append(command),
    )

    controller.run_policy("/tmp/checkpoint", task="handover", duration_s=1)

    assert "--policy.temporal_ensemble_coeff=0.01" in commands[0]
