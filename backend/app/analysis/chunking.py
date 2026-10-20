"""长文分块（分析管线的一环，**不是 RAG**，见 ADR-0005）。

分块只服务于「单份资料：分块 → 逐块分析 → 综合」的 map-reduce，本模块自身
不建索引、不做跨文档检索、不写嵌入。ADR-0005 起同一套分块**同时**是知识库
检索的粒度（向量按分块写入），所以分块参数改动需要重建索引。
分块目标约 1200 字符，按解析出的块边界切分，绝不把一段话从中间切开
（超长单块才按句读二次切分）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analysis.parsing import ParsedBlock

# 单块目标字符数与硬上限：目标用于控制模型调用次数与单次输入长度。
CHUNK_TARGET_CHARS = 1200
CHUNK_MAX_CHARS = 1800

# 超长单块二次切分时优先在这些句读后断开。
_SENTENCE_ENDINGS = tuple("。！？；!?;\n")


@dataclass(frozen=True)
class Chunk:
    """一个文本分块：序号（1 起）、正文、定位信息（写进 `locator_json`）。"""

    seq: int
    text: str
    locator: dict[str, Any]


def build_chunks(blocks: list[ParsedBlock], file_format: str) -> list[Chunk]:
    """把解析块切成有序分块；空块列表返回空分块（调用方按未识别处理）。"""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    start_locator: dict[str, Any] | None = None
    end_locator: dict[str, Any] | None = None
    buffered_chars = 0

    def flush() -> None:
        nonlocal buffer, start_locator, end_locator, buffered_chars
        if not buffer or start_locator is None or end_locator is None:
            return
        chunks.append(
            Chunk(
                seq=len(chunks) + 1,
                text="\n\n".join(buffer).strip(),
                locator={
                    "format": file_format,
                    "start": start_locator,
                    "end": end_locator,
                },
            )
        )
        buffer = []
        start_locator = None
        end_locator = None
        buffered_chars = 0

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        if len(text) > CHUNK_MAX_CHARS:
            flush()
            for piece_index, piece in enumerate(_split_long_text(text), start=1):
                locator = {**block.locator, "part": piece_index}
                chunks.append(
                    Chunk(seq=len(chunks) + 1, text=piece, locator=locator)
                )
            continue

        if buffered_chars and buffered_chars + len(text) > CHUNK_TARGET_CHARS:
            flush()

        if start_locator is None:
            start_locator = block.locator
        end_locator = block.locator
        buffer.append(text)
        buffered_chars += len(text)

    flush()
    return chunks


def _split_long_text(text: str) -> list[str]:
    """超长单块按句读切到硬上限内；找不到句读时硬切（不丢内容）。"""
    pieces: list[str] = []
    remaining = text
    while len(remaining) > CHUNK_MAX_CHARS:
        window = remaining[:CHUNK_MAX_CHARS]
        cut = max(window.rfind(ending) for ending in _SENTENCE_ENDINGS) + 1
        if cut <= 0:
            cut = CHUNK_MAX_CHARS
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]
