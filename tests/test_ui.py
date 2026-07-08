"""Phase 0: the static frontend actually loads in a real browser."""
from tests.conftest import ARTIFACTS


def test_index_loads(server, page):
    page.goto(server.base_url)
    assert "collab spreadsheet" in page.title()
    page.screenshot(path=str(ARTIFACTS / "phase0_index.png"))
