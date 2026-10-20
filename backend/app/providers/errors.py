"""连接测试的错误分类（纯函数，可独立单测）。

依据 `03-deepseek-facts.md` §5：**用「HTTP 状态码 + error.type」分支，
绝不用 `error.code`**（DeepSeek 的 code 恒为 `invalid_request_error`，
401 与 400 都一样）。`GET /models` 的 401 返回纯文本而非 JSON，解析需防御。

分类结果映射到 `ConnectionCategory`，供 `POST /api/providers/{id}/test` 返回。
"""

from __future__ import annotations

import json
from enum import Enum

import httpx

# 模型名无效的历史实测 message（官方未给稳定示例，仅作启发式细分）。
_MODEL_ERROR_MARKERS = ("not exist", "not found", "does not exist", "unknown model", "invalid model")


class ConnectionCategory(str, Enum):
    """连接测试结果分类。"""

    ok = "ok"
    network_error = "network_error"
    auth_error = "auth_error"
    model_error = "model_error"
    insufficient_balance = "insufficient_balance"
    rate_limited = "rate_limited"
    request_error = "request_error"
    server_error = "server_error"


def parse_error_body(text: str) -> tuple[str | None, str]:
    """防御性解析错误响应体，返回 (error_type, message)。

    标准信封为 `{"error":{"message":...,"type":...}}`；非 JSON（如 `/models`
    的 401 纯文本）或结构异常时回退为原文。
    """
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None, raw

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            error_type = error.get("type")
            message = error.get("message")
            return (
                error_type if isinstance(error_type, str) else None,
                message if isinstance(message, str) else "",
            )
    return None, raw


def _looks_like_model_error(message: str) -> bool:
    """400/422 下按 message 细分「模型名无效」与「参数非法」。"""
    lowered = message.lower()
    return "model" in lowered and any(marker in lowered for marker in _MODEL_ERROR_MARKERS)


def classify_status(
    status_code: int | None, error_type: str | None, message: str
) -> ConnectionCategory:
    """按状态码 + error.type 分类（纯函数真值表）。"""
    if status_code is None:
        return ConnectionCategory.network_error
    if status_code == 401 or error_type == "authentication_error":
        return ConnectionCategory.auth_error
    if status_code == 402:
        return ConnectionCategory.insufficient_balance
    if status_code == 429:
        return ConnectionCategory.rate_limited
    if status_code in (400, 422):
        if _looks_like_model_error(message):
            return ConnectionCategory.model_error
        return ConnectionCategory.request_error
    if 500 <= status_code < 600:
        return ConnectionCategory.server_error
    return ConnectionCategory.request_error


def classify_exception(exc: BaseException) -> tuple[ConnectionCategory, str]:
    """把模型调用异常映射为 (分类, 可读消息)。

    消息不含任何密钥：调用方向服务器提交密钥，服务器不原样回显；此处也不拼接。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        error_type, message = parse_error_body(exc.response.text)
        category = classify_status(exc.response.status_code, error_type, message)
        return category, message or f"HTTP {exc.response.status_code}"

    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, OSError)):
        return ConnectionCategory.network_error, str(exc) or "网络不可达"

    return ConnectionCategory.request_error, str(exc) or "请求失败"