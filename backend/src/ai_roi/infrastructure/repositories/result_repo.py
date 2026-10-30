"""计算结果与现金流仓储。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.infrastructure.db.models.result import CalcResult, CashflowRowRecord


class ResultRepository:
    """计算结果仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> CalcResult:
        """写入一次计算结果。"""
        record = CalcResult(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            created_by=created_by,
            params=params,
            payload=payload,
            kpi_summary=kpi_summary,
            params_hash=params_hash,
            engine_version=engine_version,
            formula_spec_version=formula_spec_version,
            duration_ms=duration_ms,
            client_deviation=client_deviation,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, tenant_id: int, result_id: int) -> Optional[CalcResult]:
        """按主键取结果。"""
        result = await self.session.execute(
            select(CalcResult).where(
                CalcResult.id == result_id, CalcResult.tenant_id == tenant_id
            )
        )
        return result.unique().scalar_one_or_none()

    async def latest_for_scenario(
        self, tenant_id: int, scenario_id: int
    ) -> Optional[CalcResult]:
        """取方案最近一次结果。"""
        result = await self.session.execute(
            select(CalcResult)
            .where(
                CalcResult.tenant_id == tenant_id, CalcResult.scenario_id == scenario_id
            )
            .order_by(CalcResult.id.desc())
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def latest_for_scenarios(
        self, tenant_id: int, scenario_ids: Sequence[int]
    ) -> Dict[int, CalcResult]:
        """批量取多个方案的最近结果（列表页 KPI 摘要）。

        使用窗口函数 DISTINCT ON 语义的等价写法：先按 (scenario_id, id desc) 排序，
        Python 侧取每个 scenario 的首条，避免为 P0 引入复杂 SQL。
        """
        if not scenario_ids:
            return {}
        result = await self.session.execute(
            select(CalcResult)
            .where(
                CalcResult.tenant_id == tenant_id,
                CalcResult.scenario_id.in_(list(scenario_ids)),
            )
            .order_by(CalcResult.scenario_id, CalcResult.id.desc())
        )
        latest: Dict[int, CalcResult] = {}
        for record in result.unique().scalars().all():
            if record.scenario_id is not None and record.scenario_id not in latest:
                latest[record.scenario_id] = record
        return latest

    async def find_by_hash(
        self, tenant_id: int, params_hash: str, engine_version: str
    ) -> Optional[CalcResult]:
        """按参数指纹命中缓存结果（同引擎版本才可复用）。"""
        if not params_hash:
            return None
        result = await self.session.execute(
            select(CalcResult)
            .where(
                CalcResult.tenant_id == tenant_id,
                CalcResult.params_hash == params_hash,
                CalcResult.engine_version == engine_version,
            )
            .order_by(CalcResult.id.desc())
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def list_for_scenario(
        self, tenant_id: int, scenario_id: int, limit: int = 20
    ) -> List[CalcResult]:
        """列出方案的历史结果。"""
        result = await self.session.execute(
            select(CalcResult)
            .where(
                CalcResult.tenant_id == tenant_id, CalcResult.scenario_id == scenario_id
            )
            .order_by(CalcResult.id.desc())
            .limit(limit)
        )
        return list(result.unique().scalars().all())


class CashflowRepository:
    """现金流明细仓储（分区表）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_insert(
        self,
        tenant_id: int,
        result_id: int,
        rows: List[Dict[str, Any]],
        plan: str = "A",
    ) -> int:
        """批量写入现金流行。

        Args:
            rows: 每项形如 `{"period": 0, "revenue": Decimal, ...}`（来自
                `engine._cashflow_dict`，Decimal 原样传入，由 asyncpg 映射到 numeric）。

        Returns:
            写入行数。
        """
        if not rows:
            return 0
        records: List[CashflowRowRecord] = []
        for row in rows:
            records.append(
                CashflowRowRecord(
                    tenant_id=tenant_id,
                    result_id=result_id,
                    period=int(row.get("period", 0)),
                    plan=plan,
                    revenue=_num(row.get("revenue")),
                    opex_cash=_num(row.get("opex_cash")),
                    depreciation=_num(row.get("depreciation")),
                    ebit=_num(row.get("ebt")),
                    tax=_num(row.get("tax")),
                    capex=_num(row.get("capex")),
                    net_cf=_num(row.get("net_cf")),
                    discounted_cf=_num(row.get("discounted_cf")),
                    cum_net_cf=_num(row.get("cum_cf")),
                    cum_discounted_cf=_num(row.get("cum_discounted_cf")),
                )
            )
        self.session.add_all(records)
        await self.session.flush()
        return len(records)

    async def list_for_result(
        self, tenant_id: int, result_id: int, plan: str = "A"
    ) -> List[CashflowRowRecord]:
        """读取结果的现金流明细。"""
        result = await self.session.execute(
            select(CashflowRowRecord)
            .where(
                CashflowRowRecord.tenant_id == tenant_id,
                CashflowRowRecord.result_id == result_id,
                CashflowRowRecord.plan == plan,
            )
            .order_by(CashflowRowRecord.period)
        )
        return list(result.unique().scalars().all())

    async def delete_for_result(self, tenant_id: int, result_id: int) -> None:
        """清理结果的现金流明细。"""
        await self.session.execute(
            delete(CashflowRowRecord).where(
                CashflowRowRecord.tenant_id == tenant_id,
                CashflowRowRecord.result_id == result_id,
            )
        )


def _num(value: Any) -> Decimal:
    """把结果载荷中的数值安全转 Decimal（None → 0）。"""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
