"""方案提示词资产的版本化契约（工单 6 / ADR-0006）。

plan-v3 把方案「章节」一节固定为机器可解析的条目格式（每章一行：标题 + 要点 + 建议字数）；
版本号显式记录并留痕，旧版本资产仍然可读（ADR-0001「不得静默走样」）。

注意术语（GLOSSARY）：`##` 切出的是**方案分节**，「章节」只是其中一节的名字；
本文件只钉住提示词资产，成品章节的解析见 `test_plan_sections.py`。
"""

from __future__ import annotations

from app.grilling import prompts

CANONICAL_SECTION_FORMAT = (
    "标题：",
    "要点：",
    "建议字数：",
    "每章一行",
)


def test_plan_prompt_asset_fixes_chapter_section_format_and_keeps_old_version() -> None:
    """方案提示词升到 plan-v3：固定「章节」条目格式、留痕可查、旧版本仍可读。"""
    assert prompts.PLAN_PROMPT_VERSION == "plan-v3"

    asset = prompts.load_asset(prompts.PLAN_PROMPT_VERSION)

    # 沿用既有的署名与偏离记录（ADR-0001：不得静默走样）
    assert "Matt Pocock" in asset
    assert "MIT" in asset
    assert "偏离" in asset
    assert "简体中文" in asset
    # 「章节」一节的条目格式契约：解析器读的就是这三段
    for token in CANONICAL_SECTION_FORMAT:
        assert token in asset
    # 版本变更留痕（工单 6 验收：版本号显式记录）
    assert "plan-v3" in asset
    assert "plan-v2 → plan-v3" in asset

    # 旧版本不丢：plan-v2 资产仍在，且不含新格式要求
    previous = prompts.load_asset("plan-v2")
    assert "plan-v2" in previous
    assert "建议字数：" not in previous
