"""模板机制：内置最小默认模板、登记校验、解析（全局默认 / 任务级临时覆盖）。

术语（GLOSSARY）**模板**：样式文件，Word 模板由用户提供；系统只管理与应用，从不联网
搜模板。术语「默认模板 / 临时覆盖」：全局默认模板 + 任务级临时选用；**临时选择不改变
全局默认**——解析结果只决定本次 `generations.template_used`，不写回全局。

两个调研已核实的硬陷阱（A2，有源码级证据）都在这里兜住：

1. **`.dotx` / `.dotm` / `.docm` 打不开**：python-docx 的 `Document()` 校验主部件内容类型
   必须等于 `WML_DOCUMENT_MAIN`（`docx/api.py:28`），模板类型不符直接抛 `ValueError`。
   → 登记 / 临时覆盖只接受 `.docx`；其它后缀与「改名为 .docx 的 .dotx」都给出
   「请另存为 .docx」的友好错误。
2. **模板样式未定义会 `KeyError`**（`docx/styles/style.py` 的 `no style with name`）：
   只在 `w:lsdException`（潜在样式）里出现、PKG 里无实体定义的标题样式取不到。
   → 写前用 `'Heading 1' in document.styles` 探测（见 `word.py`），失败走两段式回退。

**模板缺失 / 损坏时明确报错，绝不静默退回空白生成**（工单硬要求 + 规格 US 19）：
本模块只抛 `TemplateError`，由路由翻成可读的 4xx；调用方不得吞掉它改用内置模板。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.shared import Pt

# 内置最小默认模板：保证开箱可用。落在 `templates/_builtin/` 下，首次运行时按需生成。
BUILTIN_DIR_NAME = "_builtin"
BUILTIN_TEMPLATE_NAME = "minimal-default.docx"
BUILTIN_TEMPLATE_REL = f"{BUILTIN_DIR_NAME}/{BUILTIN_TEMPLATE_NAME}"

# 唯一接受的模板后缀：`.dotx/.dotm/.docm` 与 Word 的模板主部件内容类型打不开（陷阱 1）。
ALLOWED_TEMPLATE_SUFFIXES = (".docx",)

# 内置模板至少定义的六类样式：Heading 1~3 / 正文 / 列表 / 表格。
REQUIRED_STYLES = ("Heading 1", "Heading 2", "Heading 3", "Normal", "List Bullet", "Table Grid")

# 内置模板里显式给出的格式（让「换模板 → 样式变化」有可观察差异）。
_HEADING_SIZES = {1: 20, 2: 16, 3: 14}
_BODY_SIZE = 11
# 中文字形走 eastAsia 字体标记，否则 Word 会用默认宋体渲染中文（模板形同虚设）。
_BODY_FONT = "微软雅黑"

_HINT_SAVE_AS_DOCX = "请在本机把该文件另存为 .docx 后再试"


class TemplateError(Exception):
    """模板缺失 / 损坏 / 格式不受支持（可读原因，路由翻成 4xx）。"""


@dataclass(frozen=True)
class ResolvedTemplate:
    """一次生成所用的模板：登记标识（`templates/` 下的 posix 相对路径）与实际文件路径。"""

    template_used: str
    path: Path


def builtin_template_path(templates_dir: str | Path) -> Path:
    """内置最小默认模板的完整路径。"""
    return Path(templates_dir) / BUILTIN_DIR_NAME / BUILTIN_TEMPLATE_NAME


def ensure_builtin_template(templates_dir: str | Path) -> Path:
    """幂等生成内置最小默认模板，返回其路径（已存在则直接返回，不重写）。"""
    path = builtin_template_path(templates_dir)
    if path.is_file():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    _build_minimal_default(path)
    return path


def _build_minimal_default(path: Path) -> None:
    """用 python-docx 生成最小默认模板：显式定义六类样式。

    以 python-docx 自带 default.docx 为底（其样式表已是实体定义，非潜在样式），
    **显式重设**标题级别、正文与列表的字号 / 加粗 / 中文字体，使「内置模板」在
    外观上确实是一份模板，而不是空壳。先写临时文件再原子替换，避免半成品被读到。
    """
    document = Document()

    for level, size in _HEADING_SIZES.items():
        heading = document.styles[f"Heading {level}"]
        heading.font.size = Pt(size)
        heading.font.bold = True
        _apply_east_asian_font(heading.font, _BODY_FONT)

    body = document.styles["Normal"]
    body.font.size = Pt(_BODY_SIZE)
    _apply_east_asian_font(body.font, _BODY_FONT)

    # 列表与表格样式在 python-docx 自带模板里已定义；此处只确认可被模板机制取到，
    # 让「至少定义六类样式」成为显式契约而非隐含继承。
    for name in ("List Bullet", "Table Grid"):
        document.styles[name]

    temp_path = path.with_suffix(".tmp.docx")
    document.save(str(temp_path))
    temp_path.replace(path)


def _apply_east_asian_font(font, font_name: str) -> None:
    """给样式的字体同时设置西文与中文（eastAsia）字形名。"""
    font.name = font_name
    rpr = font.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), font_name)


def validate_template_file(path: Path, *, label: str) -> None:
    """校验模板可用：后缀、存在、可被文档库打开。不通过即抛 `TemplateError`。

    「可被打开」这一条就是陷阱 1 的兜底：把 `.dotx` 改名成 `.docx` 后，python-docx
    会因主部件内容类型不符抛 `ValueError`，此处翻成「请另存为 .docx」。
    """
    if path.suffix.lower() not in ALLOWED_TEMPLATE_SUFFIXES:
        raise TemplateError(
            f"只接受 .docx 模板（{label}：{path.name}）；{_HINT_SAVE_AS_DOCX}"
        )
    if not path.is_file():
        raise TemplateError(f"模板文件不存在（{label}）：{path.name}")

    try:
        Document(str(path))
    except ValueError as exc:  # 主部件内容类型不符（典型的 .dotx 改名）
        raise TemplateError(
            f"模板无法作为 Word 文档打开（{label}：{path.name}），"
            f"它很可能是 .dotx/.dotm/.docm 改名而来；{_HINT_SAVE_AS_DOCX}"
        ) from exc
    except (PackageNotFoundError, BadZipFile, KeyError, OSError) as exc:
        raise TemplateError(
            f"模板文件已损坏或不是有效的 .docx（{label}：{path.name}）；{_HINT_SAVE_AS_DOCX}"
        ) from exc


def resolve_template(
    templates_dir: str | Path,
    *,
    requested: str | None,
    default_name: str | None,
) -> ResolvedTemplate:
    """解析本次生成所用模板：任务级临时覆盖 > 全局默认模板 > 内置最小默认模板。

    - 显式 `requested`（临时覆盖）或已登记的全局默认**缺失 / 损坏** → 明确报错，
      绝不静默退回内置模板或空白生成；
    - 全局默认由 `templates` 表维护，本函数只读不写——临时覆盖不改变全局默认。
    """
    base = Path(templates_dir)

    if requested:
        relative = _normalize_relative(requested)
        path = _resolve_within(base, relative)
        validate_template_file(path, label="任务级临时覆盖")
        return ResolvedTemplate(template_used=relative, path=path)

    if default_name:
        relative = _normalize_relative(default_name)
        path = _resolve_within(base, relative)
        validate_template_file(path, label="全局默认模板")
        return ResolvedTemplate(template_used=relative, path=path)

    path = ensure_builtin_template(base)
    return ResolvedTemplate(template_used=BUILTIN_TEMPLATE_REL, path=path)


def template_path(templates_dir: str | Path, name: str) -> Path:
    """把模板名解析为模板目录内的实际路径；越界即报错（文件访问白名单）。"""
    return _resolve_within(Path(templates_dir), _normalize_relative(name))


def discover_templates(templates_dir: str | Path) -> list[dict]:
    """列出模板目录里可被选用的模板文件（登记与选用共用同一份事实）。

    只扫 `templates/` 一层 + 内置目录，不递归：模板是用户显式放入的文件，
    不做「联网找模板」，也不把子目录当模板集。
    """
    base = Path(templates_dir)
    discovered: list[dict] = []

    if base.is_dir():
        for entry in sorted(base.iterdir(), key=lambda item: item.name):
            if entry.is_dir():
                continue
            discovered.append(_template_entry(entry.name, base))

    builtin = builtin_template_path(base)
    if builtin.is_file():
        discovered.append(_template_entry(BUILTIN_TEMPLATE_REL, base))

    return discovered


def _template_entry(relative: str, base: Path) -> dict:
    """模板文件的展示条目：名称 / 格式 / 是否内置 / 是否可作为模板使用。"""
    suffix = Path(relative).suffix.lower().lstrip(".")
    return {
        "name": relative,
        "format": suffix,
        "builtin": relative == BUILTIN_TEMPLATE_REL,
        "usable": Path(relative).suffix.lower() in ALLOWED_TEMPLATE_SUFFIXES,
    }


def _normalize_relative(name: str) -> str:
    """把用户给的名字规范成 `templates/` 下的 posix 相对路径；越界即报错。"""
    candidate = name.strip().replace("\\", "/")
    if not candidate:
        raise TemplateError("模板名称不能为空")
    if candidate.startswith("/") or ":" in candidate or ".." in candidate.split("/"):
        raise TemplateError(f"模板名称不得越出模板目录：{name}")
    return candidate


def _resolve_within(base: Path, relative: str) -> Path:
    """把相对路径解析到模板目录内，并断言解析结果确在白名单目录下。"""
    resolved = (base / relative).resolve()
    base_resolved = base.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise TemplateError(f"模板路径越出模板目录：{relative}")
    return resolved