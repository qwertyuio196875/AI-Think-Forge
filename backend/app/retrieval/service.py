"""检索服务：把「查询文本」变成「本次要注入的引用清单」（工单 21 / ADR-0005）。

调用方（拷问 #23、填充 #24）只调 `retrieve`，拿到 `RetrievalResult` 就直接渲染
卡片 / 拼提示词；向量存在 SQLite 还是 ANN 索引，本模块之外一概不可见（抽象见
`store.py`）。本模块负责四件与存储无关的事：

1. **查询向量化**：向 `EmbeddingClient` 要一次嵌入；拿不到就降级，绝不静默
   （验收③：降级状态必须在结果里明确可见）；
2. **阈值**：余弦低于 `MIN_SIMILARITY` 的片段一律丢弃——宁可不给，也不塞弱相关
   内容（验收①）；
3. **条数**：最多 `TOP_K` 条（验收②）；
4. **注入预算**：按命中顺序累加汉字数（唯一入口 `app.hanzi.count_hanzi`），超过
   `MAX_INJECT_HANZI` 就停在那里并标记 `truncated`，绝不报错、绝不截断到半个字。

降级骨架的边界（工单 22 接手）：本工单只把「为什么降级」如实放进 `message` 与
`missing_index_count` / `skipped_incompatible`，**不做关键词检索**。`degraded`
的 `hits` 因此是空的——#22 在这里接上二元组匹配即可，参数与预算规则不用改。
"""

from __future__ import annotations

from pathlib import Path

from app.hanzi import count_hanzi
from app.providers.embedding_client import EmbeddingClient, EmbeddingError
from app.retrieval.locator import describe_locator
from app.retrieval.models import (
    MAX_INJECT_HANZI,
    MIN_SIMILARITY,
    RETRIEVAL_STATUS_LABELS,
    TOP_K,
    RetrievalHit,
    RetrievalResult,
    RetrievalStatus,
)
from app.retrieval.sqlite_store import SqliteVectorStore
from app.retrieval.store import (
    EmbeddingStore,
    RetrievalCandidate,
    RetrievalStoreError,
    VectorQuery,
)


class RetrievalService:
    """知识库检索的唯一入口；`store` 可注入，用于替换存储实现（抽象验收）。"""

    def __init__(
        self,
        *,
        db_path: str | Path,
        embedding_client: EmbeddingClient,
        store: EmbeddingStore | None = None,
        top_k: int = TOP_K,
        min_similarity: float = MIN_SIMILARITY,
        max_inject_hanzi: int = MAX_INJECT_HANZI,
    ) -> None:
        self._db_path = str(db_path)
        self._embedding_client = embedding_client
        self._store: EmbeddingStore = store or SqliteVectorStore(db_path)
        self._top_k = top_k
        self._min_similarity = min_similarity
        self._max_inject_hanzi = max_inject_hanzi

    def retrieve(self, query: str) -> RetrievalResult:
        """检索一次并给出可直接注入的引用清单（含降级 / 未使用知识库的明示）。"""
        text = (query or "").strip()
        if not text:
            return _result(RetrievalStatus.ok, message="查询为空，本次没有可用于检索的内容")

        vector = self._embed_query(text)
        if vector is None:
            return _result(
                RetrievalStatus.degraded,
                message="嵌入模型不可用，本次处于降级检索（结果可能不完整）；"
                "请检查嵌入模型配置后重试",
                missing_index_count=self._missing_index_count(),
            )

        try:
            search = self._store.search(
                VectorQuery(
                    vector=tuple(vector),
                    model_name=self._embedding_client.model_name,
                    version=self._embedding_client.version,
                ),
                limit=self._top_k,
            )
        except RetrievalStoreError as exc:
            return _result(RetrievalStatus.degraded, message=f"向量检索失败，本次处于降级检索：{exc}")

        return self._compose(search.candidates, skipped=search.skipped_incompatible)

    # --- 内部 ---------------------------------------------------------------

    def _embed_query(self, text: str) -> list[float] | None:
        """查询向量；未配置 / 调用失败 / 返回空都算「拿不到」，转降级。"""
        try:
            vectors = self._embedding_client.embed([text])
        except EmbeddingError:
            return None
        except Exception:  # noqa: BLE001 - 嵌入是可降级依赖，任何失败都只降级
            return None
        if len(vectors) != 1 or not vectors[0]:
            return None
        return [float(value) for value in vectors[0]]

    def _compose(self, candidates: list[RetrievalCandidate], *, skipped: int) -> RetrievalResult:
        """阈值过滤 + top-k + 预算累加；并把「空结果」的原因说清楚。"""
        hits: list[RetrievalHit] = []
        total_hanzi = 0
        truncated = False

        for candidate in candidates:
            if candidate.similarity < self._min_similarity:
                continue
            if len(hits) >= self._top_k:
                break
            hit = _hit(candidate)
            if total_hanzi + hit.hanzi_count > self._max_inject_hanzi:
                # 预算不够就停在这里：宁少一条，也不把一条截成半个意思。
                truncated = True
                break
            hits.append(hit)
            total_hanzi += hit.hanzi_count

        if hits:
            message = None
            if skipped:
                message = f"有 {skipped} 条向量来自其它嵌入模型，已跳过；建议重建索引后再检索"
            return _result(
                RetrievalStatus.ok,
                hits=hits,
                total_hanzi=total_hanzi,
                truncated=truncated,
                skipped_incompatible=skipped,
                message=message,
            )

        if skipped:
            return _result(
                RetrievalStatus.degraded,
                message=f"知识库里的向量来自其它嵌入模型（{skipped} 条），当前不可比对；"
                "请重建索引后再检索",
                skipped_incompatible=skipped,
            )

        missing = self._missing_index_count()
        if missing:
            return _result(
                RetrievalStatus.degraded,
                message=f"知识库有 {missing} 份资料只有分块、缺少向量，本次处于降级检索；"
                "请重建索引后再检索",
                missing_index_count=missing,
            )

        if self._stored_source_count() == 0:
            return _result(
                RetrievalStatus.unavailable,
                message="知识库里还没有已入库的资料，本次未使用知识库",
            )

        return _result(
            RetrievalStatus.ok,
            message=f"没有相关度达到 {self._min_similarity:g} 的片段，本次未注入知识库内容",
        )

    def _missing_index_count(self) -> int:
        counter = getattr(self._store, "missing_index_count", None)
        return int(counter()) if callable(counter) else 0

    def _stored_source_count(self) -> int:
        counter = getattr(self._store, "stored_source_count", None)
        return int(counter()) if callable(counter) else 0


def _hit(candidate: RetrievalCandidate) -> RetrievalHit:
    """候选 → 命中；`hanzi_count` 含定位标签，等于这条命中真实占用的预算。"""
    position = describe_locator(candidate.locator)
    return RetrievalHit(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        source_id=candidate.source_id,
        name=candidate.name,
        seq=candidate.seq,
        similarity=round(float(candidate.similarity), 4),
        format=position.format,
        locator=dict(candidate.locator or {}),
        locator_label=position.label,
        paragraph=position.paragraph,
        line=position.line,
        page=position.page,
        slide=position.slide,
        text=candidate.text,
        hanzi_count=count_hanzi(candidate.text) + count_hanzi(position.label),
    )


def _result(
    status: RetrievalStatus,
    *,
    message: str | None = None,
    hits: list[RetrievalHit] | None = None,
    total_hanzi: int = 0,
    truncated: bool = False,
    skipped_incompatible: int = 0,
    missing_index_count: int = 0,
) -> RetrievalResult:
    """统一构造结果：状态标签永远与状态同源，不会各写一套。"""
    return RetrievalResult(
        status=status,
        status_label=RETRIEVAL_STATUS_LABELS[status.value],
        message=message,
        hits=hits or [],
        total_hanzi=total_hanzi,
        truncated=truncated,
        skipped_incompatible=skipped_incompatible,
        missing_index_count=missing_index_count,
    )
