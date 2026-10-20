"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter

from app import config

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """存活探针：前端在启动时用它判断后端是否就绪。"""
    return {"status": "ok", "app": config.APP_NAME, "version": config.APP_VERSION}
