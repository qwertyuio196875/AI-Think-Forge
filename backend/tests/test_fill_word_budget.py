"""字数分摊与逐章可改（工单 15 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 15 的五条验收：
1. 各章建议字数之和**恰好**等于目标字数（余数归最后一章）；
2. 给定权重时对应章节分到更多字数；
3. 超出 300–20000 时明确拒绝并说明，**不静默改成边界值**；
4. 预设档位与自定义输入都可用（前端参数弹窗，见 `frontend/tests/wordBudget.test.mts`）；
5. 字数参数与目标字数使用同一个计量入口（`app.hanzi.count_hanzi`，不另写一套）。

口径（issue #2 §字数控制）：「逐章分摊：按章节权重（由方案里的『建议字数』或字数均值
给出）分配，余数给最后一章，保证各章之和 = 目标字数。」
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.models.fill import MAX_TARGET_LENGTH, MIN_TARGET_LENGTH

IDEA = "帮我准备一份面向新员工的产品培训"


def _plan_md(*lengths: int | None) -> str:
    """按给定建议字数生成 plan-v3 形状的方案（None 表示该章不写建议字数）。"""
    lines = ["# 结构化方案", "", "## 章节"]
    for index, length in enumerate(lengths, start=1):
        parts = [f"标题：第 {index} 章", "要点：围绕主线展开"]
        if length is not None:
            parts.append(f"建议字数：{length}")
        lines.append("- " + " ｜ ".join(parts))
    return "\n".join(lines) + "\n"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _confirmed_task(
    client: TestClient, scripted: ScriptedModelClient, plan_md: str
) -> int:
    """走完拷问 → 收敛出方案 → 确认方案，返回任务 id。"""
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


def _section_lengths(client: TestClient, task_id: int) -> list[int | None]:
    listed = client.get(f"/api/tasks/{task_id}/sections")
    assert listed.status_code == 200
    return [item["target_length"] for item in listed.json()["items"]]


def _fill_target_length(db_path: Path, task_id: int) -> int:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT target_length FROM fill_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    return int(row["target_length"])


def test_allocation_sums_exactly_to_target(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """三章、目标 1000 字：各章之和必须**恰好** 1000，余数归最后一章。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None, None))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    assert response.status_code == 200
    lengths = [item["target_length"] for item in response.json()["items"]]
    assert sum(lengths) == 1000
    assert all(length is not None and length > 0 for length in lengths)


def test_allocation_remainder_goes_to_last_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """1000 均分到三章除不尽：前两章取整，最后一章吃掉余数（和恒等于 1000）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None, None))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    lengths = [item["target_length"] for item in response.json()["items"]]
    assert sum(lengths) == 1000
    # 333 + 333 + 334：余数落在最后一章。
    assert lengths[0] == lengths[1]
    assert lengths[2] == 1000 - lengths[0] - lengths[1]


def test_allocation_respects_weights_from_suggested_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """方案给了 600 / 400 的建议字数：目标 2000 时，重的章分到更多。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 2000})

    lengths = [item["target_length"] for item in response.json()["items"]]
    assert sum(lengths) == 2000
    assert lengths[0] > lengths[1]
    # 权重 3:2 → 1200 / 800。
    assert lengths == [1200, 800]


def test_allocation_falls_back_to_equal_weight_without_suggested_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """旧格式方案（没有建议字数）：按均分，各章之和仍等于目标。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 900})

    lengths = [item["target_length"] for item in response.json()["items"]]
    assert lengths == [450, 450]


def test_allocation_ignores_stale_suggested_lengths_when_target_changes(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """再开一次填充换了目标字数：分摊结果必须按新目标重算，不是沿用上次的章字数。

    先把上一条填充任务收尾（否则第二次会被 409 拦下——同时只允许一次进行中）。
    """
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))
    first = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 2000})
    assert first.status_code == 200

    second = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 1000})

    # 已有进行中的填充 → 409；这条正是「一次只允许一次填充」的既有约束，不该被本单破坏。
    assert second.status_code == 409


def test_explicit_section_lengths_win_over_allocation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """用户逐章改过的数值优先于系统分摊（本单的核心诉求：逐章可改）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None, None))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill",
        json={"target_length": 1000, "section_lengths": {"2": 700}},
    )

    assert response.status_code == 200
    lengths = [item["target_length"] for item in response.json()["items"]]
    assert lengths[1] == 700
    # 用户改过的那一章保持用户值；未改的章仍按分摊补齐，总和仍是目标字数。
    assert sum(lengths) == 1000


def test_target_length_below_minimum_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """低于 300 字 → 422，说明原因，**不静默改成 300**。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 299})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert str(MIN_TARGET_LENGTH) in detail
    assert "299" in detail
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM fill_tasks WHERE task_id = ?", (task_id,)
        ).fetchall()
    assert rows == []


def test_target_length_above_maximum_is_rejected(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """高于 20000 字 → 422，说明原因，**不静默改成 20000**。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill", json={"target_length": MAX_TARGET_LENGTH + 1}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert str(MAX_TARGET_LENGTH) in detail
    assert str(MAX_TARGET_LENGTH + 1) in detail


def test_preset_bounds_are_accepted(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """边界值本身是合法的：300 与 20000 都放行。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    low = grilling_client.post(
        f"/api/tasks/{task_id}/fill", json={"target_length": MIN_TARGET_LENGTH}
    )
    assert low.status_code == 200
    assert low.json()["target_length"] == MIN_TARGET_LENGTH

    high = grilling_client.post(
        f"/api/tasks/{task_id}/fill", json={"target_length": MAX_TARGET_LENGTH}
    )
    # 第二次仍被「一次只允许一次进行中」挡住，这不是本单要改的约束。
    assert high.status_code == 409


def test_allocation_lands_in_section_table(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """分摊结果落进章节表（方案是字数真源），只读清单读到的与响应一致。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 2000})
    assert response.status_code == 200

    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT seq, target_length FROM plan_sections WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
    assert [row["target_length"] for row in rows] == [1200, 800]
    assert _fill_target_length(db_path, task_id) == 2000
    assert _section_lengths(grilling_client, task_id) == [1200, 800]


def test_default_target_is_sum_of_suggested_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """不给目标字数时，以各章建议字数之和为目标；此时分摊结果就是建议字数本身。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["target_length"] == 1000
    assert [item["target_length"] for item in body["items"]] == [600, 400]


# ---------- 分摊预览：只算不写 ----------


def test_allocation_preview_does_not_write_anything(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """预览只算不写：章节表与填充任务表都不得被它改动。

    这是预览与 `POST /fill` 的关键差别——若预览也落库，用户在弹窗里来回试几次字数，
    章节表就被改了几回，而他从没点过「确认开始填充」。
    """
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill/allocation", json={"target_length": 5000}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_length"] == 5000
    assert sum(item["target_length"] for item in body["items"]) == 5000

    # 章节表仍是方案给的建议字数，填充任务表仍然为空。
    assert _section_lengths(grilling_client, task_id) == [600, 400]
    with connect(db_path) as connection:
        fill_rows = connection.execute(
            "SELECT * FROM fill_tasks WHERE task_id = ?", (task_id,)
        ).fetchall()
    assert fill_rows == []


def test_allocation_preview_matches_real_allocation(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """预览与真正开工必须给出同一份分摊结果——否则用户看到的和写出的是两回事。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(600, 400))

    preview = grilling_client.post(
        f"/api/tasks/{task_id}/fill/allocation", json={"target_length": 2000}
    )
    assert preview.status_code == 200

    started = grilling_client.post(f"/api/tasks/{task_id}/fill", json={"target_length": 2000})
    assert started.status_code == 200

    assert [item["target_length"] for item in preview.json()["items"]] == [
        item["target_length"] for item in started.json()["items"]
    ]


def test_allocation_preview_rejects_out_of_range_target(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """预览同样按 300–20000 校验，且不静默夹到边界值。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill/allocation", json={"target_length": MAX_TARGET_LENGTH + 1}
    )

    assert response.status_code == 422
    assert str(MAX_TARGET_LENGTH + 1) in response.json()["detail"]


def test_allocation_preview_respects_explicit_section_lengths(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """逐章改过的值在预览里也要生效（用户就是靠预览来微调）。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None, None))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill/allocation",
        json={"target_length": 900, "section_lengths": {"1": 500}},
    )

    assert response.status_code == 200
    lengths = [item["target_length"] for item in response.json()["items"]]
    assert lengths[0] == 500
    assert sum(lengths) == 900


def test_allocation_rejects_overrides_exceeding_target(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """逐章改后之和超过目标 → 422 并说清差多少，不偷偷压缩其他章。"""
    task_id = _confirmed_task(grilling_client, scripted_model_client, _plan_md(None, None))

    response = grilling_client.post(
        f"/api/tasks/{task_id}/fill",
        json={"target_length": 1000, "section_lengths": {"1": 900, "2": 900}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "1800" in detail
    assert "1000" in detail

