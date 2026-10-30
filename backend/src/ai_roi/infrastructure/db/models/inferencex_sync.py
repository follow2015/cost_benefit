"""InferenceX 采集运行记录（平台级，非租户业务数据）。

为什么要独立一张表而不是塞进 ``audit_log``：
- 采集既有**无租户的定时执行**（audit_log.tenant_id 为 NOT NULL + FK，写不进去），
  也有手动触发，需要一个不依赖租户的落点；
- 前端要回答「上次什么时候采的 / 采到几条 / 为什么失败」，需要结构化字段，
  审计的 ``detail`` 是自由 JSON、且按租户可见性设计，不适合当系统任务日志。

可见性：``tenant_id IS NULL``（系统/定时）与触发者租户行同表，走
``shared_read_policies``——全租户可读、写入仅超管或本租户，与基准表同构。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_roi.domain.inferencex import (
    STATUS_RUNNING,
    TRIGGER_SCHEDULED,
)
from ai_roi.infrastructure.db.base import Base, TimestampMixin


class InferencexSyncRun(Base, TimestampMixin):
    """一次采集的完整留痕（成功与失败都记，失败也带原因）。"""

    __tablename__ = "inferencex_sync_run"
    __table_args__ = (
        Index("ix_inferencex_sync_run_started", "started_at"),
        Index("ix_inferencex_sync_run_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="inferencex")
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default=TRIGGER_SCHEDULED)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_RUNNING)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    model_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    platform_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<InferencexSyncRun {self.status} trigger={self.trigger} at={self.started_at}>"
