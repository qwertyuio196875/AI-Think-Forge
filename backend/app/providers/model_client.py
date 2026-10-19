"""模型客户端接缝（fake 注入点 1）。

业务代码只依赖 `ModelClient` 协议，不绑定任何厂商 SDK；真实实现走
OpenAI 兼容适配层（后续工单落地）。测试经 FastAPI `dependency_overrides`
注入脚本化应答的 fake。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelClient(Protocol):
    """OpenAI 兼容的对话补全客户端抽象。"""

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        """对一组对话消息求补全文本。"""
        ...


class UnconfiguredModelClient:
    """未配置模型时的占位实现：显式失败，避免静默返回空结果。"""

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        raise NotImplementedError("模型客户端尚未配置（TB-1 落地真实实现）")
