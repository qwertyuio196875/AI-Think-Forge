"""TB-1 schema 与默认播种。

覆盖：`providers` / `settings` 两张表存在；首次启动按角色档位播种 3 条
DeepSeek provider；默认值为当前有效模型 ID；播种幂等（重复启动不重复插入，
用户清空后也不再回填）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.db.database import connect
from app.main import create_app


def test_providers_and_settings_tables_exist(db_path: Path) -> None:
    """启动 lifespan 建表后，providers 与 settings 两表均存在。"""
    with TestClient(create_app(db_path=db_path)):
        pass

    with connect(db_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert {"providers", "settings"} <= tables


def test_default_providers_seeded_on_first_start(client: TestClient) -> None:
    """首次启动播种 3 条 provider，顺序固定。"""
    body = client.get("/api/providers").json()

    assert body["total"] == 3
    assert [item["name"] for item in body["items"]] == [
        "DeepSeek 主流程",
        "DeepSeek 总结",
        "DeepSeek 旗舰",
    ]


def test_default_provider_rows_match_role_mapping(client: TestClient) -> None:
    """档位作为角色标签落地：主流程 plus 且默认、总结 turbo、旗舰 max。"""
    items = {item["name"]: item for item in client.get("/api/providers").json()["items"]}

    main = items["DeepSeek 主流程"]
    assert main["base_url"] == "https://api.deepseek.com"
    assert main["model_name"] == "deepseek-flash"
    assert main["kind"] == "plus"
    assert main["is_default"] is True

    summary = items["DeepSeek 总结"]
    assert summary["base_url"] == "https://api.deepseek.com"
    assert summary["model_name"] == "deepseek-flash"
    assert summary["kind"] == "turbo"
    assert summary["is_default"] is False

    flagship = items["DeepSeek 旗舰"]
    assert flagship["model_name"] == "deepseek-v4-pro"
    assert flagship["kind"] == "max"
    assert flagship["is_default"] is False


def test_seed_uses_no_retired_model_ids(client: TestClient) -> None:
    """默认值不得写入任何已停用 / 过期模型 ID。"""
    models = {item["model_name"] for item in client.get("/api/providers").json()["items"]}

    assert models <= {"deepseek-flash", "deepseek-v4-pro"}
    assert "deepseek-chat" not in models
    assert "deepseek-reasoner" not in models
    assert "qwen-turbo" not in models


def test_seeding_is_idempotent_across_restarts(db_path: Path) -> None:
    """重复启动不重复插入（仍为 3 条）。"""
    with TestClient(create_app(db_path=db_path)) as first:
        assert first.get("/api/providers").json()["total"] == 3

    with TestClient(create_app(db_path=db_path)) as second:
        assert second.get("/api/providers").json()["total"] == 3


def test_seed_does_not_backfill_after_providers_deleted(db_path: Path) -> None:
    """用户清空 provider 后重启不回填，尊重用户删除。"""
    with TestClient(create_app(db_path=db_path)) as client:
        for item in client.get("/api/providers").json()["items"]:
            assert client.delete(f"/api/providers/{item['id']}").status_code == 204

    with TestClient(create_app(db_path=db_path)) as restarted:
        assert restarted.get("/api/providers").json()["total"] == 0