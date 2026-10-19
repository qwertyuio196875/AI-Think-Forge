"""资料分析路由：上传校验 → 解析 → 分块 → 逐块分析 → 综合；以及一键送入主题创作。

术语（GLOSSARY）：**资料分析** / **总结** / **未识别** / **来源** / **分块** /
**一键送入主题创作**。这是分析管线，**不是 RAG**（ADR-0002）：只处理刚上传的单份
资料，不建索引、不做跨文档检索。

纪律：
- 上传只收 TXT / MD / DOCX / PDF / PPTX，扩展名 + 50MB 上限；文件落 `data/` 白名单；
- 解析失败 / 未识别都如实落库并显式返回，**绝不用空字符串冒充成功**；
  PDF / PPTX 的解析结果带解析器标识与页 / 幻灯片级 locator（TB-8）；
- 模型失败返回可读 502，已入库的来源 / 文档 / 分块不受影响，可安全重试；
- 总结走 turbo 档，该档缺失时回退默认 provider 并把实际所用者写进结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app import config
from app.analysis.chunking import Chunk, build_chunks
from app.analysis.parsing import SUPPORTED_SUFFIXES, ParseError, parse_document
from app.analysis.service import (
    SummaryGenerationError,
    analyze_chunks,
    count_hanzi,
    primary_unrecognized,
    unrecognized_parts,
)
from app.analysis.web import (
    decode_html,
    extract_page_title,
    parse_web_document,
    unrecognized_reason,
)
from app.api.deps import (
    AnalysisRepositoryDep,
    DataDirDep,
    MessageRepositoryDep,
    SummaryDeliverableRepositoryDep,
    TaskRepositoryDep,
    TemplateRepositoryDep,
    TemplatesDirDep,
    TieredModelClientDep,
    UrlFetcherDep,
)
from app.generation.service import generate_summary_word_deliverable
from app.generation.templates import TemplateError
from app.generation.word import DeliverableIntegrityError
from app.grilling.service import SEED_ROUND_NO
from app.models.analysis import (
    AnalysisResultResponse,
    AnalysisSourceListItem,
    AnalysisSourceListResponse,
    AnalysisSourceResponse,
    AnalysisSummary,
    DocumentInfo,
    SendToCreationRequest,
    SendToCreationResponse,
    SourceInfo,
    SummaryCitation,
    SummaryWordDeliverableResponse,
    SummaryWordRequest,
    UnrecognizedContent,
    UrlSourceRequest,
)
from app.models.task import Task
from app.providers.model_client import ModelCallError
from app.providers.url_fetcher import UrlFetchError
from app.security.uploads import (
    UploadError,
    read_upload,
    safe_filename,
    store_under,
    validate_extension,
)
from app.security.url_guard import UrlSecurityError, validate_url

router = APIRouter(prefix="/analysis", tags=["analysis"])

# 上传子目录（`data/uploads/`，白名单内）。
UPLOAD_SUBDIR = "uploads"
# 引用摘录长度：够用户认出位置即可，不把整块原文复制进总结记录。
EXCERPT_MAX_CHARS = 80
# 任务标题取文件名截断，与主题创作的标题口径一致。
TITLE_MAX_LENGTH = 60
# 总结 Word 交付的媒体类型（下载端点用）。
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _original_name(source: dict) -> str:
    """来源的可读名称：优先原始文件名，退回路径末段。"""
    return str(source["meta"].get("original_name") or Path(source["ref"]).name)


def _url_title(url: str) -> str:
    """URL 来源的任务标题：`主机 + 路径末段`（页面标题要抓取后才知道）。"""
    parsed = urlsplit(url)
    host = parsed.netloc
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return (f"{host}/{tail}" if tail else host)[:TITLE_MAX_LENGTH]


def _document_info(record: dict, *, chunks: int) -> DocumentInfo:
    """文档记录 → 响应模型（只取对外字段）。"""
    return DocumentInfo(
        id=record["id"],
        source_id=record["source_id"],
        path=record["path"],
        parse_status=record["parse_status"],
        parse_message=record["parse_message"],
        heading_source=record["heading_source"],
        parser=record.get("parser"),
        encoding=record["encoding"],
        headings=record["headings"],
        images=record["images"],
        chunks=chunks,
        created_at=record["created_at"],
    )


def _persist_parsed_document(
    analysis_repository: AnalysisRepositoryDep,
    source: dict,
    path: str,
    parsed,
    *,
    parse_status: str,
    unrecognized: dict | None = None,
    unrecognized_parts: list[dict] | None = None,
    message: str | None = None,
    encoding: str | None = None,
    images: int = 0,
) -> AnalysisSourceResponse:
    """「落库 + 解析结果 + 分块」共用管线（上传与 URL 两个入口行为一致）。

    `parse_status="parsed"` 时按解析块建分块；`unrecognized` 时只落文档与显式契约，
    绝不建块、不生成空总结。`encoding` / `images` 由入口显式传入，保持两条入口
    既有的字段口径完全不变。
    """
    headings = sum(1 for block in parsed.blocks if block.heading_level is not None)
    chunks = build_chunks(parsed.blocks, parsed.format) if parse_status == "parsed" else []
    document = analysis_repository.create_document(
        source["id"],
        path,
        parse_status=parse_status,
        heading_source=parsed.heading_source,
        parser=parsed.parser,
        encoding=encoding,
        headings=headings,
        images=images,
        unrecognized=unrecognized,
        unrecognized_parts=unrecognized_parts,
    )
    if chunks:
        analysis_repository.add_chunks(
            document["id"],
            [
                {"seq": chunk.seq, "text": chunk.text, "locator": chunk.locator}
                for chunk in chunks
            ],
        )

    return AnalysisSourceResponse(
        source=SourceInfo(**source),
        document=_document_info(document, chunks=len(chunks)),
        unrecognized=UnrecognizedContent(**unrecognized) if unrecognized else None,
        unrecognized_parts=[
            UnrecognizedContent(**item) for item in (unrecognized_parts or [])
        ],
        message=message,
    )


def _summary_model(record: dict, *, hanzi_count: int) -> AnalysisSummary:
    """总结记录 → 响应模型。"""
    return AnalysisSummary(
        id=record["id"],
        source_id=record["source_id"],
        task_id=record["task_id"],
        text=record["text"],
        hanzi_count=hanzi_count,
        citations=[SummaryCitation(**item) for item in record["citations"]],
        chunk_count=record["chunk_count"],
        truncated=record["truncated"],
        provider_kind=record["provider_kind"],
        provider_used=record["provider_used"],
        model_used=record["model_used"],
        provider_fallback=record["provider_fallback"],
        provider_note=record["provider_note"],
        created_at=record["created_at"],
    )


def _unrecognized_model(value: dict | None) -> UnrecognizedContent | None:
    """未识别契约 dict → 响应模型。"""
    return UnrecognizedContent(**value) if value else None


@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    response_model=AnalysisSourceResponse,
)
def upload_source(
    task_repository: TaskRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    data_dir: DataDirDep,
    file: Annotated[UploadFile, File()],
) -> AnalysisSourceResponse:
    """上传并解析一份资料（TXT / MD / DOCX / PDF / PPTX），建立来源 / 文档 / 分块。

    解析失败仍返回 201 与 `parse_status="failed"` + 可读 `message`：来源与文档
    已入库、文件已落盘，用户可换文件或重试，不丢已存数据。
    """
    try:
        filename = safe_filename(file.filename or "")
        suffix = validate_extension(filename, SUPPORTED_SUFFIXES, label="资料分析")
        payload = read_upload(file.file)
        stored_path, relative = store_under(data_dir, UPLOAD_SUBDIR, filename, payload)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    task = task_repository.create("analysis", filename[:TITLE_MAX_LENGTH])
    source = analysis_repository.create_source(
        "file",
        relative,
        meta={
            "original_name": filename,
            "size": len(payload),
            "extension": suffix,
        },
        task_id=task["id"],
    )

    try:
        parsed = parse_document(stored_path, suffix.lstrip("."))
    except ParseError as exc:
        document = analysis_repository.create_document(
            source["id"],
            relative,
            parse_status="failed",
            parse_message=str(exc),
        )
        return AnalysisSourceResponse(
            source=SourceInfo(**source),
            document=_document_info(document, chunks=0),
            message=str(exc),
        )

    primary = primary_unrecognized(parsed)
    parts = unrecognized_parts(parsed)

    if primary is not None:
        return _persist_parsed_document(
            analysis_repository,
            source,
            relative,
            parsed,
            parse_status="unrecognized",
            unrecognized=primary,
            unrecognized_parts=parts,
            message=(
                "未识别到可分析的文本"
                + ("（疑似扫描件 / 图片，未做 OCR）" if parsed.images else "")
            ),
            encoding=parsed.encoding,
            images=parsed.images,
        )

    return _persist_parsed_document(
        analysis_repository,
        source,
        relative,
        parsed,
        parse_status="parsed",
        unrecognized_parts=parts,
        encoding=parsed.encoding,
        images=parsed.images,
    )


@router.post(
    "/sources/url",
    status_code=status.HTTP_201_CREATED,
    response_model=AnalysisSourceResponse,
)
def create_url_source(
    payload: UrlSourceRequest,
    task_repository: TaskRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    url_fetcher: UrlFetcherDep,
) -> AnalysisSourceResponse:
    """抓取一个公开网页作为资料，并建立来源 / 文档 / 分块（后续复用同一分析管线）。

    安全与纪律（规格 §2 / US 15）：
    - 提交即做**不联网的前置校验**（仅 http/https、拒绝内嵌凭据、拒绝字面量内网 /
      环回 / 链路本地 / 元数据 / 组播 / 保留地址），不合格 → 400 且**不落库**；
    - 抓取由 `UrlFetcher` 完成（真实实现逐跳重新校验、限超时 15s、限 5MB、最多 3 次
      重定向），失败 / 需登录 / 超时 / 超限**如实落库并提示，绝不绕过**；
    - 正文提取过滤导航 / 广告；无正文 → `unrecognized`（`no_main_text` /
      `empty_page`），绝不用空内容冒充成功。
    """
    try:
        validated = validate_url(payload.url, resolve=False)
    except UrlSecurityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    task = task_repository.create("analysis", _url_title(validated.url))

    try:
        page = url_fetcher.fetch(validated.url)
    except UrlFetchError as exc:
        # 抓取失败也如实登记（来源 / 文档落库、可读原因），与上传失败口径一致：
        # 不丢已存数据、可换链接重试，且绝不假装成功。
        source = analysis_repository.create_source(
            "url",
            validated.url,
            meta={"url": validated.url, "fetch_error": exc.reason},
            task_id=task["id"],
        )
        document = analysis_repository.create_document(
            source["id"],
            validated.url,
            parse_status="failed",
            parse_message=str(exc),
        )
        return AnalysisSourceResponse(
            source=SourceInfo(**source),
            document=_document_info(document, chunks=0),
            message=str(exc),
        )

    html = decode_html(page.body, page.content_type)
    parsed = parse_web_document(html, url=page.final_url)
    meta = {
        "url": validated.url,
        "final_url": page.final_url,
        "original_name": extract_page_title(html) or page.final_url,
        "fetched_at": page.fetched_at,
        "status": page.status,
        "content_type": page.content_type,
        "size": page.size,
        "redirects": page.redirects,
    }
    source = analysis_repository.create_source(
        "url", validated.url, meta=meta, task_id=task["id"]
    )

    if not parsed.blocks:
        reason = unrecognized_reason(html)
        contract = {
            "unrecognized": True,
            "reason": reason,
            "locator": {
                "format": "url",
                "url": page.final_url,
                "status": page.status,
                "content_type": page.content_type,
            },
            "needs_ocr": False,
        }
        return _persist_parsed_document(
            analysis_repository,
            source,
            page.final_url,
            parsed,
            parse_status="unrecognized",
            unrecognized=contract,
            message=(
                "该网页未提取到可分析的正文"
                "（可能是登录页 / 动态渲染页面 / 非文章页）"
            ),
        )

    return _persist_parsed_document(
        analysis_repository,
        source,
        page.final_url,
        parsed,
        parse_status="parsed",
        encoding=parsed.encoding,
    )


@router.get("/sources", response_model=AnalysisSourceListResponse)
def list_sources(
    analysis_repository: AnalysisRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisSourceListResponse:
    """来源列表（按 id 倒序）：带最新文档与总结标记，供历史续看 / 分析页列表。"""
    records, total = analysis_repository.list_sources(limit=limit, offset=offset)
    items = [
        AnalysisSourceListItem(
            source=SourceInfo(**record["source"]),
            document=(
                _document_info(
                    record["document"],
                    chunks=analysis_repository.count_chunks(record["document"]["id"]),
                )
                if record["document"] is not None
                else None
            ),
            has_summary=record["has_summary"],
            summary_id=record["summary_id"],
            summary_created_at=record["summary_created_at"],
        )
        for record in records
    ]
    return AnalysisSourceListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


@router.get("/sources/{source_id}", response_model=AnalysisSourceResponse)
def get_source(
    source_id: int,
    analysis_repository: AnalysisRepositoryDep,
) -> AnalysisSourceResponse:
    """读取来源与解析结果（含分块数、未识别契约），供分析页展示与重试。"""
    source = analysis_repository.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 不存在"
        )

    document = analysis_repository.get_document_for_source(source_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 尚无文档"
        )

    chunks = analysis_repository.count_chunks(document["id"])
    return AnalysisSourceResponse(
        source=SourceInfo(**source),
        document=_document_info(document, chunks=chunks),
        unrecognized=_unrecognized_model(document["unrecognized"]),
        unrecognized_parts=[
            UnrecognizedContent(**item) for item in document["unrecognized_parts"]
        ],
        message=document["parse_message"],
    )


@router.post("/sources/{source_id}/analyze", response_model=AnalysisResultResponse)
def analyze_source(
    source_id: int,
    task_repository: TaskRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    tiered_model_client: TieredModelClientDep,
) -> AnalysisResultResponse:
    """对已解析的资料执行「分块 → 逐块分析 → 综合」，保存总结并返回引用位置。

    - 未识别：短路返回显式契约，不调用模型、不生成空总结；
    - 解析失败：409 可读提示，已存数据保留；
    - 模型失败：502 可读提示，已存来源 / 文档 / 分块保留，可安全重试。
    """
    source = analysis_repository.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 不存在"
        )

    document = analysis_repository.get_document_for_source(source_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 尚无文档"
        )

    if document["parse_status"] == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该资料解析失败，无法分析：{document['parse_message'] or '原因未知'}",
        )

    parts = [UnrecognizedContent(**item) for item in document["unrecognized_parts"]]
    if document["parse_status"] == "unrecognized" or document["unrecognized"]:
        return AnalysisResultResponse(
            source=SourceInfo(**source),
            document=_document_info(document, chunks=0),
            unrecognized=_unrecognized_model(document["unrecognized"]),
            unrecognized_parts=parts,
            message=(
                document["parse_message"]
                or "未识别到可分析的文本，未调用模型（不对空内容做无意义处理）"
            ),
        )

    chunk_records = analysis_repository.list_chunks(document["id"])
    chunks = [
        Chunk(seq=record["seq"], text=record["text"], locator=record["locator"])
        for record in chunk_records
    ]
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该资料没有可分析的分块，请重新上传",
        )

    try:
        task = (
            task_repository.get(source["task_id"])
            if source["task_id"] is not None
            else None
        )
        outcome = analyze_chunks(
            chunks,
            source_name=_original_name(source),
            resolver=tiered_model_client,
            provider_id=task.get("provider_id") if task is not None else None,
        )
    except ModelCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型调用失败：{exc}",
        ) from exc
    except SummaryGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"总结生成失败：{exc}",
        ) from exc

    citations = [
        {
            "chunk_seq": chunk.seq,
            "locator": chunk.locator,
            "excerpt": " ".join(chunk.text.split())[:EXCERPT_MAX_CHARS],
        }
        for chunk in chunks
    ]
    record = analysis_repository.create_summary(
        source_id,
        outcome.text,
        task_id=source["task_id"],
        citations=citations,
        chunk_count=outcome.chunk_count,
        truncated=outcome.truncated,
        provider_kind=outcome.resolved.provider_kind,
        provider_used=outcome.resolved.provider_name,
        model_used=outcome.resolved.model_name,
        provider_fallback=outcome.resolved.fallback,
        provider_note=outcome.resolved.note,
    )
    if source["task_id"] is not None:
        task_repository.set_status(source["task_id"], "completed")

    return AnalysisResultResponse(
        source=SourceInfo(**source),
        document=_document_info(document, chunks=len(chunks)),
        summary=_summary_model(record, hanzi_count=outcome.hanzi_count),
        unrecognized_parts=parts,
    )


@router.get("/sources/{source_id}/summary", response_model=AnalysisSummary)
def get_summary(
    source_id: int,
    analysis_repository: AnalysisRepositoryDep,
) -> AnalysisSummary:
    """读取某来源最新的总结（保存即落库，可重复查看 / 复制）。"""
    source = analysis_repository.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 不存在"
        )

    record = analysis_repository.get_summary_for_source(source_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"来源 {source_id} 尚无总结，请先执行分析",
        )

    return _summary_model(record, hanzi_count=count_hanzi(record["text"]))


@router.post(
    "/sources/{source_id}/summary/word",
    response_model=SummaryWordDeliverableResponse,
)
def generate_summary_word(
    source_id: int,
    analysis_repository: AnalysisRepositoryDep,
    summary_deliverable_repository: SummaryDeliverableRepositoryDep,
    template_repository: TemplateRepositoryDep,
    data_dir: DataDirDep,
    templates_dir: TemplatesDirDep,
    payload: SummaryWordRequest | None = None,
) -> SummaryWordDeliverableResponse:
    """按模板把某来源的最新总结生成 Word（US16），并记录本次实际所用模板。

    - 来源不存在 → 404；尚无总结 → 409（不凭空生成空文档）；
    - 模板缺失 / 损坏 → 400（明确报错，不静默退回内置模板）；
    - 完整性检查未通过 → 500，且产物已由服务层丢弃、不落记录（US22）。
    """
    source = analysis_repository.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 不存在"
        )

    summary = analysis_repository.get_summary_for_source(source_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"来源 {source_id} 尚无总结，请先执行分析",
        )

    request = payload or SummaryWordRequest()
    try:
        result = generate_summary_word_deliverable(
            source=source,
            summary=summary,
            requested_template=request.template,
            data_dir=data_dir,
            templates_dir=templates_dir,
            template_repository=template_repository,
            deliverable_repository=summary_deliverable_repository,
        )
    except TemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except DeliverableIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"成品完整性检查未通过，已丢弃产物：{exc}",
        ) from exc

    return SummaryWordDeliverableResponse(**result)


@router.get("/summary-deliverables/{deliverable_id}")
def download_summary_word(
    deliverable_id: int,
    summary_deliverable_repository: SummaryDeliverableRepositoryDep,
    data_dir: DataDirDep,
) -> FileResponse:
    """下载已生成的总结 Word 成品；记录不存在或文件已丢失均 404。"""
    record = summary_deliverable_repository.get(deliverable_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"总结成品 {deliverable_id} 不存在",
        )

    path = Path(record["file_path"]).resolve()
    deliverables_root = (Path(data_dir) / config.DELIVERABLES_SUBDIR).resolve()
    if not path.is_relative_to(deliverables_root):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"总结成品 {deliverable_id} 的路径不在允许的成品目录内",
        )
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"总结成品 {deliverable_id} 的文件已不存在：{path}",
        )
    return FileResponse(path, media_type=DOCX_MEDIA_TYPE, filename=path.name)


@router.post(
    "/sources/{source_id}/send-to-creation",
    status_code=status.HTTP_201_CREATED,
    response_model=SendToCreationResponse,
)
def send_to_creation(
    source_id: int,
    task_repository: TaskRepositoryDep,
    message_repository: MessageRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    payload: SendToCreationRequest | None = None,
) -> SendToCreationResponse:
    """**一键送入主题创作**：新建主题创作任务，把该来源的总结预填为已知信息。

    复用既有 grilling 的种子输入路径（第 0 轮 user 消息），但**不调用模型**：
    预填只是把资料带进创作，首轮问题要等用户下次推进 / 发起时才需要模型。
    """
    source = analysis_repository.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"来源 {source_id} 不存在"
        )

    summary = analysis_repository.get_summary_for_source(source_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该来源尚无总结，无法送入主题创作；请先完成分析",
        )

    original_name = _original_name(source)
    stem = Path(original_name).stem
    title = (payload.title if payload else None) or f"{stem[:TITLE_MAX_LENGTH]} · 主题创作"

    known_input = (
        f"【资料来源】{original_name}\n"
        f"【资料总结】\n{summary['text']}"
    )
    task = task_repository.create("creation", title[:TITLE_MAX_LENGTH])
    message_repository.append(task["id"], SEED_ROUND_NO, "user", known_input)

    return SendToCreationResponse(
        task=Task.from_record(task),
        source_id=source_id,
        summary_id=summary["id"],
        known_input=known_input,
    )
