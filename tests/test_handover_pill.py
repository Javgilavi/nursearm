from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nursearm.skills.handover_pill import HandoverPill


class FakeRobot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Any, Any]] = []

    def run_policy(
        self,
        policy_path: str,
        task: str,
        duration_s: Any = None,
        camera_arg: Any = None,
        fps: Any = None,
    ) -> None:
        self.calls.append((policy_path, task, duration_s, camera_arg, fps))


class FakePerception:
    def observe(self) -> SimpleNamespace:
        return SimpleNamespace(frame=None)


def make_skill(policy_path: str | None) -> HandoverPill:
    return HandoverPill(
        name="handover_pill",
        description="handover",
        policy_path=policy_path,
        prompt="Hand over the {color} pill",
    )


def make_checkpoint(path: Path) -> None:
    (path / "config.json").write_text("{}")
    (path / "model.safetensors").write_bytes(b"weights")


def test_handover_rejects_unsupported_color() -> None:
    result = make_skill(None).run({"color": "red"}, FakeRobot(), FakePerception())
    assert not result.success
    assert "green" in result.note
    assert "black" in result.note


def test_handover_runs_selected_color(tmp_path: Path) -> None:
    make_checkpoint(tmp_path)
    robot = FakeRobot()
    result = make_skill(str(tmp_path)).run(
        {"color": "green", "duration_s": 20},
        robot,
        FakePerception(),
    )

    assert not result.success
    assert "not visually verified" in result.note
    assert robot.calls == [(str(tmp_path), "Give the green pill to the hand", 20, None, None)]


def test_color_specific_checkpoint_overrides_shared(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    black_checkpoint = tmp_path / "black"
    black_checkpoint.mkdir()
    make_checkpoint(black_checkpoint)
    monkeypatch.setenv("NURSEARM_HANDOVER_BLACK_POLICY", str(black_checkpoint))
    robot = FakeRobot()

    make_skill("/shared/checkpoint").run(
        {"color": "black"},
        robot,
        FakePerception(),
    )

    assert robot.calls[0][0] == str(black_checkpoint)


def test_handover_uses_observation_overrides(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    make_checkpoint(tmp_path)
    monkeypatch.setenv("NURSEARM_HANDOVER_CAMERA_ARG", "{wrist: {type: opencv}}")
    monkeypatch.setenv("NURSEARM_HANDOVER_FPS", "15")
    monkeypatch.setenv("NURSEARM_HANDOVER_TASK_TEMPLATE", "Give the {color} pill")
    robot = FakeRobot()

    make_skill(str(tmp_path)).run(
        {"color": "black"},
        robot,
        FakePerception(),
    )

    assert robot.calls == [
        (
            str(tmp_path),
            "Give the black pill",
            None,
            "{wrist: {type: opencv}}",
            15.0,
        )
    ]
