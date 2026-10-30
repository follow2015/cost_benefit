"""组网配套目录（配件库）仓储：平台内置 + 租户自建的查询。

写入路径（create/update/delete）保留在应用层服务中：它们混合了业务守卫
（超管权限、越权等价于不存在）与 `SET LOCAL app.is_super` 的 RLS 提升，
属于用例编排而非单纯持久化。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.infrastructure.db.models.network_catalog import NetworkCatalogItem


class NetworkCatalogRepository:
    """配件目录查询仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, tenant_id: int) -> List[NetworkCatalogItem]:
        """平台内置 + 本租户自建（租户覆盖排前）。"""
        rows = (
            await self.session.execute(
                select(NetworkCatalogItem)
                .where(
                    NetworkCatalogItem.tenant_id.is_(None)
                    | (NetworkCatalogItem.tenant_id == tenant_id)
                )
                .order_by(NetworkCatalogItem.category, NetworkCatalogItem.code)
            )
        ).scalars().all()
        return list(rows)

    async def resolve_prices(
        self, tenant_id: Optional[int]
    ) -> Dict[str, Dict[str, Any]]:
        """类别 → 价格/规格覆盖。平台内置为底，租户自建覆盖平台内置。

        返回键 = category（如 `compute_switch_ib`）；值 = 覆盖字典：
        - `price_cny`：单价（字符串）；
        - `spec`：规格（JSONB，含 ports/speed 等，驱动拓扑推导）。
        同类别多 code 时取「最后一条 active」为有效（租户条目后写覆盖平台内置）。
        """
        conds = [NetworkCatalogItem.is_active.is_(True)]
        if tenant_id is not None:
            conds.append(
                NetworkCatalogItem.tenant_id.is_(None)
                | (NetworkCatalogItem.tenant_id == tenant_id)
            )
        else:
            conds.append(NetworkCatalogItem.tenant_id.is_(None))
        rows = (
            await self.session.execute(
                select(NetworkCatalogItem)
                .where(*conds)
                .order_by(NetworkCatalogItem.tenant_id.is_(None).desc(), NetworkCatalogItem.id)
            )
        ).scalars().all()
        prices: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            prices[row.category] = {"price_cny": str(row.price_cny), "spec": row.spec or {}}
        return prices

    async def get_by_id(self, row_id: int) -> Optional[NetworkCatalogItem]:
        """按主键读取（不含租户过滤，越权判断由用例负责）。"""
        row = (
            await self.session.execute(
                select(NetworkCatalogItem).where(NetworkCatalogItem.id == row_id)
            )
        ).scalar_one_or_none()
        return row

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
        as_of: date,
        version: int,
        is_active: bool,
    ) -> NetworkCatalogItem:
        """新增一条配件目录（含默认审计列 as_of/version/is_active）。"""
        row = NetworkCatalogItem(
            tenant_id=tenant_id,
            category=category,
            code=code,
            name=name,
            price_cny=price_cny,
            unit=unit,
            spec=spec or {},
            source=source,
            as_of=as_of,
            version=version,
            is_active=is_active,
        )
        self.session.add(row)
        await self.session.flush()
        return row


def item_out(row: NetworkCatalogItem) -> Dict[str, Any]:
    """出参序列化（ORM → DTO，属接口层传输细节）。"""
    return {
        "id": row.id,
        "category": row.category,
        "code": row.code,
        "name": row.name,
        "price_cny": str(row.price_cny),
        "unit": row.unit,
        "spec": row.spec or {},
        "source": row.source or "",
        "as_of": row.as_of,
        "version": row.version or 1,
        "is_active": row.is_active,
        "is_builtin": row.tenant_id is None,
    }
