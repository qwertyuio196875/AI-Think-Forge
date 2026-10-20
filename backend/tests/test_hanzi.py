"""汉字字数计量的测试。

本工单的公开接口就是一个纯函数，没有 HTTP 面：`count_hanzi` / `is_hanzi` 本身
就是接缝，因此这里直接调用它们（与「只能走进程内 HTTP」的仓储/路由测试不同）。
用例钉住规格口径：按汉字计、不含标点与空白、全角标点不计，中英混排时英文与数字不计。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.hanzi import count_hanzi


@pytest.mark.parametrize("text", ["", " ", "\n\t  \r\n", "　　"])
def test_blank_text_counts_zero(text: str) -> None:
    """空串与纯空白（含全角空格 U+3000）都算 0 个汉字。"""
    assert count_hanzi(text) == 0


@pytest.mark.parametrize(
    "text",
    [
        "，。！？；：、（）《》〈〉「」『』【】—…·",
        ",.!?;:()<>[]{}'\"~-_/\\|@#$%^&*+=",
        "“”‘’",
    ],
)
def test_punctuation_only_counts_zero(text: str) -> None:
    """纯标点串（全角与半角各一组）算 0 个汉字。"""
    assert count_hanzi(text) == 0


def test_basic_han_characters_counted_one_each() -> None:
    """基础汉字区每字计 1。"""
    assert count_hanzi("你好世界") == 4


# --- 中英混排：英文单词与数字不计入汉字数 -----------------------------------------


def test_chinese_english_mix_counts_only_han() -> None:
    """中英混排只数汉字：`ThinkForge`、`v1.1`、`2026` 一个也不算。"""
    text = "ThinkForge 是一个 2026 年的 AI 工作台，支持 v1.1 版本。"
    # 汉字：是 一 个 年 的 工 作 台 支 持 版 本（共 12 个）
    assert count_hanzi(text) == 12


def test_digits_and_ascii_punctuation_not_counted() -> None:
    """纯数字与半角标点混排为 0。"""
    assert count_hanzi("2026-10-20 15:21:24 (UTC+8)") == 0


def test_fullwidth_punctuation_not_counted() -> None:
    """全角标点夹在汉字中间不占字数，也不影响相邻汉字的计数。"""
    assert count_hanzi("你好，世界！今天“很”好。") == 8


def test_newlines_and_indent_not_counted() -> None:
    """换行、缩进、段间空行都不计入汉字数。"""
    text = "第一段\n\n    第二段\r\n\t第三段\n"
    assert count_hanzi(text) == 9


# --- 汉字范围：扩展区计入，假名/谚文等非汉字不计 ---------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\u3400\u3401\u3402", 3),  # 扩展 A
        ("\uf900\uf901", 2),  # 兼容表意文字
        ("\U00020000\U00020001", 2),  # 扩展 B（超出 BMP）
        ("ひらがなカタカナ", 0),  # 日文假名
        ("한국어", 0),  # 谚文
        ("ㄅㄆㄇ", 0),  # 注音符号
        ("〇〡〢", 0),  # 表意数字符号（不是汉字字形）
    ],
)
def test_only_han_characters_are_counted(text: str, expected: int) -> None:
    """汉字扩展区照样计 1；假名、谚文、注音符号不是汉字，不计。"""
    assert count_hanzi(text) == expected


def test_ideographic_space_is_whitespace_not_han() -> None:
    """U+3000 是全角空格，属于空白，不算汉字。"""
    assert count_hanzi("你\u3000好") == 2


# --- 全仓唯一实现（验收点：任何调用方不得另写一套）---------------------------------

# 汉字码位的写法合集：调用方若自己写一套，必然要重新列出这些区间。
# 覆盖 Python 的 `0x4E00`、`\u4e00`、`\U00020000` 与 TS 正则常用的 `\u{4e00}`、`U+4E00`。
_HAN_RANGE_PATTERN = re.compile(
    r"0x([0-9A-Fa-f]{4,6})"
    r"|\\u\{?([0-9A-Fa-f]{4,6})\}?"
    r"|\\U([0-9A-Fa-f]{8})"
    r"|U\+([0-9A-Fa-f]{4,6})"
)
_HAN_RANGE_MARKERS = {
    0x3400,
    0x4DBF,
    0x4E00,
    0x9FFF,
    0xF900,
    0xFAFF,
    0x20000,
    0x2FA1F,
}


def _han_range_hits(path: Path) -> list[str]:
    """返回该文件里出现的汉字码位字面量（逐行文本）。"""
    source = path.read_text(encoding="utf-8")
    hits: list[str] = []
    for line in source.splitlines():
        for match in _HAN_RANGE_PATTERN.finditer(line):
            digits = next(group for group in match.groups() if group)
            if int(digits, 16) in _HAN_RANGE_MARKERS:
                hits.append(line.strip())
                break
    return hits


def test_han_counting_exists_in_exactly_one_module() -> None:
    """汉字码位区间只允许出现在 `app/hanzi.py`：全仓不得有第二套计量。

    这是架构守卫：新增调用方应 import `count_hanzi`，而不是再抄一遍区间。
    前端同理——界面上的字数必须来自后端返回字段，不能在 TS 里重算。
    """
    repo_root = Path(__file__).resolve().parents[2]
    allowed = {repo_root / "backend" / "app" / "hanzi.py"}
    scanned_roots = [
        repo_root / "backend" / "app",
        repo_root / "frontend" / "src",
    ]
    suffixes = {".py", ".ts", ".mts", ".vue"}

    offenders: dict[str, list[str]] = {}
    for root in scanned_roots:
        for path in root.rglob("*"):
            if path.suffix not in suffixes or path in allowed:
                continue
            hits = _han_range_hits(path)
            if hits:
                offenders[str(path.relative_to(repo_root))] = hits

    assert offenders == {}, f"发现第二套汉字计量实现：{offenders}"
