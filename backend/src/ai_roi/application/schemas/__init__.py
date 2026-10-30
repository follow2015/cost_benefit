"""Pydantic DTO（请求/响应契约）。字段名与前端 `src/types/*.ts` 严格一一对应。"""

from ai_roi.application.schemas.auth import LoginRequest, TokenResponse, UserOut
from ai_roi.application.schemas.benchmark import (
    ApiPriceOut,
    BenchmarkBundleOut,
    CloudPriceOut,
    GpuOut,
    ModelOut,
)
from ai_roi.application.schemas.calc import (
    CalcRequest,
    CalcResultOut,
    CalcSummaryOut,
    CompareRequest,
    CompareResponse,
)
from ai_roi.application.schemas.common import ApiResponse, PageMeta, PageResponse
from ai_roi.application.schemas.scenario import (
    ScenarioCreate,
    ScenarioDetailOut,
    ScenarioListItemOut,
    ScenarioUpdate,
)

__all__ = [
    "ApiPriceOut",
    "ApiResponse",
    "BenchmarkBundleOut",
    "CalcRequest",
    "CalcResultOut",
    "CalcSummaryOut",
    "CloudPriceOut",
    "CompareRequest",
    "CompareResponse",
    "GpuOut",
    "LoginRequest",
    "ModelOut",
    "PageMeta",
    "PageResponse",
    "ScenarioCreate",
    "ScenarioDetailOut",
    "ScenarioListItemOut",
    "ScenarioUpdate",
    "TokenResponse",
    "UserOut",
]
