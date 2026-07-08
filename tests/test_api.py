"""Phase 0: basic HTTP plumbing — health check and static file serving."""
import httpx


def test_health(server):
    r = httpx.get(f"{server.base_url}/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_static_index_served(server):
    r = httpx.get(server.base_url)
    assert r.status_code == 200
    assert "collab spreadsheet" in r.text
