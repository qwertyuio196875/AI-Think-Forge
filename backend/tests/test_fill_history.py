"""前情提要（工单 12 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 12 的四条验收：

1. **喂给第 N 章的上下文包含前 N-1 章累积的摘要**；
2. **摘要生成失败不阻断正文生成**，仅该段提要缺失；
3. **摘要有长度上限**，不会无限膨胀；
4. **第一章的上下文不含空提要噪声**。

为什么要摘要：逐章填充时第 N 章若不知道前面写了什么，每章都像独立写出来的，
拼起来是一堆互不相干的短文。摘要是唯一跨章传递上下文的载体。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect
from app.fill.history import SUMMARY_MAX_HANZI

IDEA = "帮我准备一份面向新员工的产品培训"

PLAN_MD = (
    "# 结构化方案\n\n"
    "## 目标\n让新员工在入职两周内掌握产品全貌。\n\n"
    "## 章节\n"
    "- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：600\n"
    "- 标题：第一次上手 ｜ 要点：第一天要做的五件事 ｜ 建议字数：400\n"
    "- 标题：常见疑问 ｜ 要点：三个高频问题的解答 ｜ 建议字数：300\n"
)

# 正文长度必须与方案建议字数（600 / 400 / 300）相称：工单 16 的收尾校验会在
# 总字数偏差超 ±15% 时对最短的一章重生成一次。夹具若只有几十个字（偏差 −95%），
# 这些用例会**正确地**触发重生成，于是「每写完一章压一次摘要」的断言就会多出一条。
def _body(title: str, hanzi: int, filler: str) -> str:
    """造一段约 `hanzi` 个汉字的正文，开头带小标题与可识别的首句。"""
    unit = len(filler)
    repeat = max(1, -(-hanzi // unit))
    return f"## {title}\n\n{filler * repeat}\n"


BODY_FIRST = _body(
    "早上开工",
    580,
    "第一篇正文讲产品主线是怎么串起来的：先从三个真实场景入手，再落到每天要走的流程上。",
)
BODY_SECOND = _body(
    "第一天",
    390,
    "第二篇正文讲第一天要做的五件事，按顺序做完再回头看，会发现门槛比想象中低得多。",
)
BODY_THIRD = _body(
    "额度问题",
    290,
    "第三篇正文讲三个高频问题的答案，其中额度的答案随用量变化，要按实际场景判断。",
)

# 三章各自的摘要：能被区分开，才能验证「喂给第 N 章的是前 N-1 章」。
SUMMARY_FIRST = "第一章讲完了产品主线与三个真实场景。"
SUMMARY_SECOND = "第二章讲完了第一天要做的五件事。"
SUMMARY_THIRD = "第三章回答了三类高频问题。"


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _start_fill(
    client: TestClient,
    scripted: ScriptedModelClient,
    *responses: str,
) -> int:
    """走完拷问 → 确认方案 → 开始填充，返回任务 id；`responses` 是后续调用的应答序列。"""
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


def _writing_prompts(scripted: ScriptedModelClient) -> list[str]:
    """取出「正文写作」那几次调用的完整提示词（按调用顺序）。

    摘要调用与正文调用共用同一个客户端，靠提示词里的「本章要点」区分：
    只有正文调用会带上这一节（摘要是对已写正文的压缩，不给要点）。
    """
    prompts: list[str] = []
    for call in scripted.calls:
        text = "\n".join(message["content"] for message in call["messages"])
        if "## 本章要点" in text:
            prompts.append(text)
    return prompts


def _summary_prompts(scripted: ScriptedModelClient) -> list[str]:
    """取出「摘要」那几次调用的完整提示词。"""
    prompts: list[str] = []
    for call in scripted.calls:
        text = "\n".join(message["content"] for message in call["messages"])
        if "## 本章正文（已写完）" in text:
            prompts.append(text)
    return prompts


# --- 验收 ①：第 N 章含前 N-1 章摘要 -------------------------------------------------


def test_later_chapters_carry_earlier_summaries(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """第二章能看到第一章的摘要，第三章能看到前两章的摘要。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        SUMMARY_FIRST,
        BODY_SECOND,
        SUMMARY_SECOND,
        BODY_THIRD,
        SUMMARY_THIRD,
    )

    assert grilling_client.post(f"/api/tasks/{task_id}/fill/run").status_code == 200

    prompts = _writing_prompts(scripted_model_client)
    assert len(prompts) == 3
    # 第一章：没有前面的提要。
    assert SUMMARY_FIRST not in prompts[0]
    # 第二章：含第一章摘要，不含第二章自己的（它还没写）。
    assert SUMMARY_FIRST in prompts[1]
    assert SUMMARY_SECOND not in prompts[1]
    # 第三章：前两章的摘要都在。
    assert SUMMARY_FIRST in prompts[2]
    assert SUMMARY_SECOND in prompts[2]


def test_first_chapter_has_no_history_noise(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """第一章的上下文给的是「暂无」占位，不是一段空白，也不是别的章的摘要。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        SUMMARY_FIRST,
        BODY_SECOND,
        SUMMARY_SECOND,
        BODY_THIRD,
        SUMMARY_THIRD,
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    first = _writing_prompts(scripted_model_client)[0]
    assert "暂无：这是第一章" in first


# --- 验收 ②：摘要失败不阻断正文 ------------------------------------------------------


def test_summary_failure_does_not_block_writing(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """摘要调用失败：正文照样写完，成品照样产出，只是少了那段提要。

    用 `set_error` 让**所有**调用都失败来模拟「摘要服务挂了」是不对的——那会把正文
    调用也一起打挂。这里用「摘要专用失败」的替身：只有摘要那次调用抛错。
    """
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        SUMMARY_FIRST,
        BODY_SECOND,
        SUMMARY_SECOND,
        BODY_THIRD,
        SUMMARY_THIRD,
    )
    scripted_model_client.fail_summary_calls(httpx.ConnectError("summary boom"))

    response = grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    # 摘要失败不阻断：正文照样写完，整篇仍然完成。
    assert response.status_code == 200
    assert response.json()["completed_sections"] == 3

    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT status FROM plan_sections WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
    assert [row["status"] for row in rows] == ["completed"] * 3


# --- 验收 ③：摘要长度上限 ------------------------------------------------------------


def test_overlong_summary_is_truncated(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """模型返回超长摘要时被截断，前情提要不会无限膨胀。"""
    overlong = "很长的摘要内容。" * 200
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        overlong,
        BODY_SECOND,
        overlong,
        BODY_THIRD,
        overlong,
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    prompts = _writing_prompts(scripted_model_client)
    # 第三章的提要里，每条摘要都被截到上限以内。
    for text in prompts:
        assert len(text) < 12000, "前情提要无限膨胀了"


def test_summary_max_hanzi_is_a_real_bound() -> None:
    """长度上限是一个真实的常量（不是随手写的魔法数字）。"""
    assert 50 <= SUMMARY_MAX_HANZI <= 500


# --- 验收 ④：摘要调用参数 ------------------------------------------------------------


def test_summary_call_uses_smaller_budget_than_writing(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """摘要是短输出，输出上限与超时都比正文小——不必为一句摘要留 8192 token。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        SUMMARY_FIRST,
        BODY_SECOND,
        SUMMARY_SECOND,
        BODY_THIRD,
        SUMMARY_THIRD,
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    summary_calls = [
        call
        for call in scripted_model_client.calls
        if "## 本章正文（已写完）" in "\n".join(m["content"] for m in call["messages"])
    ]
    assert summary_calls
    for call in summary_calls:
        assert call["max_tokens"] is not None and call["max_tokens"] < 8192
        assert call["timeout"] is not None and call["timeout"] < 180.0


def test_each_finished_section_triggers_one_summary(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """每写完一章压一次摘要（三次正文 → 三次摘要）。"""
    task_id = _start_fill(
        grilling_client,
        scripted_model_client,
        BODY_FIRST,
        SUMMARY_FIRST,
        BODY_SECOND,
        SUMMARY_SECOND,
        BODY_THIRD,
        SUMMARY_THIRD,
    )

    grilling_client.post(f"/api/tasks/{task_id}/fill/run")

    assert len(_writing_prompts(scripted_model_client)) == 3
    assert len(_summary_prompts(scripted_model_client)) == 3
