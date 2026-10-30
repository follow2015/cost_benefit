"""方案与快照仓储。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.infrastructure.db.models.scenario import Scenario, ScenarioSnapshot


class ScenarioRepository:
    """方案仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: int, scenario_id: int) -> Optional[Scenario]:
        """按主键取方案（带租户条件走复合索引）。"""
        result = await self.session.execute(
            select(Scenario).where(
                Scenario.id == scenario_id, Scenario.tenant_id == tenant_id
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_many(self, tenant_id: int, ids: Sequence[int]) -> List[Scenario]:
        """批量取方案（对比页用），保持入参顺序。"""
        if not ids:
            return []
        result = await self.session.execute(
            select(Scenario).where(
                Scenario.tenant_id == tenant_id, Scenario.id.in_(list(ids))
            )
        )
        found = {item.id: item for item in result.unique().scalars().all()}
        return [found[i] for i in ids if i in found]

    def _list_stmt(
        self, tenant_id: int, keyword: str = "", status: Optional[str] = None
    ) -> Select[Tuple[Scenario]]:
        """构造列表查询。"""
        stmt = select(Scenario).where(Scenario.tenant_id == tenant_id)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(Scenario.name.ilike(pattern))
        if status:
            stmt = stmt.where(Scenario.status == status)
        return stmt

    async def list_page(
        self,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        status: Optional[str] = None,
    ) -> Tuple[List[Scenario], int]:
        """分页列出方案，返回 (items, total)。"""
        stmt = self._list_stmt(tenant_id, keyword, status)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        page_stmt = (
            stmt.order_by(Scenario.updated_at.desc(), Scenario.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(page_stmt)
        return list(result.unique().scalars().all()), total

    async def create(
        self,
        tenant_id: int,
        created_by: Optional[int],
        name: str,
        description: str,
        params: Dict[str, Any],
        conventions: Dict[str, Any],
        tags: List[str],
        is_template: bool = False,
    ) -> Scenario:
        """创建方案。"""
        scenario = Scenario(
            tenant_id=tenant_id,
            created_by=created_by,
            name=name,
            description=description,
            params=params,
            conventions=conventions,
            tags=tags,
            is_template=is_template,
        )
        self.session.add(scenario)
        await self.session.flush()
        return scenario

    async def delete(self, tenant_id: int, scenario_id: int) -> None:
        """删除方案（级联删除快照/结果）。"""
        await self.session.execute(
            delete(Scenario).where(
                Scenario.id == scenario_id, Scenario.tenant_id == tenant_id
            )
        )


class SnapshotRepository:
    """方案快照仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        tenant_id: int,
        scenario_id: int,
        version: int,
        params: Dict[str, Any],
        conventions: Dict[str, Any],
        diff: Dict[str, Any],
        created_by: Optional[int],
        note: str = "",
    ) -> ScenarioSnapshot:
        """写入快照。"""
        snapshot = ScenarioSnapshot(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            version=version,
            params=params,
            conventions=conventions,
            diff=diff,
            created_by=created_by,
            note=note,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def list_by_scenario(
        self, tenant_id: int, scenario_id: int, limit: int = 50
    ) -> List[ScenarioSnapshot]:
        """列出方案的快照历史（新→旧）。"""
        result = await self.session.execute(
            select(ScenarioSnapshot)
            .where(
                ScenarioSnapshot.tenant_id == tenant_id,
                ScenarioSnapshot.scenario_id == scenario_id,
            )
            .order_by(ScenarioSnapshot.version.desc())
            .limit(limit)
        )
        return list(result.unique().scalars().all())
