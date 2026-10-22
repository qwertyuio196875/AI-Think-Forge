"""中文关键词检索的分词与打分（工单 22 / ADR-0005 补充说明）。

**分词方案已定死：二元组（bigram）匹配，不引入分词库。**

为什么是二元组而不是 jieba 之类的分词器：

- **零新增依赖**。ADR-0005 选定的技术路线是「SQLite 存块 + 内存 numpy 暴力余弦，
  零新依赖、零额外服务」。为一个降级路径引入分词库，等于给整个项目加一条
  「词表要维护、版本要跟」的长期负担，与该路线的取舍相反。
- **bigram 对中文短文本召回足够**。知识库检索面对的是「一句提问」这种短查询，
  用户与文档共享的往往就是相邻两字（「分块」「注入」「降级」），二元组恰好覆盖
  这类重合。
- **不需要人工维护词表**。分词器要定期更新词典才能跟上新词；bigram 永远与语料
  同步，代价是精确率偏低——这由既有的**阈值 + top-k** 两道闸兜住（见下）。

**二元组的已知代价与对策**：精确率低、召回偏高，容易把「恰好提到同一个词」的
片段也捞进来。对策不是「调一个更好的打分公式」，而是复用规格已经定死的两道闸：

1. **阈值**：覆盖率低于 `MIN_SIMILARITY`（0.3）的片段一律丢弃——宁可不给；
2. **条数**：最多 `TOP_K`（6）条，弱相关的自然被挤出去。

**打分公式选「查询侧覆盖率」**（命中词元数 ÷ 查询词元数）而不是 Jaccard / Dice：
覆盖率只看「查询的词有多少被召回」，不受分块长短影响。分块器切出的块大小差异
很大（600–1800 字符），用 Jaccard 会让长块天然吃亏——这正是向量检索里
「块内主题太杂、语义被平均掉」的同一个毛病。

**为什么单字不成词**：`的`、`是`、`怎` 这类单字在几乎每份资料里都出现，
参与匹配会让任何查询都命中一大片无关内容。因此只取二元组（汉字）与整词
（连续的字母 / 数字），单字与标点一律丢弃。
"""

from __future__ import annotations

from app.hanzi import is_hanzi

# 词元最小长度：汉字取二元组（2 字），拉丁词 / 数字至少 2 个字符。
# 单字符词元（"a"、"3"）信息量太低，容易造成误命中，一律丢弃。
MIN_TOKEN_LENGTH = 2


def bigram_tokens(text: str) -> set[str]:
    """把文本切成检索词元集合（顺序无关，重复只算一次）。

    切分规则：

    - **连续汉字**：取相邻两字的二元组（`知识库` → `知识`、`识库`）；成段只有
      一个汉字时不产出词元（单字太弱，见模块说明）；
    - **连续的字母 / 数字**：按整词保留并转小写（`PPT` → `ppt`、`16` → `16`），
      免得 `PPT` 与 `ppt` 被当成两个词；
    - **标点、空白与其它符号**：只起分隔作用，不进入词元。

    返回空集合表示「这段文本没有可检索的词」——调用方据此判定「查不到」，
    而不是拿空集合去做除零。
    """
    tokens: set[str] = set()
    hanzi_run: list[str] = []
    latin_run: list[str] = []

    def flush_hanzi() -> None:
        if len(hanzi_run) >= 2:
            for index in range(len(hanzi_run) - 1):
                tokens.add(hanzi_run[index] + hanzi_run[index + 1])
        hanzi_run.clear()

    def flush_latin() -> None:
        if len(latin_run) >= MIN_TOKEN_LENGTH:
            tokens.add("".join(latin_run))
        latin_run.clear()

    for character in text.lower():
        if is_hanzi(character):
            flush_latin()
            hanzi_run.append(character)
        elif character.isascii() and character.isalnum():
            flush_hanzi()
            latin_run.append(character)
        else:
            flush_hanzi()
            flush_latin()

    flush_hanzi()
    flush_latin()
    return tokens


def keyword_coverage(query_tokens: set[str], document_tokens: set[str]) -> float:
    """查询侧覆盖率：查询词元被文档覆盖的比例，范围 `[0, 1]`。

    - 查询或文档任一为空 → 0（不匹配，不做除零）；
    - 全部命中 → 1.0；一个没命中 → 0.0。

    只看「查询被覆盖了多少」，不看文档有多少词——理由见模块说明。
    """
    if not query_tokens or not document_tokens:
        return 0.0
    return len(query_tokens & document_tokens) / len(query_tokens)
