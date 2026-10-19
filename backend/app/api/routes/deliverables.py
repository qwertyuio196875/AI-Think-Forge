"""成品投递：把 `generations` 记录对应的产物交给前端（打开成品 / 应用内预览演示）。

为什么需要这个端点：浏览器经 `http://127.0.0.1:8720` 无法加载 `file://` 本地文件，
所以产物必须由后端投递；前端两个入口都只拿 **generation id**，不传路径。

安全边界（本端点的重点）：
- 只能按 id 间接取 `generations.file_path`，**从不接受客户端传入的路径**；
- 记录里的绝对路径经 `Path.resolve()` 解析后，必须仍位于 `data/deliverables/`
  之内，否则（`..`、软链、绝对路径逃逸）一律与「文件不存在」同样处理；
- 越界与缺失都回 **404**，响应体不带路径：不让客户端借错误信息探测文件系统；
- 只投递白名单扩展名（`.docx` / `.html`），其它后缀即便落在目录内也不投。

HTML 一轨是自包含单文件（样式 / 脚本全内联，见 ADR-0003 与完整性检查），应用内用
`iframe` 预览；因此**不额外加 CSP**，否则会阻断产物自己的内联资源。Content-Disposition
对 HTML 用 `inline`（能在 iframe 里直接渲染），对 Word 用 `attachment`（存盘打开）。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app import config
from app.api.deps import DataDirDep, GenerationRepositoryDep

router = APIRouter(prefix="/deliverables", tags=["deliverables"])

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
# 白名单：既决定 Content-Type，也决定哪些文件允许被投递。
MEDIA_TYPES = {
    ".docx": DOCX_MEDIA_TYPE,
    ".html": "text/html; charset=utf-8",
}
# 可内联渲染、适合应用内 iframe 预览的格式；其余按附件下载。
INLINE_SUFFIXES = frozenset({".html"})


def _unavailable() -> HTTPException:
    """「取不到这份成品」的统一回应：不区分缺失 / 越界，也不带路径。"""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="成品文件不存在或不可访问",
    )


def _resolve_deliverable(deliverables_root: Path, recorded_path: str) -> Path:
    """把记录里的产物路径解析为真实路径，并确认仍在白名单目录内。

    逐跳防逃逸：
    1. 输入只来自数据库记录（调用方不接收客户端路径）；
    2. `resolve()` 消掉 `..` 并解析软链 / junction，得到文件系统真实路径
       （Windows 下同时消解大小写与 8.3 短名）；
    3. `is_relative_to(root)` 做包含判断：绝对路径逃逸、`..`、软链指向外部都会被挡；
    4. 最后才检查 `is_file()`，目录 / 设备文件同样不投递。
    """
    root = deliverables_root.resolve()
    try:
        candidate = Path(recorded_path).resolve()
    except OSError as exc:  # 非法路径（无权限 / 坏盘符等）按「不可访问」处理
        raise _unavailable() from exc

    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise _unavailable()
    return candidate


def _content_disposition(filename: str, suffix: str) -> str:
    """可读文件名：ASCII 回退 + RFC 5987 的 `filename*=UTF-8''…`（支持中文）。"""
    disposition = "inline" if suffix in INLINE_SUFFIXES else "attachment"
    fallback = "".join(
        char for char in filename if char.isprintable() and char not in '"\\'
    )
    if not fallback.isascii() or not fallback:
        fallback = f"deliverable{suffix}"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/{generation_id}")
def download_deliverable(
    generation_id: int,
    generation_repository: GenerationRepositoryDep,
    data_dir: DataDirDep,
) -> FileResponse:
    """按成品记录 id 投递产物；记录不存在、路径越界或文件缺失一律 404。"""
    record = generation_repository.get(generation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"成品 {generation_id} 不存在",
        )

    artifact = _resolve_deliverable(
        Path(data_dir) / config.DELIVERABLES_SUBDIR, record["file_path"]
    )
    suffix = artifact.suffix.lower()
    media_type = MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise _unavailable()

    return FileResponse(
        artifact,
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(artifact.name, suffix)},
    )
