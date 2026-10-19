"""API 路由聚合：全部挂在 `/api` 前缀下。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    analysis,
    deck,
    deliverables,
    generations,
    grilling,
    health,
    history,
    providers,
    tasks,
    templates,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(providers.router)
api_router.include_router(tasks.router)
api_router.include_router(history.router)
api_router.include_router(grilling.router)
api_router.include_router(analysis.router)
api_router.include_router(generations.router)
api_router.include_router(deliverables.router)
api_router.include_router(templates.router)
api_router.include_router(deck.router)
