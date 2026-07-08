"""Phase 3: persistence across restarts, document registry, JSON export."""
import time

import httpx
from playwright.sync_api import expect

from tests.test_grid import _cell, _open


def _wait_export(server, doc_id, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = httpx.get(f"{server.base_url}/api/export/{doc_id}")
        if r.status_code == 200:
            last = r.json()
            if predicate(last["rows"]):
                return last
        time.sleep(0.2)
    raise AssertionError(f"export never matched, last response: {last}")


def test_export_returns_structured_rows(server, browser):
    a = _open(browser, server, "exp1", "alice")
    _cell(a, 0, "start").fill("00:00:01.000")
    _cell(a, 0, "text").fill("first utterance")
    _cell(a, 0, "speaker").fill("SPK_01")
    _cell(a, 1, "text").fill("second utterance")

    data = _wait_export(server, "exp1", lambda rows: rows[0]["text"] == "first utterance")
    assert data["doc_id"] == "exp1"
    assert len(data["rows"]) == 5
    assert data["rows"][0] == {
        "start": "00:00:01.000", "end": "", "speaker": "SPK_01",
        "text": "first utterance", "noise": "",
    }
    assert data["rows"][1]["text"] == "second utterance"


def test_documents_registry(server, browser):
    _open(browser, server, "reg1", "alice")
    docs = httpx.get(f"{server.base_url}/api/documents").json()
    assert "reg1" in [d["doc_id"] for d in docs]


def test_export_unknown_document_404(server):
    r = httpx.get(f"{server.base_url}/api/export/nope")
    assert r.status_code == 404


def test_state_survives_restart(server, browser):
    a = _open(browser, server, "persist1", "alice")
    _cell(a, 0, "text").fill("survives restarts")
    _cell(a, 3, "noise").fill("clean")
    _wait_export(server, "persist1", lambda rows: rows[0]["text"] == "survives restarts")
    time.sleep(1.0)  # let the ystore commit the last updates
    a.context.close()

    server.stop()
    server.start()

    b = _open(browser, server, "persist1", "bob")
    expect(_cell(b, 0, "text")).to_have_value("survives restarts", timeout=10_000)
    expect(_cell(b, 3, "noise")).to_have_value("clean")
    # replayed history must not duplicate the seeded rows
    expect(b.locator("#grid-body tr")).to_have_count(5)
