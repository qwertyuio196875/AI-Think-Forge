"""应用工厂与 ASGI 入口。

- `create_app(db_path=...)` 构建应用，库路径可配置（测试注入临时库）。
- 启动 lifespan 幂等建表（「应用启动时建表幂等」）+ 首次播种默认模型配置。
- fake 注入点的默认实例挂在 `app.state`，测试可经 dependency_overrides 替换。
- 若 `frontend/dist` 存在，则由后端静态托管工作台（一条启动脚本的口径）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.router import api_router
from app.db.database import init_db
from app.db.seed import seed_default_providers
from app.providers.key_store import KeyringKeyStore
from app.providers.model_client import UnconfiguredModelClient
from app.providers.openai_client import HttpModelClientFactory
from app.providers.url_fetcher import UnconfiguredUrlFetcher


def _resolve_db_path(db_path: str | Path | None) -> str:
    """优先级：显式参数 > 环境变量 > 默认 data/ 路径。"""
    if db_path is not None:
        return str(db_path)
    env_db_path = os.environ.get(config.DB_PATH_ENV_VAR)
    if env_db_path:
        return env_db_path
    return str(config.DEFAULT_DB_PATH)


def create_app(db_path: str | Path | None = None, *, mount_frontend: bool = True) -> FastAPI:
    """构建 FastAPI 应用。

    `mount_frontend=False` 供测试跳过静态托管：`frontend/dist` 是否已构建不应
    影响测试（挂载在 "/" 会遮蔽测试期追加的路由）。
    """
    resolved_db_path = _resolve_db_path(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(app.state.db_path)
        seed_default_providers(app.state.db_path)
        yield

    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)

    # 仅开发用：放行本机 Vite 开发源（前端不代理，浏览器跨源直连）。
    # 生产同源托管 dist 时该中间件不生效于同源请求，且白名单固定、不用通配来源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.DEV_CORS_ORIGINS),
        allow_methods=list(config.DEV_CORS_METHODS),
        allow_headers=list(config.DEV_CORS_HEADERS),
    )

    app.state.db_path = resolved_db_path
    app.state.model_client = UnconfiguredModelClient()
    app.state.model_client_factory = HttpModelClientFactory()
    app.state.key_store = KeyringKeyStore()
    app.state.url_fetcher = UnconfiguredUrlFetcher()

    app.include_router(api_router, prefix=config.API_PREFIX)

    # API 路由注册在前；静态托管挂在 "/" 兜底，仅当前端构建产物存在时启用。
    if mount_frontend and config.FRONTEND_DIST_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(config.FRONTEND_DIST_DIR), html=True),
            name="frontend",
        )

    return app


# uvicorn 入口：`uvicorn app.main:app`
app = create_app()
