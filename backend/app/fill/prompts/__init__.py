"""填充提示词资产：版本化加载与渲染（工单 10 / ADR-0006）。

设计要点与拷问 / 方案提示词一致（ADR-0001）：
- 资产以版本化文件固化（`fill_v1.md`），代码只经版本常量引用，规则不散落；
- 「填充」是本系统唯一的写作环节，规则写进资产而非交给模型自由心证。

两类资产：
- `fill-v1`：把一章扩写成正文；
- `summary-v1`（工单 12）：把已写完的一章压成约 100 字摘要，供下一章承接。

工单 10 只提供**单章**的正文提示词渲染。上下文里的「剩余字数」（#16）与
「本次引用片段」（#24）留了位置但**暂不填**：它们由各自的工单接上。
"""

from __future__ import annotations

from pathlib import Path

FILL_PROMPT_VERSION = "fill-v1"
SUMMARY_PROMPT_VERSION = "summary-v1"

_ASSET_BY_VERSION = {
    FILL_PROMPT_VERSION: "fill_v1.md",
    SUMMARY_PROMPT_VERSION: "summary_v1.md",
}

# 上下文里暂时留空的位置的占位说明。写清楚「暂无」比留一段空白更可控：
# 模型不会把空区块当成「用户没要求」，也不会自己编。
_NO_HISTORY = "（暂无：这是第一章，前面没有已写内容）"
_NO_REMAINING = "（暂无：本次不按剩余字数收敛）"
_NO_CITATIONS = "（暂无：本次没有使用知识库资料）"


def load_asset(version: str = FILL_PROMPT_VERSION) -> str:
    """读取指定版本的填充提示词资产原文。"""
    filename = _ASSET_BY_VERSION.get(version)
    if filename is None:
        raise ValueError(f"未知的填充提示词版本：{version}")
    return (Path(__file__).parent / filename).read_text(encoding="utf-8")


def render_section_messages(
    *,
    title: str,
    key_points: str,
    target_length: int | None,
    history: str | None = None,
    remaining_length: int | None = None,
    citations: str | None = None,
) -> list[dict]:
    """渲染「把一章扩写成正文」的对话消息。

    上下文按「已知 → 待写 → 约束」三段给：先说已写内容（跨章承接，#12 接手），
    再说本章要写什么，最后给字数与可用的资料片段（#16 / #24 接手）。缺省的那几项
    显式写「暂无」，模型不会误以为那是用户的话。
    """
    system = load_asset(FILL_PROMPT_VERSION)
    user = (
        "## 前情提要（前面已写内容的摘要）\n"
        f"{history or _NO_HISTORY}\n\n"
        "## 本章标题\n"
        f"{title}\n\n"
        "## 本章要点（必须围绕它展开，但不要照抄成条目）\n"
        f"{key_points or '（暂无：只按本章标题展开）'}\n\n"
        "## 本章目标字数（按汉字计，不含标点与空白）\n"
        f"{target_length if target_length is not None else '（暂无：请写一个完整的短章）'}\n\n"
        "## 剩余字数（全文还剩多少）\n"
        f"{remaining_length if remaining_length is not None else _NO_REMAINING}\n\n"
        "## 本次可用的资料片段\n"
        f"{citations or _NO_CITATIONS}\n\n"
        "## 本轮任务\n"
        "请按上面的规则输出本章正文 Markdown：以 `##` 小标题分小节，"
        "写出可以连读成文的段落；不要出现一级标题（`#`），不要输出代码围栏或 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_summary_messages(*, title: str, body_md: str) -> list[dict]:
    """渲染「把已写完的一章压成约 100 字摘要」的对话消息（工单 12）。

    摘要的唯一用途是给**下一章**做承接，所以输入只有「本章标题 + 本章正文」，
    不给方案、不给字数——摘要不需要对齐任何篇幅指标。
    """
    system = load_asset(SUMMARY_PROMPT_VERSION)
    user = (
        "## 本章标题\n"
        f"{title}\n\n"
        "## 本章正文（已写完）\n"
        f"{body_md}\n\n"
        "## 本轮任务\n"
        "请按上面的规则输出这段正文的摘要：约 100 个汉字，平实陈述，"
        "只说已经写过的内容；不要标题、不要列表、不要任何前后缀。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
