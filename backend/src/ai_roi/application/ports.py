"""应用层端口（Ports）：应用层依赖的抽象，由基础设施层实现。

六边形规则：
- 本模块只放 `Protocol` 与少量纯数据结构，**不得** import 基础设施/接口层；
- 仓储协议返回类型用 `Any`（ ORM 实体属于基础设施，应用层不感知具体模型），
  方法签名即契约；基础设施的 SQLAlchemy 仓储结构性地满足这些协议；
- 应用层（用例）只依赖本模块 + 领域层 + shared，依赖方向永远向内。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from ai_roi.application.schemas.benchmark import (
    ApiPriceOut,
    CloudPriceOut,
    GpuOut,
    ModelOut,
)


@runtime_checkable
class UnitOfWork(Protocol):
    """工作单元：一个用例 = 一个事务 + 一套仓储。

    基础设施的 `SqlAlchemyUnitOfWork` 是唯一实现：进入时开事务并注入 RLS
    上下文，退出时提交/回滚并归还连接。路由与服务均不得自行 commit。
    """

    session: Any

    results: "ResultRepository"
    cashflows: "CashflowRepository"
    scenarios: "ScenarioRepository"
    snapshots: "SnapshotRepository"
    users: "UserRepository"
    audit: "AuditRepository"
    benchmarks: "BenchmarkRepository"
    catalog: "NetworkCatalogRepository"
    inferencex_runs: "InferencexSyncRepository"

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...


@runtime_checkable
class ResultRepository(Protocol):
    async def create(
        self,
        tenant_id: int,
        scenario_id: Optional[int],
        scenario_version: int,
        created_by: Optional[int],
        params: Dict[str, Any],
        payload: Dict[str, Any],
        kpi_summary: Dict[str, Any],
        params_hash: str,
        engine_version: str,
        formula_spec_version: str,
        duration_ms: Optional[int] = None,
        client_deviation: Optional[str] = None,
    ) -> Any: ...

    async def get(self, tenant_id: int, result_id: int) -> Optional[Any]: ...

    async def latest_for_scenario(
        self, tenant_id: int, scenario_id: int
    ) -> Optional[Any]: ...

    async def latest_for_scenarios(
        self, tenant_id: int, scenario_ids: Sequence[int]
    ) -> Dict[int, Any]: ...

    async def find_by_hash(
        self, tenant_id: int, params_hash: str, engine_version: str
    ) -> Optional[Any]: ...

    async def list_for_scenario(
        self, tenant_id: int, scenario_id: int, limit: int = 20
    ) -> List[Any]: ...


@runtime_checkable
class CashflowRepository(Protocol):
    async def bulk_insert(
        self,
        tenant_id: int,
        result_id: int,
        rows: List[Dict[str, Any]],
        plan: str = "A",
    ) -> int: ...

    async def list_for_result(
        self, tenant_id: int, result_id: int, plan: str = "A"
    ) -> List[Any]: ...

    async def delete_for_result(self, tenant_id: int, result_id: int) -> None: ...


@runtime_checkable
class ScenarioRepository(Protocol):
    async def get(self, tenant_id: int, scenario_id: int) -> Optional[Any]: ...

    async def get_many(self, tenant_id: int, ids: Sequence[int]) -> List[Any]: ...

    async def list_page(
        self,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        status: Optional[str] = None,
    ) -> Any: ...

    async def create(
        self,
        tenant_id: int,
        created_by: Optional[int],
        name: str,
        description: str,
        params: Dict[str, Any],
        conventions: Dict[str, Any],
        tags: List[str],
        is_template: bool,
    ) -> Any: ...

    async def delete(self, tenant_id: int, scenario_id: int) -> None: ...


@runtime_checkable
class SnapshotRepository(Protocol):
    async def create(
        self,
        tenant_id: int,
        scenario_id: int,
        version: int,
        params: Dict[str, Any],
        conventions: Dict[str, Any],
        diff: Dict[str, Any],
        created_by: Optional[int],
        note: Optional[str] = None,
    ) -> Any: ...

    async def list_by_scenario(
        self, tenant_id: int, scenario_id: int, limit: int = 50
    ) -> List[Any]: ...


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: int) -> Optional[Any]: ...

    async def find_by_email(
        self, email: str, tenant_slug: Optional[str] = None
    ) -> List[Any]: ...

    async def list_by_tenant(self, tenant_id: int) -> List[Any]: ...

    async def create(
        self,
        tenant_id: int,
        email: str,
        password_hash: str,
        display_name: str,
        role: str,
    ) -> Any: ...

    async def touch_login(self, user_id: int) -> None: ...

    async def update(
        self, user_id: int, tenant_id: int, **fields: Any
    ) -> Optional[Any]: ...

    async def delete(self, user_id: int, tenant_id: int) -> bool: ...

    async def count_owners(self, tenant_id: int) -> int: ...


@runtime_checkable
class AuditRepository(Protocol):
    async def write(
        self,
        tenant_id: int,
        action: str,
        actor_id: Optional[int] = None,
        actor_email: str = "",
        target_type: str = "",
        target_id: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
        ip: str = "",
        user_agent: str = "",
    ) -> Any: ...

    async def list_recent(self, tenant_id: int, limit: int = 100) -> List[Any]: ...

    async def list_by_action(
        self, tenant_id: int, action: str, limit: int = 20
    ) -> List[Any]:
        """按动作类型取审计（基准库发布历史）。"""
        ...

    async def get(self, tenant_id: int, entry_id: int) -> Optional[Any]:
        """按 id 取单条审计（越权/跨租户返回 None）。"""
        ...


@runtime_checkable
class BenchmarkRepository(Protocol):
    """基准库端口：列表方法直接返回 DTO（ORM 映射属适配器逻辑）。"""

    async def list_gpus(self, tenant_id: Optional[int]) -> List[GpuOut]: ...

    async def list_models(self, tenant_id: Optional[int]) -> List[ModelOut]: ...

    async def list_cloud_prices(
        self, tenant_id: Optional[int]
    ) -> List[CloudPriceOut]: ...

    async def list_api_prices(
        self, tenant_id: Optional[int]
    ) -> List[ApiPriceOut]: ...

    async def find_model_meta(
        self, model_code: str, tenant_id: Optional[int]
    ) -> Optional[Dict[str, Any]]: ...

    async def find_builtin_model(self, code: str) -> Optional[Any]:
        """按 code 取平台内置模型行（外部采集写回的目标，含 meta 与 as_of）。"""
        ...

    async def find_builtin_gpu(self, code: str) -> Optional[Any]:
        """按 code 取平台内置 GPU 行（GPU 租赁行情采集的写回目标）。"""
        ...

    async def find_builtin_cloud(
        self, provider: str, gpu_code: str
    ) -> Optional[Any]:
        """按 (云厂商, GPU 型号) 取平台内置云租赁价行（官方价采集的写回目标）。"""
        ...

    async def get_model(
        self, tenant_id: Optional[int], model_id: int
    ) -> Optional[Any]: ...

    async def get_gpu(
        self, tenant_id: Optional[int], gpu_id: int
    ) -> Optional[Any]: ...

    async def get_by_id(
        self, kind: str, tenant_id: Optional[int], row_id: int
    ) -> Optional[Any]: ...

    async def insert(
        self, kind: str, tenant_id: Optional[int], values: Dict[str, Any]
    ) -> Any: ...

    async def apply_update(self, row: Any, values: Dict[str, Any]) -> Any: ...

    def entity_summary(self, kind: str, row: Any) -> Dict[str, Any]: ...

    async def remove(self, row: Any) -> None: ...


@runtime_checkable
class InferencexSyncRepository(Protocol):
    """外部基准采集留痕端口（平台级任务，跨租户共享只读）。"""

    async def record(self, **values: Any) -> Any: ...

    async def latest(self, *, include_skipped: bool = True) -> Optional[Any]:
        """最近一次运行（含失败/跳过）。"""
        ...

    async def latest_effective(self) -> Optional[Any]:
        """最近一次真正执行过采集的运行（跳过不算），用于周期判定。"""
        ...

    async def latest_success(self) -> Optional[Any]:
        """最近一次采集成功，用于 as_of 与下次计划时间。"""
        ...

    async def list_recent(self, limit: int = 20) -> List[Any]: ...

    async def try_lock(self, key: int) -> bool:
        """尝试获取跨进程互斥锁（PG advisory lock）；False 表示已有实例在跑。"""
        ...

    async def unlock(self, key: int) -> None: ...


@runtime_checkable
class NetworkCatalogRepository(Protocol):
    async def list(self, tenant_id: int) -> List[Any]: ...

    async def resolve_prices(
        self, tenant_id: Optional[int]
    ) -> Dict[str, Dict[str, Any]]: ...

    async def get_by_id(self, row_id: int) -> Optional[Any]: ...

    async def create_row(
        self,
        *,
        tenant_id: Optional[int],
        category: str,
        code: str,
        name: str,
        price_cny: Any,
        unit: str,
        spec: Dict[str, Any],
        source: str,
        as_of: Any,
        version: int,
        is_active: bool,
    ) -> Any: ...


@runtime_checkable
class Clock(Protocol):
    """时间来源（便于测试注入固定时钟）。"""

    def now(self) -> datetime: ...


@runtime_checkable
class TokenStore(Protocol):
    """刷新令牌黑名单（登出/轮换吊销）。"""

    async def revoke(self, jti: str, ttl_seconds: int) -> None: ...

    async def is_revoked(self, jti: str) -> bool: ...


RESULT_CACHE_DEFAULT_TTL: int = 300


@runtime_checkable
class RateLimiter(Protocol):
    """失败限流器（只统计失败，成功不计；fail-open）。

    双方法语义（先查后记）：`is_limited` 预检是否已超限，`hit` 记录一次失败。
    调用方在业务失败路径上调 `hit`，保证成功请求不计入窗口。
    """

    async def hit(self, key: str, window_seconds: int) -> int:
        """记录一次失败，返回当前窗口内累计次数。"""

    async def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        """返回 True 表示已超限（应拒绝）。"""


@runtime_checkable
class ResultCache(Protocol):
    """无状态试算结果缓存（键 = 参数指纹，值 = JSON 化载荷）。"""

    async def get(self, key: str) -> Optional[Dict[str, Any]]: ...

    async def set(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None: ...


@runtime_checkable
class SystemGateway(Protocol):
    """文件系统网关（报告落盘 / 上传暂存，应用层不直接碰路径）。"""

    def save(self, relative_path: str, data: bytes) -> str: ...

    def read(self, path: str) -> bytes: ...

    def exists(self, path: str) -> bool: ...

    def delete(self, path: str) -> None: ...


@runtime_checkable
class XlsxIO(Protocol):
    """Excel 渲染端口。"""

    def render(self, report: Dict[str, Any]) -> bytes: ...


@runtime_checkable
class PdfRenderer(Protocol):
    """PDF 渲染端口。"""

    def render(self, report: Dict[str, Any]) -> bytes: ...


__all__ = [
    "UnitOfWork",
    "ResultRepository",
    "CashflowRepository",
    "ScenarioRepository",
    "SnapshotRepository",
    "UserRepository",
    "AuditRepository",
    "BenchmarkRepository",
    "NetworkCatalogRepository",
    "Clock",
    "TokenStore",
    "RateLimiter",
    "ResultCache",
    "SystemGateway",
    "XlsxIO",
    "PdfRenderer",
    "AbstractAsyncContextManager",
    "AsyncIterator",
]
