"""TB-1 模型配置 CRUD 与密钥处理。

断言密钥只进密钥库、绝不落 SQLite、绝不回传；编辑不传密钥则保留原凭据；
删除同时清除凭据；设为默认是唯一默认。
"""

from __future__ import annotations

from pathlib import Path

from fakes import InMemoryKeyStore
from fastapi.testclient import TestClient

from app.db.database import connect
from app.main import create_app

PROVIDER_FIELDS = {"id", "name", "base_url", "model_name", "is_default", "kind", "has_key"}


def test_create_provider_returns_row_without_secret(client: TestClient) -> None:
    """新建返回 201 与固定字段集，响应体不含密钥。"""
    response = client.post(
        "/api/providers",
        json={
            "name": "百炼自配",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen-plus",
            "kind": "plus",
            "api_key": "sk-secret-canary-123",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == PROVIDER_FIELDS
    assert body["name"] == "百炼自配"
    assert body["kind"] == "plus"
    assert body["is_default"] is False
    assert body["has_key"] is True
    assert "sk-secret-canary-123" not in response.text


def test_create_without_api_key_stores_no_credential(
    client: TestClient, key_store: InMemoryKeyStore
) -> None:
    """未传密钥时 has_key 为 False，密钥库无该条。"""
    body = client.post(
        "/api/providers",
        json={"name": "无密钥", "base_url": "https://example.test", "model_name": "m"},
    ).json()

    assert body["has_key"] is False
    assert body["kind"] is None
    assert key_store.get_key("无密钥") is None


def test_create_duplicate_name_returns_conflict(client: TestClient) -> None:
    """凭据以 name 为键，重名被拒绝（409）。"""
    payload = {"name": "重名", "base_url": "https://example.test", "model_name": "m"}
    assert client.post("/api/providers", json=payload).status_code == 201

    assert client.post("/api/providers", json=payload).status_code == 409


def test_list_contains_has_key_without_secret(client: TestClient, key_store: InMemoryKeyStore) -> None:
    """列表中已配置密钥的 provider 标 has_key，响应全文无线索。"""
    client.post(
        "/api/providers",
        json={
            "name": "带密钥",
            "base_url": "https://example.test",
            "model_name": "m",
            "api_key": "sk-list-canary",
        },
    )

    response = client.get("/api/providers")
    items = {item["name"]: item for item in response.json()["items"]}

    assert items["带密钥"]["has_key"] is True
    assert items["DeepSeek 主流程"]["has_key"] is False
    assert "sk-list-canary" not in response.text


def test_edit_without_api_key_keeps_credential(
    client: TestClient, key_store: InMemoryKeyStore
) -> None:
    """编辑只改非敏感字段、不传 api_key 时，原凭据保留。"""
    created = client.post(
        "/api/providers",
        json={
            "name": "保留密钥",
            "base_url": "https://old.test",
            "model_name": "old-model",
            "api_key": "sk-keep-me",
        },
    ).json()

    response = client.put(
        f"/api/providers/{created['id']}",
        json={"base_url": "https://new.test", "model_name": "new-model"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base_url"] == "https://new.test"
    assert body["model_name"] == "new-model"
    assert body["has_key"] is True
    assert key_store.get_key("保留密钥") == "sk-keep-me"


def test_edit_with_api_key_replaces_credential(
    client: TestClient, key_store: InMemoryKeyStore
) -> None:
    """传了 api_key 才更新凭据。"""
    created = client.post(
        "/api/providers",
        json={
            "name": "换密钥",
            "base_url": "https://example.test",
            "model_name": "m",
            "api_key": "sk-old",
        },
    ).json()

    client.put(f"/api/providers/{created['id']}", json={"api_key": "sk-new"})

    assert key_store.get_key("换密钥") == "sk-new"


def test_edit_updates_kind_role_label(client: TestClient) -> None:
    """档位是角色标签，可编辑；落库为纯字符串值而非枚举 repr。"""
    response = client.put("/api/providers/1", json={"kind": "max"})

    assert response.status_code == 200
    assert response.json()["kind"] == "max"


def test_rename_migrates_credential(client: TestClient, key_store: InMemoryKeyStore) -> None:
    """凭据以 name 为键：改名时迁移凭据，避免遗留孤儿密钥。"""
    created = client.post(
        "/api/providers",
        json={
            "name": "旧名",
            "base_url": "https://example.test",
            "model_name": "m",
            "api_key": "sk-migrate",
        },
    ).json()

    response = client.put(f"/api/providers/{created['id']}", json={"name": "新名"})

    assert response.status_code == 200
    assert response.json()["has_key"] is True
    assert key_store.get_key("新名") == "sk-migrate"
    assert key_store.get_key("旧名") is None


def test_set_default_is_exclusive(client: TestClient) -> None:
    """设为默认后仅剩一条 is_default。"""
    items = client.get("/api/providers").json()["items"]
    flagship = next(item for item in items if item["name"] == "DeepSeek 旗舰")

    response = client.post(f"/api/providers/{flagship['id']}/default")

    assert response.status_code == 200
    assert response.json()["is_default"] is True

    after = client.get("/api/providers").json()["items"]
    defaults = [item for item in after if item["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "DeepSeek 旗舰"


def test_delete_removes_row_and_credential(
    client: TestClient, key_store: InMemoryKeyStore
) -> None:
    """删除同时清除凭据库条目。"""
    created = client.post(
        "/api/providers",
        json={
            "name": "待删除",
            "base_url": "https://example.test",
            "model_name": "m",
            "api_key": "sk-delete-me",
        },
    ).json()

    assert client.delete(f"/api/providers/{created['id']}").status_code == 204
    remaining = {item["name"] for item in client.get("/api/providers").json()["items"]}
    assert "待删除" not in remaining
    assert key_store.get_key("待删除") is None


def test_missing_provider_operations_return_404(client: TestClient) -> None:
    """不存在的 provider：编辑 / 删除 / 设默认 / 测试均 404。"""
    assert client.put("/api/providers/9999", json={"model_name": "m"}).status_code == 404
    assert client.delete("/api/providers/9999").status_code == 404
    assert client.post("/api/providers/9999/default").status_code == 404
    assert client.post("/api/providers/9999/test").status_code == 404


def test_api_key_never_written_to_sqlite_bytes(client: TestClient, db_path: Path) -> None:
    """密钥只进凭据库：建库后直接查 SQLite 文件字节，无明文密钥。"""
    secret = "sk-disk-canary-7c1f"
    client.post(
        "/api/providers",
        json={
            "name": "落库检查",
            "base_url": "https://example.test",
            "model_name": "m",
            "api_key": secret,
        },
    )

    leftovers = [
        path
        for path in Path(db_path).parent.glob(f"{Path(db_path).name}*")
        if path.is_file()
    ]
    assert leftovers, "应存在 SQLite 文件"
    for path in leftovers:
        assert secret.encode("utf-8") not in path.read_bytes(), f"{path.name} 出现明文密钥"


def test_providers_table_has_no_secret_column(db_path: Path) -> None:
    """providers 表列集合固定，不含任何密钥列。"""
    with TestClient(create_app(db_path=db_path)):
        pass

    with connect(db_path) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(providers)")}

    assert columns == {"id", "name", "base_url", "model_name", "is_default", "kind"}