"""Phase 4: active-time telemetry — hidden/idle windows must not count."""
import httpx

from tests.test_grid import _cell, _open

GO_HIDDEN = """
Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
document.dispatchEvent(new Event('visibilitychange'));
"""
GO_VISIBLE = """
delete document.visibilityState;
document.dispatchEvent(new Event('visibilitychange'));
"""


def test_active_time_excludes_hidden_and_idle(server, browser):
    a = _open(browser, server, "act1", "alice")
    _cell(a, 0, "text").click()

    a.keyboard.type("transcribing away here", delay=100)  # ~2s of real input

    a.evaluate(GO_HIDDEN)  # tab hidden + idle: 4s that must not count
    a.wait_for_timeout(4000)
    a.evaluate(GO_VISIBLE)

    a.keyboard.type(" and back", delay=100)  # ~1s of input
    a.wait_for_timeout(1500)  # let the client flush its event queue

    stats = httpx.get(f"{server.base_url}/api/stats/act1").json()
    alice = next(u for u in stats["users"] if u["user"] == "alice")

    assert alice["events"] > 5
    span = alice["last_seen"] - alice["first_seen"]

    # ~3s of typing, never more than the un-hidden portion of the span
    assert 1.0 <= alice["active_seconds"] <= 6.0
    assert alice["active_seconds"] <= span - 3.0
    # open time excludes the hidden window (heartbeats stop while hidden)
    assert alice["open_seconds"] <= span - 2.5
    assert alice["open_seconds"] >= alice["active_seconds"] - 0.6


def test_activity_endpoint_stores_batches(server):
    batch = {
        "doc_id": "act2",
        "user": "bob",
        "events": [{"type": "input", "ts": 1_000_000.0}, {"type": "heartbeat", "ts": 1_002_000.0}],
    }
    r = httpx.post(f"{server.base_url}/api/activity", json=batch)
    assert r.status_code == 200
    assert r.json() == {"stored": 2}

    stats = httpx.get(f"{server.base_url}/api/stats/act2").json()
    bob = stats["users"][0]
    assert bob["user"] == "bob"
    assert bob["events"] == 2
