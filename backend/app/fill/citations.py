"""填充阶段的引用片段处理（工单 24 / ADR-0005）。

职责三件：
- **格式化**：把「本章可用的引用片段」渲染成给模型的提示词区块文本；
- **采纳过滤**：只保留用户勾选保留的片段（界面上的取消必须真的生效）；
- **参考资料**：把一章实际采用的片段序列化/反序列化为 `references_json`，
  供成品拼装时聚合为「参考资料」清单。

消费的是工单 23 的检索结果 `to_citation_cards()` 产出的卡片：每个卡片自带
`name` / `locator_label` / `text`，本模块不做检索、不懂检索，只处理卡片列表。
"""

from __future__ import annotations

import json

# 填充提示词里「本次没有可用资料片段」的占位说明。空引用块也必须是明确的
# 「没有」，不能让模型把空区块当作用户的影射。
_NO_CITATIONS_TEXT = "（暂无：本次没有使用知识库资料）"


def render_citations_block(cards: list[dict]) -> str:
    """把「已采纳的引用片段」渲染成提示词区块文本。

    只渲染卡片里 `adopted` 为真的片段——取消必须真的生效。每段带出处（来源名 +
    定位），模型引用时能说明依据。返回的字符串尾部无多余空行，避免提示词里叠出
    空白陷阱。
    """
    adopted = [card for card in cards if card.get("adopted")]
    if not adopted:
        return _NO_CITATIONS_TEXT
    lines: list[str] = []
    for card in adopted:
        title = f"《{card.get('name', '未知资料')}》{card.get('locator_label', '')}".strip()
        lines.append(f"### {title}")
        lines.append(str(card.get("text", "")).strip())
        lines.append("")
    return "\n".join(lines).strip()


def serialize_references(cards: list[dict]) -> str:
    """把一章**实际采用**的引用卡片序列化存库。

    只存 `adopted` 的卡片，且每条保留检索卡片的关键字段（出处 + 定位 + 摘要），
    不要塞进 `text`/`collapsible` 之外的临时字段——存的是「这一章用了哪些资料」，
    不是「前端当时怎么展示」。
    """
    adopted = [card for card in cards if card.get("adopted")]
    kept: list[dict] = []
    for card in adopted:
        kept.append(
            {
                "chunk_id": card.get("chunk_id"),
                "document_id": card.get("document_id"),
                "source_id": card.get("source_id"),
                "name": card.get("name"),
                "locator_label": card.get("locator_label"),
                "paragraph": card.get("paragraph"),
            }
        )
    return json.dumps(kept, ensure_ascii=False)


def render_references_section(cards_by_section: list[list[dict]]) -> str:
    """把各章实际采用的引用聚合成成品的「参考资料」章节 Markdown。

    `cards_by_section` 是一份方案所有已完成章节的 `read_references()` 结果，按章节
    顺序传入。聚合规则：
    - **只列实际用到的来源**：空章节 / 没引用的章节不出现在清单里；
    - **去重**：同一 chunk 在多个章节被多次采用，只列一次（参考资料是出处清单，
      不是逐条引用计数）；
    - **保序**：按首次出现的顺序排列，稳定可复现。
    不空返回空串，调用方决定是否拼进成品。
    """
    seen: set[int] = set()
    ordered: list[dict] = []
    for section_cards in cards_by_section:
        for card in section_cards:
            chunk_id = card.get("chunk_id")
            if chunk_id is not None and chunk_id in seen:
                continue
            if chunk_id is not None:
                seen.add(chunk_id)
            ordered.append(card)

    if not ordered:
        return ""

    lines = ["## 参考资料"]
    for index, card in enumerate(ordered, start=1):
        name = str(card.get("name") or "未知资料")
        locator = str(card.get("locator_label") or "").strip()
        title = f"{name} {locator}".strip() if locator else name
        lines.append(f"{index}. {title}")
    return "\n".join(lines)