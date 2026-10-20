"""资料分析管线：解析结果 → 分块 → 逐块分析 → 综合（map-reduce）。

**命名纪律（ADR-0002）**：这是分析管线，不是 RAG。它只处理用户刚上传的单份资料，
不建索引、不做跨文档检索、不填充嵌入表（`embeddings` 仅按 ADR-0002 预留）。

- 未识别内容命中即**短路**：没有文本块就不调用模型、不生成空总结；
- 总结默认 ≤500 汉字；模型给长了就按句读收敛并记 `truncated`；
- 总结走 **turbo** 档（规格：主流程 plus、总结流程 turbo），由 `TieredModelClient`
  解析；该档缺失时回退默认并如实记录实际所用 provider。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.chunking import Chunk
from app.analysis.parsing import ParsedDocument
from app.analysis.prompts import (
    CHUNK_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
    render_chunk_messages,
    render_summary_messages,
)
from app.hanzi import count_hanzi, is_hanzi
from app.providers.model_client import complete_text
from app.providers.tiered_client import (
    SUMMARY_PROVIDER_KIND,
    ResolvedModelClient,
    TieredModelClient,
)

# 总结长度上限：规格 US 12「默认总结在 500 汉字内」。汉字计数不含标点 / 数字 / 西文。
SUMMARY_MAX_HANZI = 500
# 收敛时优先回退到最后一个完整句子；短于这个比例才硬切。
_SENTENCE_CUT_MIN_RATIO = 0.6
_SENTENCE_ENDINGS = tuple("。！？；!?;")


class SummaryGenerationError(ValueError):
    """模型未返回可用的总结内容（可读提示，不落空总结）。"""


@dataclass(frozen=True)
class SummaryOutcome:
    """一次综合的结果：总结正文 + 长度 / 分块数 / 截断标记 + 实际档位解析结果。"""

    text: str
    hanzi_count: int
    chunk_count: int
    truncated: bool
    resolved: ResolvedModelClient
    chunk_prompt_version: str = CHUNK_PROMPT_VERSION
    summary_prompt_version: str = SUMMARY_PROMPT_VERSION


def primary_unrecognized(parsed: ParsedDocument) -> dict | None:
    """整份资料读不出文本时的一级未识别契约；有文本块则返回 None。

    原因优先取解析器给出的 `empty_reason`（PDF / PPTX 无文本层时显式给
    `no_text_layer`），否则按图片数量推断（DOCX 的既有口径）。`needs_ocr` 表示
    「这段内容要靠 OCR 才能读」——扫描件 / 图片型文件为真，纯空白文件为假。
    """
    if parsed.blocks:
        return None

    reason = parsed.empty_reason or (
        "no_text_layer" if parsed.images else "empty_document"
    )
    return {
        "unrecognized": True,
        "reason": reason,
        "locator": {"format": parsed.format, "images": parsed.images},
        "needs_ocr": parsed.images > 0 or reason == "no_text_layer",
    }


def unrecognized_parts(parsed: ParsedDocument) -> list[dict]:
    """有文本但仍有读不到的内容（图片 / 图表 / 浮动对象）时逐项明示，不伪装成完整分析。

    版式类解析器（PDF / PPTX）逐项给出页 / 幻灯片级 locator，直接透传；DOCX 没有
    逐项信息，沿用「图片数量」的既有口径（契约不变）。
    """
    if not parsed.blocks:
        return []
    if parsed.unread_parts:
        return list(parsed.unread_parts)
    if not parsed.images:
        return []
    return [
        {
            "unrecognized": True,
            "reason": "images_not_read",
            "locator": {"format": parsed.format, "images": parsed.images},
            "needs_ocr": True,
        }
    ]


def analyze_chunks(
    chunks: list[Chunk],
    *,
    source_name: str,
    resolver: TieredModelClient,
    provider_id: int | None = None,
) -> SummaryOutcome:
    """逐块分析 N 次 + 综合 1 次（脚本化模型下可精确计数）。

    一次分析只解析一次档位；N 个分块对应 N 次逐块调用，最后恰好 1 次综合调用。
    `provider_id` 非空时表示来源所属任务 pin 了 provider（US23），透传给解析器。
    """
    if not chunks:
        raise SummaryGenerationError("没有可分析的分块")

    resolved = resolver.resolve(SUMMARY_PROVIDER_KIND, provider_id=provider_id)
    total = len(chunks)
    notes: list[str] = []
    for chunk in chunks:
        note = complete_text(
            resolved.client,
            render_chunk_messages(
                chunk.text,
                seq=chunk.seq,
                total=total,
                source_name=source_name,
            ),
            model=resolved.model_name,
        ).strip()
        notes.append(note or "（本块未提炼出内容）")

    summary = complete_text(
        resolved.client,
        render_summary_messages(notes, source_name=source_name),
        model=resolved.model_name,
    ).strip()
    if not summary:
        raise SummaryGenerationError("模型未返回总结内容")

    limited, truncated = limit_summary(summary)
    return SummaryOutcome(
        text=limited,
        hanzi_count=count_hanzi(limited),
        chunk_count=total,
        truncated=truncated,
        resolved=resolved,
    )


def limit_summary(text: str, *, max_hanzi: int = SUMMARY_MAX_HANZI) -> tuple[str, bool]:
    """把总结收敛到 `max_hanzi` 个汉字内，返回 (正文, 是否截断)。

    超长时优先在最后一个句读处收束（至少覆盖 60% 上限），否则硬切并补省略号。
    省略号不占汉字计数，因此结果一定 ≤ 上限。
    """
    normalized = text.strip()
    if count_hanzi(normalized) <= max_hanzi:
        return normalized, False

    counted = 0
    hard_cut = len(normalized)
    for index, character in enumerate(normalized):
        if is_hanzi(character):
            counted += 1
            if counted == max_hanzi:
                hard_cut = index + 1
                break

    prefix = normalized[:hard_cut]
    # 取「不短于 60% 上限」的最靠后一个句读位置；没有就硬切。
    positions = [
        position
        for ending in _SENTENCE_ENDINGS
        if (position := prefix.rfind(ending) + 1) >= hard_cut * _SENTENCE_CUT_MIN_RATIO
    ]
    cut = max(positions) if positions else hard_cut

    limited = normalized[:cut].rstrip()
    if not limited.endswith(_SENTENCE_ENDINGS):
        limited = limited.rstrip("，,、；; ") + "…"
    return limited, True
