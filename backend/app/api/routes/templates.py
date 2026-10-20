"""模板管理入口（登记 + 全局默认）。

术语（GLOSSARY）**模板**：样式文件；Word 模板由用户提供，系统只管理与应用，从不联网
搜模板。术语「默认模板 / 临时覆盖」：本路由只维护**全局默认模板**；任务级**临时覆盖**
由生成入口的请求参数在单次生成内表达（见 `app/api/routes/generations.py`），
**两者在数据与 API 上互不混淆**——临时覆盖不写 `templates` 表、不改全局默认。

模板清单以**模板目录的实际情况**为准（用户把文件放进 `templates/` 即可替换，机制不变），
登记表只在其上补「是否全局默认」等元数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.deps import TemplateRepositoryDep, TemplatesDirDep
from app.generation.templates import (
    ALLOWED_TEMPLATE_SUFFIXES,
    TemplateError,
    discover_templates,
    template_path,
    validate_template_file,
)
from app.models.generation import (
    Template,
    TemplateListResponse,
    TemplateRegisterRequest,
    TemplateRegisterResponse,
)
from app.security.uploads import (
    UploadError,
    read_upload,
    resolve_within,
    safe_filename,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=TemplateListResponse)
def list_templates(
    templates_dir: TemplatesDirDep, template_repository: TemplateRepositoryDep
) -> TemplateListResponse:
    """列出模板目录里可被选用的模板 + 各自是否全局默认。"""
    registered = {record["name"]: record for record in template_repository.list_all()}
    discovered = discover_templates(templates_dir)

    items: list[Template] = []
    seen: set[str] = set()
    for entry in discovered:
        seen.add(entry["name"])
        record = registered.get(entry["name"])
        items.append(
            Template(
                **entry,
                is_default=bool(record and record["is_default"]),
                registered=record is not None,
            )
        )

    # 已登记但文件已不在（被删除 / 改名）：如实列出并标 `missing`，不假装还在。
    for name, record in registered.items():
        if name in seen:
            continue
        items.append(
            Template(
                name=name,
                format=record["format"],
                is_default=bool(record["is_default"]),
                builtin=False,
                usable=False,
                registered=True,
                missing=True,
            )
        )

    return TemplateListResponse(items=items, total=len(items))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TemplateRegisterResponse)
def register_template(
    payload: TemplateRegisterRequest,
    templates_dir: TemplatesDirDep,
    template_repository: TemplateRepositoryDep,
) -> TemplateRegisterResponse:
    """登记一个已放入 `templates/` 的模板文件（只接受 .docx）。

    负测路径：`.dotx` / `.dotm` / `.docm`，以及改名成 `.docx` 的模板类型文件，
    都返回 400 并提示「请另存为 .docx」（调研 A2 陷阱 1）。
    """
    record = _validated_template(templates_dir, payload.name)
    registered = template_repository.register(
        record["name"], record["format"], is_default=payload.is_default
    )
    default = template_repository.get_default(registered["format"])

    return TemplateRegisterResponse(
        template=Template(
            **record,
            is_default=bool(registered["is_default"]),
            registered=True,
        ),
        default_template=default["name"] if default else None,
    )


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateRegisterResponse,
)
def upload_template(
    templates_dir: TemplatesDirDep,
    template_repository: TemplateRepositoryDep,
    file: Annotated[UploadFile, File()],
) -> TemplateRegisterResponse:
    """**模板文件上传**（multipart）：把用户 .docx 直接落进 `templates/` 并登记。

    复用资料上传同一套「扩展名 + 50MB」校验与白名单落盘；只接受 `.docx`，
    沿用 TB-5 的错误口径：`.dotx` / `.dotm` / `.docm`（含改名成 `.docx` 的模板
    类型文件）→ 400 并提示「请另存为 .docx」。同名模板已存在 → 409，不静默覆盖。
    """
    try:
        filename = safe_filename(file.filename or "")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_TEMPLATE_SUFFIXES:
            raise UploadError(
                f"只接受 .docx 模板（收到 {filename}）；"
                "请在本机把该文件另存为 .docx 后再上传"
            )
        payload = read_upload(file.file)
        target = resolve_within(templates_dir, filename)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if target.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"模板已存在：{filename}；请改名后再上传，系统不会静默覆盖",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    try:
        validate_template_file(target, label="模板上传")
    except TemplateError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    registered = template_repository.register(filename, "docx", is_default=False)
    default = template_repository.get_default("docx")
    return TemplateRegisterResponse(
        template=Template(
            name=filename,
            format="docx",
            is_default=bool(registered["is_default"]),
            builtin=False,
            usable=True,
            registered=True,
        ),
        default_template=default["name"] if default else None,
    )


@router.put("/{name}/default", response_model=TemplateRegisterResponse)
def set_default_template(
    name: str,
    templates_dir: TemplatesDirDep,
    template_repository: TemplateRepositoryDep,
) -> TemplateRegisterResponse:
    """把某个模板设为该格式的**全局默认模板**（同格式至多一个）。"""
    record = _validated_template(templates_dir, name)
    registered = template_repository.register(record["name"], record["format"], is_default=True)

    return TemplateRegisterResponse(
        template=Template(
            **record,
            is_default=bool(registered["is_default"]),
            registered=True,
        ),
        default_template=registered["name"],
    )


def _validated_template(templates_dir: str, name: str) -> dict:
    """校验模板文件并返回展示条目；校验失败抛 400（可读原因）。"""
    wanted = _normalize(name)
    entry = next(
        (item for item in discover_templates(templates_dir) if item["name"] == wanted),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"模板文件不存在：{name}（请先把模板放入 templates/ 目录）",
        )
    if not entry["usable"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"只接受 .docx 模板（收到 {name}）；"
                "请在本机把该文件另存为 .docx 后再登记"
            ),
        )

    try:
        validate_template_file(template_path(templates_dir, entry["name"]), label="模板登记")
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return entry


def _normalize(name: str) -> str:
    """模板名规范化：统一分隔符，与模板目录里的实际条目对齐。"""
    return name.strip().replace("\\", "/")