"""应用工厂与 ASGI 入口。

- `create_app(db_path=...)` 构建应用，库路径可配置（测试注入临时库）。
- 启动 lifespan 幂等建表（「应用启动时建表幂等」）。
- 两个 fake 注入点的默认实例挂在 `app.state`，测试可经 dependency_overrides 替换。
- 若 `frontend/dist` 存在，则由后端静态托管工作台（一条启动脚本的口径）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.router import api_router
from app.db.database import init_db
from app.providers.model_client import UnconfiguredModelClient
from app.providers.url_fetcher import UnconfiguredUrlFetcher


def _resolve_db_path(db_path: str | Path | None) -> str:
    """优先级：显式参数 > 环境变量 > 默认 data/ 路径。"""
    if db_path is not None:
        return str(db_path)
    env_db_path = os.environ.get(config.DB_PATH_ENV_VAR)
    if env_db_path:
        return env_db_path
    return str(config.DEFAULT_DB_PATH)


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """构建 FastAPI 应用。"""
    resolved_db_path = _resolve_db_path(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(app.state.db_path)
        yield

    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)

    app.state.db_path = resolved_db_path
    app.state.model_client = UnconfiguredModelClient()
    app.state.url_fetcher = UnconfiguredUrlFetcher()

    app.include_router(api_router, prefix=config.API_PREFIX)

    # API 路由注册在前；静态托管挂在 "/" 兜底，仅当前端构建产物存在时启用。
    if config.FRONTEND_DIST_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(config.FRONTEND_DIST_DIR), html=True),
            name="frontend",
        )

    return app


# uvicorn 入口：`uvicorn app.main:app`
app = create_app()
