"""长章分段生成（工单 17 / ADR-0006；接缝 = 进程内 HTTP；模型走 fake）。

钉住工单 17 的四条验收：
1. **8000 字量级的单章能完整产出**，不出现半篇；
2. 任一分段命中「长度上限」即按**硬错误**处理，不静默截断（规格 §字数控制最后一条）；
3. 拼接后的章节在**段落边界**处自然衔接，不重复不丢失；
4. 每次分段累计校验字数与终止原因。

口径（issue #2 §字数控制）：
- 「单章超出模型单次输出上限时，按段落分多次调用并拼接，每次累计校验字数与终止原因。」
- 「终止原因若为『达到长度上限』，**一律按硬错误处理**，绝不静默截断成半篇。」

本单只改**单章写作**这一条路径：`app.fill.writer.write_section` 在目标字数较大时改为
分段调用再拼接。既有的单次调用路径（小章节）行为与调用参数一条不变。

**分段数属实现细节，不在断言里钉死**：测试只断言「发生了多次调用」「模型实际返回的
每一段都进了正文且只进一次」，这样换一种分段策略（比如每段 1500 字）也不会让测试变红。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from docx import Document
from fakes import ScriptedModelClient
from fastapi.testclient import TestClient

from app.db.database import connect

IDEA = "帮我准备一份面向新员工的产品培训"

# 造够用的分段脚本：实际会用掉前 N 条（N 由实现的分段策略决定）。
_SCRIPTED_SEGMENTS = 10


def _plan_md(length: int) -> str:
    return (
        "# 结构化方案\n\n"
        "## 章节\n"
        f"- 标题：产品全景 ｜ 要点：从三个真实场景切入讲清主线 ｜ 建议字数：{length}\n"
    )


def _frontier_json(*triples: tuple[str, str, str]) -> str:
    frontier = [
        {"title": title, "body": body, "recommended_answer": answer}
        for title, body, answer in triples
    ]
    return json.dumps({"frontier": frontier}, ensure_ascii=False)


def _hanzi(text: str) -> int:
    """测试侧独立数一遍汉字（只用于构造断言，不依赖被测实现）。"""
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _paragraph(marker: str, hanzi: int) -> str:
    """造一段约 `hanzi` 个汉字的正文；同一段内不出现别的段标记。"""
    # 用不同的起始偏移让各段内容不同，同时保证长度稳定。
    offset = sum(ord(char) for char in marker) % 500
    body = "".join(chr(0x4E00 + (index + offset) % 500) for index in range(hanzi))
    return f"{marker}。{body}。"


def _segment_scripts() -> list[str]:
    return [_paragraph(f"第{index}段标记", 900) for index in range(1, _SCRIPTED_SEGMENTS + 1)]


def _task_with_started_fill(
    client: TestClient, scripted: ScriptedModelClient, *, length: int = 8000
) -> int:
    scripted.set_sequence(
        _frontier_json(("目标读者", "写给谁？", "新员工")),
        json.dumps({"frontier": []}, ensure_ascii=False),
        _plan_md(length),
    )
    task_id = client.post("/api/grilling/tasks", json={"idea": IDEA}).json()["task"]["id"]
    client.post(
        f"/api/grilling/tasks/{task_id}/answers", json={"round_no": 1, "answers": ["新员工"]}
    )
    assert client.post(f"/api/grilling/tasks/{task_id}/advance").status_code == 200
    assert client.post(f"/api/grilling/tasks/{task_id}/plan/confirm").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/fill", json={}).status_code == 200
    return task_id


def _section_content(db_path: Path, task_id: int) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT content_md FROM plan_sections WHERE task_id = ? AND seq = 1", (task_id,)
        ).fetchone()
    return str(row["content_md"])


def test_long_section_is_split_into_several_calls(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """8000 字量级的单章不是一次调用写完：分段多次调用，且模型返回的每段都进了正文。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=8000)
    scripts = _segment_scripts()
    scripted_model_client.set_sequence(*scripts)
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")

    assert response.status_code == 200
    writing_calls = len(scripted_model_client.calls) - calls_before
    # 一次写完 8000 汉字在 8192 token 上限下不可靠，必须分段。
    assert writing_calls >= 2, f"8000 字只调了 {writing_calls} 次，没有分段"

    content = _section_content(db_path, task_id)
    # 不丢失：模型实际返回的每一段都在正文里。
    for used in scripts[:writing_calls]:
        marker = used.split("。")[0]
        assert marker in content, f"{marker} 没有进正文（分段内容被丢了）"
    # 不重复：每段标记只出现一次。
    for used in scripts[:writing_calls]:
        marker = used.split("。")[0]
        assert content.count(marker) == 1, f"{marker} 在正文里出现了多次"
    # 累计字数达到目标量级（不是半篇）。
    assert _hanzi(content) >= 6000


def test_long_section_output_is_a_readable_docx(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """分段拼出来的正文仍然是一份能被 Word 打开、结构完整的成品。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=8000)
    scripted_model_client.set_sequence(*_segment_scripts())

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")
    assert response.status_code == 200

    artifact = response.json()["deliverable"]["file_path"]
    document = Document(artifact)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    # 章标题由系统给——这条既有纪律在分段后仍然成立。
    assert "第 1 章" in text
    assert "第1段标记" in text


def test_segment_hitting_length_cap_is_a_hard_error(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """任一分段命中长度上限 → 硬错误（502），**不静默截断成半篇**。

    模型客户端把「被截断」表达为 `ModelCallError`（见 `openai_client`：
    `finish_reason == "length"` 直接抛错）。分段路径必须原样上抛，不得吞掉后
    把已有的半篇当成品写库。
    """
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=8000)
    scripted_model_client.set_sequence(*_segment_scripts())
    # 第一次写作调用成功，之后固定抛错——这正是真实客户端遇到截断时的行为。
    scripted_model_client.fail_after(
        1,
        httpx.HTTPStatusError(
            "length", request=httpx.Request("POST", "http://x"), response=httpx.Response(200)
        ),
    )

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")

    assert response.status_code == 502
    # 硬错误：不留下半篇正文。
    assert _section_content(db_path, task_id) == ""
    with connect(db_path) as connection:
        generations = connection.execute(
            "SELECT * FROM generations WHERE task_id = ?", (task_id,)
        ).fetchall()
    assert generations == []


def test_short_section_still_uses_a_single_call(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """短章节维持单次调用：分段只在写不下时才发生，不为分段而分段。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=400)
    scripted_model_client.set_sequence(_paragraph("唯一段标记", 300))
    calls_before = len(scripted_model_client.calls)

    response = grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill")

    assert response.status_code == 200
    # 只多了一次调用（写作那一次），没有分段。
    assert len(scripted_model_client.calls) - calls_before == 1
    assert "唯一段标记" in _section_content(db_path, task_id)


def test_segments_join_at_paragraph_boundaries(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient, db_path: Path
) -> None:
    """拼接发生在段落边界：不把两段的句子粘成一句，也不删掉段间空行。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=8000)
    scripted_model_client.set_sequence(*_segment_scripts())

    assert grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill").status_code == 200
    content = _section_content(db_path, task_id)

    # 每段自成段落：段标记各只出现在一行里，且段与段之间有空行。
    for index in range(1, _SCRIPTED_SEGMENTS + 1):
        marker = f"第{index}段标记"
        lines = [line for line in content.splitlines() if marker in line]
        assert len(lines) <= 1, f"{marker} 出现在了多行里（段落边界被破坏）"
    assert "\n\n" in content


def test_remaining_length_is_passed_to_each_segment(
    grilling_client: TestClient, scripted_model_client: ScriptedModelClient
) -> None:
    """每次分段都带上「还剩多少字」——否则后续分段会一路超出去。"""
    task_id = _task_with_started_fill(grilling_client, scripted_model_client, length=8000)
    scripted_model_client.set_sequence(*_segment_scripts())
    calls_before = len(scripted_model_client.calls)

    assert grilling_client.post(f"/api/tasks/{task_id}/sections/1/fill").status_code == 200

    writing_calls = scripted_model_client.calls[calls_before:]
    assert len(writing_calls) >= 2, "应当发生至少两次写作调用"
    # 第二次及之后的分段，提示词里必须出现具体的剩余字数（不再是「暂无」）。
    for call in writing_calls[1:]:
        text = "\n".join(str(message.get("content", "")) for message in call["messages"])
        assert "剩余字数" in text
        assert "本次不按剩余字数收敛" not in text
