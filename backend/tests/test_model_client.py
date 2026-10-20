"""TB-1 真实 OpenAI 兼容客户端（httpx 直连）。

用 `httpx.MockTransport` 在进程内脚本化应答（不开 socket、不联网）验证：
请求路径与信封、默认关闭思考模式、模型覆盖、错误透传、日志脱敏。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.providers.model_client import ModelCallError, ModelClient, ModelClientConfig
from app.providers.openai_client import HttpModelClientFactory, OpenAICompatibleClient


def _make_client(handler, **overrides: Any) -> OpenAICompatibleClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    params = {
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-flash",
        "api_key": "sk-x",
        "http_client": http,
    }
    params.update(overrides)
    return OpenAICompatibleClient(**params)


def test_implements_model_client_protocol() -> None:
    """真实客户端满足 TB-0 定义的 ModelClient Protocol。"""
    client = OpenAICompatibleClient(base_url="https://api.deepseek.com", model_name="deepseek-flash")

    assert isinstance(client, ModelClient)


def test_timeout_is_positive_by_default() -> None:
    """调用必须设超时（规格：模型 API 调用应设置超时）。"""
    client = OpenAICompatibleClient(base_url="https://api.deepseek.com", model_name="m")

    assert client.timeout_seconds > 0


def test_complete_posts_openai_path_with_thinking_disabled() -> None:
    """POST `<base>/chat/completions`，Body 含模型、消息，并显式关闭思考模式。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "你好"}}]}, request=request
        )

    result = _make_client(handler).complete([{"role": "user", "content": "hi"}])

    assert result == "你好"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["body"]["model"] == "deepseek-flash"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["body"]["thinking"] == {"type": "disabled"}
    # 前沿 JSON 可到 1.5k~2k tokens；1024 会截断成半截 JSON。
    assert captured["body"]["max_tokens"] == 4096
    assert captured["auth"] == "Bearer sk-x"


def test_complete_without_api_key_sends_no_authorization() -> None:
    """未配置密钥时不带 Authorization 头（本地兼容端点可能无鉴权）。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    _make_client(handler, api_key=None).complete([{"role": "user", "content": "hi"}])

    assert captured["auth"] is None


def test_complete_honours_model_override() -> None:
    """调用时可覆盖模型名（任务级切换 max 的落点）。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    _make_client(handler).complete([{"role": "user", "content": "hi"}], model="deepseek-v4-pro")

    assert captured["body"]["model"] == "deepseek-v4-pro"


def test_length_finish_reason_is_reported_as_truncation() -> None:
    """`finish_reason=length` 明确报「截断」，不让上层误判成 JSON 结构写错。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"frontier": [{"title": "半截'},
                        "finish_reason": "length",
                    }
                ]
            },
            request=request,
        )

    with pytest.raises(ModelCallError, match="长度上限"):
        _make_client(handler).complete([{"role": "user", "content": "hi"}])


def test_http_error_is_raised_not_swallowed() -> None:
    """服务端错误原样抛出，交由上层分类（不吞异常）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request", request=request)

    with pytest.raises(httpx.HTTPStatusError):
        _make_client(handler).complete([{"role": "user", "content": "hi"}])


def test_transport_error_is_raised_not_swallowed() -> None:
    """网络异常原样抛出。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        _make_client(handler).complete([{"role": "user", "content": "hi"}])


def test_error_log_redacts_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """日志脱敏：失败日志绝不出现完整密钥。"""
    secret = "sk-super-secret-key"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps(
            {"error": {"message": f"Your api key: {secret} is invalid", "type": "authentication_error"}}
        )
        return httpx.Response(401, text=body, request=request)

    client = _make_client(handler, api_key=secret)

    with (
        caplog.at_level(logging.WARNING, logger="app.providers.openai_client"),
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.complete([{"role": "user", "content": "hi"}])

    assert secret not in caplog.text
    assert "***" in caplog.text


def test_network_error_log_redacts_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """网络异常日志同样脱敏。"""
    secret = "sk-net-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed while using {secret}")

    with (
        caplog.at_level(logging.WARNING, logger="app.providers.openai_client"),
        pytest.raises(httpx.ConnectError),
    ):
        _make_client(handler, api_key=secret).complete([{"role": "user", "content": "hi"}])

    assert secret not in caplog.text


def test_default_factory_builds_openai_compatible_client() -> None:
    """默认工厂按 provider 配置构造 httpx 直连客户端。"""
    client = HttpModelClientFactory().create(
        ModelClientConfig(base_url="https://api.deepseek.com", model_name="deepseek-flash"),
        api_key="sk-1",
    )

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model_name == "deepseek-flash"