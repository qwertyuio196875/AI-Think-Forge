"""嵌入客户端（工单 20；ADR-0005）。

为什么单独一层：嵌入是**可降级的外部依赖**——没配密钥、网络不通、服务端报错
都不该让资料进不了库。因此这里只负责「文本 → 向量」或抛一个可读的错误，
「失败后怎么记状态、怎么降级检索」留给路由与检索层决定。

默认百炼 `text-embedding-v4`（OpenAI 兼容），与模型客户端同一套写法：
httpx 直连、`MockTransport` 可注入、密钥只从环境变量读、日志一律脱敏。
`embedding_client` 是**第三个 fake 注入点**：测试经 `dependency_overrides`
注入确定性假向量，**绝不真调外网**。

失败分两类，调用方据此决定是否还能重试：
- `EmbeddingCallError`：未配置 / 网络 / 鉴权 / 响应格式不对——重试或降级；
- `EmbeddingDimensionError`：维度或模型不一致——**绝不能当成相似**，
  必须报错让人重建索引。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

import httpx

from app.security.redaction import redact

logger = logging.getLogger(__name__)

# 百炼的 OpenAI 兼容端点（与 ADR-0005 选定的默认嵌入模型配套）。
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL_NAME = "text-embedding-v4"
# 嵌入是批量小请求（一段资料全部分块一次算完），比对话补全短得多。
DEFAULT_TIMEOUT_SECONDS = 30.0
# 写入 `embeddings.vector_json` 的格式版本：读取端校验维度与模型时一并核对，
# 后续改序列化方式（如换成二进制/量化）靠它区分新旧数据。
VECTOR_FORMAT_VERSION = "v1"

BASE_URL_ENV_VAR = "THINKFORGE_EMBEDDING_BASE_URL"
MODEL_ENV_VAR = "THINKFORGE_EMBEDDING_MODEL"
API_KEY_ENV_VAR = "THINKFORGE_EMBEDDING_API_KEY"

# 未配置时的可读原因：告诉用户该设哪个变量、没设会怎样（降级而非报错崩掉）。
NO_API_KEY_MESSAGE = (
    "尚未配置嵌入模型：请设置环境变量 "
    f"{API_KEY_ENV_VAR}（默认 {DEFAULT_MODEL_NAME}）；"
    "未配置时资料仍会入库，检索降级为关键词"
)


class EmbeddingError(RuntimeError):
    """嵌入失败的基类：消息可读且不含密钥。"""


class EmbeddingCallError(EmbeddingError):
    """调用失败：未配置 / 网络 / 鉴权 / 服务端 / 响应格式不符合预期。"""


class EmbeddingDimensionError(EmbeddingError):
    """维度或模型不一致：向量之间不可比较，必须报错而不是当成相似。"""


@runtime_checkable
class EmbeddingClient(Protocol):
    """嵌入客户端抽象（fake 注入点 3）。

    `model_name` / `version` 随向量一起落库，读取端据此判断「这批向量是不是
    同一个模型产的」——换了模型又没重建索引，必须报错而不是混着算余弦。
    """

    model_name: str
    version: str

    def embed(
        self, texts: Sequence[str], *, timeout: float | None = None
    ) -> list[list[float]]:
        """把一批文本编码成向量，顺序与输入一一对应。"""
        ...


def embeddings_url(base_url: str) -> str:
    """把 base_url 归一到 Embeddings 端点（容忍尾斜杠，不删既有 `/v1`）。"""
    return base_url.rstrip("/") + "/embeddings"


class OpenAICompatibleEmbeddingClient:
    """OpenAI 兼容的嵌入端点实现（httpx 直连，不引 SDK）。"""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        version: str = VECTOR_FORMAT_VERSION,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.version = version
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        # 注入 httpx.Client 仅用于测试（MockTransport）；生产自建短生命周期客户端。
        self._http_client = http_client

    def embed(
        self, texts: Sequence[str], *, timeout: float | None = None
    ) -> list[list[float]]:
        """一次请求编码整批文本；空批次直接返回，不白花一次调用。"""
        items = list(texts)
        if not items:
            return []

        url = embeddings_url(self.base_url)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        call_timeout = timeout if timeout is not None else self.timeout_seconds
        http = self._http_client or httpx.Client(timeout=call_timeout)
        try:
            response = http.post(
                url,
                json={
                    "model": self.model_name,
                    "input": items,
                    "encoding_format": "float",
                },
                headers=headers,
                timeout=call_timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "嵌入调用失败 status=%s url=%s body=%s",
                exc.response.status_code,
                url,
                redact(exc.response.text, self._api_key),
            )
            raise EmbeddingCallError(
                f"嵌入模型调用失败（HTTP {exc.response.status_code}）"
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("嵌入调用失败 url=%s error=%s", url, redact(str(exc), self._api_key))
            raise EmbeddingCallError(f"嵌入模型调用失败：{redact(str(exc), self._api_key)}") from exc
        finally:
            if self._http_client is None:
                http.close()

        return self._parse(data, len(items))

    @staticmethod
    def _parse(data: object, expected: int) -> list[list[float]]:
        """解析响应并按 `index` 归位；条数不对、结构不对都算调用失败。"""
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != expected:
            raise EmbeddingCallError("嵌入模型返回的向量条数与请求不一致")

        ordered: list[list[float] | None] = [None] * expected
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EmbeddingCallError("嵌入模型返回的向量结构不符合预期")
            raw = row.get("embedding")
            if not isinstance(raw, list) or not raw:
                raise EmbeddingCallError("嵌入模型没有返回有效向量")
            index = row.get("index", position)
            if not isinstance(index, int) or not 0 <= index < expected:
                raise EmbeddingCallError("嵌入模型返回的向量序号越界")
            ordered[index] = [float(value) for value in raw]

        if any(vector is None for vector in ordered):
            raise EmbeddingCallError("嵌入模型返回的向量不完整")
        vectors = [vector for vector in ordered if vector is not None]
        _ensure_same_dimensions(vectors)
        return vectors


def _ensure_same_dimensions(vectors: list[list[float]]) -> None:
    """同批向量必须同维：维度不一致说明模型/版本串了，不能拿去算相似度。"""
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) > 1:
        raise EmbeddingDimensionError(
            f"嵌入向量维度不一致（出现 {sorted(dimensions)} 个维度），"
            "请确认只使用一个嵌入模型并重建索引"
        )


class ConfiguredEmbeddingClient:
    """按环境变量构造真实嵌入客户端；**调用时**读配置，改配置无需重启。

    构造期不校验密钥：应用启动时还没配嵌入模型是正常状态（资料照样能入库、
    检索降级），等到真要嵌入时再抛出可读原因，由路由记成「索引失败」。
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._env = env
        self._http_client = http_client

    def _settings(self) -> Mapping[str, str]:
        return self._env if self._env is not None else os.environ

    @property
    def model_name(self) -> str:
        return self._settings().get(MODEL_ENV_VAR) or DEFAULT_MODEL_NAME

    @property
    def version(self) -> str:
        return VECTOR_FORMAT_VERSION

    def embed(
        self, texts: Sequence[str], *, timeout: float | None = None
    ) -> list[list[float]]:
        if not texts:
            return []
        settings = self._settings()
        api_key = (settings.get(API_KEY_ENV_VAR) or "").strip()
        if not api_key:
            raise EmbeddingCallError(NO_API_KEY_MESSAGE)
        client = OpenAICompatibleEmbeddingClient(
            base_url=settings.get(BASE_URL_ENV_VAR) or DEFAULT_BASE_URL,
            model_name=self.model_name,
            api_key=api_key,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            http_client=self._http_client,
        )
        return client.embed(texts, timeout=timeout)
