"""事实型问题判定：哪些前沿问题需要外部依据（工单 23 / ADR-0005）。

**流程**：一轮前沿问题生成后 →

1. 用 `fact_check_v1.md` 资产判定每个问题是否需要外部依据（规则在资产里，不在代码里）；
2. 只对判定为事实型的问题检索知识库；
3. 把命中结果挂到对应问题上，作为**引用**返回给前端做可折叠卡片。

**为什么不在代码里写启发式**（比如「问句里有数字就检索」）：那种规则既漏又误——
「要写几千字」是决策型（用户偏好），却含数字；「行业通行的培训周期是多久」是事实型，
却不含数字。规则写进资产，才能被审阅、被版本化、被测试断言。

**降级是明确的**：检索不可用时不报错，`RetrievalResult.message` 会说明原因，界面据此
明示「本次未使用知识库」。拷问流程照常推进——没有资料也能问出用户想要什么。

**不做的事**：本模块不回答问题、不写方案、不改判定结果。判定只决定「检索与否」。
"""

from __future__ import annotations

import json

from app.grilling.prompts import render_fact_check_messages
from app.providers.model_client import ModelCallError, complete_text
from app.retrieval.models import RetrievalResult
from app.retrieval.service import RetrievalService

# 判定失败时的默认口径：**判为决策型（不检索）**。
# 理由（与资产里的第 3 条硬规则一致）：漏检索的代价是多问一句，误检索的代价是往用户的
# 决策题里塞一堆无关资料。两个代价不对称，所以默认往「不打扰」那边倒。
DEFAULT_FACTS_REQUIRED = False


class FactCheckParseError(ValueError):
    """模型输出无法解析为合法的判定结果。"""


def parse_fact_checks(text: str, *, count: int) -> list[dict]:
    """把模型输出解析为判定清单，长度恒等于 `count`（缺的按默认口径补齐）。

    容错策略：
    - `index` 越界或重复 → 忽略该条，保留其它；
    - 缺某一条 → 用默认口径（决策型、不检索）补齐，不让整轮判定作废。

    为什么补而不报错：判定只是「要不要检索」的前置，失败退化成「不检索」仍然是可用状态；
    为它让整轮拷问失败，代价远大于收益。
    """
    payload = _extract_json_object(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FactCheckParseError(f"JSON 解析失败：{exc}") from exc

    checks: list[dict] = [_default_check() for _ in range(count)]
    raw = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return checks

    for item in raw:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < count):
            continue
        facts_required = bool(item.get("facts_required"))
        query = str(item.get("fact_query") or "").strip()
        # 判定为事实型却没给查询词：用问题的正文兜底检索，而不是干脆不检索。
        checks[index] = {
            "facts_required": facts_required,
            "fact_query": query,
            "reason": str(item.get("reason") or "").strip(),
        }
    return checks


def _default_check() -> dict:
    return {
        "facts_required": DEFAULT_FACTS_REQUIRED,
        "fact_query": "",
        "reason": "（未给出判定，按决策型处理：不检索）",
    }


def _extract_json_object(text: str) -> str:
    """从可能夹带说明文字或代码围栏的输出中截出最外层 JSON 对象。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise FactCheckParseError("输出中找不到完整的 JSON 对象（可能被截断）")
    return text[start : end + 1]


def judge_questions(
    questions: list[dict], *, model_client, model_name: str | None = None
) -> list[dict]:
    """判定每个问题是否需要外部依据，返回与 `questions` 同序的判定清单。

    模型调用失败时**整体退化为「全不检索」**：拷问不能因为判定环节挂掉而停摆。
    """
    if not questions:
        return []
    try:
        raw = complete_text(
            model_client, render_fact_check_messages(questions), model=model_name
        )
        return parse_fact_checks(raw, count=len(questions))
    except (ModelCallError, FactCheckParseError):
        return [_default_check() for _ in questions]


def attach_citations(
    questions: list[dict],
    checks: list[dict],
    *,
    retrieval: RetrievalService,
) -> list[dict]:
    """给事实型问题挂上检索到的引用；决策型问题保持无引用。

    返回**新的**问题字典列表（不改入参）：前沿问题会落库与回传，就地改容易
    在别处引起「同一个对象两副样子」的问题。

    判定为事实型但未给查询词时，用 `title + body` 兜底：有依据总比没有好。
    """
    enriched: list[dict] = []
    for index, question in enumerate(questions):
        check = checks[index] if index < len(checks) else _default_check()
        item = dict(question)
        if not check.get("facts_required"):
            # 决策型：显式给空清单而不是省略字段——前端据此知道「判过了，不需要检索」，
            # 与「还没判」区分开。
            item["citations"] = []
            item["retrieval_status"] = None
            enriched.append(item)
            continue

        query = str(check.get("fact_query") or "").strip()
        if not query:
            query = f"{question.get('title', '')} {question.get('body', '')}".strip()
        result = retrieval.retrieve(query)
        item["citations"] = to_citation_cards(result)
        item["retrieval_status"] = _status_payload(result)
        enriched.append(item)
    return enriched


def to_citation_cards(result: RetrievalResult) -> list[dict]:
    """把检索命中转成引用卡片（工单 23 的展示契约）。

    每张卡片自带「显示什么」：文件名、段落号、相关度、可折叠所需的摘要。
    默认 `adopted=True`（规格：默认全选，逐条可取消）。
    """
    return [
        {
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "source_id": hit.source_id,
            "name": hit.name,
            "seq": hit.seq,
            "similarity": hit.similarity,
            "paragraph": hit.paragraph,
            "locator_label": hit.locator_label,
            "text": hit.text,
            "adopted": True,
            "collapsible": True,
        }
        for hit in result.hits
    ]


def _status_payload(result: RetrievalResult) -> dict:
    """检索状态（前端据此明示降级 / 未使用知识库，不静默隐藏）。"""
    return {
        "status": result.status.value,
        "status_label": result.status_label,
        "message": result.message,
        "degraded": result.degraded,
        "truncated": result.truncated,
    }


# 取消采用记录的标记：消息 content 以此开头即表示「本轮这些片段不用」。
REJECTED_CITATIONS_PREFIX = "rejected-citations:"


def rejected_citations_content(chunk_ids: list[int]) -> str:
    """把本轮取消采用的片段编号序列化为一条消息内容（工单 23）。

    为什么存成消息而不是新表：这是对话的一部分（「我这次不用这些资料」），与轮次同
    生命周期；下一轮渲染提示词时正好在同一条消息流里读到它，不需要额外的关联查询。
    """
    return REJECTED_CITATIONS_PREFIX + json.dumps(sorted(set(chunk_ids)))


def rejected_chunk_ids(messages: list[dict]) -> set[int]:
    """从消息流里读出所有被取消采用的片段编号。"""
    rejected: set[int] = set()
    for message in messages:
        content = str(message.get("content") or "")
        if not content.startswith(REJECTED_CITATIONS_PREFIX):
            continue
        raw = content[len(REJECTED_CITATIONS_PREFIX) :]
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(values, list):
            rejected.update(int(value) for value in values if isinstance(value, int))
    return rejected


__all__ = [
    "DEFAULT_FACTS_REQUIRED",
    "FactCheckParseError",
    "attach_citations",
    "judge_questions",
    "parse_fact_checks",
    "to_citation_cards",
]
