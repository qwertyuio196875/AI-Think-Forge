"""FastAPI 依赖注入位置。

业务依赖（任务仓库、模型配置仓库、密钥库、模型客户端、URL 抓取器）集中在此
声明，测试用 `app.dependency_overrides[<函数>]` 替换即可注入替身。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.db.message_repository import MessageRepository
from app.db.open_item_repository import OpenItemRepository
from app.db.plan_repository import PlanRepository
from app.db.plan_revision_repository import PlanRevisionRepository
from app.db.provider_repository import ProviderRepository
from app.db.task_repository import TaskRepository
from app.providers.key_store import KeyStore
from app.providers.model_client import ModelClient, ProviderModelClientFactory
from app.providers.url_fetcher import UrlFetcher


def get_db_path(request: Request) -> str:
    """当前应用的 SQLite 库路径（由 create_app 写入 app.state）。"""
    return request.app.state.db_path


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


def get_key_store(request: Request) -> KeyStore:
    """密钥库依赖（默认写 Windows 凭据管理器；测试注入内存替身）。"""
    return request.app.state.key_store


def get_model_client(request: Request) -> ModelClient:
    """模型客户端依赖（fake 注入点 1）。"""
    return request.app.state.model_client


def get_model_client_factory(request: Request) -> ProviderModelClientFactory:
    """按 provider 配置构造模型客户端的工厂依赖（连接测试使用）。"""
    return request.app.state.model_client_factory


def get_url_fetcher(request: Request) -> UrlFetcher:
    """URL 抓取器依赖（fake 注入点 2）。"""
    return request.app.state.url_fetcher


# Annotated 别名：路由以类型标注声明依赖，避免在参数默认值里调用 Depends。
TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]
ProviderRepositoryDep = Annotated[ProviderRepository, Depends(get_provider_repository)]
MessageRepositoryDep = Annotated[MessageRepository, Depends(get_message_repository)]
PlanRepositoryDep = Annotated[PlanRepository, Depends(get_plan_repository)]
OpenItemRepositoryDep = Annotated[OpenItemRepository, Depends(get_open_item_repository)]
PlanRevisionRepositoryDep = Annotated[
    PlanRevisionRepository, Depends(get_plan_revision_repository)
]
KeyStoreDep = Annotated[KeyStore, Depends(get_key_store)]
ModelClientDep = Annotated[ModelClient, Depends(get_model_client)]
ModelClientFactoryDep = Annotated[ProviderModelClientFactory, Depends(get_model_client_factory)]
UrlFetcherDep = Annotated[UrlFetcher, Depends(get_url_fetcher)]
