"""工作单元（Unit of Work）：全项目唯一的事务策略。

契约见 `ai_roi.application.ports.UnitOfWork`。规则：

1. **一个请求/用例 = 一个事务**：进入时 `BEGIN` + 注入 RLS 上下文
   （`SET LOCAL` 随事务失效，杜绝连接归还池后串号）；
2. 退出时按异常情况提交/回滚，并归还连接到池；
3. 路由与服务**不得**自行 `commit`/`rollback`/`begin`——
   需要写库就在用例里 `flush`，事务边界一律交给本模块；
4. 脚本/后台任务用 `unit_of_work(...)` 异步上下文，与 HTTP 链路同一策略。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.application.ports import (
    AuditRepository,
    BenchmarkRepository,
    CashflowRepository,
    InferencexSyncRepository,
    NetworkCatalogRepository,
    ResultRepository,
    ScenarioRepository,
    SnapshotRepository,
    UserRepository,
    UnitOfWork,
)
from ai_roi.infrastructure.db.session import SessionFactory, set_tenant_context
from ai_roi.infrastructure.repositories.audit_repo import AuditRepository as _AuditRepo
from ai_roi.infrastructure.repositories.benchmark_repo import (
    BenchmarkRepository as _BenchmarkRepo,
)
from ai_roi.infrastructure.repositories.inferencex_sync_repo import (
    InferencexSyncRepository as _InferencexSyncRepo,
)
from ai_roi.infrastructure.repositories.network_catalog_repo import (
    NetworkCatalogRepository as _CatalogRepo,
)
from ai_roi.infrastructure.repositories.result_repo import (
    CashflowRepository as _CashflowRepo,
)
from ai_roi.infrastructure.repositories.result_repo import (
    ResultRepository as _ResultRepo,
)
from ai_roi.infrastructure.repositories.scenario_repo import (
    ScenarioRepository as _ScenarioRepo,
)
from ai_roi.infrastructure.repositories.scenario_repo import (
    SnapshotRepository as _SnapshotRepo,
)
from ai_roi.infrastructure.repositories.user_repo import UserRepository as _UserRepo

__all__ = ["SqlAlchemyUnitOfWork", "unit_of_work"]


class SqlAlchemyUnitOfWork:
    """SQLAlchemy 实现：事务 + RLS + 仓储装配，一次成型。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        is_super: bool = False,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._is_super = is_super
        self._tx: Any = None

    @property
    def session(self) -> AsyncSession:
        """当前事务内的会话（仓储与即席查询都用它）。"""
        return self._session

    @property
    def results(self) -> ResultRepository:
        return _ResultRepo(self._session)

    @property
    def cashflows(self) -> CashflowRepository:
        return _CashflowRepo(self._session)

    @property
    def scenarios(self) -> ScenarioRepository:
        return _ScenarioRepo(self._session)

    @property
    def snapshots(self) -> SnapshotRepository:
        return _SnapshotRepo(self._session)

    @property
    def users(self) -> UserRepository:
        return _UserRepo(self._session)

    @property
    def audit(self) -> AuditRepository:
        return _AuditRepo(self._session)

    @property
    def benchmarks(self) -> BenchmarkRepository:
        return _BenchmarkRepo(self._session)

    @property
    def catalog(self) -> NetworkCatalogRepository:
        return _CatalogRepo(self._session)

    @property
    def inferencex_runs(self) -> InferencexSyncRepository:
        return _InferencexSyncRepo(self._session)

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._tx = self._session.begin()
        await self._tx.__aenter__()
        await set_tenant_context(
            self._session,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            is_super=self._is_super,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            await self._tx.__aexit__(exc_type, exc, tb)
        finally:
            await self._session.close()


@asynccontextmanager
async def unit_of_work(
    *,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    is_super: bool = False,
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """脚本/后台任务入口：开会话 → 开事务 → 注入 RLS → 交付 UoW。"""
    async with SessionFactory() as session:
        async with SqlAlchemyUnitOfWork(
            session, tenant_id=tenant_id, user_id=user_id, is_super=is_super
        ) as uow:
            yield uow
