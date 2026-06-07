import asyncio

from nursearm.interface import server


def test_openclaw_status_is_offline_before_first_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(server, "_openclaw_last_seen", None)

    assert server._openclaw_status() == {
        "active": False,
        "last_seen_seconds_ago": None,
    }


def test_openclaw_status_tracks_recent_and_stale_heartbeats(monkeypatch) -> None:
    monkeypatch.setattr(server, "_openclaw_last_seen", 100.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: 108.0)

    assert server._openclaw_status() == {
        "active": True,
        "last_seen_seconds_ago": 8.0,
    }

    monkeypatch.setattr(server.time, "monotonic", lambda: 109.0)
    assert server._openclaw_status() == {
        "active": False,
        "last_seen_seconds_ago": 9.0,
    }


def test_openclaw_heartbeat_records_last_seen(monkeypatch) -> None:
    monkeypatch.setattr(server, "_openclaw_last_seen", None)
    monkeypatch.setattr(server.time, "monotonic", lambda: 321.0)

    assert asyncio.run(server.openclaw_heartbeat()) == {"ok": True}
    assert server._openclaw_last_seen == 321.0
