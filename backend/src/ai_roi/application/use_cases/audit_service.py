"""审计服务：统一写入入口，屏蔽仓储细节。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai_roi.application.context import RequestContext
from ai_roi.application.ports import AuditRepository, UnitOfWork

_MAX_VALUE_LEN = 512


class AuditService:
    """审计服务。"""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.session = uow.session
        self.repo: AuditRepository = uow.audit

    async def log(
        self,
        ctx: RequestContext,
        action: str,
        target_type: str = "",
        target_id: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入一条审计（tenant_id 缺失时静默跳过，不影响主流程）。"""
        if ctx.tenant_id is None:
            return
        await self.repo.write(
            tenant_id=ctx.tenant_id,
            action=action,
            actor_id=ctx.user_id,
            actor_email=ctx.user_email,
            target_type=target_type,
            target_id=target_id,
            detail=_truncate(detail or {}),
            ip=ctx.ip,
            user_agent=ctx.user_agent[:512],
        )


def _truncate(detail: Dict[str, Any]) -> Dict[str, Any]:
    """截断过长的 detail 值，保持审计表体积可控。"""
    result: Dict[str, Any] = {}
    for key, value in detail.items():
        if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
            result[key] = value[:_MAX_VALUE_LEN] + "…(truncated)"
        elif isinstance(value, dict):
            result[key] = _truncate(value)
        else:
            result[key] = value
    return result
