"""仓储层：仅负责持久化，不含业务规则。租户过滤由 RLS 兜底，仓储仍显式带 tenant_id 以走索引。"""

from ai_roi.infrastructure.repositories.audit_repo import AuditRepository
from ai_roi.infrastructure.repositories.benchmark_repo import BenchmarkRepository
from ai_roi.infrastructure.repositories.result_repo import ResultRepository
from ai_roi.infrastructure.repositories.scenario_repo import ScenarioRepository
from ai_roi.infrastructure.repositories.user_repo import TenantRepository, UserRepository

__all__ = [
    "AuditRepository",
    "BenchmarkRepository",
    "ResultRepository",
    "ScenarioRepository",
    "TenantRepository",
    "UserRepository",
]
