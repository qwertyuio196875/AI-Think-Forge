"""静态托管下的 SPA 深链回退：刷新 /analysis?source=N 不能 404。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import create_app


def test_spa_deep_link_falls_back_to_index(
    tmp_path: Path, db_path: Path, monkeypatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><div id=\"app\">SPA</div>", encoding="utf-8"
    )
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND_DIST_DIR", dist)

    with TestClient(create_app(db_path=db_path, mount_frontend=True)) as client:
        deep = client.get("/analysis?source=1")
        assert deep.status_code == 200
        assert "SPA" in deep.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert asset.text == "console.log('ok')"

        missing_asset = client.get("/assets/no-such.js")
        assert missing_asset.status_code == 404

        missing_api = client.get("/api/no-such")
        assert missing_api.status_code == 404
        assert missing_api.headers["content-type"].startswith("application/json")

        api_root = client.get("/api")
        assert api_root.status_code == 404
        assert api_root.headers["content-type"].startswith("application/json")