"""成品章节表与章节切分（工单 7 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 7 的四条验收：
1. 同一份方案，章节清单与方案「章节」一节的条目**同序同数**（Word 侧的同一断言由
   填充工单 #10 在真实成品上复核——本单的成品目录清单就是那次核对的唯一依据）；
2. 方案里没有可切分的章节 → **空清单**，不是错误；
3. 状态能表达「待写 / 已完成 / 失败」，且字数可读（后端按唯一入口 `app.hanzi` 现算）；
4. **不提供**改名、排序、增删章节的接口。

术语（GLOSSARY）：方案分节 ≠ 成品章节。清单只来自方案「章节」那一节里的条目，
不拿 `##` 切分结果当成品目录。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.main import create_app

IDEA = "帮我准备一份面向新员工的产品培训"

# plan-v3 形状：章节一节是「每章一行、全角竖线分隔」的条目。
V3_PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)

# 旧格式（plan-v2）：章节一节在，但没有建议字数；解析仍要给出清单。
V2_PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n- 产品全景：讲清产品主线\n- 第一次上手：第一天要做的五件事\n"
)

# 没有「章节」一节：其余 `##` 都是方案分节，不得被当成成品章节。
NO_CHAPTER_PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 输出要求\nWord 文档。\n"
)


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _confirmed_task(
    client: TestClient, scripted: ScriptedModelClient, plan_md: str = V3_PLAN_MD
) -> int:
    """走完拷问 → 收敛出方案 → 确认方案，返回任务 id（确认即切分落库）。"""
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        plan_md,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    advanced = client.post(f"/api/grilling/tasks/{task_id}/advance")
    assert advanced.status_code == 200
    confirmed = client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")
    assert confirmed.status_code == 200
    return task_id


def _write_section(
    db_path: Path, task_id: int, seq: int, *, content_md: str, status: str
) -> None:
    """直接改库模拟「填充模块」写正文（本单不该有写接口；三态要靠库才能造出来）。"""
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE plan_sections SET content_md = ?, status = ?,
                   completed_at = CASE WHEN ? = 'completed' THEN '2026-10-20T00:00:00+00:00'
                                       ELSE NULL END
            WHERE task_id = ? AND seq = ?
            """,
            (content_md, status, status, task_id, seq),
        )
        connection.commit()


# --- 验收 ①：清单与方案「章节」条目同序同数 -------------------------------------


def test_confirmed_plan_exposes_sections_in_plan_order(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """确认方案 → 清单逐项对上方案「章节」一节：同序、同数、标题 / 要点 / 建议字数齐全。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    response = grilling_client.get(f"/api/tasks/{task_id}/sections")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["seq"] for item in body["items"]] == [1, 2]
    assert [item["title"] for item in body["items"]] == ["产品全景", "第一次上手"]
    assert [item["key_points"] for item in body["items"]] == [
        "从三个真实场景切入讲清主线",
        "第一天要做的五件事",
    ]
    assert [item["target_length"] for item in body["items"]] == [600, 400]


def test_section_list_belongs_to_the_current_plan(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """清单必须标明所属方案：清单一律属于某一版方案，前端据此判断是否过期。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    plan = grilling_client.get(f"/api/grilling/tasks/{task_id}/plan").json()

    body = grilling_client.get(f"/api/tasks/{task_id}/sections").json()

    assert body["plan_id"] == plan["id"]


def test_section_titles_appear_in_word_deliverable_in_same_order(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """清单与 Word 成品同序：成品正文里每章标题的出现位置必须按清单序号递增。

    本单的成品仍整篇渲染（逐章填充是工单 #10），所以这里查的是「标题在成品正文里
    的先后」而不是「几级标题」——「同数」那一半由 #10 在逐章产物上复核，
    但「同序」现在就能钉住：清单顺序与用户拿到的文件顺序一旦分叉，
    就会出现「第三章写进第四章」。
    """
    from docx import Document

    task_id = _confirmed_task(grilling_client, scripted_model_client)
    items = grilling_client.get(f"/api/tasks/{task_id}/sections").json()["items"]

    generated = grilling_client.post(f"/api/tasks/{task_id}/generations")
    assert generated.status_code == 201

    document = Document(generated.json()["file_path"])
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    positions = [text.find(item["title"]) for item in items]

    assert all(position >= 0 for position in positions), positions
    assert positions == sorted(positions)
    # 同数：清单里的每一章在成品里出现且只出现一次，没有多出来的章、也没有漏掉的章。
    assert [text.count(item["title"]) for item in items] == [1] * len(items)


def test_v2_plan_without_suggested_length_still_lists_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """旧格式方案的章节没有建议字数 → 清单照给，`target_length` 为空而不是 0 或报错。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, plan_md=V2_PLAN_MD)

    body = grilling_client.get(f"/api/tasks/{task_id}/sections").json()

    assert [item["title"] for item in body["items"]] == ["产品全景", "第一次上手"]
    assert [item["target_length"] for item in body["items"]] == [None, None]


# --- 验收 ②：无可切分章节 → 空清单，不报错 --------------------------------------


def test_plan_without_chapter_section_returns_empty_list(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案没有「章节」一节 → 200 + 空清单（不猜标题层级、不报错）。"""
    task_id = _confirmed_task(
        grilling_client, scripted_model_client, plan_md=NO_CHAPTER_PLAN_MD
    )

    response = grilling_client.get(f"/api/tasks/{task_id}/sections")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_sections_before_any_plan_returns_404(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """尚未收敛出方案 → 404（与 `GET /plan` 的口径一致，不是空清单）。"""
    scripted_model_client.set_result(_frontier_json(("Q", "正文", "推荐")))
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"][
        "id"
    ]

    response = grilling_client.get(f"/api/tasks/{task_id}/sections")

    assert response.status_code == 404


def test_sections_for_missing_task_returns_404(grilling_client: TestClient) -> None:
    """任务不存在 → 404。"""
    assert grilling_client.get("/api/tasks/9999/sections").status_code == 404


# --- 验收 ③：三态 + 字数可读 ----------------------------------------------------


def test_new_sections_start_pending_with_zero_hanzi(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """刚切出来的章是「待写」、零字、无完成时间。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    items = grilling_client.get(f"/api/tasks/{task_id}/sections").json()["items"]

    assert [item["status"] for item in items] == ["pending", "pending"]
    assert [item["status_label"] for item in items] == ["待写", "待写"]
    assert [item["hanzi_count"] for item in items] == [0, 0]
    assert [item["completed_at"] for item in items] == [None, None]


def test_completed_and_failed_statuses_are_readable_with_hanzi_count(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
) -> None:
    """三态与字数：已完成 / 失败都能读出来，字数据按汉字计（标点、空白、数字都不算）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    _write_section(
        db_path, task_id, 1, content_md="产品全景已经写完了，共八字。", status="completed"
    )
    _write_section(db_path, task_id, 2, content_md="第一次上手", status="failed")

    items = grilling_client.get(f"/api/tasks/{task_id}/sections").json()["items"]

    assert [item["status"] for item in items] == ["completed", "failed"]
    assert [item["status_label"] for item in items] == ["已完成", "失败"]
    # 「产品全景已经写完了，共八字。」：只数汉字 → 产品全景已经写完了共八字 = 12
    assert items[0]["hanzi_count"] == 12
    assert items[1]["hanzi_count"] == 5
    assert items[0]["completed_at"] is not None
    assert items[1]["completed_at"] is None


def test_target_length_is_not_hanzi_count(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
) -> None:
    """`target_length` 是方案给的建议字数（不变）；`hanzi_count` 随已写正文变化。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    _write_section(db_path, task_id, 1, content_md="第一章", status="pending")

    first = grilling_client.get(f"/api/tasks/{task_id}/sections").json()["items"][0]

    assert first["hanzi_count"] == 3
    assert first["target_length"] == 600


# --- 验收 ④：不提供改名 / 排序 / 增删接口 ---------------------------------------


def test_section_list_is_read_only(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """章节清单只读：写方法一律 405，改名 / 排序端点根本不存在。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)

    for method in ("post", "put", "patch", "delete"):
        response = getattr(grilling_client, method)(f"/api/tasks/{task_id}/sections")
        assert response.status_code == 405, method

    for path in (
        f"/api/tasks/{task_id}/sections/1",
        f"/api/tasks/{task_id}/sections/reorder",
    ):
        assert grilling_client.patch(path, json={"title": "改名"}).status_code == 404
        assert grilling_client.delete(path).status_code == 404


# --- 唯一键「方案 + 序号」与修订后重切 ------------------------------------------


def test_reconfirming_the_same_plan_does_not_duplicate_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """同一份方案重复确认 → 清单条数不变（唯一键「方案 + 序号」，不堆重复行）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    for _ in range(2):
        assert (
            grilling_client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code
            == 200
        )

    body = grilling_client.get(f"/api/tasks/{task_id}/sections").json()

    assert body["total"] == 2
    assert [item["seq"] for item in body["items"]] == [1, 2]


def test_revision_rebuilds_sections_matching_by_title(
    grilling_client: TestClient,
    scripted_model_client: ScriptedModelClient,
    db_path: Path,
) -> None:
    """方案修订 → 按标题重切：留下的章保住正文与状态，改名的章废弃重建，新章待写。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    _write_section(db_path, task_id, 1, content_md="产品全景原稿", status="completed")

    revised_md = (
        "# 结构化方案\n\n"
        "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
        "## 章节\n"
        "- 标题：产品全景 ｜ 要点：换个讲法 ｜ 建议字数：800\n"
        "- 标题：常见问题 ｜ 要点：答疑清单 ｜ 建议字数：300\n"
    )
    scripted_model_client.set_result(revised_md)
    revised = grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions",
        json={"instruction": "把第二章换成常见问题"},
    )
    assert revised.status_code == 200

    items = grilling_client.get(f"/api/tasks/{task_id}/sections").json()["items"]

    assert [item["title"] for item in items] == ["产品全景", "常见问题"]
    assert [item["seq"] for item in items] == [1, 2]
    # 标题匹配上的一章：状态留住、字数还在，目标字数按新方案更新。
    assert items[0]["status"] == "completed"
    assert items[0]["hanzi_count"] == 6
    assert items[0]["target_length"] == 800
    # 新出现的章：待写、零字。
    assert items[1]["status"] == "pending"
    assert items[1]["hanzi_count"] == 0


def test_revision_to_a_plan_without_chapters_clears_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案被修订成没有章节 → 旧目录一并清空，不留残影。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    scripted_model_client.set_result(NO_CHAPTER_PLAN_MD)

    grilling_client.post(
        f"/api/grilling/tasks/{task_id}/plan/revisions", json={"instruction": "先不列章节"}
    )

    body = grilling_client.get(f"/api/tasks/{task_id}/sections").json()

    assert body["items"] == []
    assert body["total"] == 0


def test_sections_survive_restart(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """章节落库：重建 app 后清单与重启前完全一致（重启续作）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client)
    before = grilling_client.get(f"/api/tasks/{task_id}/sections").json()

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        after = rebuilt.get(f"/api/tasks/{task_id}/sections").json()

    assert after == before
