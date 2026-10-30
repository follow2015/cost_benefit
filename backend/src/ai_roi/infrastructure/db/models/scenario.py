"""方案（Scenario）与方案快照（ScenarioSnapshot）。

参数整体以 JSONB 存储（`params`），字段结构与 `ai_roi.domain.calc.codec.params_to_dict` 一致，
也与前端 `src/types/scenario.ts` 的 `ScenarioParamsDTO` 一致 —— 这是前后端契约的单一事实来源。

Decimal 在 JSONB 中以**字符串**存放，避免 float 精度污染（架构 §3.4）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_roi.infrastructure.db.base import Base, TimestampMixin

SCENARIO_DRAFT = "draft"
SCENARIO_ACTIVE = "active"
SCENARIO_ARCHIVED = "archived"


class Scenario(Base, TimestampMixin):
    """一份完整的测算方案（参数集 + 口径 + 元信息）。"""

    __tablename__ = "scenario"
    __table_args__ = (
        Index("ix_scenario_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_scenario_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SCENARIO_ACTIVE)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    conventions: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    tags: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    is_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    snapshots: Mapped[List["ScenarioSnapshot"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Scenario id={self.id} name={self.name!r} v{self.version}>"


class ScenarioSnapshot(Base, TimestampMixin):
    """方案参数快照（每次保存/计算前留痕，供 P1 版本对比与审计）。"""

    __tablename__ = "scenario_snapshot"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_scenario_snapshot_version"),
        Index("ix_scenario_snapshot_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    conventions: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    diff: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    scenario: Mapped[Scenario] = relationship(back_populates="snapshots", lazy="noload")

    def __repr__(self) -> str:
        return f"<ScenarioSnapshot scenario={self.scenario_id} v{self.version}>"
