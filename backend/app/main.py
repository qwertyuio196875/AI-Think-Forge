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
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.api.router import api_router
from app.db.database import init_db
from app.db.provider_repository import ProviderRepository
from app.db.seed import seed_default_providers
from app.providers.key_store import KeyringKeyStore
from app.providers.openai_client import HttpModelClientFactory
from app.providers.provider_backed_client import ProviderBackedModelClient
from app.providers.tiered_client import TieredModelClient
from app.providers.url_fetcher import HttpUrlFetcher


class SPAStaticFiles(StaticFiles):
    """静态托管 + SPA history 路由回退。

    前端使用 `createWebHistory`，像 `/analysis?source=1` 这样的深链在浏览器刷新
    时必须仍返回 `index.html`，由 Vue Router 接管；`/api/**` 的未知路径仍返回
    JSON 404，`/assets/**` 或带扩展名的缺失文件仍返回 404，不能被前端入口吞掉。
    """

    @staticmethod
    def _is_spa_route(path: str) -> bool:
        normalized = path.replace("\\", "/")
        last_segment = normalized.rsplit("/", 1)[-1]
        return (
            normalized not in {"api", "assets"}
            and not normalized.startswith(("api/", "assets/"))
            and "." not in last_segment
        )

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and self._is_spa_route(path):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and self._is_spa_route(path):
            return await super().get_response("index.html", scope)
        return response


def _resolve_db_path(db_path: str | Path | None) -> str:
    """优先级：显式参数 > 环境变量 > 默认 data/ 路径。"""
    if db_path is not None:
        return str(db_path)
    env_db_path = os.environ.get(config.DB_PATH_ENV_VAR)
    if env_db_path:
        return env_db_path
    return str(config.DEFAULT_DB_PATH)


def create_app(
    db_path: str | Path | None = None,
    *,
    mount_frontend: bool = True,
    data_dir: str | Path | None = None,
    templates_dir: str | Path | None = None,
) -> FastAPI:
    """构建 FastAPI 应用。

    `mount_frontend=False` 供测试跳过静态托管：`frontend/dist` 是否已构建不应
    影响测试（挂载在 "/" 会遮蔽测试期追加的路由）。
    `data_dir` / `templates_dir` 供测试指向临时目录，使成品与模板不写进仓库
    `data/`、`templates/`；生产留空即用 `app.config` 的默认白名单目录。
    """
    resolved_db_path = _resolve_db_path(db_path)
    resolved_data_dir = str(data_dir) if data_dir is not None else str(config.DATA_DIR)
    resolved_templates_dir = (
        str(templates_dir) if templates_dir is not None else str(config.TEMPLATES_DIR)
    )

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
    app.state.data_dir = resolved_data_dir
    app.state.templates_dir = resolved_templates_dir
    app.state.model_client_factory = HttpModelClientFactory()
    app.state.key_store = KeyringKeyStore()
    # 生产默认模型客户端按「当前默认 provider + 凭据管理器 + 工厂」解析真实客户端，
    # 而不是恒为未配置占位实现（否则拷问／方案／修订主链路永远调不到模型）。
    # 测试仍经 `dependency_overrides[get_model_client]` 覆盖该接缝。
    app.state.model_client = ProviderBackedModelClient(
        ProviderRepository(app.state.db_path),
        app.state.key_store,
        app.state.model_client_factory,
    )
    # 资料分析的总结流程按档位解析（turbo）；主流程仍走上面的默认 provider 客户端。
    app.state.tiered_model_client = TieredModelClient(
        ProviderRepository(app.state.db_path),
        app.state.key_store,
        app.state.model_client_factory,
    )
    # URL 抓取器（TB-9）：真实实现逐跳重新做 SSRF 校验、限超时 15s / 5MB / 3 次重定向。
    # 测试经 `dependency_overrides[get_url_fetcher]` 注入替身（全程不联网）。
    app.state.url_fetcher = HttpUrlFetcher()

    app.include_router(api_router, prefix=config.API_PREFIX)

    # API 路由注册在前；静态托管挂在 "/" 兜底，仅当前端构建产物存在时启用。
    if mount_frontend and config.FRONTEND_DIST_DIR.is_dir():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(config.FRONTEND_DIST_DIR), html=True),
            name="frontend",
        )

    return app


# uvicorn 入口：`uvicorn app.main:app`
app = create_app()
