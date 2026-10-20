"""模型客户端接缝（fake 注入点 1）。

业务代码只依赖 `ModelClient` 协议，不绑定任何厂商 SDK；真实实现走
OpenAI 兼容适配层（`app/providers/openai_client.py`，httpx 直连）。
测试经 FastAPI `dependency_overrides` 注入脚本化应答的 fake。

TB-1 追加：`ModelClientConfig`（构造客户端所需的最小配置）、
`chat_completions_url`（base_url 归一，容忍 `/v1` 别名）与
`ProviderModelClientFactory`（按 provider 配置构造客户端的接缝）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.providers.errors import classify_exception


@runtime_checkable
class ModelClient(Protocol):
    """OpenAI 兼容的对话补全客户端抽象。"""

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        """对一组对话消息求补全文本。"""
        ...


class ModelCallError(RuntimeError):
    """模型调用失败（网络 / 鉴权 / 服务端 / 未配置）：消息可读且不含密钥。"""


def complete_text(
    client: ModelClient, messages: list[dict], *, model: str | None = None
) -> str:
    """调用模型并统一把「调用失败」收敛为 `ModelCallError`。

    真实实现是 httpx 直连（`app.providers.openai_client`），失败形态为 `httpx.HTTPError`
    ——调用点（拷问 / 方案 / 修订）据此给出可读的 502 而不是把堆栈抛给用户，
    数据仍照 §4 留在库里，用户可安全重试。

    只包「调用侧失败」：网络与 HTTP 异常、以及未配置的占位客户端；
    其它异常照旧抛出，避免把程序缺陷伪装成模型故障。
    """
    try:
        return client.complete(messages, model=model)
    except (httpx.HTTPError, OSError) as exc:
        _, message = classify_exception(exc)
        raise ModelCallError(message) from exc
    except NotImplementedError as exc:
        raise ModelCallError("尚未配置可用的模型客户端") from exc


@dataclass(frozen=True)
class ModelClientConfig:
    """构造一个模型客户端所需的最小配置（不含密钥）。"""

    base_url: str
    model_name: str
    timeout_seconds: float = 60.0


@runtime_checkable
class ProviderModelClientFactory(Protocol):
    """按 provider 配置构造 `ModelClient` 的接缝（fake 注入点）。"""

    def create(self, config: ModelClientConfig, *, api_key: str | None = None) -> ModelClient:
        """为给定配置与密钥构造客户端。"""
        ...


def chat_completions_url(base_url: str) -> str:
    """把 base_url 归一到 Chat Completions 端点。

    官方 base_url 不含 `/v1`，但 `/v1` 是历史兼容别名且客户端可能自动补；
    因此只追加 chat 路径、不删除既有 `/v1`。
    """
    return base_url.rstrip("/") + "/chat/completions"


class UnconfiguredModelClient:
    """未配置模型时的占位实现：显式失败，避免静默返回空结果。

    保留作**文档性 fallback**（说明「未配置」应如何显式失败），
    **不再是 `app.state.model_client` 的生产默认**——生产默认是
    `app.providers.provider_backed_client.ProviderBackedModelClient`。
    """

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        raise NotImplementedError("模型客户端尚未配置（TB-1 落地真实实现）")
