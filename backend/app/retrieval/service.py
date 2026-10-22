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

**降级路径（工单 22）**：嵌入不可用时改走**关键词检索**（二元组匹配，见
`keyword.py`），RAG 仍然可用，只是召回变差——因此状态标成「降级检索」，让
界面明示。关键词检索也不可用时，状态标成「本次未使用知识库」，**不是**错误：
填充流程照常走完，只是这一轮不带任何资料。

两条路径共用**同一套**阈值 / top-k / 预算规则：降级不是「另一套更宽松的规矩」，
弱相关片段照样丢、注入总量照样不超 3000 汉字。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.hanzi import count_hanzi
from app.providers.embedding_client import EmbeddingClient, EmbeddingError
from app.retrieval.keyword_store import KeywordCandidate, KeywordStore
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
from app.retrieval.sqlite_store import SqliteKeywordStore, SqliteVectorStore
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
        keyword_store: KeywordStore | None = None,
        top_k: int = TOP_K,
        min_similarity: float = MIN_SIMILARITY,
        max_inject_hanzi: int = MAX_INJECT_HANZI,
    ) -> None:
        self._db_path = str(db_path)
        self._embedding_client = embedding_client
        self._store: EmbeddingStore = store or SqliteVectorStore(db_path)
        self._keyword_store: KeywordStore = keyword_store or SqliteKeywordStore(db_path)
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
            return self._retrieve_by_keyword(text)

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
            return self._retrieve_by_keyword(text, reason=f"向量检索失败：{exc}")

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

    def _retrieve_by_keyword(self, text: str, *, reason: str | None = None) -> RetrievalResult:
        """降级路径：改用二元组关键词检索（工单 22）。

        嵌入不可用不是错误——RAG 仍然可用，只是召回变差，因此状态是「降级检索」。
        关键词检索也失败时才是「本次未使用知识库」：**不抛异常**，填充流程照常
        走完，只是这一轮不带资料。
        """
        try:
            search = self._keyword_store.search(text, limit=self._top_k)
        except Exception as exc:  # noqa: BLE001 - 关键词检索失败也只是「没有资料」
            return _result(
                RetrievalStatus.unavailable,
                message=(
                    f"{reason or '嵌入模型不可用'}，关键词检索也不可用：{exc}；"
                    "本次未使用知识库"
                ),
                missing_index_count=self._missing_index_count(),
            )

        hits, total_hanzi, truncated = self._apply_budget(search.candidates)
        missing = self._missing_index_count()
        if hits:
            # 降级但有结果：明示「处于降级状态」，让用户知道召回不如正常检索。
            # 若还有「只有分块、缺少向量」的资料，一并说明——这是召回变差的主因，
            # 提示重建索引比只说「降级」更有用。
            detail = reason or "嵌入模型不可用，本次改用关键词检索"
            message = f"{detail}，当前处于降级检索（结果可能不完整）"
            if missing:
                message += (
                    f"；知识库有 {missing} 份资料只有分块、缺少向量，请重建索引后再检索"
                )
            return _result(
                RetrievalStatus.degraded,
                hits=hits,
                total_hanzi=total_hanzi,
                truncated=truncated,
                missing_index_count=missing,
                message=message,
            )

        # 关键词检索也没命中：区分「库是空的」与「确实没有相关内容」。
        if missing:
            return _result(
                RetrievalStatus.degraded,
                message=(
                    f"嵌入模型不可用，本次改用关键词检索；"
                    f"知识库有 {missing} 份资料只有分块、缺少向量，请重建索引后再检索"
                ),
                missing_index_count=missing,
            )
        if self._keyword_source_count() == 0:
            return _result(
                RetrievalStatus.unavailable,
                message="知识库里还没有已入库的资料，本次未使用知识库",
            )
        return _result(
            RetrievalStatus.degraded,
            message=(
                f"{reason or '嵌入模型不可用'}，本次改用关键词检索；"
                f"没有相关度达到 {self._min_similarity:g} 的片段，本次未注入知识库内容"
            ),
        )

    def _compose(self, candidates: list[RetrievalCandidate], *, skipped: int) -> RetrievalResult:
        """向量路径：阈值过滤 + top-k + 预算累加；并把「空结果」的原因说清楚。"""
        hits, total_hanzi, truncated = self._apply_budget(candidates)

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

    def _apply_budget(
        self, candidates: Sequence[RetrievalCandidate | KeywordCandidate]
    ) -> tuple[list[RetrievalHit], int, bool]:
        """阈值 + top-k + 注入预算：降级路径与向量路径共用同一套规则。"""
        hits: list[RetrievalHit] = []
        total_hanzi = 0
        truncated = False

        for candidate in candidates:
            score = _score_of(candidate)
            if score < self._min_similarity:
                continue
            if len(hits) >= self._top_k:
                break
            hit = _hit(candidate, score)
            if total_hanzi + hit.hanzi_count > self._max_inject_hanzi:
                # 预算不够就停在这里：宁少一条，也不把一条截成半个意思。
                truncated = True
                break
            hits.append(hit)
            total_hanzi += hit.hanzi_count

        return hits, total_hanzi, truncated

    def _missing_index_count(self) -> int:
        counter = getattr(self._store, "missing_index_count", None)
        return int(counter()) if callable(counter) else 0

    def _stored_source_count(self) -> int:
        counter = getattr(self._store, "stored_source_count", None)
        return int(counter()) if callable(counter) else 0

    def _keyword_source_count(self) -> int:
        """关键词路径能覆盖的资料份数（有分块即算，索引失败也救得回来）。"""
        counter = getattr(self._keyword_store, "stored_source_count", None)
        if callable(counter):
            return int(counter())
        return self._stored_source_count()


def _score_of(candidate: RetrievalCandidate | KeywordCandidate) -> float:
    """候选的相关度：向量候选取余弦，关键词候选取覆盖率。"""
    if isinstance(candidate, KeywordCandidate):
        return float(candidate.score)
    return float(candidate.similarity)


def _hit(candidate: RetrievalCandidate | KeywordCandidate, score: float) -> RetrievalHit:
    """候选 → 命中；`hanzi_count` 含定位标签，等于这条命中真实占用的预算。

    `candidate` 可能是向量候选（`similarity`）也可能是关键词候选（`score`），
    两者字段同名同义，因此在检索层一律折算成「相关度」这一个数。
    """
    position = describe_locator(candidate.locator)
    return RetrievalHit(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        source_id=candidate.source_id,
        name=candidate.name,
        seq=candidate.seq,
        similarity=round(float(score), 4),
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
