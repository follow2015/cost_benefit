"""聚合路由。"""

from __future__ import annotations

from fastapi import APIRouter

from ai_roi.interfaces.api.v1 import (
    auth,
    audit,
    benchmarks,
    calc,
    formulas,
    health,
    imports,
    network_catalog,
    reports,
    scenarios,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(scenarios.router)
api_router.include_router(calc.router)
api_router.include_router(benchmarks.router)
api_router.include_router(network_catalog.router)
api_router.include_router(reports.router)
api_router.include_router(imports.router)
api_router.include_router(audit.router)
api_router.include_router(formulas.router)

__all__ = ["api_router"]
