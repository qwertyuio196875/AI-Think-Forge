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


@runtime_checkable
class ModelClient(Protocol):
    """OpenAI 兼容的对话补全客户端抽象。"""

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        """对一组对话消息求补全文本。"""
        ...


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
    """未配置模型时的占位实现：显式失败，避免静默返回空结果。"""

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        raise NotImplementedError("模型客户端尚未配置（TB-1 落地真实实现）")
