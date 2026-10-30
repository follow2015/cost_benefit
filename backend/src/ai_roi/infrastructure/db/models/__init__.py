"""ORM 模型汇总（供 Alembic 的 target_metadata 与仓储层导入）。"""

from ai_roi.infrastructure.db.models.audit import AuditLog
from ai_roi.infrastructure.db.models.benchmark import (
    BenchmarkApiPrice,
    BenchmarkCloudPrice,
    BenchmarkGpu,
    BenchmarkModel,
)
from ai_roi.infrastructure.db.models.inferencex_sync import InferencexSyncRun
from ai_roi.infrastructure.db.models.network_catalog import NetworkCatalogItem
from ai_roi.infrastructure.db.models.result import CalcResult, CashflowRowRecord
from ai_roi.infrastructure.db.models.scenario import Scenario, ScenarioSnapshot
from ai_roi.infrastructure.db.models.tenant import Tenant, User

__all__ = [
    "AuditLog",
    "BenchmarkApiPrice",
    "BenchmarkCloudPrice",
    "BenchmarkGpu",
    "BenchmarkModel",
    "InferencexSyncRun",
    "NetworkCatalogItem",
    "CalcResult",
    "CashflowRowRecord",
    "Scenario",
    "ScenarioSnapshot",
    "Tenant",
    "User",
]
