"""Phase 2: collaborative spreadsheet with awareness (cursors/selections)."""
from playwright.sync_api import expect

from tests.conftest import ARTIFACTS


def _open(browser, server, room, user):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{server.base_url}/?room={room}&user={user}")
    expect(page.locator("#status")).to_have_text("synced", timeout=15_000)
    expect(page.locator("#grid-body tr")).to_have_count(5, timeout=10_000)
    return page


def _cell(page, row, col):
    return page.locator(f'input[data-row="{row}"][data-col="{col}"]')


def test_cell_edits_sync_both_ways(server, browser):
    a = _open(browser, server, "grid1", "alice")
    b = _open(browser, server, "grid1", "bob")

    _cell(a, 0, "text").fill("hello from alice")
    expect(_cell(b, 0, "text")).to_have_value("hello from alice", timeout=10_000)

    _cell(b, 0, "speaker").fill("SPK_01")
    expect(_cell(a, 0, "speaker")).to_have_value("SPK_01", timeout=10_000)

    # concurrent edits to different cells must both survive
    _cell(a, 1, "start").fill("00:00:01.000")
    _cell(b, 2, "noise").fill("babble")
    expect(_cell(b, 1, "start")).to_have_value("00:00:01.000", timeout=10_000)
    expect(_cell(a, 2, "noise")).to_have_value("babble", timeout=10_000)
    # earlier edits untouched
    expect(_cell(a, 0, "text")).to_have_value("hello from alice")
    expect(_cell(b, 0, "speaker")).to_have_value("SPK_01")


def test_add_and_delete_rows_sync(server, browser):
    a = _open(browser, server, "grid2", "alice")
    b = _open(browser, server, "grid2", "bob")

    a.click("#add-row")
    expect(b.locator("#grid-body tr")).to_have_count(6, timeout=10_000)

    b.locator("#grid-body tr").nth(5).locator("button").click()
    expect(a.locator("#grid-body tr")).to_have_count(5, timeout=10_000)


def test_selection_awareness_visible_remotely(server, browser):
    a = _open(browser, server, "grid3", "alice")
    b = _open(browser, server, "grid3", "bob")

    expect(a.locator("#users")).to_have_text("alice, bob", timeout=10_000)

    _cell(a, 2, "speaker").focus()
    remote = _cell(b, 2, "speaker")
    expect(remote).to_have_attribute("data-remote-user", "alice", timeout=10_000)

    _cell(b, 3, "text").focus()
    expect(_cell(a, 3, "text")).to_have_attribute("data-remote-user", "bob", timeout=10_000)

    a.screenshot(path=str(ARTIFACTS / "phase2_grid_alice.png"))
    b.screenshot(path=str(ARTIFACTS / "phase2_grid_bob.png"))
