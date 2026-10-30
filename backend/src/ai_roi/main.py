"""FastAPI 应用入口。

启动：
    uvicorn ai_roi.main:app --reload --port 8000

响应统一为 `{code, message, data}`；Decimal 一律以字符串出入（架构 §3.4），
因此使用 ORJSONResponse 时不会出现 float 精度损失。
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ai_roi.interfaces.api.router import api_router
from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION
from ai_roi.shared.config import settings
from ai_roi.interfaces.api.errors import register_exception_handlers
from ai_roi.shared.logging import configure_logging
from ai_roi.infrastructure.db.session import dispose_engine
from ai_roi.infrastructure.redis.client import close_redis
from ai_roi.infrastructure.scheduler import get_scheduler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动日志 + 基准采集调度 + 关闭时释放连接池与 Redis。"""
    configure_logging()
    logger.info(
        "app.startup",
        app=settings.APP_NAME,
        env=settings.APP_ENV,
        engine_version=ENGINE_VERSION,
        formula_spec_version=FORMULA_SPEC_VERSION,
        currency=settings.DEFAULT_CURRENCY,
        taxed=settings.DEFAULT_TAXED,
        redis=bool(settings.REDIS_URL),
    )
    scheduler = get_scheduler()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await dispose_engine()
        await close_redis()
        logger.info("app.shutdown")


app = FastAPI(
    title="AI 算力投资 ROI 测算平台 API",
    description=(
        "P0（MVP）后端：三方案对比与临界规模、每百万 token 成本推导、"
        "投资财务指标（TCO/ROI/NPV/IRR/回本/现金流）、敏感性与情景分析。\n\n"
        "口径：CNY 本位币、税前、利用率 U = 有效负载 / 满负荷算力。"
    ),
    version=ENGINE_VERSION,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.TRUSTED_HOSTS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Process-Time-Ms"],
)


@app.middleware("http")
async def request_context_middleware(
    request: Request, call_next: Callable[[Request], object]
) -> Response:
    """注入请求 id、记录耗时（用于 ≤2s 计算响应的 SLO 观测）。"""
    request_id = request.headers.get("x-request-id", uuid.uuid4().hex[:16])
    started = time.perf_counter()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    try:
        response: Response = await call_next(request)  # type: ignore[misc]
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("http.request", method=request.method, elapsed_ms=elapsed_ms)
        structlog.contextvars.clear_contextvars()
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    return response


register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    """根路径指引。"""
    return {
        "code": "OK",
        "message": "AI 算力投资 ROI 测算平台 API",
        "data": {"docs": "/docs", "api": settings.API_V1_PREFIX, "health": "/api/v1/healthz"},
    }
