"""#3 模型调用可选参数：按次指定输出上限与超时。

本工单是**纯扩展**：`ModelClient.complete()` 增加两个可选的关键字参数，
不传时一切照旧。因此本文件只钉三件事：

- 传了的新参数真的抵达网络请求（超时进 httpx 请求级 timeout、输出上限进 body）；
- 不传时沿用既有默认值（60 秒 / 4096），既有调用点一行不改也照旧；
- 「达到长度上限」仍是硬错误——放宽上限不等于允许静默截断。

观测点在客户端与 HTTP 传输层之间（`httpx.MockTransport`），与
`test_model_client.py` 既有做法一致：不联网、零花费。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fakes import InMemoryKeyStore

from app.providers.model_client import (
    ModelCallError,
    ModelClient,
    ModelClientConfig,
    UnconfiguredModelClient,
    complete_text,
)
from app.providers.openai_client import OpenAICompatibleClient
from app.providers.provider_backed_client import ProviderBackedModelClient


def _capturing_client(**overrides: Any) -> tuple[OpenAICompatibleClient, dict[str, Any]]:
    """构造真实客户端 + 记录本次 HTTP 请求的抓取器。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["timeout"] = dict(request.extensions.get("timeout") or {})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    params: dict[str, Any] = {
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-flash",
        "api_key": "sk-x",
        "http_client": httpx.Client(transport=httpx.MockTransport(handler)),
    }
    params.update(overrides)
    return OpenAICompatibleClient(**params), captured


def test_output_cap_can_be_set_per_call() -> None:
    """调用方可以只给这一次调用指定更高的输出上限（长章节不再被 4096 卡住）。"""
    client, captured = _capturing_client()

    client.complete([{"role": "user", "content": "hi"}], max_tokens=8192)

    assert captured["body"]["max_tokens"] == 8192


def test_timeout_can_be_set_per_call() -> None:
    """调用方可以按次指定超时：短调用 60 秒、长章节 180 秒，不必重建客户端。"""
    client, captured = _capturing_client()

    client.complete([{"role": "user", "content": "hi"}], timeout=180.0)

    assert captured["timeout"]["read"] == 180.0
    assert captured["timeout"]["connect"] == 180.0


def test_short_timeout_is_not_lost_to_the_client_default() -> None:
    """调短也必须生效：共用 http 客户端时，构造期 60 秒默认值不能盖掉本次 5 秒。"""
    client, captured = _capturing_client()

    client.complete([{"role": "user", "content": "hi"}], timeout=5.0)

    assert captured["timeout"]["read"] == 5.0


def test_defaults_are_kept_when_no_new_parameter_is_given() -> None:
    """不传新参数时行为与超时完全不变：仍是 60 秒 / 4096。"""
    client, captured = _capturing_client()

    client.complete([{"role": "user", "content": "hi"}])

    assert captured["timeout"]["read"] == 60.0
    assert captured["body"]["max_tokens"] == 4096


def test_length_finish_reason_still_fails_with_a_raised_cap() -> None:
    """放宽输出上限不等于允许静默截断：终止原因为「长度上限」仍抛硬错误。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "半篇正"}, "finish_reason": "length"}
                ]
            },
            request=request,
        )

    client = OpenAICompatibleClient(
        base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ModelCallError, match="长度上限"):
        client.complete(
            [{"role": "user", "content": "hi"}], max_tokens=8192, timeout=180.0
        )


class _RecordingClient:
    """记录收到的调用参数；用来检查新增参数是否沿调用链抵达客户端。"""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        self.kwargs = {"model": model, "max_tokens": max_tokens, "timeout": timeout}
        return "正文"


def test_complete_text_passes_new_parameters_through() -> None:
    """业务调用方经 `complete_text` 调用时，也能带上按次参数（否则等于没有入口）。"""
    recorder = _RecordingClient()

    complete_text(
        recorder,
        [{"role": "user", "content": "hi"}],
        model="deepseek-flash",
        max_tokens=8192,
        timeout=180.0,
    )

    assert recorder.kwargs == {
        "model": "deepseek-flash",
        "max_tokens": 8192,
        "timeout": 180.0,
    }


def test_complete_text_keeps_omitting_parameters_by_default() -> None:
    """缺省时传给客户端的是 None，由客户端自己回落到既有默认值。"""
    recorder = _RecordingClient()

    complete_text(recorder, [{"role": "user", "content": "hi"}])

    assert recorder.kwargs == {"model": None, "max_tokens": None, "timeout": None}


def test_protocol_implementations_accept_new_parameters() -> None:
    """协议扩容后，占位实现也必须接受同一组关键字（接缝一致性）。"""
    assert isinstance(OpenAICompatibleClient("https://x", "m"), ModelClient)
    assert isinstance(UnconfiguredModelClient(), ModelClient)

    with pytest.raises(NotImplementedError):
        UnconfiguredModelClient().complete(
            [{"role": "user", "content": "hi"}], max_tokens=8192, timeout=180.0
        )


class _SingleProviderRepository:
    """只认默认 provider 的仓库替身（不碰数据库）。"""

    def __init__(self) -> None:
        self._provider = {
            "name": "DeepSeek 主流程",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-flash",
        }

    def get_default(self) -> dict:
        return self._provider

    def get_by_id(self, provider_id: int) -> dict:
        raise AssertionError("本用例不应按下标解析 provider")


def test_provider_backed_client_forwards_parameters_to_real_client() -> None:
    """生产默认客户端这一层也要透传，否则调用方拿不到按次入口。"""
    scripted = _RecordingClient()
    provider_backed = ProviderBackedModelClient(
        _SingleProviderRepository(),
        InMemoryKeyStore(),
        _ReturningFactory(scripted),
    )

    provider_backed.complete(
        [{"role": "user", "content": "hi"}], max_tokens=8192, timeout=180.0
    )

    assert scripted.kwargs["max_tokens"] == 8192
    assert scripted.kwargs["timeout"] == 180.0


class _ReturningFactory:
    """固定返回给定客户端的工厂替身，顺带记下最后一次配置。"""

    def __init__(self, client: ModelClient) -> None:
        self._client = client
        self.last_config: ModelClientConfig | None = None

    def create(self, config: ModelClientConfig, *, api_key: str | None = None) -> ModelClient:
        self.last_config = config
        return self._client
