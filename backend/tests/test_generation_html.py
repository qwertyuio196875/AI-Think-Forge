"""TB-6 单文件 HTML 演示（ADR-0003 的另一轨）接缝测试。

唯一接缝 = 进程内 HTTP；模型走 fake；**不联网**。

对应规格 User Stories 18~22 的 HTML 一轨与工单 15 的窄路径：
- 正测：确认方案 → 生成单文件 `.html`，产物结构可解析、双击经 `file://` 可直开；
- **资源内联**：样式 / 脚本 / 西文字体全部内联（`data:` URI），中文用系统字体回退，
  产物元数据记 `inlined_fonts` 与 `cjk_fallback`；
- **无外部网络引用**：扫描产物文本，断言无 `http(s)://`、无指向网络的 `src=` / `href=`、
  无 CDN 与 `<link>`；
- **结构完整性检查**（US 22）：未过则丢弃产物、不落库、不交付；
- 主题族：原型定义的三套本地主题（`slate` / `ember` / `mono`），调色板以原型 `DECKT` 为准；
- 演示能力：键盘翻页（← / → / PageUp / PageDown / 空格）与页码显示；
- 生成记录复用 `generations`（`format=html`、所用品主题、产物位置）。

语义质量不做自动化断言（规格 Testing Decisions）——只断言状态、持久化与产物文件。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.generation.deck import DeckBuild, split_deck_document
from app.generation.themes import DECK_THEMES, deck_theme
from app.generation.word import DeliverableIntegrityError

IDEA = "帮我准备一份面向新员工的产品培训"

# 方案正文：H1 + 两个 H2 章节（含列表）+ 一张表格，够验证「方案 → 幻灯片」的映射。
PLAN_MD = (
    "# AI 编程工具使用指南\n\n"
    "从装环境到能自己改一个小工具。\n\n"
    "## 卡住人的从来不是模型\n"
    "环境：命令能跑通，报错对得上表。\n\n"
    "- 提示词：一次只让工具做一件小事\n"
    "- 会复制粘贴就算入门\n\n"
    "## 什么时候别用它\n"
    "- 需要精确复现的计算\n"
    "- 公司代码与内部数据\n\n"
    "| 项 | 值 |\n| --- | --- |\n| 篇幅 | 10 页 |\n"
)

_EXPECTED_THEMES = {
    "slate": {"name": "Slate 极简", "bg": "#f6f7f9", "fg": "#1c2027", "acc": "#2f6bdf"},
    "ember": {"name": "Ember 暖调", "bg": "#fbf6ef", "fg": "#2a2018", "acc": "#c4712a"},
    "mono": {"name": "Mono 等宽", "bg": "#101319", "fg": "#e8edf5", "acc": "#3f9d70"},
}

# 外部网络引用的形态：任一命中即视为「不是单文件」。
_EXTERNAL_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"<link\b", re.IGNORECASE),
    re.compile(r"<script[^>]+\bsrc\s*=", re.IGNORECASE),
    re.compile(r"""(?:src|href|poster|data-src)\s*=\s*["']?\s*(?:https?:)?//""", re.IGNORECASE),
    re.compile(r"""url\(\s*["']?\s*(?!data:)[^)"']*["']?\s*\)""", re.IGNORECASE),
    re.compile(r"@import", re.IGNORECASE),
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _confirmed_task(
    client: TestClient, scripted: ScriptedModelClient, plan_md: str = PLAN_MD
) -> int:
    """走完拷问 → 收敛 → 确认方案，返回已确认方案的任务 id。"""
    scripted.set_sequence(
        _frontier_json(("Q", "正文", "推荐")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        plan_md,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["答"]}
    )
    client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    return task_id


def _external_references(text: str) -> list[str]:
    """扫描产物文本里的外部网络引用（空列表 = 完全自包含）。"""
    found: list[str] = []
    for pattern in _EXTERNAL_PATTERNS:
        found.extend(match.group(0) for match in pattern.finditer(text))
    return found


def _deck_files(data_dir: Path) -> list[Path]:
    root = data_dir / "deliverables"
    return sorted(root.rglob("*.html")) if root.is_dir() else []


# --- 正测：确认方案 → 单文件 HTML 演示 -------------------------------------------


def test_confirmed_plan_produces_single_file_html_deck(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """确认方案 → 生成 `.html`：结构可解析、资源全内联、无外部网络引用。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "slate"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["format"] == "html"
    assert body["integrity_ok"] is True
    assert body["plan_id"] > 0

    artifact = Path(body["file_path"])
    assert artifact.exists()
    assert artifact.suffix == ".html"
    text = artifact.read_text(encoding="utf-8")

    # 单文件：无外部网络引用（工单硬要求，US 21）
    assert _external_references(text) == []
    assert "http://" not in text and "https://" not in text

    # 结构可解析：单文件、幻灯片容器 + 翻页脚本 + 页码
    document = split_deck_document(text)
    assert document["slide_count"] == body["slides"] >= 3
    assert document["layouts"][0] == "title"
    assert document["layouts"][-1] == "end"

    # 西文内联、中文回退系统字体、网络资源如实声明
    assert body["inlined_fonts"]
    assert all("latin" in name for name in body["inlined_fonts"])
    assert body["cjk_fallback"] is True
    assert body["external_resources"] == []
    assert "font/woff2;base64," in text
    assert "Microsoft YaHei" in text


def test_deck_artifact_declares_theme_palette_from_prototype(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """主题 id 与调色板以原型 `DECKT` 为准，且如实记入产物与生成记录。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    body = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "ember"}
    ).json()

    text = Path(body["file_path"]).read_text(encoding="utf-8")
    assert body["theme_used"] == "ember"
    assert "--dkt-bg: #fbf6ef" in text
    assert "--dkt-fg: #2a2018" in text
    assert "--dkt-acc: #c4712a" in text

    # 生成记录复用 `generations`：格式 / 所用品主题 / 产物位置
    assert body["template_used"] == "deck-theme:ember"
    record = grilling_client.get(f"/api/tasks/{task_id}/generations").json()["items"][0]
    assert record["format"] == "html"
    assert record["template_used"] == "deck-theme:ember"
    assert record["file_path"] == body["file_path"]


# --- 主题族：三套本地主题 -------------------------------------------------------


def test_three_local_themes_defined_by_prototype_palette() -> None:
    """内建三套主题（`slate` / `ember` / `mono`），调色板逐值与原型 `DECKT` 一致。"""
    assert set(DECK_THEMES) == set(_EXPECTED_THEMES)

    for theme_id, expected in _EXPECTED_THEMES.items():
        theme = deck_theme(theme_id)
        assert theme.name == expected["name"]
        assert theme.bg == expected["bg"]
        assert theme.fg == expected["fg"]
        assert theme.accent == expected["acc"]
        # 每套主题都要内联自己的西文字体（否则离线会掉字形），并如实标明来源
        assert theme.inlined_fonts
        assert theme.derived_from


def test_unknown_theme_is_rejected_not_silently_defaulted(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """未知主题 → 400 明确报错；绝不静默退回默认主题。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html", "theme": "hyper-neon"}
    )

    assert response.status_code == 400
    assert "主题" in response.json()["detail"]
    assert grilling_client.get(f"/api/tasks/{task_id}/generations").json()["total"] == 0


# --- 生成闸门：与 TB-5 逐字一致 --------------------------------------------------


def test_html_generation_keeps_confirmation_gate(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """HTML 一轨的闸门判定与 TB-5 逐字一致：无方案 / 未确认 → 409，不产出文件。"""
    scripted_model_client.set_sequence(
        _frontier_json(("Q", "正文", "推荐")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
    )
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]

    no_plan = grilling_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "html"}
    )
    assert no_plan.status_code == 409
    assert no_plan.json()["detail"] == f"任务 {task_id} 尚无结构化方案，无法生成"

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["答"]}
    )
    grilling_client.post(f"/api/grilling/tasks/{task_id}/advance")

    draft = grilling_client.post(f"/api/tasks/{task_id}/generations", json={"format": "html"})
    assert draft.status_code == 409
    assert draft.json()["detail"] == (
        "结构化方案尚未确认，拒绝生成（方案确认是进入生成阶段的唯一闸门）"
    )


# --- 完整性检查（US 22） --------------------------------------------------------


def test_external_reference_makes_integrity_check_fail_and_discard_artifact(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """产物含外部引用 / 结构损坏 → 检查未通过：丢弃产物、不落库、明确报错。"""

    def _broken(build: DeckBuild) -> None:
        raise DeliverableIntegrityError("模拟：产物含外部网络引用")

    monkeypatch.setattr("app.generation.service.verify_html_deliverable", _broken)

    task_id = _confirmed_task(grilling_client, scripted_model_client)
    response = grilling_client.post(f"/api/tasks/{task_id}/generations", json={"format": "html"})

    assert response.status_code == 500
    assert "完整性检查未通过" in response.json()["detail"]
    assert grilling_client.get(f"/api/tasks/{task_id}/generations").json()["total"] == 0
    assert _deck_files(data_dir) == []


def test_verifier_flags_injected_external_reference(tmp_path: Path) -> None:
    """敏感度自证：把一条外链塞进产物，完整性检查必须转红（扫描真的在起作用）。"""
    from app.generation.deck import build_html_deck, verify_html_deliverable

    output = tmp_path / "deck.html"
    build = build_html_deck(
        plan_md=PLAN_MD,
        task_title="演示",
        theme=deck_theme("slate"),
        output_path=output,
    )
    verify_html_deliverable(build)  # 合格产物先通过

    tampered = output.read_text(encoding="utf-8").replace(
        "</head>", '<link rel="stylesheet" href="https://cdn.example.com/deck.css"></head>'
    )
    output.write_text(tampered, encoding="utf-8")

    with pytest.raises(DeliverableIntegrityError) as error:
        verify_html_deliverable(build)
    assert "外部网络引用" in str(error.value)


# --- 演示能力：键盘翻页 / 页码 / 演讲者模式 -------------------------------------


def test_deck_supports_keyboard_navigation_page_numbers_and_presenter_mode(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """键盘翻页（← / → / PageUp / PageDown / 空格）、页码显示与页内演讲者模式可用。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    body = grilling_client.post(f"/api/tasks/{task_id}/generations", json={"format": "html"}).json()

    document = split_deck_document(Path(body["file_path"]).read_text(encoding="utf-8"))

    assert {"ArrowLeft", "ArrowRight", "PageUp", "PageDown"} <= document["keys"]
    assert document["handles_space"] is True
    assert document["has_page_counter"] is True
    assert document["has_keydown_listener"] is True
    # 演讲者模式（页内覆盖层 + 计时器 + 讲者备注）；原型口径允许「尽力而为」，
    # 但既然做了就必须真的存在于产物里，且如实标注实现形态。
    assert document["has_presenter_overlay"] is True
    assert body["presenter_mode"] == "in-page-overlay"


# --- 主题族清单（供前端主题选择器读同一份事实） ---------------------------------


def test_deck_theme_catalog_exposes_provenance_and_inlined_fonts(
    grilling_client: TestClient,
) -> None:
    """主题清单：三套主题的调色板 / 内联字体 / 来源署名与许可以同一份事实对外。"""
    listed = grilling_client.get("/api/deck-themes")

    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 3
    assert payload["cjk_fallback"] is True

    slate = next(item for item in payload["items"] if item["id"] == "slate")
    assert slate["name"] == "Slate 极简"
    assert slate["palette"]["bg"] == "#f6f7f9"
    assert slate["fonts"]
    # 如实标明哪些是 OpenDesign 派生、哪些是本地原创（工单硬要求）
    assert "OpenDesign" in slate["derived_from"]
    assert slate["license"] == "MIT"
    assert slate["network_resources"] == []


def test_deck_theme_catalog_lists_only_local_themes_without_network(
    grilling_client: TestClient,
) -> None:
    """三套主题都不依赖网络资源；若将来有主题必须保留网络资源，必须在清单里明示。"""
    items = grilling_client.get("/api/deck-themes").json()["items"]

    assert all(item["network_resources"] == [] for item in items)
    assert {item["id"] for item in items} == set(_EXPECTED_THEMES)


# --- 方案 → 幻灯片映射（结构性，不做语义质量断言） ------------------------------


def test_plan_sections_map_to_slides_with_speaker_notes(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案章节落在幻灯片上：标题页 → 各 H2 章节 → 结束页；讲者备注取自章节正文。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    body = grilling_client.post(f"/api/tasks/{task_id}/generations", json={"format": "html"}).json()
    text = Path(body["file_path"]).read_text(encoding="utf-8")

    assert "AI 编程工具使用指南" in text  # H1 → 标题页
    titles = re.findall(r'<h2 class="slide-title">([^<]*)</h2>', text)
    assert titles == ["卡住人的从来不是模型", "什么时候别用它"]
    assert "需要精确复现的计算" in text  # 列表项不丢内容
    assert "10 页" in text  # 表格内容不丢内容
    assert text.count('class="speaker-notes"') == body["slides"]

    # 产物是 UTF-8 且能被 XML 解析器当作 XHTML 片段读取（结构未损坏的旁证）
    assert ElementTree.fromstring(f"<root>{_first_slide(text)}</root>") is not None


def _first_slide(text: str) -> str:
    """取产物里的第一张幻灯片片段（结构断言的辅助）。"""
    start = text.index('<section class="slide"')
    end = text.index("</section>", start) + len("</section>")
    return text[start:end]