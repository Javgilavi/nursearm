"""Append-only, timestamped log of agent decisions and robot actions.

Writes newline-delimited JSON (JSONL) to ``data/audit/<session>.jsonl`` and also
fans events out to any subscribers (e.g. the web UI over a WebSocket).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Subscriber = Callable[[dict[str, Any]], None]


class AuditLog:
    def __init__(self, session_id: str | None = None, root: Path | None = None) -> None:
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        root = root or Path(__file__).resolve().parent.parent.parent / "data" / "audit"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"{self.session_id}.jsonl"
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        """Register a callback (e.g. push to the UI) invoked on every event."""
        self._subscribers.append(fn)

    def log(self, event: dict[str, Any]) -> dict[str, Any]:
        record = {"ts": datetime.now(UTC).isoformat(), "session": self.session_id, **event}
        line = json.dumps(record, default=str)
        with self._lock:
            with self.path.open("a") as f:
                f.write(line + "\n")
        logger.info("AUDIT %s", line)
        for fn in self._subscribers:
            try:
                fn(record)
            except Exception:  # a broken subscriber must never break logging
                logger.exception("audit subscriber failed")
        return record

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]
