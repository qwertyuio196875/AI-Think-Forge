"""单文件 HTML 演示成品的渲染与完整性检查（规格 US 18 / 21 / 22）。

产物是一份**自包含** `.html`：样式 / 翻页脚本 / 西文字体（latin 子集 base64 woff2）
全部内联，中文走系统字体回退，双击经 `file://` 直开，不需要服务器、Node 或外网。

两条硬纪律：

1. **无外部网络引用**：渲染完成后扫描产物文本（`http(s)://`、指向网络的 `src=`/`href=`、
   `<link>`、CDN、非 `data:` 的 `url()`），命中即视为不是单文件 → 检查不通过；
2. **先确认产物合格，再落库**（US 22）：检查未通过就丢弃产物、不写生成记录，绝不交付。

渲染是**确定性**的：把已确认的结构化方案（`plans.content_md`）解析为块序列再排成幻灯片，
不调用模型（与 Word 一轨同理：未经确认的推测绝不变成成品）。

来源署名：版式骨架与翻页运行时改编自 OpenDesign 的 MIT 主题（见 `themes.py` 与
`assets/THIRD-PARTY-LICENSES.md`）；调色板、CSS 与页内演讲者模式为本项目本地原创。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from app.generation.plan_document import Block, parse_plan_blocks
from app.generation.themes import DeckTheme
from app.generation.word import DeliverableIntegrityError

# 布局标识：标题页 / 列表页 / 引文页 / 表格页 / 结束页。
LAYOUT_TITLE = "title"
LAYOUT_LIST = "list"
LAYOUT_QUOTE = "quote"
LAYOUT_TABLE = "table"
LAYOUT_END = "end"

# 结束页文案（原型演示态的收尾口径）。
END_TITLE = "谢谢"
END_SUBTITLE = "提问环节"

# 网络引用的形态：命中任一即视为「不是单文件」（工单硬要求，扫描断言 0 条）。
_EXTERNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"<link\b", re.IGNORECASE),
    re.compile(r"<script[^>]+\bsrc\s*=", re.IGNORECASE),
    re.compile(r"""\b(?:src|href|poster|data-src)\s*=\s*["']?\s*(?:https?:)?//""", re.IGNORECASE),
    re.compile(r"""url\(\s*["']?\s*(?!data:)[^)"']*\)""", re.IGNORECASE),
    re.compile(r"@import", re.IGNORECASE),
)

# 键盘翻页按键：`e.key === 'X'` 与辅助函数里的 `key === 'X'` 都算（同一份事实）。
_KEYDOWN_KEY = re.compile(r"(?:\w+\.)?key\s*===\s*'([^']*)'")


@dataclass(frozen=True)
class DeckPiece:
    """幻灯片里的一块内容（按顺序渲染，保序即不丢内容）。"""

    kind: str  # sub | text | items | table
    text: str = ""
    items: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class DeckSlide:
    """一张幻灯片：布局 + 标题 + 内容块 + 讲者备注（演讲者模式用）。"""

    layout: str
    title: str
    subtitle: str = ""
    pieces: tuple[DeckPiece, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class DeckBuild:
    """一次单文件 HTML 写入的结果与完整性检查所需的期望结构。"""

    path: Path
    theme: DeckTheme
    task_title: str
    plan_title: str
    slides: tuple[DeckSlide, ...]
    external_resources: tuple[str, ...]
    provenance: tuple[str, ...]

    @property
    def inlined_fonts(self) -> tuple[str, ...]:
        """内联的西文字体清单。"""
        return self.theme.inlined_fonts

    @property
    def slide_count(self) -> int:
        """幻灯片页数。"""
        return len(self.slides)


def slides_from_plan(plan_md: str, task_title: str) -> tuple[DeckSlide, ...]:
    """把结构化方案正文排成幻灯片：标题页 → 各章节页 → 结束页。

    结构随任务类型裁剪，故映射必须容错：识别不了的整行按正文段落处理，绝不丢内容
    （与 Word 一轨共用 `parse_plan_blocks`，两份成品的章节解析口径一致）。
    """
    blocks = parse_plan_blocks(plan_md)
    headings = [block for block in blocks if block.kind == "heading"]
    plan_title = headings[0].text if headings else task_title

    subtitle = ""
    section_blocks: list[Block] = []
    seen_first_heading = False
    for block in blocks:
        if block.kind == "heading" and not seen_first_heading:
            seen_first_heading = True
            continue
        # 标题页副标题：方案标题之后的**第一段正文**（进入章节前），不额外编造内容。
        if not subtitle and not section_blocks and block.kind == "paragraph":
            subtitle = block.text
            continue
        section_blocks.append(block)

    slides: list[DeckSlide] = [
        DeckSlide(
            layout=LAYOUT_TITLE,
            title=plan_title,
            subtitle=subtitle,
            notes=f"{plan_title}｜{subtitle}" if subtitle else plan_title,
        )
    ]

    body_slides = _section_slides(section_blocks, fallback_title=plan_title)
    slides.extend(body_slides)

    slides.append(
        DeckSlide(
            layout=LAYOUT_END,
            title=END_TITLE,
            subtitle=END_SUBTITLE,
            notes="结束页：谢谢 / 提问环节",
        )
    )
    return tuple(slides)


def _section_slides(blocks: list[Block], *, fallback_title: str) -> list[DeckSlide]:
    """章节块 → 幻灯片：`H1/H2` 开新页，`H3` 作页内小标题，其余按顺序落在当前页。"""
    slides: list[DeckSlide] = []
    title: str | None = None
    pieces: list[DeckPiece] = []

    def flush() -> None:
        if title is None:
            return
        slides.append(
            DeckSlide(
                layout=_layout_of(pieces),
                title=title,
                pieces=tuple(pieces),
                notes=_notes_of(title, pieces),
            )
        )

    for block in blocks:
        if block.kind == "heading" and block.level <= 2:
            flush()
            title = block.text
            pieces = []
            continue
        if title is None:
            # 方案没有二级结构：整篇归入一张以方案标题命名的页面，内容不丢。
            title = fallback_title
        if block.kind in ("bullet", "numbered") and pieces and pieces[-1].kind == "items":
            # 连续的列表项归入同一个列表（不拆成一堆单元素列表）。
            previous = pieces[-1]
            pieces[-1] = DeckPiece(kind="items", items=(*previous.items, block.text))
            continue
        pieces.append(_piece_of(block))

    flush()
    return slides


def _piece_of(block: Block) -> DeckPiece:
    """方案块 → 幻灯片内容块（标题块已在章节切分里消费）。"""
    if block.kind in ("bullet", "numbered"):
        return DeckPiece(kind="items", items=(block.text,))
    if block.kind == "table":
        return DeckPiece(kind="table", rows=block.rows)
    if block.kind == "heading":  # H3 及更深的标题 → 页内小标题
        return DeckPiece(kind="sub", text=block.text)
    return DeckPiece(kind="text", text=block.text)


def _layout_of(pieces: list[DeckPiece]) -> str:
    """按内容形态选布局：有列表项 / 表格 / 单段引文各有对应版式。"""
    if any(piece.kind == "items" for piece in pieces):
        return LAYOUT_LIST
    if any(piece.kind == "table" for piece in pieces):
        return LAYOUT_TABLE
    return LAYOUT_QUOTE


def _notes_of(title: str, pieces: list[DeckPiece]) -> str:
    """讲者备注：本页的标题与全部正文（演讲者模式显示，不额外生成内容）。"""
    parts = [title]
    for piece in pieces:
        if piece.kind == "table":
            parts.extend(" | ".join(row) for row in piece.rows)
        elif piece.kind == "items":
            parts.extend(piece.items)
        elif piece.text:
            parts.append(piece.text)
    return " ｜ ".join(parts)


def build_html_deck(
    *,
    plan_md: str,
    task_title: str,
    theme: DeckTheme,
    output_path: str | Path,
) -> DeckBuild:
    """把已确认的方案渲染成单文件 `.html`（原子落盘；检查由 `verify_html_deliverable` 做）。

    页数由 `slides_from_plan` 按 H1/H2 自动切页（**兜底路径**）。当有页面规划时应改用
    `build_html_deck_from_slides`（工单 27 / ADR-0004 主体路径），本函数保留给规划缺失时。
    """
    slides = slides_from_plan(plan_md, task_title)
    return build_html_deck_from_slides(
        slides=slides,
        task_title=task_title,
        plan_md=plan_md,
        theme=theme,
        output_path=output_path,
    )


def build_html_deck_from_slides(
    *,
    slides: tuple[DeckSlide, ...],
    task_title: str,
    plan_md: str,
    theme: DeckTheme,
    output_path: str | Path,
) -> DeckBuild:
    """把**已排好的幻灯片**渲染成单文件 `.html`（原子落盘）。

    这是工单 27 / ADR-0004 的主体路径：页数与版式由页面规划决定（`slides_for_page_plan`），
    而不是按 H1/H2 自动切页。其余纪律与 `build_html_deck` 相同——确定性渲染、自包含、
    外部引用由 `verify_html_deliverable` 单独检查。
    """
    provenance = _provenance(task_title, plan_md, theme)
    html = _render(slides, theme, provenance)

    references = tuple(find_external_references(html))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再原子替换：中途失败不会留下半成品被当成成品文件。
    temp_path = output.with_name(output.name + ".part")
    temp_path.write_text(html, encoding="utf-8")
    temp_path.replace(output)

    return DeckBuild(
        path=output,
        theme=theme,
        task_title=task_title,
        # 统一以幻灯片首张标题作为计划标题（无论是否来自规划）。
        plan_title=slides[0].title if slides else task_title,
        slides=slides,
        external_resources=references,
        provenance=provenance,
    )


def find_external_references(text: str) -> list[str]:
    """扫描产物文本里的外部网络引用；返回命中片段（空列表 = 完全自包含）。"""
    found: list[str] = []
    for pattern in _EXTERNAL_PATTERNS:
        found.extend(match.group(0) for match in pattern.finditer(text))
    return found


def verify_html_deliverable(build: DeckBuild) -> None:
    """**回读产物**做完整性检查：单文件、无外链、结构可解析、翻页能力齐备。

    任一条不通过都抛 `DeliverableIntegrityError`（服务层据此丢弃产物、不落库、不交付）。
    """
    try:
        text = build.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DeliverableIntegrityError(f"产物无法作为 UTF-8 单文件读取：{exc}") from exc

    references = find_external_references(text)
    if references:
        raise DeliverableIntegrityError(
            f"产物含外部网络引用（要求 0 条，规格 US 21）：{sorted(set(references))[:5]}"
        )
    if build.external_resources:
        raise DeliverableIntegrityError(
            f"产物声明了网络资源却未在记录中声明：{list(build.external_resources)}"
        )

    document = split_deck_document(text)
    if document["slide_count"] != build.slide_count:
        raise DeliverableIntegrityError(
            f"幻灯片页数不符：期望 {build.slide_count}，实际 {document['slide_count']}"
        )
    if document["slide_count"] < 2:
        raise DeliverableIntegrityError("产物缺少幻灯片容器（结构损坏）")
    if document["layouts"][0] != LAYOUT_TITLE or document["layouts"][-1] != LAYOUT_END:
        raise DeliverableIntegrityError(
            f"幻灯片首尾结构不符：实际 {document['layouts'][:1]} … {document['layouts'][-1:]}"
        )
    if not document["has_keydown_listener"] or not document["handles_space"]:
        raise DeliverableIntegrityError("产物缺少键盘翻页脚本（演示能力不可用）")
    if not {"ArrowLeft", "ArrowRight", "PageUp", "PageDown"} <= document["keys"]:
        raise DeliverableIntegrityError(f"键盘翻页按键不全：实际 {sorted(document['keys'])}")
    if not document["has_page_counter"]:
        raise DeliverableIntegrityError("产物缺少页码显示（演示能力不可用）")
    if not document["inline_font_faces"]:
        raise DeliverableIntegrityError("产物未内联西文字体（离线会掉字形）")


def _provenance(task_title: str, plan_md: str, theme: DeckTheme) -> tuple[str, ...]:
    """产物署名的来源清单（如实区分 OpenDesign 派生与本地原创）。"""
    lines = [
        f"主题：{theme.name}（id={theme.id}）",
        f"来源：{theme.derived_from}",
        "本地原创部分：调色板、字体栈、CSS 与页内演讲者模式（不做像素级复刻）",
        f"内联西文字体：{'、'.join(theme.inlined_fonts)}（OFL-1.1）",
        *[f"字体署名：{line}" for line in theme.font_attribution],
        "中文：系统字体回退（未内联 CJK 字体，见 assets/THIRD-PARTY-LICENSES.md）",
        "网络资源：无（单文件，file:// 直开；样式 / 脚本 / 西文字体均内联）",
        "许可全文：本应用 backend/app/generation/assets/THIRD-PARTY-LICENSES.md",
    ]
    return tuple(lines)


def _render(
    slides: tuple[DeckSlide, ...], theme: DeckTheme, provenance: tuple[str, ...]
) -> str:
    """渲染单文件 HTML（样式 / 脚本 / 字体内联；不引用任何外部资源）。"""
    metadata = {
        "theme": theme.id,
        "theme_name": theme.name,
        "inlined_fonts": list(theme.inlined_fonts),
        "cjk_fallback": True,
        "network_resources": list(theme.network_resources),
        "slides": len(slides),
        "presenter_mode": "in-page-overlay",
    }
    # 元数据写在单引号属性里：JSON 用双引号，转义掉单引号即可安全内联。
    encoded = json.dumps(metadata, ensure_ascii=False).replace("'", "&#39;")
    sections = "\n".join(_render_slide(index, slide) for index, slide in enumerate(slides))
    # `<` 转义成 `\u003c`：方案正文可能含 `</script>`，不能让它截断内联脚本。
    notes_json = json.dumps([slide.notes for slide in slides], ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    slide_total = len(slides)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(slides[0].title)} · 演示</title>
<meta name="thinkforge:deck" content='{encoded}'>
<!--
  单文件 HTML 演示 · 由已确认的结构化方案确定性生成
{_comment_block(provenance)}
-->
<style>
{theme.font_face_css()}
{theme.token_css()}
{_BASE_CSS}
</style>
</head>
<body>
<div class="deck" data-theme="{theme.id}" data-network-resources="none" role="presentation">
{sections}
</div>
<div class="slide-counter" aria-hidden="true"><span id="current">1</span> / <span id="total">{slide_total}</span></div>
<div class="progress-bar" id="progress"></div>
<div class="nav-controls">
<button class="nav-btn" id="prevBtn" type="button" aria-label="上一页">&#8249;</button>
<button class="nav-btn" id="presenterBtn" type="button" aria-label="演讲者模式">S</button>
<button class="nav-btn" id="nextBtn" type="button" aria-label="下一页">&#8250;</button>
</div>
<div class="keyboard-hint">← → / PageUp PageDown / 空格 翻页 · S 演讲者模式</div>
<aside class="presenter" id="presenter" hidden="hidden" aria-label="演讲者模式">
<div class="presenter-head"><span>演讲者模式 · 页内</span><span id="presenterTimer">00:00</span></div>
<p class="presenter-next">下一页：<span id="presenterNext"></span></p>
<p class="presenter-title" id="presenterTitle"></p>
<pre class="presenter-notes" id="presenterNotes"></pre>
</aside>
<script>
(function () {{
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var notes = {notes_json};
  var current = 0;
  var total = slides.length;
  var currentEl = document.getElementById('current');
  var progressEl = document.getElementById('progress');
  var prevBtn = document.getElementById('prevBtn');
  var nextBtn = document.getElementById('nextBtn');
  var presenter = document.getElementById('presenter');
  var presenterBtn = document.getElementById('presenterBtn');
  var presenterTimer = document.getElementById('presenterTimer');
  var presenterTitle = document.getElementById('presenterTitle');
  var presenterNext = document.getElementById('presenterNext');
  var presenterNotes = document.getElementById('presenterNotes');
  var timerId = null;
  var startedAt = 0;

  function updateSlide() {{
    slides.forEach(function (slide, index) {{
      slide.classList.remove('active', 'prev');
      if (index === current) {{
        slide.classList.add('active');
      }} else if (index < current) {{
        slide.classList.add('prev');
      }}
    }});
    currentEl.textContent = String(current + 1);
    progressEl.style.width = ((current + 1) / total * 100) + '%';
    prevBtn.disabled = current === 0;
    nextBtn.disabled = current === total - 1;
    presenterTitle.textContent = (current + 1) + ' / ' + total + ' · ' +
      slides[current].querySelector('h1, h2').textContent;
    presenterNext.textContent = current + 1 < total
      ? slides[current + 1].querySelector('h1, h2').textContent
      : '（已是最后一页）';
    presenterNotes.textContent = notes[current];
  }}

  function changeSlide(delta) {{
    var next = current + delta;
    if (next >= 0 && next < total) {{
      current = next;
      updateSlide();
    }}
  }}

  function resetTimer() {{
    startedAt = Date.now();
  }}

  function tick() {{
    var elapsed = Math.floor((Date.now() - startedAt) / 1000);
    var minutes = String(Math.floor(elapsed / 60)).padStart(2, '0');
    var seconds = String(elapsed % 60).padStart(2, '0');
    presenterTimer.textContent = minutes + ':' + seconds;
  }}

  function togglePresenter(force) {{
    var show = force === undefined ? presenter.hidden : force;
    presenter.hidden = !show;
    if (show) {{
      resetTimer();
      tick();
      timerId = setInterval(tick, 1000);
    }} else if (timerId) {{
      clearInterval(timerId);
      timerId = null;
    }}
  }}

  function isNextKey(key) {{
    return key === 'ArrowRight' || key === 'PageDown' || key === ' ' || key === 'Spacebar';
  }}

  function isPrevKey(key) {{
    return key === 'ArrowLeft' || key === 'PageUp';
  }}

  document.addEventListener('keydown', function (e) {{
    var key = e.key;
    if (e.key === 's' || e.key === 'S') {{
      e.preventDefault();
      togglePresenter();
    }} else if (e.key === 'Escape') {{
      togglePresenter(false);
    }} else if (isNextKey(key)) {{
      e.preventDefault();
      changeSlide(1);
    }} else if (isPrevKey(key)) {{
      e.preventDefault();
      changeSlide(-1);
    }} else if (e.key === 'Home') {{
      e.preventDefault();
      current = 0;
      updateSlide();
    }} else if (e.key === 'End') {{
      e.preventDefault();
      current = total - 1;
      updateSlide();
    }}
  }});

  prevBtn.addEventListener('click', function () {{ changeSlide(-1); }});
  nextBtn.addEventListener('click', function () {{ changeSlide(1); }});
  presenterBtn.addEventListener('click', function () {{ togglePresenter(); }});

  var touchStartX = 0;
  document.addEventListener('touchstart', function (e) {{
    touchStartX = e.changedTouches[0].screenX;
  }}, {{ passive: true }});
  document.addEventListener('touchend', function (e) {{
    var delta = touchStartX - e.changedTouches[0].screenX;
    if (Math.abs(delta) > 50) {{
      changeSlide(delta > 0 ? 1 : -1);
    }}
  }}, {{ passive: true }});

  updateSlide();
  togglePresenter(false);
}})();
</script>
</body>
</html>
"""


def _render_slide(index: int, slide: DeckSlide) -> str:
    """渲染一张幻灯片（含讲者备注；备注平时隐藏，演讲者模式读取）。"""
    body = [_render_piece(piece) for piece in slide.pieces]
    return (
        f'<section class="slide" id="slide-{index + 1}" data-layout="{slide.layout}">'
        f"{_render_slide_heading(slide)}"
        f"{''.join(body)}"
        f'<p class="speaker-notes" hidden="hidden">{_escape(_slide_notes(slide))}</p>'
        "</section>"
    )


def _render_slide_heading(slide: DeckSlide) -> str:
    """标题：标题页用 `h1`，结束页用 `h2.deck-end`，其余章节页统一 `h2.slide-title`。"""
    title = _escape(slide.title)
    subtitle = (
        f'<p class="deck-sub">{_escape(slide.subtitle)}</p>' if slide.subtitle else ""
    )
    if slide.layout == LAYOUT_TITLE:
        return f'<h1 class="deck-title">{title}</h1>{subtitle}<p class="deck-meta"> 由确认后的结构化方案确定性生成 · 单文件 HTML · 无外部依赖</p>'
    if slide.layout == LAYOUT_END:
        return f'<h2 class="deck-end">{title}</h2>{subtitle}'
    return f'<h2 class="slide-title">{title}</h2>'


def _render_piece(piece: DeckPiece) -> str:
    """渲染一块内容：小标题 / 正文 / 列表 / 表格。"""
    if piece.kind == "sub":
        return f'<h3 class="slide-sub">{_escape(piece.text)}</h3>'
    if piece.kind == "items":
        items = "".join(f"<li>{_escape(item)}</li>" for item in piece.items)
        return f'<ul class="slide-list">{items}</ul>'
    if piece.kind == "table":
        return _render_table(piece.rows)
    return f'<p class="slide-text">{_escape(piece.text)}</p>'


def _render_table(rows: tuple[tuple[str, ...], ...]) -> str:
    """表格：首行作表头（Markdown 表格语义），其余为数据行。"""
    if not rows:
        return ""
    head, *body = rows
    head_html = "".join(f"<th>{_escape(cell)}</th>" for cell in head)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in body
    )
    return (
        f'<table class="slide-table"><thead><tr>{head_html}</tr></thead>'
        f"<tbody>{body_html}</tbody></table>"
    )


def _slide_notes(slide: DeckSlide) -> str:
    """讲者备注文本（与产物里 `speaker-notes` 的取值同源）。"""
    return slide.notes


def _escape(text: str) -> str:
    """HTML 文本转义（方案正文可能含 `<` / `&` 等字符）。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _comment_block(lines: tuple[str, ...]) -> str:
    """署名注释块：转义掉 `--` 以免破坏 HTML 注释。"""
    return "\n".join(f"  · {line.replace('--', '- -')}" for line in lines)


class _DeckParser(HTMLParser):
    """产物结构解析：数幻灯片、认布局、收集内联 `@font-face`。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.slides: list[str] = []
        self.has_style = False
        self.inline_font_faces: list[str] = []
        self.has_page_counter = False
        self.has_presenter_overlay = False
        self.script_chunks: list[str] = []
        self._in_script = False
        self._in_style = False
        self._class_stack: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: (value or "") for name, value in attrs}
        classes = attributes.get("class", "").split()
        if tag == "section" and "slide" in classes:
            self.slides.append(attributes.get("data-layout", ""))
        if tag == "style":
            self.has_style = True
            self._in_style = True
        if tag == "script":
            self._in_script = True
        if tag == "aside" and "presenter" in classes:
            self.has_presenter_overlay = True
        if attributes.get("id") == "current":
            self.has_page_counter = True
        if tag == "div":
            self._class_stack.append(classes)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "style":
            self._in_style = False
        if tag == "script":
            self._in_script = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        if tag == "script":
            self._in_script = False
        if tag == "div" and self._class_stack:
            self._class_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_style and "@font-face" in data:
            self.inline_font_faces.append("font-face")
        if self._in_script:
            self.script_chunks.append(data)


def split_deck_document(text: str) -> dict:
    """解析产物结构：页数 / 布局序列 / 键盘翻页按键 / 页码 / 演讲者模式。

    只读产物文本（与 `verify_html_deliverable` 同一份事实），供完整性检查与测试断言。
    """
    parser = _DeckParser()
    parser.feed(text)
    parser.close()

    script = "\n".join(parser.script_chunks)
    keys = set(_KEYDOWN_KEY.findall(script))
    return {
        "slide_count": len(parser.slides),
        "layouts": parser.slides,
        "keys": keys,
        # 空格翻页：`' '` 与旧浏览器的 `'Spacebar'` 都算（同一份事实）。
        "handles_space": bool(keys & {" ", "Spacebar"}),
        "has_keydown_listener": "addEventListener('keydown'" in script,
        "has_page_counter": parser.has_page_counter,
        "has_presenter_overlay": parser.has_presenter_overlay,
        "inline_font_faces": parser.inline_font_faces,
        "has_style": parser.has_style,
    }


# 版式 CSS：结构（绝对定位幻灯片 + 状态类 + 页码 / 进度 / 导航 + 演讲者覆盖层）
# 为本项目本地原创；颜色与字体一律走主题令牌，不写死具体值。
_BASE_CSS = """*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:var(--dkt-bg);color:var(--dkt-fg);
font-family:var(--dkt-font)}
.deck{position:fixed;inset:0}
.slide{position:absolute;inset:0;height:100%;display:flex;flex-direction:column;
justify-content:center;padding:6vh 7vw 11vh;opacity:0;pointer-events:none;
transform:translateX(40px);transition:opacity .35s ease,transform .35s ease}
.slide.active{opacity:1;pointer-events:auto;transform:none}
.slide.prev{transform:translateX(-40px)}
.deck-title{font-family:var(--dkt-head);font-size:clamp(28px,4.6vw,60px);line-height:1.16;
margin:0 0 2vh;letter-spacing:-.01em}
.deck-sub{color:var(--dkt-muted);font-size:clamp(14px,1.5vw,20px);line-height:1.6;margin:0}
.deck-meta{color:var(--dkt-muted);font-size:12px;letter-spacing:.06em;margin:3vh 0 0}
.slide-title{font-family:var(--dkt-head);font-size:clamp(22px,3vw,40px);line-height:1.2;
margin:0 0 2.4vh;padding-left:14px;border-left:4px solid var(--dkt-acc)}
.slide-sub{color:var(--dkt-acc);font-family:var(--dkt-head);font-size:clamp(15px,1.6vw,22px);
margin:1.4vh 0 .6vh}
.slide-text{font-size:clamp(14px,1.5vw,20px);line-height:1.8;margin:.7vh 0;color:var(--dkt-fg)}
.slide-list{margin:.4vh 0 0;padding-left:22px;font-size:clamp(14px,1.5vw,20px);line-height:1.75}
.slide-list li{margin:.7vh 0}
.slide-list li::marker{color:var(--dkt-acc)}
.slide-table{border-collapse:collapse;margin-top:1.2vh;font-size:clamp(12px,1.3vw,17px)}
.slide-table th,.slide-table td{border:1px solid var(--dkt-line);padding:7px 13px;text-align:left}
.slide-table th{border-bottom:2px solid var(--dkt-acc);font-family:var(--dkt-head)}
.deck-end{font-family:var(--dkt-head);font-size:clamp(30px,4.4vw,54px);margin:0 0 1.4vh}
.slide-counter{position:fixed;left:4vw;bottom:3.4vh;font-size:13px;color:var(--dkt-muted);
font-variant-numeric:tabular-nums}
.progress-bar{position:fixed;left:0;bottom:0;height:3px;width:0;background:var(--dkt-acc)}
.nav-controls{position:fixed;right:4vw;bottom:3vh;display:flex;gap:8px}
.nav-btn{width:34px;height:34px;border:1px solid var(--dkt-line);border-radius:8px;
background:transparent;color:var(--dkt-fg);font-size:16px;line-height:1;cursor:pointer}
.nav-btn:hover{border-color:var(--dkt-acc);color:var(--dkt-acc)}
.nav-btn[disabled]{opacity:.35;cursor:default}
.keyboard-hint{position:fixed;left:50%;bottom:3.6vh;transform:translateX(-50%);font-size:11px;
color:var(--dkt-muted)}
.speaker-notes{display:none}
.presenter{position:fixed;inset:0;z-index:50;display:flex;flex-direction:column;gap:12px;
padding:5vh 6vw;background:var(--dkt-bg);color:var(--dkt-fg)}
.presenter[hidden]{display:none}
.presenter-head{display:flex;justify-content:space-between;font-family:var(--dkt-head);
font-size:14px;color:var(--dkt-muted)}
.presenter-title{font-family:var(--dkt-head);font-size:clamp(20px,2.4vw,30px);margin:0}
.presenter-next{color:var(--dkt-acc);font-size:13px;margin:0}
.presenter-notes{white-space:pre-wrap;font-size:14px;line-height:1.8;margin:0;
overflow:auto;font-family:var(--dkt-font)}
:focus-visible{outline:2px solid var(--dkt-acc);outline-offset:2px}
@media (max-width:560px){.slide{padding:6vh 6vw 13vh}.keyboard-hint{display:none}}
"""