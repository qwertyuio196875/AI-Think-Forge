"""汉字字数计量：全仓唯一入口。

规格（#2「字数控制」）明文：目标字数按**汉字**计，不含标点与空白；计量函数是
唯一入口，任何地方不得另写一套。因此这里只放这一个函数，不做任何业务判断。

口径（写死在这里，调用方不要再各写一套）：

- 只数汉字本身，标点、空白（含全角空格）、换行都不计；
- 英文单词、数字、拉丁字母、注音符号等非汉字字符都不计——「按汉字算」就是
  只数汉字字形，混排里的英文与数字不折算、不按词计；
- 汉字范围取 CJK 统一表意文字（含扩展 A / 兼容区 / 扩展 B 及以后），
  不把日文假名、谚文当汉字。

前端（界面显示字数）不另写一套：它读后端返回的字数字段，见 `fill` 模块把
`count_hanzi` 的结果放进响应。
"""

from __future__ import annotations

# 汉字所在的码位区间。扩展 B 及以后超出 BMP，用 int 直接比码位，天然覆盖。
_HAN_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),  # CJK 扩展 A
    (0x4E00, 0x9FFF),  # CJK 统一表意文字（基本区）
    (0xF900, 0xFAFF),  # CJK 兼容表意文字
    (0x20000, 0x2FA1F),  # CJK 扩展 B 及以后 + 兼容补充
)


def is_hanzi(character: str) -> bool:
    """单个字符是否为汉字（不含标点、假名、谚文）。

    传空串会抛 `TypeError`：这里只判断「一个字符」，调用方负责别传空。
    """
    codepoint = ord(character)
    return any(low <= codepoint <= high for low, high in _HAN_RANGES)


def count_hanzi(text: str) -> int:
    """统计 `text` 中的汉字个数；空串为 0，纯标点/空白串为 0。"""
    return sum(1 for character in text if is_hanzi(character))
