"""健康检查与元信息。"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from sqlalchemy import text

from ai_roi.domain.calc.context import (
    ENGINE_VERSION,
    FORMULA_SPEC_VERSION,
    UTILIZATION_DEF_EFFECTIVE_LOAD,
)
from ai_roi.shared.config import settings
from ai_roi.infrastructure.db.session import SessionFactory
from ai_roi.application.schemas.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=ApiResponse[Dict[str, Any]])
async def healthz() -> ApiResponse[Dict[str, Any]]:
    """存活探针（不依赖数据库）。"""
    return ApiResponse.ok(
        {
            "status": "ok",
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "engine_version": ENGINE_VERSION,
            "formula_spec_version": FORMULA_SPEC_VERSION,
        }
    )


@router.get("/readyz", response_model=ApiResponse[Dict[str, Any]])
async def readyz() -> ApiResponse[Dict[str, Any]]:
    """就绪探针（含数据库连通性）。"""
    database_ok = True
    detail = ""
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 探针需吞掉一切异常并降级上报
        database_ok = False
        detail = str(exc)[:200]
    return ApiResponse.ok(
        {"status": "ok" if database_ok else "degraded", "database": database_ok, "detail": detail}
    )


@router.get("/meta", response_model=ApiResponse[Dict[str, Any]])
async def meta() -> ApiResponse[Dict[str, Any]]:
    """全局口径元信息（前端启动时拉取并校验与本地引擎版本一致）。"""
    return ApiResponse.ok(
        {
            "engine_version": ENGINE_VERSION,
            "formula_spec_version": FORMULA_SPEC_VERSION,
            "currency": settings.DEFAULT_CURRENCY,
            "taxed": settings.DEFAULT_TAXED,
            "utilization_definition": UTILIZATION_DEF_EFFECTIVE_LOAD,
            "decimal_precision": 34,
            "decimal_rounding": "ROUND_HALF_UP",
            "client_tolerance": "0.001",
        }
    )
