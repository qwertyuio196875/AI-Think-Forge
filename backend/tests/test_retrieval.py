"""知识库检索（工单 21 / ADR-0005）的契约测试。

**为什么这里不是 HTTP 接缝**：规格 #2 明确「检索结果不作为独立公开接口」——它以
「本次对话 / 本次填充所用引用」的形式挂在既有响应里（#23 / #24）。本工单因此没有
可打的路由，公开面就是检索层自己的接口（`RetrievalService.retrieve` 与返回模型、
`describe_locator`），与 `test_hanzi.py` 直接测纯函数同一思路；资料入库仍全程走
HTTP（上传即入库），断言只看外部可见结果：状态枚举与标签、命中字段、汉字总量。

**不测实现细节**：不断言嵌入被调用几次、不断言 SQL 形态、不断言日志。唯一的替身是
「另一种 `EmbeddingStore` 实现」，用来验收 ADR 要求的「换索引不动调用方」。
"""

from __future__ import annotations

import io

import pytest
from docx import Document
from fakes import FakeEmbeddingClient
from fastapi.testclient import TestClient

from app.providers.embedding_client import EmbeddingCallError
from app.retrieval import (
    MAX_INJECT_HANZI,
    MIN_SIMILARITY,
    TOP_K,
    RetrievalCandidate,
    RetrievalService,
    RetrievalStatus,
    StoreSearchResult,
    VectorQuery,
    describe_locator,
)

MD_MIME = "text/markdown"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 与全库都无关的查询：夹具 README 里点名的「如何给猫剪指甲」。
UNRELATED_QUERY = "如何给猫剪指甲"

# 一段不到 1200 字符、含具体数字的正文；段与段之间空行，分块器因此一块一段。
PARAGRAPH = (
    "知识库检索需要把命中的片段注入到提示词里，因此单次注入的汉字总量必须设上限，"
    "超过上限就截断而不是报错。这一段用于验证条数与预算。"
)


@pytest.fixture
def retrieval_client(client: TestClient, embedding_client: FakeEmbeddingClient) -> TestClient:
    """256 维假向量：无关文本与片段的余弦远低于 0.3，阈值断言才不靠运气。"""
    embedding_client.set_model("fake-embedding", dimensions=256)
    return client


def _upload_md(client: TestClient, name: str, text: str) -> dict:
    """上传一份 Markdown 资料（走真实的入库管线：解析 + 分块 + 写向量）。"""
    response = client.post(
        "/api/knowledge/sources",
        files={"file": (name, text.encode("utf-8"), MD_MIME)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_docx(client: TestClient, name: str, heading: str, paragraphs: list[str]) -> dict:
    """上传一份 DOCX 资料：用来验证 locator 的「段落」定位确实来自解析结果。"""
    document = Document()
    document.add_heading(heading, level=1)
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    response = client.post(
        "/api/knowledge/sources",
        files={"file": (name, buffer.getvalue(), DOCX_MIME)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _service(db_path, embedding_client: FakeEmbeddingClient, **kwargs) -> RetrievalService:
    return RetrievalService(db_path=db_path, embedding_client=embedding_client, **kwargs)


def _repeated_paragraphs(paragraph: str, count: int) -> str:
    """把同一段重复成 `count` 个自然段（段间空行 → 各自成块）。"""
    return "\n\n".join([paragraph] * count) + "\n"


def _light_paragraph() -> str:
    """约 630 字符、但只有约 140 汉字的段落：用来单独验证 top-k 而不触发预算。"""
    return "ABC 123 检索 " * 70


def _dense_paragraph() -> str:
    """约 700 汉字的密集段落：几块就会顶满 3000 的注入预算。

    预算按**汉字**计，所以这里必须真的写满汉字；用拉丁字符凑长度是顶不满的。
    """
    return (
        "知识库检索把命中的片段注入提示词，单次注入的汉字总量必须设上限，"
        "超过上限就截断而不是报错，因此每一块占用的预算都要算清楚，"
        "既不能把预算超出的片段硬塞进去，也不能因为一块太长就整次检索失败，"
        "这条规则要求在预算耗尽时停下并标记，让调用方知道拿到的是不全的结果。"
    ) * 4


# --- 正测：命中、定位、相关度 -------------------------------------------------------


def test_hit_carries_name_seq_similarity_and_text(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """命中一条引用时，文件名 / 序号 / 相关度 / 正文齐备，且定位来自既有 locator。"""
    payload = _upload_md(
        retrieval_client,
        "字数口径.md",
        "# 字数口径\n\n" + PARAGRAPH + "\n\n另一段与查询无关的内容，用来占位。\n",
    )
    assert payload["item"]["index_status"] == "stored"

    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.ok
    assert result.degraded is False
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.name == "字数口径.md"
    assert hit.source_id == payload["item"]["source_id"]
    assert hit.document_id == payload["item"]["document_id"]
    assert hit.seq >= 1
    assert hit.similarity >= MIN_SIMILARITY
    assert PARAGRAPH in hit.text
    assert hit.hanzi_count > 0
    # 单条命中的注入预算就是它自己的 hanzi_count（已含定位标签那一行），
    # 结果里的总量与之一致——不必由调用方再算一遍。
    assert result.total_hanzi == hit.hanzi_count


def test_docx_hit_uses_paragraph_locator(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """DOCX 命中沿用解析器写下的段落定位：格式 docx、段落号非空、标签形如「第 N 段」。"""
    _upload_docx(
        retrieval_client,
        "分块说明.docx",
        "分块说明",
        [PARAGRAPH, "第二段只用来把分块撑开，内容与查询无关。"],
    )

    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.ok
    hit = result.hits[0]
    assert hit.format == "docx"
    # 段落定位平铺在命中上（引用卡片不必自己解析 locator）；
    # 原始 locator 里装的是块级 {start, end}，起点那一份才是段落号。
    assert hit.paragraph is not None and hit.paragraph >= 1
    assert hit.locator_label == f"第 {hit.paragraph} 段"


@pytest.mark.parametrize(
    ("locator", "expected_format", "expected_label"),
    [
        ({"format": "md", "line": 3}, "md", "第 3 行"),
        ({"format": "docx", "paragraph": 7}, "docx", "第 7 段"),
        ({"format": "pdf", "page": 2, "line": 9}, "pdf", "第 2 页"),
        ({"format": "pptx", "slide": 5, "shape": 1}, "pptx", "第 5 张幻灯片"),
        (
            {"format": "md", "start": {"format": "docx", "paragraph": 4}, "end": {"paragraph": 6}},
            "docx",
            "第 4 段",
        ),
        ({"format": "md", "part": 2, "line": 8}, "md", "第 8 行（第 2 部分）"),
    ],
)
def test_describe_locator_uses_existing_position_metadata(
    locator: dict, expected_format: str, expected_label: str
) -> None:
    """四种既有位置元数据（格式 / 段落 / 页 / 幻灯片）都能翻成可读定位。"""
    info = describe_locator(locator)

    assert info.format == expected_format
    assert info.label == expected_label


def test_describe_locator_keeps_structured_fields() -> None:
    """定位信息既给可读标签，也给结构化字段，前端与下游不必自己解析。"""
    info = describe_locator({"format": "pdf", "page": 2, "line": 9})

    assert (info.page, info.line, info.paragraph, info.slide) == (2, 9, None, None)


# --- 负测：阈值、条数、注入预算 -----------------------------------------------------


def test_unrelated_query_drops_every_chunk(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """与全库都无关的查询：低于阈值的片段全部丢弃，宁可不给。"""
    _upload_md(
        retrieval_client,
        "分块说明.md",
        "# 分块说明\n\n" + PARAGRAPH + "\n\n再补一段，确保有多个可比较的片段。\n",
    )

    result = _service(db_path, embedding_client).retrieve(UNRELATED_QUERY)

    assert result.status is RetrievalStatus.ok
    assert result.hits == []
    assert result.total_hanzi == 0
    assert result.message is not None


def test_hits_never_exceed_top_k(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """十个都过阈值的片段，最多回 6 条（top-k 硬上限）。"""
    _upload_md(retrieval_client, "重复段落.md", _repeated_paragraphs(_light_paragraph(), 10))

    result = _service(db_path, embedding_client).retrieve(_light_paragraph())

    assert len(result.hits) == TOP_K == 6
    assert result.truncated is False
    assert result.total_hanzi <= MAX_INJECT_HANZI


def test_inject_budget_truncates_instead_of_failing(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """大片段的注入总量不超过 3000 汉字：超出时截断并标记，不报错。"""
    # 每块约 700 汉字：六块全收会超出 3000 的预算，必须在中途停下。
    _upload_md(retrieval_client, "超长资料.md", _repeated_paragraphs(_dense_paragraph(), 10))

    result = _service(db_path, embedding_client).retrieve(_dense_paragraph())

    assert result.status is RetrievalStatus.ok
    assert result.hits
    assert result.total_hanzi <= MAX_INJECT_HANZI == 3000
    assert result.total_hanzi == sum(hit.hanzi_count for hit in result.hits)
    assert result.truncated is True


# --- 负测：降级与不可用（骨架 + 标记，关键词检索属 #22）-----------------------------


def test_degraded_when_embedding_call_fails(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """嵌入调用失败：降级路径返回结果对象并明示降级，不抛错、不静默。"""
    _upload_md(retrieval_client, "分块说明.md", "# 分块说明\n\n" + PARAGRAPH + "\n")
    embedding_client.set_error(EmbeddingCallError("嵌入服务不可用"))

    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.degraded
    assert result.degraded is True
    assert result.status_label == "降级检索"
    assert "降级" in (result.message or "")
    assert result.hits == []


def test_degraded_when_every_source_lacks_vectors(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """分块在、向量缺（入库时嵌入失败）：明示降级而不是假装检索成功。"""
    embedding_client.set_error(EmbeddingCallError("尚未配置嵌入模型"))
    payload = _upload_md(retrieval_client, "没索引的资料.md", "# 标题\n\n" + PARAGRAPH + "\n")
    assert payload["item"]["index_status"] == "failed"
    assert payload["item"]["chunk_count"] > 0
    embedding_client.set_error(None)

    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.degraded
    assert result.missing_index_count == 1
    assert "缺少向量" in (result.message or "")
    assert result.hits == []


def test_degraded_when_vectors_come_from_another_model(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """换了嵌入模型但没重建索引：向量不可比，降级并提示重建，绝不静默给垃圾结果。"""
    _upload_md(retrieval_client, "分块说明.md", "# 分块说明\n\n" + PARAGRAPH + "\n")
    embedding_client.set_model("other-embedding", dimensions=256)

    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.degraded
    assert result.skipped_incompatible >= 1
    assert "重建索引" in (result.message or "")


def test_unavailable_when_knowledge_base_is_empty(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """知识库里没有任何资料：明示「本次未使用知识库」，不假装一切正常。"""
    result = _service(db_path, embedding_client).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.unavailable
    assert result.status_label == "本次未使用知识库"
    assert result.hits == []
    assert "知识库" in (result.message or "")


# --- 抽象：换一种存储实现，调用方不变 ----------------------------------------------


class _ListStore:
    """另一种 `EmbeddingStore` 实现（内存列表），验收「换索引不动调用方」。"""

    def __init__(self, candidate: RetrievalCandidate) -> None:
        self._candidate = candidate
        self.queries: list[VectorQuery] = []

    def search(self, query: VectorQuery, *, limit: int) -> StoreSearchResult:
        self.queries.append(query)
        return StoreSearchResult(candidates=[self._candidate], skipped_incompatible=0)


def test_service_accepts_alternative_store(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """检索服务只依赖 `EmbeddingStore` 抽象：换成内存实现，返回就来自它。"""
    payload = _upload_md(retrieval_client, "分块说明.md", "# 分块说明\n\n" + PARAGRAPH + "\n")
    store = _ListStore(
        RetrievalCandidate(
            chunk_id=1,
            document_id=payload["item"]["document_id"],
            source_id=payload["item"]["source_id"],
            name="自定义资料.md",
            seq=3,
            text="来自另一种存储实现的分块正文。",
            locator={"format": "pptx", "slide": 2, "shape": 1},
            similarity=0.87,
        )
    )

    result = _service(db_path, embedding_client, store=store).retrieve(PARAGRAPH)

    assert result.status is RetrievalStatus.ok
    assert [hit.name for hit in result.hits] == ["自定义资料.md"]
    assert result.hits[0].similarity == pytest.approx(0.87)
    assert result.hits[0].locator_label == "第 2 张幻灯片"
    assert store.queries and store.queries[0].model_name == "fake-embedding"
