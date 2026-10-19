"""FastAPI 依赖注入位置。

业务依赖（任务仓库、模型客户端、URL 抓取器）集中在此声明，测试用
`app.dependency_overrides[<函数>]` 替换即可注入替身。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.db.task_repository import TaskRepository
from app.providers.model_client import ModelClient
from app.providers.url_fetcher import UrlFetcher


def get_db_path(request: Request) -> str:
    """当前应用的 SQLite 库路径（由 create_app 写入 app.state）。"""
    return request.app.state.db_path


def get_task_repository(db_path: str = Depends(get_db_path)) -> TaskRepository:
    """任务仓库依赖。"""
    return TaskRepository(db_path)


def get_model_client(request: Request) -> ModelClient:
    """模型客户端依赖（fake 注入点 1）。"""
    return request.app.state.model_client


def get_url_fetcher(request: Request) -> UrlFetcher:
    """URL 抓取器依赖（fake 注入点 2）。"""
    return request.app.state.url_fetcher


# Annotated 别名：路由以类型标注声明依赖，避免在参数默认值里调用 Depends。
TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]
ModelClientDep = Annotated[ModelClient, Depends(get_model_client)]
UrlFetcherDep = Annotated[UrlFetcher, Depends(get_url_fetcher)]
