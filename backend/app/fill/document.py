"""正文成品的 Markdown 组装：把已写好的章节正文拼成一份可渲染的 Markdown（工单 10）。

为什么单独一个模块：填充写出来的正文是**章节片段**，而 Word 成品需要一份完整的
Markdown。这里只做「拼装」这一件确定性的事，不调模型、不碰数据库。

两条纪律：
- **章标题由系统给**：成品目录的一级标题就是章标题（`# 第 N 章 · 标题`），
  模型的输出只贡献章内的小节。模型偶尔会自己写一级标题，这里把它降一级，
  免得成品里出现两个平级的「章」（「第三章写进第四章」的视觉版本）。
- **只拼已写正文**：没写的章不进成品——成品里出现空章节比缺一章更糟。

标题级别的对应关系（`app.generation.plan_document` 把 `#`~`###` 映射到 Heading 1~3）：
成品里 `# 第 N 章 · 标题` → Heading 1；模型的 `##` 小节 → Heading 2；模型的 `###`
→ Heading 3。模型的一级标题先被降成 `##`，因此不会跟章标题平级。
"""

from __future__ import annotations

import json
import re

from app.fill.citations import render_references_section

# 一级标题（行首一个 `#`）。只匹配整行标题行，不动正文里的 `#`（例如 C# 的写法）。
_TOP_LEVEL_HEADING = re.compile(r"^#\s+(.*)$")

# 章标题模板：章序号 + 标题。序号来自成品目录（`plan_sections.seq`），
# 与 `plan_sections` 的序号一致，绝不另起一套编号。
CHAPTER_TITLE_TEMPLATE = "第 {seq} 章 · {title}"


def demote_top_level_headings(body_md: str) -> str:
    """把模型输出里的一级标题降成二级标题。

    章标题由系统统一添加（见 `compose_body_markdown`）；模型若再写一级标题，
    降一级后它就是章内的小节，不会跟章标题平级。
    """
    lines = []
    for line in body_md.splitlines():
        match = _TOP_LEVEL_HEADING.match(line)
        if match is not None:
            lines.append(f"## {match.group(1).strip()}")
            continue
        lines.append(line)
    return "\n".join(lines)


def compose_body_markdown(sections: list[dict]) -> str:
    """按章节顺序把已写正文拼成成品 Markdown。

    `sections` 是 `plan_sections` 的行（需含 `seq` / `title` / `content_md` /
    `references_json`），按序号升序传入。**没有正文的章不进成品**。

    成品末尾附一份「参考资料」（工单 24）：只列**实际采用**的引用片段（正文写成功
    才落进 `references_json`），跨章去重、按首次出现排序。参考资料是正文写完后的
    附注，正文拼装不受它解析成败影响。
    """
    parts: list[str] = []
    reference_groups: list[list[dict]] = []
    for section in sections:
        body = (section.get("content_md") or "").strip()
        if not body:
            continue
        title = CHAPTER_TITLE_TEMPLATE.format(seq=section["seq"], title=section["title"])
        parts.append(f"# {title}\n\n{demote_top_level_headings(body)}")
        reference_groups.append(_decode_references(section))

    references = render_references_section(reference_groups)
    if references:
        parts.append(references)
    return "\n\n".join(parts) + ("\n" if parts else "")


def _decode_references(section: dict) -> list[dict]:
    """把一章的 `references_json` 解码为引用卡片清单；损坏按空清单处理。"""
    raw = section.get("references_json") or ""
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
