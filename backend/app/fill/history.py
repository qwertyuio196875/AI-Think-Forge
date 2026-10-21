"""前情提要：把已写完的章压成摘要，累积起来喂给下一章（工单 12 / ADR-0006）。

**为什么要有它**：逐章填充时，第 N 章若不知道前面写了什么，每章都像独立写出来的，
拼起来是一堆互不相干的短文。这段摘要是唯一跨章传递上下文的载体。

**三条纪律**：
1. **摘要调用与正文调用分开**：摘要失败**不阻断**正文生成——正文才是用户要的东西，
   提要只是辅助。摘要挂了，这一章照写，下一章少一段承接而已。
2. **摘要有长度上限**：每章约 100 字，累积到几十章也不过几千字，不会把上下文撑爆。
3. **只喂已写完的章**：第一章的前情提要是空的，此时**不喂**「暂无」占位——
   那个占位会白占 token，还可能让模型以为前面真有一段没写的内容。
"""

from __future__ import annotations

from app.fill.prompts import render_summary_messages
from app.providers.model_client import complete_text

# 摘要调用的按次参数（#3）：摘要很短，输出上限与超时都压得比正文小得多。
SUMMARY_MAX_TOKENS = 512
SUMMARY_TIMEOUT_SECONDS = 60.0

# 单条摘要的汉字上限（超出截断）。提示词要求约 100 字，这里是兜底：
# 模型偶尔会返回一整段，累积起来会把上下文撑爆。
SUMMARY_MAX_HANZI = 200


def summarize_section(
    *,
    model_client,
    model_name: str | None,
    title: str,
    body_md: str,
) -> str | None:
    """把一章正文压成摘要；失败或空返回 None（调用方按「没有提要」处理）。

    返回 None 而不是抛错：摘要失败不该让整章白写。
    """
    if not body_md.strip():
        return None

    try:
        summary = complete_text(
            model_client,
            render_summary_messages(title=title, body_md=body_md),
            model=model_name,
            max_tokens=SUMMARY_MAX_TOKENS,
            timeout=SUMMARY_TIMEOUT_SECONDS,
        ).strip()
    except Exception:  # noqa: BLE001 - 摘要是可降级的辅助，失败只丢这段提要
        return None

    if not summary:
        return None
    return _truncate_hanzi(summary, SUMMARY_MAX_HANZI)


def build_history(summaries: list[str]) -> str | None:
    """把各章摘要拼成一段前情提要；一段都没有时返回 None（第一章不喂占位）。"""
    parts = [text.strip() for text in summaries if text and text.strip()]
    if not parts:
        return None
    return "\n".join(parts)


def _truncate_hanzi(text: str, limit: int) -> str:
    """按汉字数截断（超限处补省略号）。

    截断按**汉字**计，与全文的计量口径一致（`app.hanzi`）——但这里要保留标点，
    所以用字符数近似即可：摘要是模型自己的短文本，不参与任何字数校验。
    """
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
