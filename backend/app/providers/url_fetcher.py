"""URL 抓取接缝（fake 注入点 2）。

业务代码只依赖 `UrlFetcher` 协议；真实实现与 SSRF 防护（纯函数式 URL
安全校验器，可独立负测环回 / 私网 / 链路本地 / 元数据 / 非法协议）由
TB-9 落地。测试经 `dependency_overrides` 注入假响应，不联网。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# 安全边界默认值（规格 08 / 约定 10）：超时 15s、下载上限 5MB。
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024


@runtime_checkable
class UrlFetcher(Protocol):
    """公开网页 URL 抓取抽象。"""

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> bytes:
        """抓取 URL 内容并返回原始字节。"""
        ...


class UnconfiguredUrlFetcher:
    """未配置抓取器时的占位实现：显式失败，绝不发起真实请求。"""

    def fetch(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> bytes:
        raise NotImplementedError("URL 抓取器尚未配置（TB-9 落地真实实现）")
