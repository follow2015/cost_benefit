"""统一错误体系与响应包装。

统一响应：`{code, message, data}`；错误响应额外带 `error_code`（架构 §5）。

与领域层的关系：`ai_roi.domain.errors` 定义领域语义错误；本模块的 AppError 体系
是其 HTTP 传输映射（多继承同一领域异常类，保证领域抛出的异常被同一处理器捕获）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai_roi.domain.errors import (
    CalculationError as DomainCalculationError,
)
from ai_roi.domain.errors import (
    DomainError,
    NotFoundError as DomainNotFoundError,
    PermissionDeniedError as DomainPermissionDeniedError,
    UnauthorizedError as DomainUnauthorizedError,
    ValidationFailedError as DomainValidationFailedError,
)
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "APP_ERROR"

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.detail: Dict[str, Any] = detail or {}


class NotFoundError(AppError, DomainNotFoundError):
    """资源不存在。"""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class PermissionDeniedError(AppError, DomainPermissionDeniedError):
    """权限不足 / 越权访问。"""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "PERMISSION_DENIED"


class UnauthorizedError(AppError, DomainUnauthorizedError):
    """未认证或 token 失效。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"


class ValidationFailedError(AppError, DomainValidationFailedError):
    """参数校验失败（含跨参数一致性）。"""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_FAILED"


class CalculationError(AppError, DomainCalculationError):
    """计算不可行（如盈亏平衡分母 ≤0、IRR 无解）。"""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "CALCULATION_ERROR"


class RateLimitedError(AppError):
    """登录失败次数超限（防暴力破解；仅计失败，成功不计入）。"""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMITED"


def error_payload(error_code: str, message: str, detail: Dict[str, Any]) -> Dict[str, Any]:
    """构造错误响应体。"""
    return {
        "code": error_code,
        "error_code": error_code,
        "message": message,
        "data": detail or None,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.error_code, exc.message, exc.detail),
        )

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        error_code = getattr(exc, "error_code", type(exc).__name__.upper())
        return JSONResponse(
            status_code=exc.default_status_code,
            content=error_payload(error_code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload("VALIDATION_FAILED", "请求参数校验失败", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(f"HTTP_{exc.status_code}", str(exc.detail), {}),
        )
