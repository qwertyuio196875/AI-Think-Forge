"""PPT 成品装配（工单 29 / ADR-0004；测试**绝不启动浏览器**）。

钉住 issue #29 验收：
1. 产出的 pptx 能被 python-pptx 打开，页数等于规划页数（规划页 + 结尾页）；
2. 每页恰好一张满幅图片（空版式 add_picture 铺满 13.333×7.5）；
3. 任一页 PNG 尺寸不符 / 截图渲染失败时，磁盘上**不出现** pptx 文件，且不落库；
4. 成品记录能承载 pptx 格式与来源页面规划（`format='pptx'` + `page_plan_id`）。

接缝 = 进程内 HTTP；模型走 fake；截图渲染器经 `dependency_overrides[get_pptx_renderer]`
注入**产真实 2560×1440 PNG 的假实现**，任何用例都不打开 Chromium（Playwright 不加载）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.api.deps import get_pptx_renderer
from app.db.database import connect, init_db
from app.generation.pptx import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    PptxAssemblyError,
    assemble_pptx,
    verify_pptx_deliverable,
)
from app.generation.screenshots import SLIDE_PNG_TEMPLATE, SlideRenderer
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
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


class FakePptxRenderer(SlideRenderer):
    """假渲染器：**逐页写真实 2560×1440 PNG**（绝不启动浏览器），可预置失败/错尺寸。

    真实 Playwright 截出的每页是固定 2560×1440（ADR-0004）；假实现产同样尺寸的真 PNG，
    让下游装配 / 校验真的能跑通。只预置想要的失败路径，其余全部产出正常尺寸。
    """

    def __init__(
        self,
        *,
        fail_on: int | None = None,
        bad_size: bool = False,
        offset: int = 0,
    ) -> None:
        self.fail_on = fail_on          # 第几页截图直接抛错
        self.bad_size = bad_size        # 产 40×40 的错误尺寸
        self.offset = offset            # 页数偏差（+N / -N），模拟「截图页数≠deck 页数」
        self.calls: list[Path] = []

    def render(self, build, output_dir: Path) -> tuple[tuple[int, Path], ...]:
        self.calls.append(Path(build.path))
        output_dir.mkdir(parents=True, exist_ok=True)
        produced: list[tuple[int, Path]] = []
        count = build.slide_count + self.offset
        for index in range(1, count + 1):
            if self.fail_on is not None and index == self.fail_on:
                raise RuntimeError(f"截图第 {index} 页失败（预置）")
            png = output_dir / SLIDE_PNG_TEMPLATE.format(index=index)
            size = (40, 40) if self.bad_size else (IMAGE_WIDTH, IMAGE_HEIGHT)
            Image.new("RGB", size, (200, 30, 30)).save(png, "PNG")
            produced.append((index, png))
        return tuple(produced)


@pytest.fixture
def pptx_renderer() -> FakePptxRenderer:
    return FakePptxRenderer()


@pytest.fixture
def pptx_client(grilling_app, pptx_renderer: FakePptxRenderer):
    """在掀叶应用的进程内客户端上把截图渲染器替换成假实现（不启动浏览器）。"""
    grilling_app.dependency_overrides[get_pptx_renderer] = lambda: pptx_renderer
    return grilling_app


@pytest.fixture
def built_client(pptx_client, pptx_renderer):
    with TestClient(pptx_client) as test_client:
        yield test_client


def _task_filled_with_page_plan(client: TestClient, scripted: ScriptedModelClient) -> tuple[int, int]:
    """走完拷问 → 收敛 → 确认 → 全填充 → 规划页数，返回 (task_id, page_plan_id)。"""
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
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


def _make_png(path: Path, size: tuple[int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, "PNG")
    return path


# --- 验收 ①+②：pptx 可打开、页数相等、每页一张满幅图 ------------------------------


def test_assemble_pptx_full_bleed(tmp_path: Path) -> None:
    """3 张真 2560×1440 PNG → pptx 3 页，每页一张满幅图。"""
    pngs = tuple(
        (i + 1, _make_png(tmp_path / f"s{i + 1}.png", (IMAGE_WIDTH, IMAGE_HEIGHT)))
        for i in range(3)
    )
    out = tmp_path / "deck.pptx"

    result = assemble_pptx(pngs, out)

    assert result == out
    presentation = Presentation(str(out))
    assert len(presentation.slides) == 3
    for slide in presentation.slides:
        pictures = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
        assert len(pictures) == 1
        pic = pictures[0]
        assert pic.left == 0 and pic.top == 0
        assert abs(pic.width - presentation.slide_width) <= 1000
        assert abs(pic.height - presentation.slide_height) <= 1000
    assert abs(presentation.slide_width - 12191695) <= 1000  # 13.333in EMU (Inches(13.333))
    assert abs(presentation.slide_height - 6858000) <= 1000  # 7.5in EMU


def test_verify_pptx_deliverable_reopens_and_checks(tmp_path: Path) -> None:
    """装配后的产物能被 verify 回读通过，并返回正确页数。"""
    pngs = tuple(
        (i + 1, _make_png(tmp_path / f"s{i + 1}.png", (IMAGE_WIDTH, IMAGE_HEIGHT)))
        for i in range(2)
    )
    out = tmp_path / "deck.pptx"
    assemble_pptx(pngs, out)
    verdict = verify_pptx_deliverable(out, expected_slides=2)
    assert verdict.slide_count == 2 and verdict.integrity_ok


# --- 验收 ③：任一侧不符 → 磁盘不出现 pptx ----------------------------------------


def test_assemble_pptx_rejects_wrong_size_image(tmp_path: Path) -> None:
    """某张 PNG 是 40×40 → 抛 PptxAssemblyError，磁盘上不出现 pptx。"""
    good = _make_png(tmp_path / "good.png", (IMAGE_WIDTH, IMAGE_HEIGHT))
    bad = _make_png(tmp_path / "bad.png", (40, 40))
    out = tmp_path / "deck.pptx"

    with pytest.raises(PptxAssemblyError):
        assemble_pptx(((1, good), (2, bad)), out)

    assert not out.exists()


def test_assemble_pptx_requires_exact_dimensions(tmp_path: Path) -> None:
    """尺寸必须严格等于 2560×1440（不是「至少」，是恰好）。"""
    near = _make_png(tmp_path / "near.png", (IMAGE_WIDTH - 1, IMAGE_HEIGHT))
    out = tmp_path / "deck.pptx"

    with pytest.raises(PptxAssemblyError) as exc_info:
        assemble_pptx(((1, near),), out)

    assert "尺寸" in str(exc_info.value)
    assert not out.exists()


def test_assemble_pptx_rejects_unreadable_file(tmp_path: Path) -> None:
    """不是可读图片 → 抛 PptxAssemblyError，磁盘上不出现 pptx。"""
    not_png = tmp_path / "noise.png"
    not_png.write_bytes(b"\x00\x01\x02 not really an image")
    out = tmp_path / "deck.pptx"

    with pytest.raises(PptxAssemblyError):
        assemble_pptx(((1, not_png),), out)

    assert not out.exists()


# --- 服务编排级：假渲染器失败 → 磁盘不出现 pptx、不落库 -----------------------------


def test_service_deletes_half_built_pptx_on_renderer_failure(
    built_client: TestClient, scripted_model_client: ScriptedModelClient, pptx_renderer
) -> None:
    """截图第 2 页抛错 → 请求 500、无 pptx、无成品记录。"""
    pptx_renderer.fail_on = 2
    task_id, _ = _task_filled_with_page_plan(built_client, scripted_model_client)

    response = built_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "pptx"}
    )

    assert response.status_code == 500
    # 数据目录 deliverables 下没有任何 .pptx（半成品被清理）。
    assert _pptx_files(built_client) == []


def _pptx_files(client: TestClient) -> list[Path]:
    root = Path(client.app.state.data_dir) / "deliverables"
    return sorted(root.rglob("*.pptx")) if root.is_dir() else []


# --- 验收 ①+②+④：端点正测 --------------------------------------------------------


def test_pptx_generation_endpoint_full_flow(
    built_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
) -> None:
    """确认+填充+规划 → 请求 pptx：201、format=pptx、source=body、page_plan_id 落库、
    pptx 可打开、页数=规划页数+结尾页、每页一张满幅图。"""
    task_id, page_plan_id = _task_filled_with_page_plan(built_client, scripted_model_client)
    pages = decode_page_plan(
        _latest_page_plan_json(db_path, task_id)
    )

    response = built_client.post(
        f"/api/tasks/{task_id}/generations", json={"format": "pptx"}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["format"] == "pptx"
    assert body["source"] == "body"
    assert body["source_label"] == "正文成品"
    assert body["page_plan_id"] == page_plan_id
    assert body["integrity_ok"] is True

    out = Path(body["file_path"])
    assert out.exists() and out.suffix == ".pptx"

    # 页数**严格等于**规划页数（issue #29 验收 ①/#27：说 16 页就是 16 页），
    # 每页一张满幅图。
    expected_slides = len(pages)
    presentation = Presentation(str(out))
    assert len(presentation.slides) == expected_slides
    for slide in presentation.slides:
        pictures = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
        assert len(pictures) == 1
        pic = pictures[0]
        assert pic.left == 0 and pic.top == 0
        assert abs(pic.width - presentation.slide_width) <= 1000
        assert abs(pic.height - presentation.slide_height) <= 1000

    # 库里有 source=body 的 pptx 记录，且带来源页面规划。
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM generations WHERE task_id = ? AND format = 'pptx'", (task_id,)
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


# --- 验收 ④：DB 迁移（既有库放宽 CHECK + 补 page_plan_id） -------------------------


def test_db_migration_relaxes_format_check_and_adds_column(tmp_path: Path) -> None:
    """旧版库（format 仅 docx/html、无 page_plan_id）init_db 后：列补齐、格式放开、数据保留。"""
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
        columns = {row[1] for row in conn.execute("PRAGMA table_info(generations)")}
        assert "page_plan_id" in columns
        # 旧数据保留。
        row = conn.execute(
            "SELECT format, file_path FROM generations WHERE id = 1"
        ).fetchone()
        assert row[0] == "docx" and row[1] == "C:/legacy/a.docx"
        # CHECK 已放宽：能插入 pptx。
        conn.execute(
            """
            INSERT INTO generations
                (task_id, plan_id, format, file_path, template_used, page_plan_id, created_at)
            VALUES (2, 1, 'pptx', 'C:/legacy/b.pptx', 'x', 9, '2020-01-01T00:00:00+00:00')
            """
        )
        conn.commit()