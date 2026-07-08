"""Phase 1: two real browsers must converge through the FastAPI/pycrdt pipe.

Uses the minimal `simple.html` page (a single shared `Y.Map` text field)
rather than the full grid — this is a regression test for the raw sync pipe
independent of the grid UI built on top of it in later phases.
"""
from playwright.sync_api import Browser, Page, expect

from tests.conftest import ARTIFACTS


def _open(browser: Browser, url: str) -> Page:
    """Open `url` in a fresh browser context and wait for it to sync."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    expect(page.locator("#status")).to_have_text("synced", timeout=15_000)
    return page


def test_two_clients_converge(server, browser):
    url = f"{server.base_url}/simple.html?room=phase1"
    a = _open(browser, url)
    b = _open(browser, url)

    a.fill("#shared-text", "hello from A")
    expect(b.locator("#shared-text")).to_have_value("hello from A", timeout=10_000)

    b.fill("#shared-text", "and back from B")
    expect(a.locator("#shared-text")).to_have_value("and back from B", timeout=10_000)

    a.screenshot(path=str(ARTIFACTS / "phase1_client_a.png"))
    b.screenshot(path=str(ARTIFACTS / "phase1_client_b.png"))


def test_late_joiner_gets_existing_state(server, browser):
    url = f"{server.base_url}/simple.html?room=phase1-late"
    a = _open(browser, url)
    a.fill("#shared-text", "written before B joined")

    b = _open(browser, url)
    expect(b.locator("#shared-text")).to_have_value("written before B joined", timeout=10_000)
