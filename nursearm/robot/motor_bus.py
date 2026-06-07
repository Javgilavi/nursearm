"""Lightweight Feetech STS3215 motor bus — no torch, no lerobot dependency.

Uses scservo_sdk directly. Covers the six SO-101 motors:
  shoulder_pan(1)  shoulder_lift(2)  elbow_flex(3)
  wrist_flex(4)    wrist_roll(5)     gripper(6)

Positions are returned/accepted as floats in the range [-100, 100]
(gripper: 0 = open, 100 = closed).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# STS3215 control table addresses
_ADDR_TORQUE_ENABLE = 40
_ADDR_GOAL_POSITION = 42
_ADDR_GOAL_POSITION_LEN = 2
_ADDR_PRESENT_POSITION = 56
_ADDR_PRESENT_POSITION_LEN = 2
_BAUD = 1_000_000
_RESOLUTION = 4096  # 12-bit encoder

MOTOR_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
MOTOR_IDS = {name: i + 1 for i, name in enumerate(MOTOR_NAMES)}


@dataclass
class _Cal:
    homing_offset: int
    range_min: int
    range_max: int


_DEFAULT_CALIBRATION: dict[str, _Cal] = {
    "shoulder_pan":  _Cal(-1918, 709, 3188),
    "shoulder_lift": _Cal(-774, 793, 3210),
    "elbow_flex":    _Cal(-2046, 666, 3123),
    "wrist_flex":    _Cal(1090, 755, 3258),
    "wrist_roll":    _Cal(1874, 0, 4095),
    "gripper":       _Cal(-1780, 1698, 3249),
}

_CALIBRATION_PATH = (
    Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/Follower.json"
)


def _load_calibration() -> dict[str, _Cal]:
    if _CALIBRATION_PATH.exists():
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return {
                name: _Cal(
                    homing_offset=info["homing_offset"],
                    range_min=info["range_min"],
                    range_max=info["range_max"],
                )
                for name, info in data.items()
            }
        except Exception as exc:
            logger.warning("Could not load calibration file: %s — using defaults.", exc)
    return _DEFAULT_CALIBRATION


def _raw_to_normalized(raw: int, cal: _Cal, is_gripper: bool = False) -> float:
    """Convert raw encoder value (0-4095) to normalized position.

    For arm joints: -100 to +100 (maps range_min→-100, range_max→+100).
    For gripper: 0 to 100 (range_min→0, range_max→100).
    """
    span = cal.range_max - cal.range_min
    if span == 0:
        return 0.0
    frac = (raw - cal.range_min) / span  # 0.0 to 1.0
    frac = max(0.0, min(1.0, frac))
    if is_gripper:
        return round(frac * 100.0, 2)
    return round(frac * 200.0 - 100.0, 2)


def _normalized_to_raw(norm: float, cal: _Cal, is_gripper: bool = False) -> int:
    if is_gripper:
        frac = max(0.0, min(1.0, norm / 100.0))
    else:
        frac = max(0.0, min(1.0, (norm + 100.0) / 200.0))
    raw = int(cal.range_min + frac * (cal.range_max - cal.range_min))
    return max(0, min(_RESOLUTION - 1, raw))


class FeetechBus:
    """Minimal read/write bus for STS3215 motors via scservo_sdk."""

    def __init__(self, port: str) -> None:
        import scservo_sdk as scs  # noqa: PLC0415

        self._scs = scs
        self._calibration = _load_calibration()
        self._port_handler = scs.PortHandler(port)
        self._packet_handler = scs.PacketHandler(0)
        self._connected = False

    def connect(self) -> None:
        if not self._port_handler.openPort():
            raise RuntimeError(f"Cannot open port: {self._port_handler.port_name}")
        if not self._port_handler.setBaudRate(_BAUD):
            raise RuntimeError("Cannot set baud rate to 1 Mbps")
        self._connected = True
        logger.info("FeetechBus connected on %s @ %d baud.", self._port_handler.port_name, _BAUD)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_positions(self) -> dict[str, float]:
        """Read Present_Position from all 6 motors. Returns normalized values."""
        scs = self._scs
        result: dict[str, float] = {}
        for name, motor_id in MOTOR_IDS.items():
            raw, comm, err = self._packet_handler.read2ByteTxRx(
                self._port_handler, motor_id, _ADDR_PRESENT_POSITION
            )
            if comm != scs.COMM_SUCCESS or err != 0:
                logger.debug("read_positions: motor %s comm=%s err=%s", name, comm, err)
                result[name] = float("nan")
                continue
            # Feetech STS3215: high bit is sign for velocity/load but not position.
            # Position is always 0-4095.
            raw = raw & 0x0FFF
            cal = self._calibration.get(name, _DEFAULT_CALIBRATION[name])
            result[name] = _raw_to_normalized(raw, cal, is_gripper=(name == "gripper"))
        return result

    def write_positions(self, positions: dict[str, float]) -> None:
        """Send Goal_Position for each motor in `positions` dict."""
        scs = self._scs
        for name, norm in positions.items():
            if name not in MOTOR_IDS:
                continue
            motor_id = MOTOR_IDS[name]
            cal = self._calibration.get(name, _DEFAULT_CALIBRATION[name])
            raw = _normalized_to_raw(norm, cal, is_gripper=(name == "gripper"))
            comm, err = self._packet_handler.write2ByteTxRx(
                self._port_handler, motor_id, _ADDR_GOAL_POSITION, raw
            )
            if comm != scs.COMM_SUCCESS or err != 0:
                logger.warning("write_positions: motor %s comm=%s err=%s", name, comm, err)

    def set_torque(self, enabled: bool) -> None:
        val = 1 if enabled else 0
        for motor_id in MOTOR_IDS.values():
            self._packet_handler.write1ByteTxRx(
                self._port_handler, motor_id, _ADDR_TORQUE_ENABLE, val
            )

    def disconnect(self) -> None:
        if self._connected:
            self.set_torque(False)
            self._port_handler.closePort()
            self._connected = False
            logger.info("FeetechBus disconnected.")
