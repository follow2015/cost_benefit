"""领域错误（纯 Python，无框架依赖）。

分工：
- 本模块定义**领域语义**错误，只携带 `message` 与结构化 `detail`；
- HTTP 状态码映射属于接口层职责（`ai_roi/interfaces/api/errors.py` 中的 AppError 体系
  多继承本模块对应异常，保证领域抛出与接口抛出是同一个类）；
- 应用层/基础设施层抛出的技术错误不得穿透到接口层（interfaces 统一兜底）。

`error_code` 是稳定的对外契约字符串：即使异常未经接口层包装而直达处理器，
响应体中的 `error_code` 也与包装版完全一致（如 `UNAUTHORIZED`）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class DomainError(Exception):
    """领域异常基类。"""

    default_status_code: int = 400

    error_code: str = "APP_ERROR"

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Dict[str, Any] = detail or {}


class ValidationFailedError(DomainError):
    """参数校验未通过（含跨参数一致性）。detail 携带 errors/warnings 列表。"""

    default_status_code = 422
    error_code = "VALIDATION_FAILED"


class CalculationError(DomainError):
    """计算不可行（盈亏平衡分母 ≤ 0、IRR 无解等）。"""

    default_status_code = 400
    error_code = "CALCULATION_ERROR"


class UnauthorizedError(DomainError):
    """未认证 / 凭证无效或过期（登录、刷新、鉴权链路）。"""

    default_status_code = 401
    error_code = "UNAUTHORIZED"


class NotFoundError(DomainError):
    """资源不存在或无权访问（不泄露存在性）。"""

    default_status_code = 404
    error_code = "NOT_FOUND"


class PermissionDeniedError(DomainError):
    """已认证但权限不足。"""

    default_status_code = 403
    error_code = "PERMISSION_DENIED"


class UpstreamUnavailableError(DomainError):
    """外部数据源不可用（超时、5xx、结构变更）。

    语义是「上游暂时拿不到」，与「参数错误」区分开：接口层映射 502，
    调用方据此提示「沿用上次数据」而不是让用户去改参数。
    """

    default_status_code = 502
    error_code = "UPSTREAM_UNAVAILABLE"
