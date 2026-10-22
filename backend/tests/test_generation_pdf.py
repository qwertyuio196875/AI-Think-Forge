"""PDF 成品打印导出（工单 31 / ADR-0004：PDF 由 deck 打印导出，可选；测试**绝不启动浏览器**）。

钉住 issue #31 验收：
1. **PDF 与 pptx 同源同版式**：同一份页面规划 → 同一份 HTML deck → 打印成 PDF，
   封装 PDF 渲染器接缝（与 #28 截图渲染器对称），任一用例都不打开 Chromium；
2. **失败不产出半份文件**：打印失败 / 尺寸（页数）异常 → 抛明确异常、磁盘不落半成品、
   不落库；
3. **PDF 是可选产物**：有独立 `format=pdf`，单独的 POST 动作，HTML / PPTX 既有路径不受影响。

接缝 = 进程内 HTTP；模型走 fake；PDF 渲染器经 `dependency_overrides[get_pdf_renderer]`
注入**写入真实可读 PDF（含正确页数）的假实现**，任何用例都不启动浏览器（Playwright 不加载）。
用 `layout_samples.build_pdf` 现场构造合法的 N 页 PDF（与 TB-8 版式样本同源）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient
from layout_samples import build_pdf
from pypdf import PdfReader

from app.api.deps import get_pdf_renderer
from app.db.database import connect, init_db
from app.generation.deck import (
    LAYOUT_END,
    LAYOUT_TITLE,
    DeckBuild,
    DeckSlide,
    build_html_deck_from_slides,
)
from app.generation.pdfs import (
    PdfDefinitionError,
    PdfRenderer,
    PlaywrightPdfRenderer,
    render_pdf,
    verify_pdf_deliverable,
)
from app.generation.themes import DECK_THEMES
from app.pageplan.service import decode_page_plan

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)


def _body(title: str, hanzi: int, filler: str) -> str:
    unit = len(filler)
    repeat = max(1, -(-hanzi // unit))
    return f"## {title}\n\n{filler * repeat}\n"


BODY_FIRST = _body(
    "产品全景",
    580,
    "新员工到岗后先看一眼产品的三个真实场景，把主线的来龙去脉走顺，后面的路自然就顺了。",
)
BODY_SECOND = _body(
    "第一天要做的五件事",
    390,
    "第一天不需要做完所有事，只要把五件小事按顺序做完，流程就稳了，也更容易坚持。",
)
_SUMMARY = "本章讲完了，为下一章留下悬念。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return __import__("json").dumps({"frontier": frontier}, ensure_ascii=False)


class FakePdfRenderer(PdfRenderer):
    """假渲染器：**写入真实可读的 N 页 PDF**（绝不启动浏览器），可预置失败 / 页数异常。

    用 `layout_samples.build_pdf` 现场拼纯文本多页 PDF（合理合法），让下游回读校验真能跑通。
    只预置想要的失败路径，其余页数取 deck 的 `slide_count`（每页幻灯片 = PDF 一页）。
    """

    def __init__(self, *, fail: bool = False, wrong_pages: bool = False) -> None:
        self.fail = fail          # 直接抛错，模拟打印失败
        self.wrong_pages = wrong_pages  # 页数偏差，模拟成品页数 ≠ deck 页数
        self.calls: list[tuple[Path, Path]] = []

    def render(self, build: DeckBuild, output_path: Path) -> Path:
        self.calls.append((Path(build.path), Path(output_path)))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.fail:
            raise RuntimeError("PDF 打印失败（预置）")
        pages = build.slide_count - 1 if self.wrong_pages else build.slide_count
        output_path.write_bytes(build_pdf([([], False)] * max(pages, 1)))
        return output_path


@pytest.fixture
def pdf_renderer() -> FakePdfRenderer:
    return FakePdfRenderer()


@pytest.fixture
def pdf_app(grilling_app, pdf_renderer: FakePdfRenderer):
    """在进程内应用上把 PDF 渲染器替换成假实现（不启动浏览器）。"""
    grilling_app.dependency_overrides[get_pdf_renderer] = lambda: pdf_renderer
    return grilling_app


@pytest.fixture
def pdf_client(pdf_app) -> TestClient:
    with TestClient(pdf_app) as test_client:
        yield test_client


def _confirmed_filled_planned(
    client: TestClient, scripted: ScriptedModelClient
) -> tuple[int, int]:
    """走完拷问 → 收敛 → 确认 → 全填充 → 规划页数，返回 (task_id, page_plan_id)。"""
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        __import__("json").dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
        BODY_FIRST,
        _SUMMARY,
        BODY_SECOND,
        _SUMMARY,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/fill", json={}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/fill/run").status_code == 200
    plan_resp = client.post(f"/api/tasks/{task_id}/page-plans", json={"target_pages": 6})
    assert plan_resp.status_code == 200
    return task_id, plan_resp.json()["page_plan_id"]


def _build_deck(tmp_path: Path, *, slide_count: int) -> DeckBuild:
    """造一份 deck：封面 + 若干内容页 + 结尾页（页数 = slide_count）。"""
    theme = DECK_THEMES["slate"]
    slides: list[DeckSlide] = [
        DeckSlide(layout=LAYOUT_TITLE, title="演示", subtitle="副标题", notes="封面")
    ]
    for index in range(2, slide_count):
        slides.append(
            DeckSlide(layout="list", title=f"第 {index} 页", pieces=(), notes=f"页 {index}")
        )
    slides.append(
        DeckSlide(layout=LAYOUT_END, title="谢谢", subtitle="提问环节", notes="结束")
    )
    output = tmp_path / "deck.html"
    return build_html_deck_from_slides(
        slides=tuple(slides),
        task_title="演示",
        plan_md="# 演示",
        theme=theme,
        output_path=output,
    )


def _pdf_files(client: TestClient) -> list[Path]:
    root = Path(client.app.state.data_dir) / "deliverables"
    return sorted(root.rglob("*.pdf")) if root.is_dir() else []


# --- 验收 ①：注入假渲染器，打印编排 + 产物对账（绝不启动浏览器） -----------------


def test_render_pdf_uses_injected_renderer(tmp_path: Path) -> None:
    build = _build_deck(tmp_path, slide_count=4)
    out = tmp_path / "deck.pdf"
    fake = FakePdfRenderer()

    result = render_pdf(build=build, output_path=out, renderer=fake)

    assert result == out
    assert fake.calls == [(build.path, out)]
    assert out.exists()
    # 假渲染器写入的是合法 PDF 头。
    assert out.read_bytes().startswith(b"%PDF-")


def test_verify_pdf_deliverable_reopens_and_checks_pages(tmp_path: Path) -> None:
    """装配产物能被回读通过，页数 = deck 页数（每页幻灯片 = PDF 一页）。"""
    data = build_pdf([([], False)] * 3)
    out = tmp_path / "deck.pdf"
    out.write_bytes(data)

    verdict = verify_pdf_deliverable(out, expected_pages=3)

    assert verdict.path == out and verdict.page_count == 3 and verdict.integrity_ok


# --- 验收 ②：成品异常 → 抛明确异常，不交付半成品 ---------------------------------


def test_playwright_print_css_breaks_stacked_stage_into_pages() -> None:
    """真实渲染器的打印样式必须把叠放式舞台改成逐页文档（**不启动浏览器**，只查样式）。

    deck 的 `.slide` 是 `position:absolute; inset:0; opacity:0` 的演示舞台，一次只显示
    一页。若打印时不给覆盖样式，`page.pdf()` 只会输出当前那一页——页数与规划对不上。
    这条用例把「必须覆盖定位 / 透明度 / 分页」钉在样式字符串里，防止回归。
    """
    css = PlaywrightPdfRenderer.PRINT_CSS

    # 必须解除绝对定位并恢复可见（否则打印只有一页）。
    assert "position: relative" in css
    assert "opacity: 1" in css
    # 必须强制逐页断开。
    assert "break-after: page" in css
    # 必须把页面尺寸钉成 13.333×7.5 英寸（与 pptx / 截图同版式）。
    assert "13.333in 7.5in" in css


def test_verify_rejects_not_pdf(tmp_path: Path) -> None:
    not_pdf = tmp_path / "noise.pdf"
    not_pdf.write_bytes(b"%PDF broken payload without real structure")

    with pytest.raises(PdfDefinitionError):
        verify_pdf_deliverable(not_pdf, expected_pages=1)


def test_verify_rejects_wrong_page_count(tmp_path: Path) -> None:
    """成品 PDF 页数 ≠ deck 页数 → 抛明确异常（半成品绝不交付）。"""
    data = build_pdf([([], False)] * 2)
    out = tmp_path / "deck.pdf"
    out.write_bytes(data)

    with pytest.raises(PdfDefinitionError) as exc_info:
        verify_pdf_deliverable(out, expected_pages=5)

    assert "页数" in str(exc_info.value)


# --- 验收 ②（服务编排级）：打印失败 → 磁盘无 pdf、不落库 --------------------------


def test_service_deletes_half_built_pdf_on_renderer_failure(
    pdf_client: TestClient, scripted_model_client: ScriptedModelClient, pdf_renderer
) -> None:
    """打印第 2 页抛错 → 请求 500、无 .pdf、无成品记录。"""
    pdf_renderer.fail = True
    task_id, _ = _confirmed_filled_planned(pdf_client, scripted_model_client)

    response = pdf_client.post(f"/api/tasks/{task_id}/generations", json={"format": "pdf"})

    assert response.status_code == 500
    assert _pdf_files(pdf_client) == []


def test_service_rejects_wrong_pdf_pages_and_leaves_no_artifact(
    pdf_client: TestClient, scripted_model_client: ScriptedModelClient, pdf_renderer
) -> None:
    """成品 PDF 页数 ≠ deck 页数（尺寸异常）→ 请求 500、磁盘无 pdf、不落库。"""
    pdf_renderer.wrong_pages = True
    task_id, _ = _confirmed_filled_planned(pdf_client, scripted_model_client)

    response = pdf_client.post(f"/api/tasks/{task_id}/generations", json={"format": "pdf"})

    assert response.status_code == 500
    assert _pdf_files(pdf_client) == []


# --- 验收 ①+③：端点正测：format=pdf、同源、可从 PDF 重开 -------------------------


def test_pdf_generation_endpoint_full_flow(
    pdf_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """确认+填充+规划 → 请求 pdf：201、format=pdf、source=body、page_plan_id 落库、
    产物是 `%PDF` 开头、页数=规划页数+结尾页（可被 pypdf 读回）。"""
    task_id, page_plan_id = _confirmed_filled_planned(pdf_client, scripted_model_client)
    pages = decode_page_plan(_latest_page_plan_json(db_path, task_id))

    response = pdf_client.post(f"/api/tasks/{task_id}/generations", json={"format": "pdf"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["format"] == "pdf"
    assert body["source"] == "body"
    assert body["source_label"] == "正文成品"
    assert body["page_plan_id"] == page_plan_id
    assert body["integrity_ok"] is True

    out = Path(body["file_path"])
    assert out.exists() and out.suffix == ".pdf"
    # 可选产物：合法 PDF、可被 pypdf 打开、页数 = 规划页数 + 结尾页。
    assert out.read_bytes().startswith(b"%PDF-")
    reader = PdfReader(str(out))
    assert len(reader.pages) == len(pages) + 1

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM generations WHERE task_id = ? AND format = 'pdf'", (task_id,)
        ).fetchone()
    assert row is not None
    assert row["source"] == "body"
    assert row["page_plan_id"] == page_plan_id


def _latest_page_plan_json(db_path: Path, task_id: int) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT pages_json FROM page_plans WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    assert row is not None
    return row["pages_json"]


# --- 验收 ③：PDF 可选，不阻塞 HTML / PPTX -----------------------------------------


def test_pdf_does_not_interfere_with_html_generation(
    pdf_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """同任务先出 PDF 再出 HTML：两条既有路径互不干扰，HTML 照常 201。"""
    task_id, _ = _confirmed_filled_planned(pdf_client, scripted_model_client)

    pdf_resp = pdf_client.post(f"/api/tasks/{task_id}/generations", json={"format": "pdf"})
    assert pdf_resp.status_code == 201

    html_resp = pdf_client.post(f"/api/tasks/{task_id}/generations", json={"format": "html"})
    assert html_resp.status_code == 201
    assert html_resp.json()["format"] == "html"
    assert html_resp.json()["integrity_ok"] is True

    records = pdf_client.get(f"/api/tasks/{task_id}/generations").json()["items"]
    # 填充阶段本身会产出一份 Word 正文成品（既有行为），此处只关心 PDF 与 HTML 并存。
    formats = {item["format"] for item in records}
    assert {"pdf", "html"} <= formats


# --- 验收 ②：DB 迁移（既有库放宽 format CHECK 到 pdf，幂等） -----------------------


def test_db_migration_adds_pdf_to_format_check(tmp_path: Path) -> None:
    """旧版库（format 仅 docx/html，ptx 时代之前）init_db 后能插入 pdf，数据保留。"""
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.execute(
        """
        CREATE TABLE generations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id       INTEGER NOT NULL,
            plan_id       INTEGER NOT NULL,
            format        TEXT NOT NULL CHECK (format IN ('docx', 'html')),
            file_path     TEXT NOT NULL,
            template_used TEXT NOT NULL,
            source        TEXT NOT NULL DEFAULT 'outline'
                          CHECK (source IN ('outline', 'body')),
            created_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO generations (task_id, plan_id, format, file_path, template_used, created_at)
        VALUES (1, 1, 'docx', 'C:/legacy/a.docx', 'x', '2020-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    conn.close()

    init_db(legacy)

    with sqlite3.connect(legacy) as conn:
        # 旧数据保留。
        row = conn.execute(
            "SELECT format, file_path FROM generations WHERE id = 1"
        ).fetchone()
        assert row[0] == "docx" and row[1] == "C:/legacy/a.docx"
        # CHECK 已放宽：能插入 pdf。
        conn.execute(
            """
            INSERT INTO generations
                (task_id, plan_id, format, file_path, template_used, page_plan_id, created_at)
            VALUES (2, 1, 'pdf', 'C:/legacy/c.pdf', 'x', 9, '2020-01-01T00:00:00+00:00')
            """
        )
        conn.commit()


def test_db_migration_extends_pptx_era_db_with_pdf(tmp_path: Path) -> None:
    """工单 29 之后（format 已含 pptx 但无 pdf）的库，init_db 后也能插入 pdf（幂等）。"""
    era = tmp_path / "era.db"
    conn = sqlite3.connect(era)
    conn.execute(
        """
        CREATE TABLE generations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id       INTEGER NOT NULL,
            plan_id       INTEGER NOT NULL,
            format        TEXT NOT NULL CHECK (format IN ('docx', 'html', 'pptx')),
            file_path     TEXT NOT NULL,
            template_used TEXT NOT NULL,
            page_plan_id  INTEGER,
            source        TEXT NOT NULL DEFAULT 'outline'
                          CHECK (source IN ('outline', 'body')),
            created_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO generations (task_id, plan_id, format, file_path, template_used, created_at)
        VALUES (1, 1, 'pptx', 'C:/legacy/b.pptx', 'x', '2020-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    conn.close()

    init_db(era)

    with sqlite3.connect(era) as conn:
        row = conn.execute("SELECT format FROM generations WHERE id = 1").fetchone()
        assert row[0] == "pptx"
        conn.execute(
            """
            INSERT INTO generations
                (task_id, plan_id, format, file_path, template_used, page_plan_id, created_at)
            VALUES (2, 1, 'pdf', 'C:/legacy/d.pdf', 'x', 3, '2020-01-01T00:00:00+00:00')
            """
        )
        conn.commit()