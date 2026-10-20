"""资料分析的提示词资产（逐块分析 + 综合），版本号随契约变化。

纪律（规格 US 12 / 17）：
- 只据给定原文提炼，**不虚构事实**、不补写原文没有的数据；
- 不凑字重复；总结 ≤500 汉字；
- 逐块只做压缩，不做跨块猜测；综合只合并已出现的信息。
"""

from __future__ import annotations

CHUNK_PROMPT_VERSION = "analysis-chunk-v1"
SUMMARY_PROMPT_VERSION = "analysis-summary-v1"

CHUNK_SYSTEM_PROMPT = """你是资料分析管线的逐块分析助手。只依据用户给出的这一段原文提炼，
不得补充原文没有的事实、数字或结论。输出简体中文，控制在 200 字内，按下面四行给出：
主题：<这一块在讲什么>
核心观点：<作者的主张>
关键内容：<支撑观点的事实 / 论据 / 数据>
结论：<这一块自己的结论；没有就写「无明确结论」>
不要使用 Markdown 标题，不要重复原文整段。"""

SUMMARY_SYSTEM_PROMPT = """你是资料分析管线的综合助手。把多段逐块分析合并成一份总结，
只使用逐块分析里已经出现的主题、观点、事实与数据，**不得虚构**，不得凑字重复。
输出简体中文，**不超过 500 个汉字**，按下面结构各起一行：
主题：<一句话>
核心观点：<2~4 条，用「；」分隔>
关键内容：<3~6 条，含重要数据>
结论：<1~2 句>
不要输出 Markdown 标题或额外解释。"""


def render_chunk_messages(
    text: str, *, seq: int, total: int, source_name: str
) -> list[dict[str, str]]:
    """逐块分析的消息：附块序号 / 总数与来源名，便于模型保持上下文边界。"""
    return [
        {"role": "system", "content": CHUNK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"来源：{source_name}\n"
                f"这是第 {seq} / {total} 块。原文如下：\n\n{text}"
            ),
        },
    ]


def render_summary_messages(
    chunk_notes: list[str], *, source_name: str
) -> list[dict[str, str]]:
    """综合的消息：输入是逐块分析结果（不是原文），避免重复消耗长文 token。"""
    joined = "\n\n".join(
        f"【第 {index} 块分析】\n{note}" for index, note in enumerate(chunk_notes, start=1)
    )
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"来源：{source_name}\n共 {len(chunk_notes)} 块。逐块分析如下：\n\n{joined}",
        },
    ]
