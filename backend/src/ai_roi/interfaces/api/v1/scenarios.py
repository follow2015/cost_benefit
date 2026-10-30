"""方案路由（CRUD + 快照 + 复制）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ai_roi.domain.calc.codec import params_to_dict
from ai_roi.domain.calc.decimal_config import to_jsonable
from ai_roi.domain.calc.parameters import default_params
from ai_roi.interfaces.api.deps import Ctx, CurrentUser, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import (
    ACTION_SCENARIO_CREATE,
    ACTION_SCENARIO_DELETE,
    ACTION_SCENARIO_UPDATE,
)
from ai_roi.application.schemas.common import ApiResponse, OkData, PageMeta, PageResponse
from ai_roi.application.schemas.scenario import (
    ScenarioCreate,
    ScenarioDetailOut,
    ScenarioListItemOut,
    ScenarioUpdate,
    SnapshotOut,
)
from ai_roi.application.use_cases.audit_service import AuditService
from ai_roi.application.use_cases.scenario_service import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("/default-params", response_model=ApiResponse[Dict[str, Any]])
async def get_default_params() -> ApiResponse[Dict[str, Any]]:
    """返回内置默认参数模板（向导首屏预填，Decimal 已转字符串）。

    注：本接口刻意免鉴权——仅返回与租户无关的通用默认参数模板，供向导首屏预填
    使用；不含任何租户/业务数据。如未来需要按租户返回差异化模板，应改为带
    `require_permission` 的依赖。
    """
    return ApiResponse.ok(to_jsonable(params_to_dict(default_params())))


@router.get("", response_model=ApiResponse[PageResponse[ScenarioListItemOut]])
async def list_scenarios(
    user: CurrentUser,
    uow: UoW,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: str = Query(default=""),
    status: Optional[str] = Query(default=None),
) -> ApiResponse[PageResponse[ScenarioListItemOut]]:
    """分页列出方案（含最近一次 KPI 摘要）。"""
    service = ScenarioService(uow)
    items, total = await service.list_page(
        user.tenant_id, page=page, page_size=page_size, keyword=keyword, status=status
    )
    return ApiResponse.ok(
        PageResponse(
            items=items, meta=PageMeta(page=page, page_size=page_size, total=total)
        )
    )


@router.post(
    "",
    response_model=ApiResponse[ScenarioDetailOut],
    dependencies=[Depends(require_permission("scenario:write"))],
)
async def create_scenario(
    payload: ScenarioCreate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[ScenarioDetailOut]:
    """创建方案。"""
    service = ScenarioService(uow)
    detail, warnings = await service.create(user.tenant_id, user.id, payload)
    await AuditService(uow).log(
        ctx,
        ACTION_SCENARIO_CREATE,
        target_type="scenario",
        target_id=detail.id,
        detail={"name": detail.name, "warnings": len(warnings)},
    )
    message = "创建成功" if not warnings else f"创建成功，有 {len(warnings)} 条口径提示"
    return ApiResponse.ok(detail, message)


@router.get("/{scenario_id}", response_model=ApiResponse[ScenarioDetailOut])
async def get_scenario(
    scenario_id: int, user: CurrentUser, uow: UoW
) -> ApiResponse[ScenarioDetailOut]:
    """方案详情。"""
    service = ScenarioService(uow)
    return ApiResponse.ok(await service.detail(user.tenant_id, scenario_id))


@router.put(
    "/{scenario_id}",
    response_model=ApiResponse[ScenarioDetailOut],
    dependencies=[Depends(require_permission("scenario:write"))],
)
async def update_scenario(
    scenario_id: int,
    payload: ScenarioUpdate,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
) -> ApiResponse[ScenarioDetailOut]:
    """更新方案（参数变更自动升版并留痕）。"""
    service = ScenarioService(uow)
    detail, warnings, changes = await service.update(
        user.tenant_id, user.id, scenario_id, payload
    )
    await AuditService(uow).log(
        ctx,
        ACTION_SCENARIO_UPDATE,
        target_type="scenario",
        target_id=scenario_id,
        detail={"version": detail.version, "changed_fields": sorted(changes.keys())[:50]},
    )
    message = f"已保存为 v{detail.version}" if changes else "已保存（参数无变更）"
    if warnings:
        message = f"{message}，有 {len(warnings)} 条口径提示"
    return ApiResponse.ok(detail, message)


@router.delete(
    "/{scenario_id}",
    response_model=ApiResponse[OkData],
    dependencies=[Depends(require_permission("scenario:delete"))],
)
async def delete_scenario(
    scenario_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除方案。"""
    service = ScenarioService(uow)
    name = await service.delete(user.tenant_id, scenario_id)
    await AuditService(uow).log(
        ctx,
        ACTION_SCENARIO_DELETE,
        target_type="scenario",
        target_id=scenario_id,
        detail={"name": name},
    )
    return ApiResponse.ok(OkData(ok=True), f"已删除方案「{name}」")


@router.post(
    "/{scenario_id}/duplicate",
    response_model=ApiResponse[ScenarioDetailOut],
    dependencies=[Depends(require_permission("scenario:write"))],
)
async def duplicate_scenario(
    scenario_id: int,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
    new_name: str = Query(default=""),
) -> ApiResponse[ScenarioDetailOut]:
    """另存为新方案。"""
    service = ScenarioService(uow)
    detail = await service.duplicate(user.tenant_id, user.id, scenario_id, new_name)
    await AuditService(uow).log(
        ctx,
        ACTION_SCENARIO_CREATE,
        target_type="scenario",
        target_id=detail.id,
        detail={"duplicated_from": scenario_id},
    )
    return ApiResponse.ok(detail, "已复制方案")


@router.get("/{scenario_id}/snapshots", response_model=ApiResponse[List[SnapshotOut]])
async def list_snapshots(
    scenario_id: int,
    user: CurrentUser,
    uow: UoW,
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[List[SnapshotOut]]:
    """方案版本快照历史。"""
    service = ScenarioService(uow)
    return ApiResponse.ok(await service.snapshots_of(user.tenant_id, scenario_id, limit))
