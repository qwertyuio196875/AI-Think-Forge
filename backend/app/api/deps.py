"""FastAPI 依赖注入位置。

业务依赖（任务仓库、模型配置仓库、密钥库、模型客户端、URL 抓取器、嵌入客户端）
集中在此声明，测试用 `app.dependency_overrides[<函数>]` 替换即可注入替身。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.db.analysis_repository import AnalysisRepository
from app.db.embedding_repository import EmbeddingRepository
from app.db.fill_task_repository import FillTaskRepository
from app.db.generation_repository import GenerationRepository
from app.db.knowledge_repository import KnowledgeRepository
from app.db.message_repository import MessageRepository
from app.db.open_item_repository import OpenItemRepository
from app.db.plan_repository import PlanRepository
from app.db.plan_revision_repository import PlanRevisionRepository
from app.db.plan_section_repository import PlanSectionRepository
from app.db.provider_repository import ProviderRepository
from app.db.settings_repository import SettingsRepository
from app.db.summary_deliverable_repository import SummaryDeliverableRepository
from app.db.task_repository import TaskRepository
from app.db.template_repository import TemplateRepository
from app.providers.embedding_client import EmbeddingClient
from app.providers.key_store import KeyStore
from app.providers.model_client import ModelClient, ProviderModelClientFactory
from app.providers.tiered_client import TieredModelClient
from app.providers.url_fetcher import UrlFetcher
from app.retrieval.service import RetrievalService


def get_db_path(request: Request) -> str:
    """当前应用的 SQLite 库路径（由 create_app 写入 app.state）。"""
    return request.app.state.db_path


def get_data_dir(request: Request) -> str:
    """当前应用的运行时数据目录（成品落盘位置，`data/` 白名单）。"""
    return request.app.state.data_dir


def get_templates_dir(request: Request) -> str:
    """当前应用的模板目录（用户模板 + 内置默认模板，`templates/` 白名单）。"""
    return request.app.state.templates_dir


def get_task_repository(db_path: str = Depends(get_db_path)) -> TaskRepository:
    """任务仓库依赖。"""
    return TaskRepository(db_path)


def get_provider_repository(db_path: str = Depends(get_db_path)) -> ProviderRepository:
    """模型配置仓库依赖。"""
    return ProviderRepository(db_path)


def get_message_repository(db_path: str = Depends(get_db_path)) -> MessageRepository:
    """对话消息仓库依赖（拷问轮次的提问与回答同序落库）。"""
    return MessageRepository(db_path)


def get_plan_repository(db_path: str = Depends(get_db_path)) -> PlanRepository:
    """结构化方案仓库依赖（draft/confirmed + 确认时间）。"""
    return PlanRepository(db_path)


def get_open_item_repository(db_path: str = Depends(get_db_path)) -> OpenItemRepository:
    """待确认事项仓库依赖（来源轮次 / 条目 / 状态）。"""
    return OpenItemRepository(db_path)


def get_plan_revision_repository(db_path: str = Depends(get_db_path)) -> PlanRevisionRepository:
    """方案版本记录仓库依赖（对话式修订留痕，旧版本不可丢）。"""
    return PlanRevisionRepository(db_path)


def get_plan_section_repository(
    db_path: str = Depends(get_db_path),
) -> PlanSectionRepository:
    """成品章节仓库依赖（一章一行，唯一键「方案 + 序号」）。"""
    return PlanSectionRepository(db_path)


def get_generation_repository(db_path: str = Depends(get_db_path)) -> GenerationRepository:
    """成品（成品文件）读写依赖（表未落地时只读计数仍计 0）。"""
    return GenerationRepository(db_path)


def get_template_repository(db_path: str = Depends(get_db_path)) -> TemplateRepository:
    """模板登记仓库依赖（名称 / 格式 / 是否全局默认）。"""
    return TemplateRepository(db_path)


def get_analysis_repository(db_path: str = Depends(get_db_path)) -> AnalysisRepository:
    """资料分析仓库依赖（来源 / 文档 / 分块 / 总结）。"""
    return AnalysisRepository(db_path)


def get_summary_deliverable_repository(
    db_path: str = Depends(get_db_path),
) -> SummaryDeliverableRepository:
    """总结 Word 交付记录仓库依赖。"""
    return SummaryDeliverableRepository(db_path)


def get_knowledge_repository(db_path: str = Depends(get_db_path)) -> KnowledgeRepository:
    """知识库仓库依赖（复用来源 / 文档 / 分块三表，只认不隶属任务的资料）。"""
    return KnowledgeRepository(db_path)


def get_embedding_repository(db_path: str = Depends(get_db_path)) -> EmbeddingRepository:
    """向量仓库依赖（`embeddings` 表的唯一写入 / 校验读取入口）。"""
    return EmbeddingRepository(db_path)


def get_settings_repository(db_path: str = Depends(get_db_path)) -> SettingsRepository:
    """应用设置仓库依赖（key-value）。"""
    return SettingsRepository(db_path)


def get_fill_task_repository(db_path: str = Depends(get_db_path)) -> FillTaskRepository:
    """填充任务记录仓库依赖（`fill_tasks` 表的唯一写入入口）。"""
    return FillTaskRepository(db_path)


def get_key_store(request: Request) -> KeyStore:
    """密钥库依赖（默认写 Windows 凭据管理器；测试注入内存替身）。"""
    return request.app.state.key_store


def get_model_client(request: Request) -> ModelClient:
    """模型客户端依赖（fake 注入点 1）。"""
    return request.app.state.model_client


def get_model_client_factory(request: Request) -> ProviderModelClientFactory:
    """按 provider 配置构造模型客户端的工厂依赖（连接测试使用）。"""
    return request.app.state.model_client_factory


def get_tiered_model_client(request: Request) -> TieredModelClient:
    """按档位解析模型客户端的依赖（资料分析总结走 turbo 档）。"""
    return request.app.state.tiered_model_client


def get_url_fetcher(request: Request) -> UrlFetcher:
    """URL 抓取器依赖（fake 注入点 2）。"""
    return request.app.state.url_fetcher


def get_embedding_client(request: Request) -> EmbeddingClient:
    """嵌入客户端依赖（fake 注入点 3）。

    生产默认是按环境变量构造的百炼客户端；测试注入确定性假向量，
    **绝不让普通测试真的调外部嵌入服务**。
    """
    return request.app.state.embedding_client


def get_retrieval_service(
    request: Request,
    db_path: str = Depends(get_db_path),
) -> RetrievalService:
    """知识库检索服务依赖（工单 21 / 23）。

    每次请求构造一个：它无状态、只持有库路径与嵌入客户端，构造代价可忽略。
    为什么不缓存到 `app.state`：缓存会让「换嵌入模型后重建索引」这类操作需要额外
    的失效逻辑，而这层本来就没有值得省的初始化成本。

    嵌入客户端从 `request.app.state` 直接取（与 `get_embedding_client` 同一个来源），
    这样本函数只需要一个 `Depends`，不必为第二个依赖再写一次默认参数。
    """
    return RetrievalService(
        db_path=db_path, embedding_client=request.app.state.embedding_client
    )


# Annotated 别名：路由以类型标注声明依赖，避免在参数默认值里调用 Depends。
TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]
ProviderRepositoryDep = Annotated[ProviderRepository, Depends(get_provider_repository)]
MessageRepositoryDep = Annotated[MessageRepository, Depends(get_message_repository)]
PlanRepositoryDep = Annotated[PlanRepository, Depends(get_plan_repository)]
OpenItemRepositoryDep = Annotated[OpenItemRepository, Depends(get_open_item_repository)]
PlanRevisionRepositoryDep = Annotated[
    PlanRevisionRepository, Depends(get_plan_revision_repository)
]
PlanSectionRepositoryDep = Annotated[
    PlanSectionRepository, Depends(get_plan_section_repository)
]
GenerationRepositoryDep = Annotated[
    GenerationRepository, Depends(get_generation_repository)
]
FillTaskRepositoryDep = Annotated[FillTaskRepository, Depends(get_fill_task_repository)]
TemplateRepositoryDep = Annotated[TemplateRepository, Depends(get_template_repository)]
AnalysisRepositoryDep = Annotated[AnalysisRepository, Depends(get_analysis_repository)]
SummaryDeliverableRepositoryDep = Annotated[
    SummaryDeliverableRepository, Depends(get_summary_deliverable_repository)
]
KnowledgeRepositoryDep = Annotated[KnowledgeRepository, Depends(get_knowledge_repository)]
EmbeddingRepositoryDep = Annotated[EmbeddingRepository, Depends(get_embedding_repository)]
SettingsRepositoryDep = Annotated[SettingsRepository, Depends(get_settings_repository)]
DataDirDep = Annotated[str, Depends(get_data_dir)]
TemplatesDirDep = Annotated[str, Depends(get_templates_dir)]
KeyStoreDep = Annotated[KeyStore, Depends(get_key_store)]
ModelClientDep = Annotated[ModelClient, Depends(get_model_client)]
ModelClientFactoryDep = Annotated[ProviderModelClientFactory, Depends(get_model_client_factory)]
TieredModelClientDep = Annotated[TieredModelClient, Depends(get_tiered_model_client)]
UrlFetcherDep = Annotated[UrlFetcher, Depends(get_url_fetcher)]
EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]
RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]
