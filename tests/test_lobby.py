"""Phase 6: lobby page and persisted annotator identity."""
from playwright.sync_api import expect

from tests.test_grid import _open


def test_lobby_lists_documents_and_opens_them(server, browser):
    _open(browser, server, "lob1", "alice")  # registers the document

    page = browser.new_page()
    page.goto(server.base_url)
    link = page.locator("#doc-list a", has_text="lob1")
    expect(link).to_be_visible(timeout=10_000)
    link.click()
    expect(page.locator("#status")).to_have_text("synced", timeout=15_000)


def test_lobby_creates_new_document(server, browser):
    page = browser.new_page()
    page.goto(server.base_url)
    page.fill("#new-doc-name", "fresh1")
    page.click("#new-doc button")
    expect(page.locator("#status")).to_have_text("synced", timeout=15_000)


def test_annotator_name_persists_across_reloads(server, browser):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{server.base_url}/?room=nm1")  # no ?user= → anonymous name
    expect(page.locator("#status")).to_have_text("synced", timeout=15_000)

    page.fill("#username", "carol")
    page.keyboard.press("Tab")  # blur commits the change
    expect(page.locator("#users")).to_have_text("carol", timeout=10_000)

    page.goto(f"{server.base_url}/?room=nm1")
    expect(page.locator("#username")).to_have_value("carol", timeout=15_000)
    expect(page.locator("#users")).to_have_text("carol", timeout=10_000)
