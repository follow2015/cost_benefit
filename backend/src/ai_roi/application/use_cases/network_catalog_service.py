"""组网配套目录（配件库）服务：平台内置 + 租户自建的 CRUD 与审计。

价格来源策略：引擎默认用 `supporting_cost.py` 内置常量；本表有条目时（平台内置
或租户覆盖）优先用库内价格——`resolve_prices` 返回类别 → 单价的覆盖字典，供引擎
`estimate_network/estimate_storage` 按 `category+code` 覆盖默认值。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_roi.application.ports import NetworkCatalogRepository, UnitOfWork
from ai_roi.domain.errors import NotFoundError, PermissionDeniedError


class NetworkCatalogService:
    """配件目录服务（编排 + 业务守卫；持久化经 UoW 端口）。"""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self._s = uow.session
        self.repo: NetworkCatalogRepository = uow.catalog

    async def list(self, tenant_id: int) -> List[Any]:
        """平台内置 + 本租户自建（租户覆盖排前）。"""
        return await self.repo.list(tenant_id)

    async def resolve_prices(self, tenant_id: Optional[int]) -> Dict[str, Dict[str, Any]]:
        """类别 → 价格/规格覆盖。平台内置为底，租户自建覆盖平台内置。

        返回键 = category（如 `compute_switch_ib`）；值 = 覆盖字典：
        - `price_cny`：单价（字符串）；
        - `spec`：规格（JSONB，含 ports/speed 等，驱动拓扑推导）。
        同类别多 code 时取「最后一条 active」为有效（租户条目后写覆盖平台内置）。
        """
        return await self.repo.resolve_prices(tenant_id)

    async def create(
        self,
        tenant_id: int,
        payload: Dict[str, Any],
        is_super: bool = False,
    ) -> Any:
        """新增配件条目；`is_builtin=True` 需超管。"""
        if payload.get("is_builtin") and not is_super:
            raise PermissionDeniedError(
                "平台内置配件仅平台超级管理员可维护，请改为创建本租户条目",
                {"required": "is_super"},
            )
        tenant = None if payload.get("is_builtin") else tenant_id
        if tenant is None:
            await self._s.execute(text("SET LOCAL app.is_super = 'on';"))
        return await self.repo.create_row(
            tenant_id=tenant,
            category=payload["category"],
            code=payload["code"],
            name=payload["name"],
            price_cny=payload["price_cny"],
            unit=payload.get("unit", "台"),
            spec=payload.get("spec") or {},
            source=payload.get("source") or "",
            as_of=date.today(),
            version=1,
            is_active=payload.get("is_active", True),
        )

    async def update(
        self,
        tenant_id: int,
        row_id: int,
        payload: Dict[str, Any],
        is_super: bool = False,
    ) -> Any:
        """更新配件条目（仅提交字段生效，版本自增）。"""
        row = await self._get_owned(tenant_id, row_id, is_super)
        if row.tenant_id is None and not is_super:
            raise PermissionDeniedError("平台内置配件仅超管可改", {"required": "is_super"})
        if row.tenant_id is None:
            await self._s.execute(text("SET LOCAL app.is_super = 'on';"))
        for key in ("name", "price_cny", "unit", "spec", "source", "is_active"):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        row.version = (row.version or 1) + 1
        await self._s.flush()
        return row

    async def delete(
        self, tenant_id: int, row_id: int, is_super: bool = False
    ) -> Dict[str, Any]:
        """删除配件条目（软删）。"""
        row = await self._get_owned(tenant_id, row_id, is_super)
        if row.tenant_id is None and not is_super:
            raise PermissionDeniedError("平台内置配件仅超管可删", {"required": "is_super"})
        if row.tenant_id is None:
            await self._s.execute(text("SET LOCAL app.is_super = 'on';"))
        summary = {"category": row.category, "code": row.code, "name": row.name}
        await self._s.delete(row)
        await self._s.flush()
        return summary

    async def _get_owned(
        self, tenant_id: int, row_id: int, is_super: bool = False
    ) -> Any:
        row = await self.repo.get_by_id(row_id)
        if row is None:
            raise NotFoundError(f"配件条目 {row_id} 不存在")
        if row.tenant_id is not None and row.tenant_id != tenant_id:
            raise NotFoundError(f"配件条目 {row_id} 不存在")
        return row
