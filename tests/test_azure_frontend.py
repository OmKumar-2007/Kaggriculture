from fastapi.testclient import TestClient

from backend import main


def test_same_origin_frontend_routes_and_private_paths(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>FarmCraft</html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(main, "STATIC_FRONTEND_DIR", tmp_path)
    with TestClient(main.app) as client:
        assert "FarmCraft" in client.get("/").text
        assert "FarmCraft" in client.get("/admin").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/missing-route").status_code == 404
        assert client.get("/missing.css").status_code == 404
