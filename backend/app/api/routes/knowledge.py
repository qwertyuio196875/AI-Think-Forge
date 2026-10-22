"""知识库路由（工单 19 入库与清单；工单 20 嵌入写入）。

术语（GLOSSARY）：**知识库** = 用户显式添加的本地资料集合，含分块与检索索引。
归属约定（ADR-0005）：知识库资料复用 `sources` / `documents` / `document_chunks`，
以**不隶属任何任务**（`sources.task_id IS NULL`）表示；不新建平行表族。

纪律：
- 分块复用资料分析同一条管线（`analysis/chunking.py`：目标 1200 / 上限 1800，
  按标题边界切），本模块不另造分块器；
- 上传即入库：解析 + 建分块 + 写向量一次完成，全成功为「已入库」；
- **解析或索引失败不丢资料**：文件已落盘、来源与文档已入库，状态置「索引失败」
  并附可读原因，返回 201 让用户看得到、读得到，绝不静默吞掉（验收②）；
- 嵌入失败同样只是「索引失败」：分块与原文保留，向量一条不写（工单 20）；
  检索的降级由工单 21 / 22 负责，本模块不实现检索；
- 重建索引 = 重解析 + 重切块 + **整份替换向量**，因此换嵌入模型后不会新旧混存。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.analysis.chunking import build_chunks
from app.analysis.parsing import SUPPORTED_SUFFIXES, ParseError, parse_document
from app.analysis.service import primary_unrecognized, unrecognized_parts
from app.api.deps import (
    AnalysisRepositoryDep,
    DataDirDep,
    EmbeddingClientDep,
    EmbeddingRepositoryDep,
    KnowledgeRepositoryDep,
)
from app.db.knowledge_repository import (
    INDEX_STATUS_FAILED,
    INDEX_STATUS_INDEXING,
    INDEX_STATUS_STORED,
)
from app.models.knowledge import (
    INDEX_STATUS_LABELS,
    KnowledgeDeleteResponse,
    KnowledgeReindexItem,
    KnowledgeReindexRequest,
    KnowledgeReindexResponse,
    KnowledgeSourceItem,
    KnowledgeSourceListResponse,
    KnowledgeUploadResponse,
)
from app.providers.embedding_client import EmbeddingError
from app.security.uploads import (
    UploadError,
    read_upload,
    resolve_within,
    safe_filename,
    store_under,
    validate_extension,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# 上传子目录与资料分析共用 `data/uploads/`（同一个白名单，同一套清理口径）。
UPLOAD_SUBDIR = "uploads"


def _label(index_status: str) -> str:
    """索引状态 → 中文标签；未知值原样返回，不编造「已入库」。"""
    return INDEX_STATUS_LABELS.get(index_status, index_status)


def _item(record: dict) -> KnowledgeSourceItem:
    """清单记录（来源 + 最新文档 + 分块数）→ 响应模型。"""
    source = record["source"]
    document = record["document"]
    meta = source.get("meta") or {}
    size = meta.get("size")
    return KnowledgeSourceItem(
        source_id=source["id"],
        name=str(meta.get("original_name") or Path(source["ref"]).name),
        kind=source["kind"],
        ref=source["ref"],
        size=int(size) if isinstance(size, int) else None,
        document_id=document["id"] if document is not None else None,
        parse_status=document["parse_status"] if document is not None else None,
        parse_message=document["parse_message"] if document is not None else None,
        chunk_count=record["chunk_count"],
        index_status=source["index_status"],
        index_status_label=_label(source["index_status"]),
        index_message=source["index_message"],
        indexed_at=source["indexed_at"],
        created_at=source["created_at"],
    )


def _load_record(knowledge_repository: KnowledgeRepositoryDep, source_id: int) -> dict:
    """读取一份知识库资料的最新记录（来源 + 文档 + 分块数）。"""
    source = knowledge_repository.get(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"知识库资料 {source_id} 不存在",
        )
    return knowledge_repository.get_record(source_id)


def _write_embeddings(
    *,
    embedding_client: EmbeddingClientDep,
    embedding_repository: EmbeddingRepositoryDep,
    document_id: int,
    texts: list[str],
    chunk_ids: list[int],
) -> str | None:
    """把分块写成向量；成功返回 `None`，失败返回可读原因（不抛异常）。

    嵌入是**可降级的外部依赖**：任何失败都只意味着「这份资料暂时没有向量」，
    资料与分块必须原样保留，索引状态如实记成「索引失败」——绝不为了向量把
    已经入库的资料回滚掉（验收：失败资料仍可读）。
    """
    try:
        vectors = embedding_client.embed(texts)
    except EmbeddingError as exc:
        return f"向量索引失败：{exc}"
    except Exception as exc:  # noqa: BLE001 - 嵌入的任何异常都只影响索引状态
        return f"向量索引失败：{exc}"

    if len(vectors) != len(texts):
        return f"向量索引失败：返回 {len(vectors)} 条向量，与 {len(texts)} 个分块不符"

    try:
        embedding_repository.replace_document_vectors(
            document_id,
            list(zip(chunk_ids, vectors, strict=True)),
            model_name=embedding_client.model_name,
            version=embedding_client.version,
        )
    except EmbeddingError as exc:
        return f"向量索引失败：{exc}"
    except ValueError as exc:
        return f"向量索引失败：{exc}"
    return None


def _persist_parsed(
    *,
    knowledge_repository: KnowledgeRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    embedding_client: EmbeddingClientDep,
    embedding_repository: EmbeddingRepositoryDep,
    source_id: int,
    relative: str,
    parsed,
) -> dict:
    """把解析结果落成文档 + 分块 + 向量，并把索引状态置为「已入库」。

    向量写入失败时**不回滚分块**：状态置「索引失败」并附原因，资料照旧可读；
    重建索引会整份替换向量，所以下次重试不会残留半份。
    """
    headings = sum(1 for block in parsed.blocks if block.heading_level is not None)
    chunks = build_chunks(parsed.blocks, parsed.format)

    existing = analysis_repository.get_document_for_source(source_id)
    if existing is None:
        document = analysis_repository.create_document(
            source_id,
            relative,
            parse_status="parsed",
            heading_source=parsed.heading_source,
            parser=parsed.parser,
            encoding=parsed.encoding,
            headings=headings,
            images=parsed.images,
            unrecognized_parts=unrecognized_parts(parsed),
        )
    else:
        document = analysis_repository.update_document(
            existing["id"],
            path=relative,
            parse_status="parsed",
            clear_parse_message=True,
            heading_source=parsed.heading_source,
            parser=parsed.parser,
            encoding=parsed.encoding,
            headings=headings,
            images=parsed.images,
            unrecognized_parts=unrecognized_parts(parsed),
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"知识库资料 {source_id} 的文档已不存在",
            )

    knowledge_repository.replace_chunks(
        document["id"],
        [{"seq": chunk.seq, "text": chunk.text, "locator": chunk.locator} for chunk in chunks],
    )

    # 以落库后的分块为准（id 与 text 都来自库里），避免内存对象与库不一致。
    stored_chunks = analysis_repository.list_chunks(document["id"])
    if stored_chunks:
        reason = _write_embeddings(
            embedding_client=embedding_client,
            embedding_repository=embedding_repository,
            document_id=document["id"],
            texts=[chunk["text"] for chunk in stored_chunks],
            chunk_ids=[chunk["id"] for chunk in stored_chunks],
        )
        if reason is not None:
            knowledge_repository.set_index_status(source_id, INDEX_STATUS_FAILED, message=reason)
            return knowledge_repository.get_record(source_id)

    knowledge_repository.set_index_status(source_id, INDEX_STATUS_STORED)
    return knowledge_repository.get_record(source_id)


def _persist_failure(
    *,
    knowledge_repository: KnowledgeRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    source_id: int,
    relative: str,
    message: str,
    parsed=None,
    parse_status: str = "failed",
    unrecognized: dict | None = None,
) -> dict:
    """解析 / 索引失败：文档如实落库，状态置「索引失败」，资料本身保留可读。"""
    existing = analysis_repository.get_document_for_source(source_id)
    fields = {
        "path": relative,
        "parse_status": parse_status,
        "parse_message": message,
        "heading_source": getattr(parsed, "heading_source", None),
        "parser": getattr(parsed, "parser", None),
        "encoding": getattr(parsed, "encoding", None),
        "headings": (
            sum(1 for block in parsed.blocks if block.heading_level is not None)
            if parsed is not None
            else 0
        ),
        "images": getattr(parsed, "images", 0),
        "unrecognized": unrecognized,
        "unrecognized_parts": unrecognized_parts(parsed) if parsed is not None else [],
    }
    if existing is None:
        analysis_repository.create_document(
            source_id, relative, **{k: v for k, v in fields.items() if k != "path"}
        )
    else:
        analysis_repository.update_document(existing["id"], **fields)

    knowledge_repository.set_index_status(source_id, INDEX_STATUS_FAILED, message=message)
    return knowledge_repository.get_record(source_id)


@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    response_model=KnowledgeUploadResponse,
)
def upload_source(
    knowledge_repository: KnowledgeRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    embedding_client: EmbeddingClientDep,
    embedding_repository: EmbeddingRepositoryDep,
    data_dir: DataDirDep,
    file: Annotated[UploadFile, File()],
) -> KnowledgeUploadResponse:
    """上传一份资料并入知识库（TXT / MD / DOCX / PDF / PPTX，50MB 上限）。

    解析失败同样返回 201：文件与来源已入库，状态为「索引失败」并带可读原因，
    用户可以删掉重传，资料本身不会凭空消失。嵌入失败同理——分块保留、向量不写，
    状态如实标「索引失败」，检索走降级（降级检索属工单 21 / 22）。
    """
    try:
        filename = safe_filename(file.filename or "")
        suffix = validate_extension(filename, SUPPORTED_SUFFIXES, label="知识库")
        payload = read_upload(file.file)
        stored_path, relative = store_under(data_dir, UPLOAD_SUBDIR, filename, payload)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    source = knowledge_repository.create_source(
        "file",
        relative,
        meta={
            "original_name": filename,
            "size": len(payload),
            "extension": suffix,
        },
    )

    try:
        parsed = parse_document(stored_path, suffix.lstrip("."))
    except ParseError as exc:
        record = _persist_failure(
            knowledge_repository=knowledge_repository,
            analysis_repository=analysis_repository,
            source_id=source["id"],
            relative=relative,
            message=str(exc),
        )
        return KnowledgeUploadResponse(item=_item(record), message=str(exc))

    primary = primary_unrecognized(parsed)
    if primary is not None:
        message = "未识别到可分析的文本"
        if parsed.images:
            message += "（疑似扫描件 / 图片，未做 OCR）"
        record = _persist_failure(
            knowledge_repository=knowledge_repository,
            analysis_repository=analysis_repository,
            source_id=source["id"],
            relative=relative,
            message=message,
            parsed=parsed,
            parse_status="unrecognized",
            unrecognized=primary,
        )
        return KnowledgeUploadResponse(item=_item(record), message=message)

    try:
        record = _persist_parsed(
            knowledge_repository=knowledge_repository,
            analysis_repository=analysis_repository,
            embedding_client=embedding_client,
            embedding_repository=embedding_repository,
            source_id=source["id"],
            relative=relative,
            parsed=parsed,
        )
    except Exception as exc:  # noqa: BLE001 - 解析成功但建分块失败也要留痕可见
        message = f"分块索引失败：{exc}"
        record = _persist_failure(
            knowledge_repository=knowledge_repository,
            analysis_repository=analysis_repository,
            source_id=source["id"],
            relative=relative,
            message=message,
            parsed=parsed,
            parse_status="parsed",
        )
        return KnowledgeUploadResponse(item=_item(record), message=message)

    # 已入库但向量没写成（通常是嵌入模型没配）：把原因一并回给前端，别让用户
    # 只看到「已入库」却检索不到东西。
    return KnowledgeUploadResponse(item=_item(record), message=record["source"]["index_message"])


@router.get("/sources", response_model=KnowledgeSourceListResponse)
def list_sources(
    knowledge_repository: KnowledgeRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeSourceListResponse:
    """知识库清单（按 id 倒序）：文件名、分块数、索引状态一目了然。"""
    records, total = knowledge_repository.list_sources(limit=limit, offset=offset)
    return KnowledgeSourceListResponse(
        items=[_item(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/sources/{source_id}", response_model=KnowledgeDeleteResponse)
def delete_source(
    source_id: int,
    knowledge_repository: KnowledgeRepositoryDep,
    data_dir: DataDirDep,
) -> KnowledgeDeleteResponse:
    """删除一份知识库资料，连带清掉它的文档、分块与嵌入。

    磁盘删除是尽力而为：数据库是事实来源，文件删不掉（被占用等）也不影响清单，
    因此吞掉 `OSError` 而不让整次删除失败。
    """
    source = knowledge_repository.get(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"知识库资料 {source_id} 不存在",
        )

    deleted_chunks = knowledge_repository.delete(source_id)
    if deleted_chunks is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"知识库资料 {source_id} 不存在",
        )

    try:
        resolve_within(data_dir, source["ref"]).unlink(missing_ok=True)
    except (OSError, ValueError):
        # 文件已被占用 / 路径不在白名单：库里的记录已删，清单以库为准。
        pass

    return KnowledgeDeleteResponse(source_id=source_id, deleted_chunk_count=deleted_chunks)


@router.post("/reindex", response_model=KnowledgeReindexResponse)
def reindex(
    knowledge_repository: KnowledgeRepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    embedding_client: EmbeddingClientDep,
    embedding_repository: EmbeddingRepositoryDep,
    data_dir: DataDirDep,
    request: KnowledgeReindexRequest | None = None,
) -> KnowledgeReindexResponse:
    """重建知识库索引（重解析 + 重切块 + 整份替换向量）。

    典型用途是换了分块参数或**换了嵌入模型**：旧向量随旧分块一并删除，新向量
    按新模型写入，因此不会新旧混存（验收④）。逐份处理、单份失败不中断整批：
    失败的资料状态置「索引失败」并保留原文，结果里逐条可见，绝不整体 500 掩盖
    部分失败。
    """
    payload = request or KnowledgeReindexRequest()
    if payload.source_id is not None:
        _load_record(knowledge_repository, payload.source_id)
        target_ids = [payload.source_id]
    else:
        target_ids = knowledge_repository.list_reindex_targets()

    items: list[KnowledgeReindexItem] = []
    for source_id in target_ids:
        source = knowledge_repository.get(source_id)
        if source is None:
            continue
        knowledge_repository.set_index_status(source_id, INDEX_STATUS_INDEXING)
        suffix = Path(source["ref"]).suffix.lstrip(".")
        try:
            stored_path = resolve_within(data_dir, source["ref"])
            if not stored_path.is_file():
                raise ParseError("原始文件已不在磁盘上，无法重建索引")
            parsed = parse_document(stored_path, suffix)
            if primary_unrecognized(parsed) is not None:
                message = "未识别到可分析的文本，未建索引"
                _persist_failure(
                    knowledge_repository=knowledge_repository,
                    analysis_repository=analysis_repository,
                    source_id=source_id,
                    relative=source["ref"],
                    message=message,
                    parsed=parsed,
                    parse_status="unrecognized",
                    unrecognized=primary_unrecognized(parsed),
                )
                items.append(
                    KnowledgeReindexItem(
                        source_id=source_id,
                        index_status=INDEX_STATUS_FAILED,
                        index_status_label=_label(INDEX_STATUS_FAILED),
                        message=message,
                    )
                )
                continue
            record = _persist_parsed(
                knowledge_repository=knowledge_repository,
                analysis_repository=analysis_repository,
                embedding_client=embedding_client,
                embedding_repository=embedding_repository,
                source_id=source_id,
                relative=source["ref"],
                parsed=parsed,
            )
            # 以落库后的真实状态回报：向量没写成同样是「索引失败」，不能硬写已入库。
            index_status = record["source"]["index_status"]
            items.append(
                KnowledgeReindexItem(
                    source_id=source_id,
                    index_status=index_status,
                    index_status_label=_label(index_status),
                    message=record["source"]["index_message"],
                )
            )
        except (ParseError, ValueError, OSError) as exc:
            message = str(exc)
            knowledge_repository.set_index_status(source_id, INDEX_STATUS_FAILED, message=message)
            items.append(
                KnowledgeReindexItem(
                    source_id=source_id,
                    index_status=INDEX_STATUS_FAILED,
                    index_status_label=_label(INDEX_STATUS_FAILED),
                    message=message,
                )
            )

    return KnowledgeReindexResponse(items=items, total=len(items))
