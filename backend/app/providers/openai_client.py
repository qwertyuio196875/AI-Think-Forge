"""OpenAI 兼容模型客户端（httpx 直连，不引入 `openai` SDK）。

规格要求厂商无关：同一适配层同时服务 DeepSeek 与百炼，切换靠配置。
httpx 直连亦便于测试用 `httpx.MockTransport` 做确定性注入。

两点 DeepSeek 事实驱动的默认行为：
- **默认关闭思考模式**：DeepSeek 思考模式默认开启且 effort=high，思维链 token
  按输出计费，会让成本显著上升；故请求体固定带 `{"thinking":{"type":"disabled"}}`。
- **base_url 容忍 `/v1`**：只追加 chat 路径，不删除既有 `/v1`。
"""

from __future__ import annotations

import logging

import httpx

from app.providers.model_client import ModelClient, ModelClientConfig, chat_completions_url
from app.security.redaction import redact

logger = logging.getLogger(__name__)

# 连接测试与常规调用共用；长生成的更大超时由后续工单按需覆盖。
DEFAULT_TIMEOUT_SECONDS = 60.0
# 保守输出上限，避免探测性调用意外产生大额输出。
DEFAULT_MAX_TOKENS = 1024


class OpenAICompatibleClient:
    """实现 `ModelClient` 协议；每次调用独立发起 HTTP 请求。"""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._max_tokens = max_tokens
        # 注入 httpx.Client 仅用于测试（MockTransport）；生产代码自建短生命周期客户端。
        self._http_client = http_client

    def _build_payload(self, messages: list[dict], model: str | None) -> dict:
        return {
            "model": model or self.model_name,
            "messages": messages,
            "max_tokens": self._max_tokens,
            # 显式关闭思考模式（DeepSeek 默认开启，思维链按输出计费）。
            "thinking": {"type": "disabled"},
        }

    def complete(self, messages: list[dict], *, model: str | None = None) -> str:
        """发起一次非流式 Chat Completions 调用并返回首个候选文本。"""
        url = chat_completions_url(self.base_url)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        http = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = http.post(url, json=self._build_payload(messages, model), headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "模型调用失败 status=%s url=%s body=%s",
                exc.response.status_code,
                url,
                redact(exc.response.text, self._api_key),
            )
            raise
        except httpx.HTTPError as exc:
            logger.warning("模型调用失败 url=%s error=%s", url, redact(str(exc), self._api_key))
            raise
        finally:
            if self._http_client is None:
                http.close()

        return data["choices"][0]["message"]["content"]


class HttpModelClientFactory:
    """默认工厂：按 provider 配置构造 httpx 直连客户端。"""

    def create(self, config: ModelClientConfig, *, api_key: str | None = None) -> ModelClient:
        return OpenAICompatibleClient(
            base_url=config.base_url,
            model_name=config.model_name,
            api_key=api_key,
            timeout_seconds=config.timeout_seconds,
        )