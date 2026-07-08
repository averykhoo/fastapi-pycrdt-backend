"""Phase 6: audio upload/serving, hotkey timestamp stamping, row seeking."""
import io
import wave

import httpx
from playwright.sync_api import expect

from tests.conftest import ARTIFACTS
from tests.test_grid import _cell, _open


def _wav_bytes(seconds=2.5, rate=8000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _upload(server, doc_id):
    r = httpx.post(f"{server.base_url}/api/audio/{doc_id}",
                   files={"file": ("test.wav", _wav_bytes(), "audio/wav")})
    assert r.status_code == 200
    return r.json()


def test_audio_upload_and_serve(server):
    meta = _upload(server, "aud0")
    assert meta["size"] > 0

    r = httpx.get(f"{server.base_url}/api/audio/aud0")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert len(r.content) == meta["size"]


def test_audio_missing_404(server):
    assert httpx.get(f"{server.base_url}/api/audio/nope").status_code == 404


def test_stamp_hotkeys_and_row_seek(server, browser):
    _upload(server, "aud1")
    a = _open(browser, server, "aud1", "alice")

    a.wait_for_function("document.getElementById('player').readyState >= 1")
    a.evaluate("document.getElementById('player').currentTime = 1.5")

    _cell(a, 0, "text").click()
    a.keyboard.press("Alt+s")
    expect(_cell(a, 0, "start")).to_have_value("00:00:01.500")

    a.evaluate("document.getElementById('player').currentTime = 1.9")
    a.keyboard.press("Alt+e")
    expect(_cell(a, 0, "end")).to_have_value("00:00:01.900")

    # clicking a row number seeks the player to that row's start time
    _cell(a, 1, "start").fill("00:00:00.750")
    a.locator("#grid-body tr").nth(1).locator("td.rownum").click()
    assert abs(a.evaluate("document.getElementById('player').currentTime") - 0.75) < 0.05

    # Alt+G from a cell in the row does the same
    a.evaluate("document.getElementById('player').currentTime = 0")
    _cell(a, 0, "text").click()
    a.keyboard.press("Alt+g")
    assert abs(a.evaluate("document.getElementById('player').currentTime") - 1.5) < 0.05

    a.screenshot(path=str(ARTIFACTS / "phase6_audio.png"))
