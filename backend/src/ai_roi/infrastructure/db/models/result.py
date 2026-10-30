"""计算结果（CalcResult）与逐期现金流（cashflow_row，按 tenant_id 哈希分区）。

设计要点（架构 §4.3）：
- `calc_result` 存整份结果 JSONB（KPI/单位成本/交点/敏感性/情景），便于结果页一次取回。
- 逐期现金流行数多（120 期 × 方案数 × 情景数），单独落表并**按 tenant_id HASH 分区**（8 分区），
  分区键必须进入主键，故主键为 (id, tenant_id)。
- 结果带 `engine_version` / `formula_spec_version` / `params_hash`，用于缓存命中与可复现性校验。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_roi.infrastructure.db.base import Base, TimestampMixin


class CalcResult(Base, TimestampMixin):
    """一次计算的完整结果。"""

    __tablename__ = "calc_result"
    __table_args__ = (
        Index("ix_calc_result_tenant_scenario", "tenant_id", "scenario_id"),
        Index("ix_calc_result_hash", "tenant_id", "params_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("scenario.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    kpi_summary: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    formula_spec_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_deviation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<CalcResult id={self.id} scenario={self.scenario_id}>"


class CashflowRowRecord(Base):
    """逐期现金流明细（分区表）。

    金额列使用 `Numeric(24, 6)`（PostgreSQL numeric 精确十进制），读回时由
    `ai_roi.domain.calc.decimal_config.D()` 转 Decimal，全程不经过 float。
    """

    __tablename__ = "cashflow_row"
    __table_args__ = (
        Index("ix_cashflow_row_result", "tenant_id", "result_id", "period"),
        {"postgresql_partition_by": "HASH (tenant_id)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    result_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    plan: Mapped[str] = mapped_column(String(8), nullable=False, default="A")
    revenue: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    opex_cash: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    depreciation: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    ebit: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    capex: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    net_cf: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    discounted_cf: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    cum_net_cf: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    cum_discounted_cf: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<CashflowRow result={self.result_id} t={self.period}>"
