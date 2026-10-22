"""拷问提示词资产：版本化加载与渲染。

设计要点（工单 11 / 12，ADR-0001）：
- 提示词以**版本化资产**固化在 `grilling_v1.md` / `plan_v1.md`，代码只经版本常量引用，
  规则不散落在多个文件里；
- 资产保留 MIT 署名（基于 Matt Pocock 的 grilling 技能规则适配），并显式记录移植偏离；
- 渲染函数把用户原始输入作为「已知信息」、把**历轮问答与已确定决策**一并喂进提示词：
  这是「下一轮问题按上一轮回答重算」而非固定问题集的依据，也可被测试断言。

资产中的 `%%MAX_QUESTIONS%%` 占位在渲染时替换为 `MAX_FRONTIER_QUESTIONS`，
保证「每轮问题数上限」只有一个来源。

历轮问答以 `rounds` 传入——结构为 `[{"round_no", "frontier", "answers"}, ...]`，
由 `app.grilling.service` 从规格 §4 的 `messages` 表复原，**不引入第二套隐藏状态存储**。
"""

from __future__ import annotations

from pathlib import Path

from app.grilling.open_items import SKIP_ANSWER_MARKER

# 每轮问题数上限：对原规则的显式移植偏离（原规则未设上限）。
MAX_FRONTIER_QUESTIONS = 5

GRILLING_PROMPT_VERSION = "grilling-v2"
# plan-v3（工单 6 / ADR-0006）：把「章节」一节固定为机器可解析的条目格式
# （每章一行：标题 + 要点 + 建议字数），成品章节据此确定性切分。
# 旧格式方案不会被拒——解析方在 `app.grilling.plan_sections` 里降级处理。
PLAN_PROMPT_VERSION = "plan-v3"
REVISION_PROMPT_VERSION = "revision-v1"
# fact-check-v1（工单 23 / ADR-0005）：事实型问题判定。判定规则写死在资产里，
# 不交给模型自由心证——否则同一个问题这轮检索、下轮不检索，引用卡片时有时无。
FACT_CHECK_PROMPT_VERSION = "fact-check-v1"

# 版本 → 资产文件名。旧版本保留可读（版本化资产是「旧版本不丢」的留痕），
# 代码只经版本常量引用当前版本。
_ASSET_BY_VERSION = {
    "grilling-v1": "grilling_v1.md",
    GRILLING_PROMPT_VERSION: "grilling_v2.md",
    "plan-v1": "plan_v1.md",
    "plan-v2": "plan_v2.md",
    PLAN_PROMPT_VERSION: "plan_v3.md",
    REVISION_PROMPT_VERSION: "revision_v1.md",
    FACT_CHECK_PROMPT_VERSION: "fact_check_v1.md",
}

_MAX_QUESTIONS_TOKEN = "%%MAX_QUESTIONS%%"

_NO_HISTORY = "（暂无：这是第一轮）"

_NO_OPEN_ITEMS = "（暂无：没有未定的待确认事项）"

_SKIP_RENDERED = "（用户暂时跳过：未定，已进入待确认事项）"

_NO_CITATIONS = "（暂无：本轮没有采用任何知识库引用）"


def load_asset(version: str = GRILLING_PROMPT_VERSION) -> str:
    """读取指定版本的提示词资产原文（未替换占位）。"""
    filename = _ASSET_BY_VERSION.get(version)
    if filename is None:
        raise ValueError(f"未知的提示词版本：{version}")
    return (Path(__file__).parent / filename).read_text(encoding="utf-8")


def _render_history(rounds: list[dict] | None) -> str:
    """把历轮问答渲染成可读文本（问题标题 → 用户回答）。

    被「暂时跳过」的作答渲染为未定说明，绝不显示成用户给出的答案
    （用户未回应不等于同意）。
    """
    if not rounds:
        return _NO_HISTORY

    blocks: list[str] = []
    for round_info in rounds:
        lines = [f"### 第 {round_info['round_no']} 轮"]
        answers = round_info.get("answers", [])
        for index, question in enumerate(round_info.get("frontier", [])):
            answer = answers[index] if index < len(answers) else None
            if answer is None or not str(answer).strip() or answer == SKIP_ANSWER_MARKER:
                rendered = _SKIP_RENDERED
            else:
                rendered = answer
            lines.append(f"- Q: {question['title']}　→　用户回答：{rendered}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_open_items(open_items: list[str] | None) -> str:
    """把未定的待确认事项渲染为区块内容（供「未定」区块使用）。"""
    if not open_items:
        return _NO_OPEN_ITEMS
    return "\n".join(f"- {item}" for item in open_items)


def _render_citations(citations: list[dict] | None) -> str:
    """把「已采用的引用片段」渲染为区块内容（工单 23 / 24）。

    只渲染**用户勾选保留**的片段：界面上的取消必须真的生效，否则用户看到的与实际
    喂给模型的就变成两回事。片段带出处（文件名 + 定位），模型引用时能说明依据。
    """
    if not citations:
        return _NO_CITATIONS
    lines: list[str] = []
    for item in citations:
        title = f"《{item.get('name', '未知资料')}》{item.get('locator_label', '')}".strip()
        lines.append(f"### {title}")
        lines.append(str(item.get("text", "")).strip())
        lines.append("")
    return "\n".join(lines).strip()


def render_frontier_messages(
    known_input: str,
    rounds: list[dict] | None = None,
    determined: list[str] | None = None,
    open_items: list[str] | None = None,
    citations: list[dict] | None = None,
) -> list[dict]:
    """渲染「生成前沿问题」的对话消息：系统规则 + 已知信息 + 已确定决策 + 未定 + 历轮问答。

    已知信息、历轮问答与已确定决策都在提示词里显式给出并要求不重复询问，从提示词层面
    消除「已提供 / 已决定却被再问」的问题；历轮问答与已确定决策同时是
    「按上轮回答重算」的输入。

    「未定（待确认事项）」区块单列：被跳过的题属于未定，既不能当已定决策、也不能被
    当作下一轮问题的既定前置条件（用户未回应不等于同意）。
    """
    system = load_asset(GRILLING_PROMPT_VERSION).replace(
        _MAX_QUESTIONS_TOKEN, str(MAX_FRONTIER_QUESTIONS)
    )
    determined_block = "（暂无：这是第一轮）"
    if determined:
        determined_block = "\n".join(f"- {item}" for item in determined)
    user = (
        "## 已知信息（用户已提供，视为已确定，绝不再问）\n"
        f"{known_input}\n\n"
        "## 已确定决策（来自历轮问答，视为已定，绝不再问）\n"
        f"{determined_block}\n\n"
        "## 未定（待确认事项：用户暂时跳过，**不得**当作已定或既定前置条件）\n"
        f"{_render_open_items(open_items)}\n\n"
        "## 历轮问答（据此把前沿向外推）\n"
        f"{_render_history(rounds)}\n\n"
        "## 已采用的知识库引用（用户勾选保留的资料片段；可作为提问依据）\n"
        f"{_render_citations(citations)}\n\n"
        "## 本轮任务\n"
        f"请基于以上已知信息与历轮问答，提出当前「前沿」的全部问题（1~{MAX_FRONTIER_QUESTIONS} 个，"
        "相互独立，且只问尚未解决的关键问题）；每个问题给出推荐答案、为什么现在问与备选方向；"
        "若关键问题都已解决，输出空前沿以收敛（不要为延续对话而提问）。严格按输出契约返回 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_plan_messages(
    known_input: str,
    rounds: list[dict] | None = None,
    determined: list[str] | None = None,
    open_items: list[str] | None = None,
) -> list[dict]:
    """渲染「生成结构化方案」的对话消息：已知信息 + 已确定决策 + 未定 + 全部历轮问答。

    方案在收敛时生成：章节随任务类型裁剪（结构灵活，不强求同一结构）；
    未经确认的推测只写进「待确认事项」，绝不写成已定需求。
    「未定」区块把跳过的问题单列，使它们只能落在「待确认事项」一节。
    """
    system = load_asset(PLAN_PROMPT_VERSION)
    determined_block = "（暂无）"
    if determined:
        determined_block = "\n".join(f"- {item}" for item in determined)
    user = (
        "## 已知信息（用户最初提供的输入）\n"
        f"{known_input}\n\n"
        "## 已确定决策（来自历轮问答，视为已定）\n"
        f"{determined_block}\n\n"
        "## 未定（待确认事项，不得写成已定需求）\n"
        f"{_render_open_items(open_items)}\n\n"
        "## 历轮问答（含用户暂时跳过的问题）\n"
        f"{_render_history(rounds)}\n\n"
        "## 本轮任务\n"
        "请把以上共识整理为一份结构化的 Markdown 方案（直接输出 Markdown，不要输出 JSON）；"
        "章节按任务类型裁剪，未与用户确认的推测（含「未定」区块的每一条）只放进「待确认事项」。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_revision_messages(
    previous_plan_md: str,
    instruction: str,
    known_input: str,
    rounds: list[dict] | None = None,
    determined: list[str] | None = None,
    open_items: list[str] | None = None,
) -> list[dict]:
    """渲染「对话式修订」的对话消息：当前方案 + 用户修订指令 + 已定 + 未定 + 历轮问答。

    修订只改方案文本；「未定」区块仍单列，避免修订把未定的待确认事项写成已定需求。
    """
    system = load_asset(REVISION_PROMPT_VERSION)
    determined_block = "（暂无）"
    if determined:
        determined_block = "\n".join(f"- {item}" for item in determined)
    user = (
        "## 当前结构化方案（待修订）\n"
        f"{previous_plan_md}\n\n"
        "## 已确定决策（来自历轮问答，视为已定）\n"
        f"{determined_block}\n\n"
        "## 未定（待确认事项，不得写成已定需求）\n"
        f"{_render_open_items(open_items)}\n\n"
        "## 历轮问答（含用户暂时跳过的问题）\n"
        f"{_render_history(rounds)}\n\n"
        "## 用户的修订指令（继续对话）\n"
        f"{instruction}\n\n"
        "## 本轮任务\n"
        "请据用户的修订指令更新方案，输出**完整**的 Markdown 方案正文（不要输出 JSON）；"
        "只改与指令相关的部分，其余章节保持原样。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_fact_check_messages(questions: list[dict]) -> list[dict]:
    """渲染「判定哪些前沿问题需要外部依据」的对话消息（工单 23）。

    一次判定整轮问题（而不是逐个问）：同一轮的问题彼此有关联，放在一起判更稳，
    也省调用次数。`index` 让结果能对回原问题，不依赖输出顺序。

    判定规则全部来自资产（`fact_check_v1.md`），这里只负责把问题按序编号喂进去。
    """
    system = load_asset(FACT_CHECK_PROMPT_VERSION)
    lines: list[str] = []
    for index, question in enumerate(questions):
        title = str(question.get("title", "")).strip()
        body = str(question.get("body", "")).strip()
        lines.append(f"{index}. 标题：{title}\n   正文：{body}")
    listing = "\n".join(lines) if lines else "（本轮没有问题）"
    user = (
        "## 本轮前沿问题（按下标编号）\n"
        f"{listing}\n\n"
        "## 本轮任务\n"
        "请逐个判定上列问题是否需要外部依据，按资产里的输出契约返回 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]