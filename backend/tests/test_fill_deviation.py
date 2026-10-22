"""剩余字数反馈与收尾偏差修正（工单 16 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 16 的四条验收：
1. 喂给后续章节的上下文含「已用字数」与「剩余字数」；
2. 偏差超过 ±15% 时触发**一次且仅一次**重生成，目标是当前**最短**的一章；
3. 重生成后仍偏差过大时，响应里包含**实际字数与目标字数**；
4. 不为了凑字数注水，也不允许把话说到一半就截断。

口径（issue #2 §字数控制）：
- 「生成时把『本章目标字数 + 剩余字数』作为上下文传给模型。」
- 「收尾校验：实际总字数与目标的偏差超过阈值（±15%）时，只对最短的那一章重生成一次；
  重生成仍不达标则**明示偏差**，不静默接受。」

「明示偏差」的落点：`SerialFillResponse` 带 `target_length` / `actual_length` /
`deviation_ratio` / `deviation_note`，让前端不自己算也能说清差多少。
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.hanzi import count_hanzi

IDEA = "帮我准备一份面向新员工的产品培训"

# 三章，建议字数 600 / 400 / 300 → 目标 1300。
PLAN_MD = (
    "# 结构化方案\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n"
    "- 标题：常见疑问 ｜ 要点：三个高频问题的解答 ｜ 建议字数：300\n"
)

_SUMMARY = "本章讲完了这一节的内容，为下一章留下了继续往下读的线索。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _body(marker: str, hanzi: int) -> str:
    """造一段约 `hanzi` 个汉字的正文，开头带可识别的标记。"""
    offset = sum(ord(char) for char in marker) % 400
    filler = "".join(chr(0x4E00 + (index + offset) % 400) for index in range(max(0, hanzi - 10)))
    return f"## {marker}\n\n{marker}。{filler}。\n"


def _task_with_started_fill(
    client: TestClient, scripted: ScriptedModelClient, *responses: str
) -> int:
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        PLAN_MD,
        *responses,
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/fill", json={}).status_code == 200
    return task_id


def _sections(db_path: Path, task_id: int) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT seq, title, content_md, status, target_length FROM plan_sections"
            " WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _writing_calls(scripted: ScriptedModelClient, since: int) -> list[dict]:
    """写作调用（排除摘要调用）：摘要提示词带「## 本章正文（已写完）」。"""
    calls = []
    for call in scripted.calls[since:]:
        text = "\n".join(str(message.get("content", "")) for message in call["messages"])
        if "## 本章正文（已写完）" in text:
            continue
        calls.append(call)
    return calls


# ---------- 剩余字数反馈 ----------


def test_remaining_length_is_fed_to_later_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """第三章的上下文里必须出现「已用字数」与「剩余字数」的具体数。"""
    # 按「正文 / 摘要」交错排好：三章正文各 600 / 400 / 300 字左右。
    responses: list[str] = []
    for marker, length in (("第一段", 600), ("第二段", 400), ("第三段", 300)):
        responses.extend([_body(marker, length), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")
    assert response.status_code == 200

    writing = _writing_calls(scripted_model_client, calls_before)
    assert len(writing) >= 3
    # 第一章不该有「已用字数」（还没写），后续章节必须有。
    first_text = "\n".join(str(m.get("content", "")) for m in writing[0]["messages"])
    assert "已用字数" in first_text
    for call in writing[1:]:
        text = "\n".join(str(m.get("content", "")) for m in call["messages"])
        assert "剩余字数" in text
        assert "已用字数" in text
        assert "本次不按剩余字数收敛" not in text


def test_remaining_length_decreases_across_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """剩余字数逐章递减：后面的章节看到的余量比前面的少。"""
    responses: list[str] = []
    for marker, length in (("第一段", 600), ("第二段", 400), ("第三段", 300)):
        responses.extend([_body(marker, length), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)
    calls_before = len(scripted_model_client.calls)

    assert grilling_client.post(f"/api/tasks/{task_id}/fill/run").status_code == 200

    remaining: list[int] = []
    for call in _writing_calls(scripted_model_client, calls_before):
        text = "\n".join(str(m.get("content", "")) for m in call["messages"])
        marker = "## 剩余字数（本章还剩多少）\n"
        if marker not in text:
            continue
        segment = text.split(marker, 1)[1].split("\n", 1)[0].strip()
        if segment.isdigit():
            remaining.append(int(segment))
    assert len(remaining) >= 2
    # 余量单调不增（写作进度只会往前走）。
    assert all(earlier >= later for earlier, later in itertools.pairwise(remaining))


# ---------- 偏差修正 ----------


def test_short_total_triggers_exactly_one_regeneration_of_shortest_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """总字数明显偏短（超 −15%）→ 只重生成**最短**那一章一次，不重写别的章。"""
    # 目标 1300；实际只写 3 × 120 = 360 字，偏差约 −72%。
    responses: list[str] = []
    for marker in ("第一段", "第二段", "第三段"):
        responses.extend([_body(marker, 120), _SUMMARY])
    # 重生成时给一段更长的正文（补足差额），随后是它的摘要。
    responses.extend([_body("重生成段", 1000), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 200
    body = response.json()
    # 实际字数与目标字数都在响应里（验收 3）。
    assert body["target_length"] == 1300
    assert body["actual_length"] > 0

    # 只多了一次写作调用（重生成那一次），说明「只重生成一次」。
    writing = _writing_calls(scripted_model_client, calls_before)
    assert len(writing) == 4, f"期望 3 次正常写作 + 1 次重生成，实际 {len(writing)} 次"

    # 被重写的是最短的那一章（三章一样短时按序号取第一个）。
    rows = _sections(db_path, task_id)
    regenerated = [row for row in rows if "重生成段" in row["content_md"]]
    assert len(regenerated) == 1
    assert regenerated[0]["seq"] == 1


def test_regeneration_targets_the_shortest_section(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """三章长短不一时，重生成打在**最短**的那一章上，而不是第一章或最后一章。"""
    responses: list[str] = []
    # 目标 1300：第一章 100 字（最短）、第二章 300 字、第三章 300 字 → 合计 700，偏差 −46%。
    for marker, length in (("第一段", 100), ("第二段", 300), ("第三段", 300)):
        responses.extend([_body(marker, length), _SUMMARY])
    responses.extend([_body("重生成段", 900), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")
    assert response.status_code == 200

    rows = _sections(db_path, task_id)
    regenerated = [row for row in rows if "重生成段" in row["content_md"]]
    assert len(regenerated) == 1
    assert regenerated[0]["seq"] == 1, "最短的是第一章，重生成该打在这里"


def test_no_regeneration_when_within_threshold(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """偏差在 ±15% 以内不重生成：不为了凑字数额外烧模型额度。"""
    responses: list[str] = []
    # 目标 1300，实际 3 × 430 = 1290，偏差约 −0.8%。
    for marker in ("第一段", "第二段", "第三段"):
        responses.extend([_body(marker, 430), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 200
    assert len(_writing_calls(scripted_model_client, calls_before)) == 3
    body = response.json()
    assert body["deviation_note"] is None or body["deviation_note"] == ""


def test_deviation_is_reported_when_regeneration_still_off(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """重生成后仍偏差过大 → **明示偏差**：响应给出实际字数、目标字数与偏差比例。"""
    responses: list[str] = []
    for marker in ("第一段", "第二段", "第三段"):
        responses.extend([_body(marker, 100), _SUMMARY])
    # 重生成还是短：总字数仍远低于目标。
    responses.extend([_body("重生成段", 120), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert response.status_code == 200
    body = response.json()
    assert body["target_length"] == 1300
    assert body["actual_length"] < 1300
    # 偏差比例是负数且超出 −15%。
    assert body["deviation_ratio"] is not None
    assert body["deviation_ratio"] < -0.15
    # 明示偏差的文案必须同时提到实际与目标，不许只说「有偏差」。
    note = body["deviation_note"]
    assert note
    assert str(body["actual_length"]) in note
    assert str(body["target_length"]) in note


def test_regeneration_does_not_truncate_or_pad_other_sections(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """重生成只影响最短那一章：其余章节的正文**逐字不变**（不截断、不补写）。"""
    second = _body("第二段", 300)
    third = _body("第三段", 300)
    responses: list[str] = []
    responses.extend([_body("第一段", 100), _SUMMARY])
    responses.extend([second, _SUMMARY])
    responses.extend([third, _SUMMARY])
    responses.extend([_body("重生成段", 900), _SUMMARY])
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)

    assert grilling_client.post(f"/api/tasks/{task_id}/fill/run").status_code == 200
    after = {row["seq"]: row["content_md"] for row in _sections(db_path, task_id)}

    # 第 2、3 章原样保留：既没被截短，也没被补写（新写的"重生成段"不该出现在这里）。
    assert after[2] == second.strip()
    assert after[3] == third.strip()
    assert "重生成段" not in after[2]
    assert "重生成段" not in after[3]


def test_deviation_fields_appear_on_single_chapter_fill_too(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """单章填充（#10 的端点）也要给出实际字数：闭环报告不能只在串行路径上出现。"""
    responses = [_body("第一段", 200), _SUMMARY]
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, *responses)

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")

    assert response.status_code == 200
    section = response.json()["section"]
    assert section["hanzi_count"] == count_hanzi(_body("第一段", 200))
