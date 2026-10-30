"""组网配套目录（配件库）：算力/存储/管理交换机、NIC、光模块、线缆、存储单价。

价格来源策略（用户决策 2026-08-19）：
- 计算引擎默认使用 `supporting_cost.py` 的内置经验常量（现状口径）；
- 本表有对应条目时（平台内置 `tenant_id IS NULL` 或租户覆盖）优先使用库内价格，
  引擎按 `category+code` 查找并覆盖默认值；
- 与 benchmark 表同构：平台内置全租户可读、仅超管可写；租户自建仅租户可读。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_roi.infrastructure.db.base import Base, TimestampMixin

CAT_COMPUTE_SWITCH_IB = "compute_switch_ib"
CAT_COMPUTE_SWITCH_ROCE = "compute_switch_roce"
CAT_STORAGE_SWITCH = "storage_switch"
CAT_MGMT_SWITCH = "mgmt_switch"
CAT_NIC_IB = "nic_ib"
CAT_NIC_ROCE = "nic_roce"
CAT_OPTICS_400G = "optics_400g"
CAT_OPTICS_100G = "optics_100g"
CAT_AOC_CABLE = "aoc_cable"
CAT_MPO_CABLE = "mpo_cable"
CAT_STORAGE_PER_GB = "storage_per_gb"
CAT_STORAGE_MONTHLY_PER_GB = "storage_monthly_per_gb"

CATEGORIES = [
    CAT_COMPUTE_SWITCH_IB,
    CAT_COMPUTE_SWITCH_ROCE,
    CAT_STORAGE_SWITCH,
    CAT_MGMT_SWITCH,
    CAT_NIC_IB,
    CAT_NIC_ROCE,
    CAT_OPTICS_400G,
    CAT_OPTICS_100G,
    CAT_AOC_CABLE,
    CAT_MPO_CABLE,
    CAT_STORAGE_PER_GB,
    CAT_STORAGE_MONTHLY_PER_GB,
]


class NetworkCatalogItem(Base, TimestampMixin):
    """组网配套目录条目（单价基准，可被租户覆盖）。"""

    __tablename__ = "network_catalog"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "category", "code", name="uq_network_catalog_tenant_category_code"
        ),
        Index("ix_network_catalog_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    price_cny: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="台")
    spec: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<NetworkCatalogItem {self.category}/{self.code}>"
