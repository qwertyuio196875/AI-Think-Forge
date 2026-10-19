"""上传校验与落盘（扩展名白名单 + 大小上限 + 工作目录白名单）。

规格 US 30 / 实现约定：上传必须校验扩展名与大小（默认 50MB），文件访问限定
`data/`、`templates/` 白名单。本模块把这两条规则收在一处，供资料分析与模板上传
共用同一套口径，避免两个入口的校验渐渐漂移。

只做「能不能收、落到哪」；解析成功与否由 `app.analysis.parsing` 负责。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import BinaryIO

# 上传大小上限（规格与实现约定：默认 50MB）。
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# 分块读取，避免把超大文件一次性读进内存。
READ_CHUNK_BYTES = 1024 * 1024
# 文件名长度上限：Windows 路径单段上限 255，留出前缀与后缀余量。
MAX_FILENAME_LENGTH = 120


class UploadError(ValueError):
    """上传被拒（可读原因）；`status_code` 供路由直接翻译为 HTTP 状态码。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_extension(
    filename: str, allowed: frozenset[str] | tuple[str, ...] | set[str], *, label: str
) -> str:
    """校验扩展名（大小写不敏感），返回小写后缀；不通过即抛 `UploadError`。"""
    suffix = Path(filename or "").suffix.lower()
    normalized_allowed = tuple(sorted({item.lower() for item in allowed}))
    if suffix not in normalized_allowed:
        allowed_text = " / ".join(item.upper().lstrip(".") for item in normalized_allowed)
        raise UploadError(
            f"{label}只接受 {allowed_text}（收到 {filename or '空文件名'}）；"
            "请转换格式后重试"
        )
    return suffix


def safe_filename(filename: str) -> str:
    """把上传文件名收敛成安全的单段文件名（防目录穿越 / 非法字符）。

    只取最后一段，去掉 Windows / POSIX 路径分隔符与保留字符；空名或只剩
    `.` / `..` 一律拒绝。超长时保留后缀截断主干。
    """
    normalized = (filename or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].strip()
    name = "".join(
        character
        for character in name
        if character.isprintable() and character not in '<>:"/\\|?*'
    )
    if name in {"", ".", ".."}:
        raise UploadError("文件名为空或不可用")

    suffix = Path(name).suffix
    if len(name) > MAX_FILENAME_LENGTH:
        stem = Path(name).stem[: MAX_FILENAME_LENGTH - len(suffix)]
        name = f"{stem}{suffix}"
    return name


def read_upload(fileobj: BinaryIO, *, max_bytes: int | None = None) -> bytes:
    """分块读取上传内容并强制大小上限；超限抛 413 口径的 `UploadError`。

    默认上限在调用时读取模块常量，测试可 monkeypatch 后走同一段真实逻辑。
    """
    limit = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    limit_mb = max(1, limit // (1024 * 1024))
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = fileobj.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UploadError(
                f"文件超过上传上限 {limit_mb} MB（已读取 {total} 字节）",
                status_code=413,
            )
        chunks.append(chunk)

    if total == 0:
        raise UploadError("上传文件为空")
    return b"".join(chunks)


def store_under(base_dir: str | Path, subdir: str, filename: str, data: bytes) -> tuple[Path, str]:
    """把内容写到 `<base_dir>/<subdir>/<唯一前缀>-<文件名>`，返回 (绝对路径, 相对路径)。

    相对路径以 `base_dir` 为根、用 posix 分隔符记录（存进 `documents.path`），
    以后读取时仍从同一个白名单根解析。写前断言目标确实在 `base_dir` 内。
    """
    base = Path(base_dir).resolve()
    target_dir = (base / subdir).resolve()
    if target_dir != base and base not in target_dir.parents:
        raise UploadError(f"上传目录越出数据目录：{subdir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex[:12]}-{safe_filename(filename)}"
    resolved = target.resolve()
    if base not in resolved.parents:
        raise UploadError(f"上传路径越出数据目录：{filename}")

    resolved.write_bytes(data)
    return resolved, resolved.relative_to(base).as_posix()


def resolve_within(base_dir: str | Path, relative: str) -> Path:
    """把白名单内的相对路径解析为绝对路径；越界即抛 `UploadError`。"""
    base = Path(base_dir).resolve()
    resolved = (base / relative).resolve()
    if resolved != base and base not in resolved.parents:
        raise UploadError(f"路径越出工作目录白名单：{relative}")
    return resolved
