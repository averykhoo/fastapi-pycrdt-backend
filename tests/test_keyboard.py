"""Phase 6: keyboard-first annotation flow."""
from playwright.sync_api import expect

from tests.test_grid import _cell, _open


def test_enter_moves_down_and_extends_grid(server, browser):
    a = _open(browser, server, "kb1", "alice")

    _cell(a, 3, "text").click()
    a.keyboard.type("row four")
    a.keyboard.press("Enter")
    expect(_cell(a, 4, "text")).to_be_focused()

    a.keyboard.type("row five")
    a.keyboard.press("Enter")  # last row: Enter grows the grid
    expect(a.locator("#grid-body tr")).to_have_count(6)
    expect(_cell(a, 5, "text")).to_be_focused()

    expect(_cell(a, 3, "text")).to_have_value("row four")
    expect(_cell(a, 4, "text")).to_have_value("row five")
