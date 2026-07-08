"""Phase 5: A/B harness — sticky assignment, variant-gated feature, results."""
import httpx
from playwright.sync_api import expect

from tests.conftest import ARTIFACTS
from tests.test_grid import _cell, _open


def _create_experiment(server):
    r = httpx.post(f"{server.base_url}/api/experiments",
                   json={"name": "ai-suggest", "variants": ["control", "ai"]})
    assert r.status_code == 200


def _variant(server, user):
    return httpx.get(f"{server.base_url}/api/assignments/{user}").json()["ai-suggest"]


def _users_of_each_variant(server):
    by_variant = {}
    for i in range(50):
        user = f"annotator{i}"
        by_variant.setdefault(_variant(server, user), user)
        if len(by_variant) == 2:
            return by_variant["ai"], by_variant["control"]
    raise AssertionError(f"assignment never produced both variants: {by_variant}")


def test_assignments_sticky_and_cover_variants(server):
    _create_experiment(server)
    first = {f"user{i}": _variant(server, f"user{i}") for i in range(12)}
    assert set(first.values()) == {"control", "ai"}
    for user, variant in first.items():
        assert _variant(server, user) == variant  # sticky on re-ask


def test_feature_gating_and_results_pipeline(server, browser):
    _create_experiment(server)
    ai_user, control_user = _users_of_each_variant(server)

    a = _open(browser, server, "ab1", ai_user)
    expect(a.locator("button.ai-suggest")).to_have_count(5)
    a.locator("#grid-body tr").nth(0).locator("button.ai-suggest").click()
    expect(_cell(a, 0, "text")).to_have_value("AI suggestion for row 1")
    _cell(a, 1, "text").click()
    a.keyboard.type("manual line", delay=50)
    a.screenshot(path=str(ARTIFACTS / "phase5_ai_variant.png"))

    b = _open(browser, server, "ab1", control_user)
    expect(b.locator("button.ai-suggest")).to_have_count(0)
    _cell(b, 2, "text").click()
    b.keyboard.type("control types too", delay=50)

    a.wait_for_timeout(1500)  # let both clients flush activity batches
    results = httpx.get(f"{server.base_url}/api/experiments/ai-suggest/results").json()
    by_variant = {v["variant"]: v for v in results["variants"]}

    assert by_variant["ai"]["users"] >= 1
    assert by_variant["control"]["users"] >= 1
    assert by_variant["ai"]["edits"] >= 2  # suggestion click + typing
    assert by_variant["control"]["edits"] >= 1
    assert by_variant["ai"]["active_seconds"] > 0
    assert by_variant["control"]["edits_per_active_minute"] > 0


def test_results_unknown_experiment_404(server):
    r = httpx.get(f"{server.base_url}/api/experiments/nope/results")
    assert r.status_code == 404
