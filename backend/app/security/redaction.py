"""日志与错误消息的脱敏工具。

密钥只应存在于 Windows 凭据管理器：任何进入日志、异常消息或 API 响应的
文本都必须先经 `redact`，确保不出现完整密钥。
"""

from __future__ import annotations

PLACEHOLDER = "***"


def redact(text: str, *secrets: str | None) -> str:
    """把文本中出现的任何已知密钥替换为占位符。

    空串与 None 会被忽略，避免把空串替换成占位符破坏可读文本。
    """
    if not text:
        return text
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, PLACEHOLDER)
    return redacted