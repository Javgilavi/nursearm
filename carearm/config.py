"""Tiny config loader. Reads ``config/robot.yaml`` and ``config/skills.yaml`` and
the ``.env`` file. No magic — just a typed accessor so the rest of the code never
hard-codes a serial port or an API key.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


@lru_cache
def robot_config() -> dict[str, Any]:
    return _load(CONFIG_DIR / "robot.yaml")


@lru_cache
def skills_config() -> dict[str, Any]:
    return _load(CONFIG_DIR / "skills.yaml")


def env(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {key} (set it in .env)")
    return value


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f) or {}
