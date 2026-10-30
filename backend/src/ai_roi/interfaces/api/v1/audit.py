"""审计日志只读路由（P1 REQ-16）。

`GET /audit?scenario_id=&limit=` 返回本租户最近审计列表（含动作中文标签）。
权限：`audit:read`（owner / 平台超管）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ai_roi.interfaces.api.deps import CurrentUser, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import ACTION_LABELS
from ai_roi.application.schemas.common import ApiResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_entry(entry: Any) -> Dict[str, Any]:
    """审计 ORM → 列表 DTO（含动作中文标签）。

    基准库「发布」会整库快照入 `detail.snapshot`（数十行 JSON），列表里只保留条目计数，
    正文由 `GET /benchmarks/publishes` 的历史与回滚接口使用——避免审计列表被单条快照撑爆。
    """
    detail = dict(entry.detail or {})
    if "snapshot" in detail:
        detail["snapshot_omitted"] = True
        detail.pop("snapshot", None)
    return {
        "id": entry.id,
        "action": entry.action,
        "action_label": ACTION_LABELS.get(entry.action, entry.action),
        "actor_email": entry.actor_email,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "detail": detail,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("", dependencies=[Depends(require_permission("audit:read"))])
async def list_audit(
    user: CurrentUser,
    uow: UoW,
    scenario_id: Optional[int] = Query(None, description="按方案过滤（target_type=scenario）"),
    limit: int = Query(100, ge=1, le=500),
) -> ApiResponse[List[Dict[str, Any]]]:
    """读取本租户最近审计（P1 版本与审计页用）。"""
    entries = await uow.audit.list_recent(user.tenant_id, limit)
    if scenario_id is not None:
        entries = [
            e
            for e in entries
            if e.target_type == "scenario" and e.target_id == scenario_id
        ]
    return ApiResponse.ok([_to_entry(e) for e in entries])
