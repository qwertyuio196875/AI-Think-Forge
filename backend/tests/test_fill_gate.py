"""填充闸门与填充任务记录（工单 9 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 9 的验收：
1. 方案未确认就请求填充 → **409**，且不产生任何章节正文（填充是唯一会调模型的写作环节，
   闸门一旦失守，模型就会替未定内容写正文）；
2. 已确认但**切不出章节** → **422**，并提示返回修订方案（不猜测、不按标题层级退化切分）；
3. 已确认且可切分 → **200**，返回章节清单与本次填充标识；
4. 有未处置的待确认事项 → 同样被拒（沿用既有闸门，纵深防御）；
5. 填充任务表记录目标字数 / 已完成章节数 / 状态 / 当前错误信息。

本单**只做闸门与任务记录**：不调模型、不逐章生成（#10 / #11）、不做字数分摊（#15）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.db.open_item_repository import OpenItemRepository
from app.main import create_app
from app.models.fill import DEFAULT_TARGET_LENGTH, MAX_TARGET_LENGTH

IDEA = "帮我准备一份面向新员工的产品培训"

V3_PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 读者\n新入职员工。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n\n"
    "## 关键约束\n篇幅控制在十页以内。\n"
)

# 旧格式：章节一节在，但每章没有建议字数 → 目标字数无从求和，只能落回系统默认值。
V2_PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n- 产品全景：讲清产品主线\n- 第一次上手：第一天要做的五件事\n"
)

# 没有「章节」一节：确认能成功（方案本身合法），但切不出成品章节 → 填充入口必须拒绝。
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


def _task_with_plan(
    client: TestClient,
    scripted: ScriptedModelClient,
    plan_md: str = V3_PLAN_MD,
    *,
    confirm: bool = True,
) -> int:
    """走完拷问 → 收敛出方案（可选：确认），返回任务 id。"""
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
    if confirm:
        confirmed = client.post(f"/api/grilling/tasks/{task_id}/plan/confirm")
        assert confirmed.status_code == 200
    return task_id


def _section_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT seq, title, content_md, status, target_length FROM plan_sections"
            " WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fill_rows(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM fill_tasks WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def test_fill_unknown_task_is_404(client: TestClient) -> None:
    response = client.post("/api/tasks/9999/fill", json={"target_length": 1000})
    assert response.status_code == 404
    assert response.json()["detail"] == "任务 9999 不存在"


def test_fill_without_plan_is_409(grilling_client: TestClient) -> None:
    """还没有任何结构化方案就请求填充 → 409。"""
    task_id = grilling_client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})
    assert response.status_code == 409
    assert "尚无结构化方案" in response.json()["detail"]


def test_fill_rejected_while_plan_is_not_confirmed(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """未确认 → 409，且不产生任何章节正文、不落填充任务。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client, confirm=False)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    assert response.status_code == 409
    assert "结构化方案尚未确认" in response.json()["detail"]
    assert all(row["content_md"] == "" for row in _section_rows(db_path, task_id))
    assert _fill_rows(db_path, task_id) == []


def test_fill_rejected_when_unresolved_open_item_exists(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """纵深防御：方案已确认后又被补进一条未处置事项，填充入口仍须拒绝。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)
    OpenItemRepository(str(db_path)).create(task_id, 2, "目标读者是否限定为一线主管？")

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    assert response.status_code == 409
    assert "待确认事项" in response.json()["detail"]
    assert _fill_rows(db_path, task_id) == []


def test_fill_rejected_when_no_section_can_be_split(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """已确认但方案「章节」一节切不出条目 → 422，并提示返回修订方案。"""
    task_id = _task_with_plan(
        grilling_client, scripted_model_client, NO_CHAPTER_PLAN_MD, confirm=True
    )
    assert _section_rows(db_path, task_id) == []

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "修订方案" in detail
    assert _fill_rows(db_path, task_id) == []


def test_fill_creates_task_and_returns_initial_progress(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """已确认且可切分 → 200，返回章节清单 + 本次填充标识 + 初始进度。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] > 0
    assert body["task_id"] == task_id
    assert body["plan_id"] > 0
    # 缺省目标字数 = 方案里各章建议字数之和（600 + 400），不做真正的按章分摊（#15）。
    assert body["target_length"] == 1000
    assert body["completed_sections"] == 0
    assert body["status"] == "running"
    assert body["status_label"] == "进行中"
    assert body["error"] is None
    assert body["total"] == 2
    assert [item["seq"] for item in body["items"]] == [1, 2]
    assert [item["title"] for item in body["items"]] == ["产品全景", "第一次上手"]
    assert all(item["status"] == "pending" for item in body["items"])

    # 只建任务记录，不写正文、不调模型（模型调用属 #10 / #11）。
    assert all(row["content_md"] == "" for row in _section_rows(db_path, task_id))
    assert len(scripted_model_client.calls) == calls_before

    rows = _fill_rows(db_path, task_id)
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]
    assert rows[0]["target_length"] == 1000
    assert rows[0]["completed_sections"] == 0
    assert rows[0]["status"] == "running"
    assert rows[0]["error"] is None

    # 初始进度与只读章节清单必须是同一份数据：前端不该为填充再写一套章节解析，
    # 也不该出现「总共几章」两个答案。
    listed = grilling_client.get(f"/api/tasks/{task_id}/sections").json()
    assert body["items"] == listed["items"]
    assert body["total"] == listed["total"]


def test_fill_accepts_explicit_target_and_per_section_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """显式目标字数与逐章建议字数落库，并可由只读章节清单读到。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill",
        json={"target_length": 1200, "section_lengths": {"1": 800, "2": 400}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_length"] == 1200
    assert [item["target_length"] for item in body["items"]] == [800, 400]
    assert [row["target_length"] for row in _section_rows(db_path, task_id)] == [800, 400]
    assert _fill_rows(db_path, task_id)[0]["target_length"] == 1200

    listed = grilling_client.get(f"/api/tasks/{task_id}/sections").json()
    assert [item["target_length"] for item in listed["items"]] == [800, 400]


def test_fill_rejects_per_section_length_for_unknown_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    task_id = _task_with_plan(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill", json={"section_lengths": {"1": 500, "9": 500}}
    )

    assert response.status_code == 422
    assert "9" in response.json()["detail"]
    assert _fill_rows(db_path, task_id) == []


def test_fill_rejects_target_length_over_cap(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """ADR-0006：目标字数上限 20000，超出即拒绝并说明原因。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill", json={"target_length": MAX_TARGET_LENGTH + 1}
    )

    assert response.status_code == 422
    assert str(MAX_TARGET_LENGTH) in response.json()["detail"]
    assert _fill_rows(db_path, task_id) == []


def test_fill_rejects_sum_of_suggested_lengths_over_cap(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """缺省目标字数由各章建议字数求和得出，求和超上限同样要拒（不是只看用户显式值）。

    这条也钉住「先判再写」：求和是算完才知道的，拒绝时不得把逐章字数先写进章节表。
    """
    plan_md = (
        "# 结构化方案\n\n## 章节\n"
        "- 标题：产品全景 ｜ 要点：主线 ｜ 建议字数：15000\n"
        "- 标题：第一次上手 ｜ 要点：五件事 ｜ 建议字数：8000\n"
    )
    task_id = _task_with_plan(grilling_client, scripted_model_client, plan_md)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})

    assert response.status_code == 422
    assert str(MAX_TARGET_LENGTH) in response.json()["detail"]
    assert _fill_rows(db_path, task_id) == []
    assert [row["target_length"] for row in _section_rows(db_path, task_id)] == [15000, 8000]


def test_fill_defaults_target_length_when_plan_has_no_suggested_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """旧方案（plan-v2）没有建议字数：落回系统默认目标字数，入口仍然放行。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client, V2_PLAN_MD)

    # 请求体整个省略也必须可用：横幅上的「填充为正文」不该强迫前端先编一个空对象。
    response = grilling_client.post(f"/api/tasks/{task_id}/fill")

    assert response.status_code == 200
    assert response.json()["target_length"] == DEFAULT_TARGET_LENGTH


def test_second_fill_while_one_is_running_is_409(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """同一任务同时只允许一次填充（逐章串行写入的前提）。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)
    first = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})
    assert first.status_code == 200

    second = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})

    assert second.status_code == 409
    assert "进行中的填充任务" in second.json()["detail"]
    assert len(_fill_rows(db_path, task_id)) == 1


def test_fill_task_record_survives_restart(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """填充任务落库，重启后仍可读到（进度不能只活在内存里）。"""
    task_id = _task_with_plan(grilling_client, scripted_model_client)
    created = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 900})
    assert created.status_code == 200
    fill_id = created.json()["id"]

    with TestClient(create_app(db_path=db_path, mount_frontend=False)) as rebuilt:
        # 用同一判据复跑一次：进行中的填充仍在，故仍旧拒绝重复启动。
        again = rebuilt.post(f"/api/tasks/{task_id}/fill", json={})
        assert again.status_code == 409

    rows = _fill_rows(db_path, task_id)
    assert len(rows) == 1
    assert rows[0]["id"] == fill_id
    assert rows[0]["target_length"] == 900
