"""组网配套目录（配件库）路由。

- 读取（P0）：列表返回平台内置 + 租户自建；
- 写入（P1）：POST / PUT / DELETE，需 `benchmark:write` 权限（与基准库同组权限），
  平台内置条目仅超管可维护；写操作落审计。
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from ai_roi.interfaces.api.deps import Ctx, CurrentUser, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import (
    ACTION_BENCHMARK_CREATE,
    ACTION_BENCHMARK_DELETE,
    ACTION_BENCHMARK_UPDATE,
)
from ai_roi.application.schemas.common import ApiResponse, OkData
from ai_roi.application.schemas.network_catalog import (
    NetworkCatalogItemIn,
    NetworkCatalogItemOut,
    NetworkCatalogItemUpdate,
)
from ai_roi.application.use_cases.audit_service import AuditService
from ai_roi.application.use_cases.network_catalog_service import NetworkCatalogService
from ai_roi.infrastructure.repositories.network_catalog_repo import item_out

router = APIRouter(prefix="/network-catalog", tags=["network-catalog"])

_WRITE = Depends(require_permission("benchmark:write"))


@router.get("", response_model=ApiResponse[List[NetworkCatalogItemOut]])
async def list_items(user: CurrentUser, uow: UoW) -> ApiResponse[List[NetworkCatalogItemOut]]:
    """配件目录列表（平台内置 + 租户自建）。"""
    rows = await NetworkCatalogService(uow).list(user.tenant_id)
    return ApiResponse.ok([item_out(r) for r in rows])


@router.post("", response_model=ApiResponse[NetworkCatalogItemOut], dependencies=[_WRITE])
async def create_item(
    payload: NetworkCatalogItemIn, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[NetworkCatalogItemOut]:
    """新增配件条目（is_builtin=True 需超管）。"""
    row = await NetworkCatalogService(uow).create(
        user.tenant_id, payload.model_dump(), is_super=user.is_super
    )
    await AuditService(uow).log(
        ctx,
        ACTION_BENCHMARK_CREATE,
        target_type="network_catalog",
        target_id=row.id,
        detail={"category": row.category, "code": row.code},
    )
    return ApiResponse.ok(item_out(row), "已新增配件条目")


@router.put("/{row_id}", response_model=ApiResponse[NetworkCatalogItemOut], dependencies=[_WRITE])
async def update_item(
    row_id: int,
    payload: NetworkCatalogItemUpdate,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
) -> ApiResponse[NetworkCatalogItemOut]:
    """更新配件条目（版本自增）。"""
    row = await NetworkCatalogService(uow).update(
        user.tenant_id, row_id, payload.model_dump(exclude_unset=True), is_super=user.is_super
    )
    await AuditService(uow).log(
        ctx,
        ACTION_BENCHMARK_UPDATE,
        target_type="network_catalog",
        target_id=row_id,
        detail={"category": row.category, "code": row.code},
    )
    return ApiResponse.ok(item_out(row), f"已更新至 v{row.version}")


@router.delete("/{row_id}", response_model=ApiResponse[OkData], dependencies=[_WRITE])
async def delete_item(
    row_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除配件条目。"""
    summary = await NetworkCatalogService(uow).delete(
        user.tenant_id, row_id, is_super=user.is_super
    )
    await AuditService(uow).log(
        ctx,
        ACTION_BENCHMARK_DELETE,
        target_type="network_catalog",
        target_id=row_id,
        detail=summary,
    )
    return ApiResponse.ok(OkData(ok=True), "已删除配件条目")
