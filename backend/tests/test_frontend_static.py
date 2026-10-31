"""Same-origin serving of a built frontend (KIROTHON_FRONTEND_DIST): opt-in and never shadows the API."""
from fastapi.testclient import TestClient

from app.main import app


def test_built_frontend_is_served_without_shadowing_api(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    monkeypatch.setenv("KIROTHON_FRONTEND_DIST", str(dist))
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        page = client.get("/")
        assert page.status_code == 200 and "<title>app</title>" in page.text
        assert client.get("/some/deep/link").text == page.text            # single page fallback
        asset = client.get("/assets/index-abc.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/api/team/does-not-exist").status_code == 404   # API 404 stays JSON, not the page
        assert "<title>" not in client.get("/api/team/does-not-exist").text
        assert "no" != client.get("/../secret.txt").text
        assert client.get("/api/team/meta").status_code == 200


def test_without_build_nothing_is_served(monkeypatch):
    monkeypatch.delenv("KIROTHON_FRONTEND_DIST", raising=False)
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200
