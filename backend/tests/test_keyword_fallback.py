"""关键词降级检索（工单 22 / ADR-0005 补充说明）的契约测试。

工单 22 的验收四条，逐条对应下面四组测试：

1. **嵌入失败时检索仍返回结果，且带降级标记** → `test_degraded_fallback_returns_hits`；
2. **嵌入与关键词双失败时明示「本次未使用知识库」，填充流程仍能走完**
   → `test_unavailable_when_keyword_search_also_fails` 与
   `test_fill_flow_still_completes_when_retrieval_unavailable`；
3. **中文分词方案定死**（二元组匹配，零新增依赖）→ `test_bigram_tokenizer_*`；
4. **降级检索的结果同样遵守阈值与注入预算** → `test_fallback_respects_threshold_and_budget`。

**为什么这里不是 HTTP 接缝**：规格 #2 明确「检索结果不作为独立公开接口」——它以
「本次对话 / 本次填充所用引用」的形式挂在既有响应里（#23 / #24）。因此本工单能
钉的公开面是检索层自己的接口（`RetrievalService.retrieve` 与返回模型）。资料入库
仍全程走 HTTP（上传即入库），断言只看外部可见结果：状态枚举与标签、命中字段、
注入汉字总量。

**不测实现细节**：不断言嵌入被调用几次、不断言 SQL 形态、不断言内部函数名。
唯一的替身是「另一种 `KeywordStore` 实现」，用来验收「存储可替换、调用方不变」。
"""

from __future__ import annotations

import io
import json

import pytest
from docx import Document
from fakes import FakeEmbeddingClient
from fastapi.testclient import TestClient

from app.providers.embedding_client import EmbeddingCallError
from app.retrieval import (
    MAX_INJECT_HANZI,
    MIN_SIMILARITY,
    TOP_K,
    RetrievalService,
    RetrievalStatus,
)
from app.retrieval.keyword import bigram_tokens, keyword_coverage

MD_MIME = "text/markdown"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 与全库都无关的查询：夹具 README 里点名的「如何给猫剪指甲」。
UNRELATED_QUERY = "如何给猫剪指甲"

# 一段含具体词的正文：降级检索靠二元组匹配命中它。
KEYWORD_PARAGRAPH = (
    "知识库检索需要把命中的片段注入到提示词里，因此单次注入的汉字总量必须设上限，"
    "超过上限就截断而不是报错。这一段用于验证降级路径也能召回相关片段。"
)

# 与上面**不共享任何二元组**的资料，用来把无关片段挡在阈值外。
# （注意：不能写「猫咪剪指甲」这类与查询同题的资料——那本来就该被命中，
# 那样构造出来的「无关」是假的。）
UNRELATED_PARAGRAPH = "本季度我们对海外市场的经销渠道做了重新梳理，结论是维持原有的分层体系。"

# 「嵌入不可用」的可读原因：降级路径必须把它如实带给用户。
EMBEDDING_DOWN_REASON = "嵌入服务不可用"


def _keyword_light_paragraph() -> str:
    """约 700 字符、但只有几十个汉字的段落。

    两个用途：让分块器把 10 段切成 10 块（单块 718 字符 > 目标 1200 的一半，
    不会被合并），同时汉字数足够低，让「验证 top-k」这件事不被注入预算抢先触发
    ——预算由 `test_fallback_respects_inject_budget` 单独验证。
    """
    return "知识库检索 单次注入 汉字总量 上限 截断 " + "ABC 123 filler " * 50


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
    """上传一份 DOCX 资料：验证降级路径的定位也沿用既有 locator。"""
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


def _break_embedding(embedding_client: FakeEmbeddingClient) -> None:
    """把嵌入客户端打成「调用即失败」，这是降级路径的开关。"""
    embedding_client.set_error(EmbeddingCallError(EMBEDDING_DOWN_REASON))


def _repeated_paragraphs(paragraph: str, count: int) -> str:
    """把同一段重复成 `count` 个自然段（段间空行 → 各自成块）。"""
    return "\n\n".join([paragraph] * count) + "\n"


def _dense_paragraph() -> str:
    """约 700 汉字的密集段落：几块就会顶满 3000 的注入预算。"""
    return (
        "知识库检索把命中的片段注入提示词，单次注入的汉字总量必须设上限，"
        "超过上限就截断而不是报错，因此每一块占用的预算都要算清楚，"
        "既不能把预算超出的片段硬塞进去，也不能因为一块太长就整次检索失败，"
        "这条规则要求在预算耗尽时停下并标记，让调用方知道拿到的是不全的结果。"
    ) * 4


# --- 验收③：中文分词方案定死（二元组匹配，零新增依赖）----------------------------


def test_bigram_tokens_are_adjacent_character_pairs() -> None:
    """二元组 = 相邻两字的组合：分词方案已定死，不依赖任何分词库。"""
    assert bigram_tokens("知识库") == {"知识", "识库"}


def test_bigram_tokens_keep_latin_words_and_numbers() -> None:
    """连续的字母 / 数字按整词保留：'PPT'、'16' 这类词不被拆成一堆碎片。"""
    tokens = bigram_tokens("PPT 导出 16 页")

    assert "ppt" in tokens
    assert "16" in tokens
    assert "导出" in tokens
    # 汉字二元组只跨**同一段**连续汉字（空格 / 标点是分隔符）。
    assert "出导" not in tokens
    assert "出文" in bigram_tokens("导出文档")


def test_bigram_tokens_ignore_single_character_and_punctuation() -> None:
    """单字与标点不成词：'的'、'是' 这类功能词不该单独参与匹配。"""
    # 单个汉字成段时不产出任何词元。
    assert bigram_tokens("的") == set()
    assert bigram_tokens("。") == set()
    assert bigram_tokens("的是。") == {"的是"}


def test_bigram_tokens_of_empty_text_is_empty() -> None:
    """空文本没有词元：降级检索据此判定「查不到」，而不是凭空给 0 分命中。"""
    assert bigram_tokens("") == set()
    assert bigram_tokens("   ") == set()


def test_keyword_coverage_is_query_side_recall() -> None:
    """覆盖率 = 查询词元被命中的比例：查询的每个词都有机会被召回。"""
    query = bigram_tokens("知识库检索")
    document = bigram_tokens("知识库检索需要把片段注入提示词")

    assert keyword_coverage(query, document) == pytest.approx(1.0)
    # 查询里有一半没被覆盖 → 0.5。
    assert keyword_coverage(query, bigram_tokens("知识库与天气无关")) == pytest.approx(0.5)
    # 完全不重合 → 0。
    assert keyword_coverage(query, bigram_tokens("猫咪剪指甲要用磨甲器")) == 0.0
    # 词元为空 → 0，不做除零。
    assert keyword_coverage(set(), document) == 0.0


# --- 验收①：嵌入失败时检索仍返回结果，且带降级标记 --------------------------------


def test_degraded_fallback_returns_hits(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """嵌入不可用时改走关键词检索：仍然召回相关片段，并明示处于降级状态。"""
    _upload_md(retrieval_client, "注入预算.md", "# 注入预算\n\n" + KEYWORD_PARAGRAPH + "\n")
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve("知识库检索 单次注入 汉字总量 上限")

    # 状态是「降级」，且降级标记可见——界面据此明示，不静默隐藏。
    assert result.status is RetrievalStatus.degraded
    assert result.degraded is True
    assert result.status_label == "降级检索"
    assert "降级" in (result.message or "")

    # 关键：降级**不是**空结果——RAG 仍然可用。
    assert result.hits
    assert result.hits[0].name == "注入预算.md"
    assert KEYWORD_PARAGRAPH in result.hits[0].text
    assert result.hits[0].similarity >= MIN_SIMILARITY


def test_degraded_fallback_keeps_hit_locator_metadata(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """降级命中的定位与正常检索同源：文件名、段落号、格式字段都齐备。"""
    _upload_docx(
        retrieval_client,
        "降级定位.docx",
        "降级定位",
        [KEYWORD_PARAGRAPH, "第二段与查询无关，只用来把分块撑开。"],
    )
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve("知识库检索 单次注入 汉字总量 上限")

    assert result.hits
    hit = result.hits[0]
    assert hit.name == "降级定位.docx"
    assert hit.format == "docx"
    assert hit.paragraph is not None and hit.paragraph >= 1
    assert hit.locator_label == f"第 {hit.paragraph} 段"
    assert hit.hanzi_count > 0


def test_degraded_fallback_hits_are_sorted_by_relevance(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """降级命中按相关度降序：最贴题的片段排在前面。"""
    _upload_md(
        retrieval_client,
        "更贴题.md",
        "# 更贴题\n\n知识库检索 单次注入 汉字总量 上限 截断 而不是报错\n",
    )
    _upload_md(
        retrieval_client,
        "较泛.md",
        "# 较泛\n\n知识库检索 也有提到\n",
    )
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve("知识库检索 单次注入 汉字总量 上限")

    assert result.hits
    assert result.hits[0].name == "更贴题.md"
    relevances = [hit.similarity for hit in result.hits]
    assert relevances == sorted(relevances, reverse=True)


# --- 验收④：降级检索同样遵守阈值与注入预算 ----------------------------------------


def test_fallback_respects_threshold(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """与全库都无关的查询：低于阈值的片段全部丢弃，宁可不给。"""
    _upload_md(
        retrieval_client,
        "猫舍.md",
        "# 猫舍\n\n" + UNRELATED_PARAGRAPH + "\n",
    )
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve(UNRELATED_QUERY)

    assert result.hits == []
    assert result.total_hanzi == 0
    assert result.message is not None


def test_fallback_never_exceeds_top_k(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """十个都过阈值的片段，降级路径最多回 6 条（top-k 硬上限，与向量路径一致）。"""
    _upload_md(
        retrieval_client,
        "重复段落.md",
        _repeated_paragraphs(_keyword_light_paragraph(), 10),
    )
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve("知识库检索 单次注入 汉字总量 上限")

    assert len(result.hits) == TOP_K == 6
    assert result.truncated is False
    assert result.total_hanzi <= MAX_INJECT_HANZI


def test_fallback_respects_inject_budget(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """大片段的注入总量不超过 3000 汉字：超出时截断并标记，不报错。"""
    _upload_md(retrieval_client, "超长资料.md", _repeated_paragraphs(_dense_paragraph(), 10))
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client).retrieve(
        "知识库检索 注入 提示词 汉字 总量 上限 截断 报错"
    )

    assert result.hits
    assert result.total_hanzi <= MAX_INJECT_HANZI == 3000
    assert result.total_hanzi == sum(hit.hanzi_count for hit in result.hits)
    assert result.truncated is True


# --- 验收②：嵌入与关键词双失败 → 明示「本次未使用知识库」--------------------------


def test_unavailable_when_keyword_search_also_fails(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """嵌入与关键词双失败：明示「本次未使用知识库」，而不是假装一切正常。"""
    _upload_md(retrieval_client, "注入预算.md", "# 注入预算\n\n" + KEYWORD_PARAGRAPH + "\n")
    _break_embedding(embedding_client)

    # 关键词检索也失败：把存储层换成会抛错的实现。
    class _BrokenStore:
        def search(self, query, *, limit):
            raise RuntimeError("关键词索引读不出来")

    result = _service(
        db_path, embedding_client, keyword_store=_BrokenStore()
    ).retrieve("知识库检索 单次注入 汉字总量 上限")

    assert result.status is RetrievalStatus.unavailable
    assert result.status_label == "本次未使用知识库"
    assert result.degraded is False
    assert result.hits == []
    assert "未使用知识库" in (result.message or "")


def test_unavailable_when_keyword_search_also_fails_does_not_raise(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """关键词检索失败**不抛异常**：填充流程要能继续走完，不能被检索拖垮。"""

    class _BrokenStore:
        def search(self, query, *, limit):
            raise RuntimeError("关键词索引读不出来")

    _break_embedding(embedding_client)

    result = _service(
        db_path, embedding_client, keyword_store=_BrokenStore()
    ).retrieve("知识库检索")

    assert result.status is RetrievalStatus.unavailable
    assert result.hits == []


def test_fill_flow_still_completes_when_retrieval_unavailable(
    grilling_client: TestClient, scripted_model_client, db_path
) -> None:
    """双失败时填充流程仍能走完：检索不可用只是「本次未使用知识库」，不是错误。

    填充入口（#9）与检索（#22）互不阻塞：检索不可用时，填充请求照常返回 200。
    """
    scripted_model_client.set_sequence(
        json.dumps(
            {
                "frontier": [
                    {
                        "title": "目标读者",
                        "body": "写给谁？",
                        "recommended_answer": "新员工",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        json.dumps({"frontier": []}, ensure_ascii=False),
        (
            "# 结构化方案\n\n"
            "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
            "## 读者\n新入职员工。\n\n"
            "## 章节\n"
            "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
            "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n\n"
            "## 关键约束\n篇幅控制在十页以内。\n"
        ),
    )
    task_id = grilling_client.post(
        "/api/grilling/tasks", json={"idea": "帮我准备一份面向新员工的产品培训"}
    ).json()["task"]["id"]
    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert grilling_client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["seq"] for item in body["items"]] == [1, 2]


# --- 抽象：换一种关键词存储实现，调用方不变 ----------------------------------------


def test_service_accepts_alternative_keyword_store(
    retrieval_client: TestClient, db_path, embedding_client: FakeEmbeddingClient
) -> None:
    """关键词检索的存储也可替换：调用方只认结果，不认存储实现。"""
    from app.retrieval.keyword_store import KeywordCandidate, KeywordSearchResult

    class _ListKeywordStore:
        """另一种关键词存储实现（内存列表）。"""

        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str, *, limit: int) -> KeywordSearchResult:
            self.queries.append(query)
            return KeywordSearchResult(
                candidates=[
                    KeywordCandidate(
                        chunk_id=1,
                        document_id=1,
                        source_id=1,
                        name="自定义资料.md",
                        seq=3,
                        text="来自另一种关键词存储实现的分块正文。",
                        locator={"format": "pptx", "slide": 2, "shape": 1},
                        score=0.87,
                    )
                ]
            )

    store = _ListKeywordStore()
    _break_embedding(embedding_client)

    result = _service(db_path, embedding_client, keyword_store=store).retrieve("知识库检索")

    assert result.status is RetrievalStatus.degraded
    assert [hit.name for hit in result.hits] == ["自定义资料.md"]
    assert result.hits[0].similarity == pytest.approx(0.87)
    assert result.hits[0].locator_label == "第 2 张幻灯片"
    assert store.queries == ["知识库检索"]
