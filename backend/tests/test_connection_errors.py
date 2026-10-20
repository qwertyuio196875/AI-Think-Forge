"""TB-1 配置错误分类与连接测试。

两层：
1. 纯函数（`classify_status` / `classify_exception` / `parse_error_body`）独立单测，
   依据 03-deepseek-facts.md §5 的「HTTP 状态码 + error.type」真值表；
   不使用 `error.code`（DeepSeek 恒为 invalid_request_error）。
2. 连接测试经 API 接缝驱动，注入脚本化模型客户端工厂；成功一例 + 三类失败各一例。
"""

from __future__ import annotations

import httpx
import pytest
from fakes import ScriptedModelClient, ScriptedModelClientFactory

from app.api.deps import get_model_client_factory
from app.providers.errors import (
    ConnectionCategory,
    classify_exception,
    classify_status,
    parse_error_body,
)
from app.providers.model_client import ModelClientConfig, chat_completions_url

TEST_URL = "https://api.deepseek.com/chat/completions"


# --------------------------------------------------------------------------- #
# 纯函数：错误分类真值表
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status_code", "error_type", "message", "expected"),
    [
        (None, None, "connection refused", ConnectionCategory.network_error),
        (401, "authentication_error", "Authentication Fails", ConnectionCategory.auth_error),
        (401, None, "Authentication Fails (governor)", ConnectionCategory.auth_error),
        (400, "invalid_request_error", "Model Not Exist", ConnectionCategory.model_error),
        (400, "invalid_request_error", "unknown model: foo", ConnectionCategory.model_error),
        (400, "invalid_request_error", "max_tokens is out of range", ConnectionCategory.request_error),
        (422, "invalid_request_error", "invalid parameter", ConnectionCategory.request_error),
        (402, None, "insufficient balance", ConnectionCategory.insufficient_balance),
        (429, None, "rate limited", ConnectionCategory.rate_limited),
        (500, None, "internal error", ConnectionCategory.server_error),
        (503, None, "service unavailable", ConnectionCategory.server_error),
    ],
)
def test_classify_status_truth_table(
    status_code: int | None,
    error_type: str | None,
    message: str,
    expected: ConnectionCategory,
) -> None:
    """状态码 + error.type 决定分类；error.code 不参与分支。"""
    assert classify_status(status_code, error_type, message) is expected


def test_parse_error_body_handles_json_envelope() -> None:
    """标准错误信封取 error.type 与 error.message。"""
    body = '{"error":{"message":"Model Not Exist","type":"invalid_request_error","code":"invalid_request_error"}}'

    error_type, message = parse_error_body(body)

    assert error_type == "invalid_request_error"
    assert message == "Model Not Exist"


def test_parse_error_body_handles_plain_text() -> None:
    """GET /models 的 401 是纯文本，解析必须防御性回退。"""
    error_type, message = parse_error_body("Authentication Fails (governor)")

    assert error_type is None
    assert message == "Authentication Fails (governor)"


def test_parse_error_body_handles_empty_body() -> None:
    """空响应体不抛错。"""
    assert parse_error_body("") == (None, "")
    assert parse_error_body("   ") == (None, "")


def test_network_exception_maps_to_network_error() -> None:
    """httpx 连接异常（无状态码）归为 network_error。"""
    category, _ = classify_exception(httpx.ConnectError("all connections failed"))

    assert category is ConnectionCategory.network_error


def test_timeout_exception_maps_to_network_error() -> None:
    """读 / 连接超时同样是无状态码的网络类失败。"""
    category, _ = classify_exception(httpx.ReadTimeout("timed out"))

    assert category is ConnectionCategory.network_error


def test_http_status_exception_maps_by_status() -> None:
    """带响应体的 HTTPStatusError 按状态码 + error.type 分类。"""
    error = httpx.HTTPStatusError(
        "client error",
        request=httpx.Request("POST", TEST_URL),
        response=httpx.Response(
            401,
            text='{"error":{"message":"Authentication Fails","type":"authentication_error"}}',
            request=httpx.Request("POST", TEST_URL),
        ),
    )

    category, message = classify_exception(error)

    assert category is ConnectionCategory.auth_error
    assert message == "Authentication Fails"


def test_chat_completions_url_tolerates_v1_suffix() -> None:
    """base_url 容忍客户端自动补 /v1：只补 chat 路径，不删既有 /v1。"""
    assert chat_completions_url("https://api.deepseek.com") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert chat_completions_url("https://api.deepseek.com/") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert chat_completions_url("https://api.deepseek.com/v1") == (
        "https://api.deepseek.com/v1/chat/completions"
    )


# --------------------------------------------------------------------------- #
# 连接测试：API 接缝 + 脚本化模型客户端工厂
# --------------------------------------------------------------------------- #


def _status_error(status_code: int, text: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "error",
        request=httpx.Request("POST", TEST_URL),
        response=httpx.Response(
            status_code, text=text, request=httpx.Request("POST", TEST_URL)
        ),
    )


def _provider_id_of(client, name: str) -> int:
    items = client.get("/api/providers").json()["items"]
    return next(item["id"] for item in items if item["name"] == name)


def test_connection_test_success(client, app, key_store) -> None:
    """成功路径：返回 ok 分类与可读消息，且工厂收到配置与该 provider 的密钥。"""
    key_store.set_key("DeepSeek 主流程", "sk-probe")
    factory = ScriptedModelClientFactory(ScriptedModelClient(result="pong"))
    app.dependency_overrides[get_model_client_factory] = lambda: factory
    provider_id = _provider_id_of(client, "DeepSeek 主流程")

    response = client.post(f"/api/providers/{provider_id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["category"] == "ok"
    assert factory.last_config == ModelClientConfig(
        base_url="https://api.deepseek.com", model_name="deepseek-flash"
    )
    assert factory.last_api_key == "sk-probe"
    assert "sk-probe" not in response.text


def test_connection_test_network_error(client, app, key_store) -> None:
    """地址不可达：注入网络异常，返回 network_error。"""
    key_store.set_key("DeepSeek 主流程", "sk-probe")
    factory = ScriptedModelClientFactory(
        ScriptedModelClient(error=httpx.ConnectError("connection refused"))
    )
    app.dependency_overrides[get_model_client_factory] = lambda: factory
    provider_id = _provider_id_of(client, "DeepSeek 主流程")

    body = client.post(f"/api/providers/{provider_id}/test").json()

    assert body["ok"] is False
    assert body["category"] == "network_error"
    assert body["message"]


def test_connection_test_auth_error(client, app, key_store) -> None:
    """鉴权失败：401 → auth_error。"""
    key_store.set_key("DeepSeek 主流程", "sk-bad")
    factory = ScriptedModelClientFactory(
        ScriptedModelClient(
            error=_status_error(
                401,
                '{"error":{"message":"Authentication Fails","type":"authentication_error"}}',
            )
        )
    )
    app.dependency_overrides[get_model_client_factory] = lambda: factory
    provider_id = _provider_id_of(client, "DeepSeek 主流程")

    body = client.post(f"/api/providers/{provider_id}/test").json()

    assert body["ok"] is False
    assert body["category"] == "auth_error"


def test_connection_test_model_error(client, app, key_store) -> None:
    """模型名无效：400 + invalid_request_error → model_error。"""
    key_store.set_key("DeepSeek 旗舰", "sk-probe")
    factory = ScriptedModelClientFactory(
        ScriptedModelClient(
            error=_status_error(
                400,
                '{"error":{"message":"Model Not Exist","type":"invalid_request_error",'
                '"code":"invalid_request_error"}}',
            )
        )
    )
    app.dependency_overrides[get_model_client_factory] = lambda: factory
    provider_id = _provider_id_of(client, "DeepSeek 旗舰")

    body = client.post(f"/api/providers/{provider_id}/test").json()

    assert body["ok"] is False
    assert body["category"] == "model_error"


def test_connection_test_without_key_still_probes(client, app) -> None:
    """未配置密钥时不短路：仍用真实客户端探测（本测试注入 401 替身）。"""
    factory = ScriptedModelClientFactory(
        ScriptedModelClient(
            error=_status_error(401, '{"error":{"message":"no key","type":"authentication_error"}}')
        )
    )
    app.dependency_overrides[get_model_client_factory] = lambda: factory
    provider_id = _provider_id_of(client, "DeepSeek 总结")

    body = client.post(f"/api/providers/{provider_id}/test").json()

    assert body["category"] == "auth_error"
    assert factory.last_api_key is None


def test_default_client_factory_is_wired(app) -> None:
    """默认工厂挂在 app.state（真实实现由 TB-1 落地）。"""
    assert hasattr(app.state.model_client_factory, "create")