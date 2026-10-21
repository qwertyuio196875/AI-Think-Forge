"""长章分段写作（工单 17 / ADR-0006）。

**为什么需要它**：模型单次输出有硬上限（`app.providers.openai_client` 的 4096 token
默认值，写作路径按次覆盖到 8192）。8000 汉字的单章一次写不完，而「写不完」在真实
客户端上的表现是 `finish_reason == "length"` → `ModelCallError`（不是悄悄返回半篇）。
所以长章必须拆成多次调用，每次写一段，再按段落边界拼起来。

**四条纪律**（对应工单 17 的验收）：

1. **不静默截断**：任一分段命中长度上限，`ModelCallError` 直接上抛，由调用方翻成
   502。绝不把已经写好的前几段当成品交出去——那是「半篇文章」。
2. **不重复、不丢失**：分段按顺序累加，每段的正文原样接在上一段之后；拼接只发生在
   段落边界（`\\n\\n`），绝不把两段的句子粘成一句。
3. **累计校验字数**：每写完一段就用唯一计量入口 `app.hanzi.count_hanzi` 数一遍累计
   汉字数，达到目标即停；剩余额度逐段递减地传给模型（「还剩多少字」）。
4. **把已写结尾喂回去**：第二段起带上上一段的结尾，让模型接着往下写，而不是把已经
   写过的内容重写一遍。

分段阈值是**保守的**：短章仍走单次调用（`write_section` 的分支），不为分段而分段——
多调一次就多一次费用与一次失败机会。
"""

from __future__ import annotations

from app.fill.prompts import render_section_messages
from app.hanzi import count_hanzi
from app.providers.model_client import ModelCallError, complete_text

# 超过这个汉字数才分段。定在 3000：8192 token 的输出上限对中文大约能容下 3000~4000
# 汉字，低于它就一次写得完，多调一次只是多花钱、多一次失败机会。
SEGMENT_THRESHOLD_HANZI = 3000

# 每一段向模型要的字数。2000 汉字在 8192 token 上限下仍有余量，且比 3000 更不容易
# 碰到截断——分段的意义正是不让任何一次调用贴到上限。
SEGMENT_TARGET_HANZI = 2000

# 每段至少要写下这么多汉字，否则判定为「模型没在推进」，提前收工。
# 不设这个下限的话，一个总是返回空串的模型会让循环跑满轮次、白烧额度。
SEGMENT_MIN_PROGRESS_HANZI = 200

# 把已写结尾喂回去时保留的字符数：够模型接上文风与话头，又不至于让上下文膨胀。
CONTINUATION_TAIL_CHARS = 400


def needs_segmentation(target_length: int | None) -> bool:
    """这一章是否需要分段。`None`（方案没给建议字数）不分段：没有目标就无从拆。"""
    return target_length is not None and target_length > SEGMENT_THRESHOLD_HANZI


def write_body_segmented(
    *,
    model_client,
    model_name: str | None,
    title: str,
    key_points: str,
    target_length: int,
    history: str | None,
    max_tokens: int,
    timeout: float,
    citations: str | None = None,
) -> str:
    """分段写完一章正文，返回按段落拼好的 Markdown。

    调用方保证 `target_length > SEGMENT_THRESHOLD_HANZI`（见 `needs_segmentation`）。

    失败语义：任一分段抛 `ModelCallError` 即整体失败，原样上抛——**不返回已写的前几段**。
    """
    parts: list[str] = []
    written = 0
    max_rounds = _max_rounds(target_length)

    for _ in range(max_rounds):
        remaining = target_length - written
        if remaining <= 0:
            break

        # 每次只向模型要「这一段」的量，并把剩余额度如实告诉它，避免一路超出去。
        segment_target = min(SEGMENT_TARGET_HANZI, remaining)
        messages = render_section_messages(
            title=title,
            key_points=key_points,
            target_length=segment_target,
            history=history,
            remaining_length=remaining,
            citations=citations,
            continuation=_tail(parts),
        )

        segment = complete_text(
            model_client,
            messages,
            model=model_name,
            max_tokens=max_tokens,
            timeout=timeout,
        ).strip()

        if not segment:
            # 模型没给正文：已经写下的部分仍然有效（多段里有一段空，不该抹掉前面的）。
            # 若一段都没写成，交给调用方按「没有返回正文」处理。
            break

        parts.append(segment)
        progress = count_hanzi(segment)
        written += progress
        if progress < SEGMENT_MIN_PROGRESS_HANZI:
            # 明显没在推进（例如模型只回了一句「好的」）：停止追加轮次，避免空转烧额度。
            break

    return _join(parts)


def _max_rounds(target_length: int) -> int:
    """分段轮次上限。

    按「每段至少 500 汉字」估：目标越大允许的轮次越多；再留 2 轮余量，好让模型某次
    写得短时仍能补齐。上限存在的意义是防止死循环，不是精确的段数。
    """
    return max(2, (target_length // 500) + 2)


def _tail(parts: list[str]) -> str | None:
    """已写内容的结尾，供下一段承接；第一段为 None（提示词里给「暂无」）。"""
    if not parts:
        return None
    return parts[-1][-CONTINUATION_TAIL_CHARS:]


def _join(parts: list[str]) -> str:
    """按**段落边界**拼接分段：段与段之间留一个空行。

    不直接用 `"".join`：那会把两段的句子粘成一句（上一段结尾没有换行时尤为明显）。
    也不做任何「去重」：两段内容若真的一样，那是模型的重复，应当被看见，而不是被
    悄悄删掉一半——静默改写用户拿到的正文比重复更糟。
    """
    cleaned = [part.strip() for part in parts if part.strip()]
    return "\n\n".join(cleaned)


__all__ = [
    "CONTINUATION_TAIL_CHARS",
    "SEGMENT_MIN_PROGRESS_HANZI",
    "SEGMENT_TARGET_HANZI",
    "SEGMENT_THRESHOLD_HANZI",
    "ModelCallError",
    "needs_segmentation",
    "write_body_segmented",
]
