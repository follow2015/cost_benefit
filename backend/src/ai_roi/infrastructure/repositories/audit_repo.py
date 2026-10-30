"""审计日志仓储。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.infrastructure.db.models.audit import AuditLog


class AuditRepository:
    """审计仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> AuditLog:
        """写入一条审计。"""
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_recent(self, tenant_id: int, limit: int = 100) -> List[AuditLog]:
        """列出最近审计（P1 审计 UI 用）。"""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
        return list(result.unique().scalars().all())

    async def list_by_action(
        self, tenant_id: int, action: str, limit: int = 20
    ) -> List[AuditLog]:
        """按动作类型倒序列出审计（基准库「发布历史」用）。"""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.action == action)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
        return list(result.unique().scalars().all())

    async def get(self, tenant_id: int, entry_id: int) -> Optional[AuditLog]:
        """按 id 取本租户的一条审计（越权与跨租户一律视为不存在）。"""
        result = await self.session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id, AuditLog.id == entry_id
            )
        )
        return result.unique().scalar_one_or_none()
