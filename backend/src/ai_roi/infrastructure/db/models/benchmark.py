"""基准参考库（GPU / 模型 / 云租赁价 / API 价）。

P0 只做**读取**（向导中的"填入基准值"与 k 系数回退）；
P1 起开放写入（基准库管理 UI，REQ-13），写入受 `benchmark:write` 权限与 RLS 双重约束。
基准数据分两类：
- 平台内置（`tenant_id IS NULL`，全租户可读，**仅平台超管可写**）
- 租户自建（`tenant_id = 当前租户`，租户管理员可写）
RLS 策略对基准表放行 `tenant_id IS NULL OR tenant_id = app.tenant_id`。

元数据三件套（PRD REQ-13「带版本与来源字段」）：
- `as_of`：生效日期（写接口别名 `effective_from`）
- `source`：数据来源说明
- `version`：条目修订号，每次更新自增，便于回溯口径变化
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_roi.infrastructure.db.base import Base, TimestampMixin


class BenchmarkGpu(Base, TimestampMixin):
    """GPU 硬件基准：单价、功耗、显存、典型吞吐。"""

    __tablename__ = "benchmark_gpu"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_benchmark_gpu_tenant_code"),
        Index("ix_benchmark_gpu_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    price_cny: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    tdp_w: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    vram_gb: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    rent_cny_per_hour: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<BenchmarkGpu {self.code}>"


class BenchmarkModel(Base, TimestampMixin):
    """模型基准：参数规模、典型单卡/整机吞吐（tok/s）、显存需求。"""

    __tablename__ = "benchmark_model"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_benchmark_model_tenant_code"),
        Index("ix_benchmark_model_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    params_b: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    active_params_b: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True, default=None
    )
    is_moe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    throughput_prefill: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    throughput_decode: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    throughput_effective: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    k_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    vram_required_gb: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    quant: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, default=None)
    ctx_default: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    spec_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, default=None)
    disagg_support: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    meta: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<BenchmarkModel {self.code}>"


class BenchmarkCloudPrice(Base, TimestampMixin):
    """云 GPU 租赁价基准（方案 B 预填）。"""

    __tablename__ = "benchmark_cloud_price"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "gpu_code", "region", name="uq_benchmark_cloud_price_key"
        ),
        Index("ix_benchmark_cloud_price_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    gpu_code: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="cn")
    price_cny_per_hour: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    include_power: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    include_hosting: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    billing_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="hourly")
    meta: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<BenchmarkCloudPrice {self.provider}/{self.gpu_code}>"


class BenchmarkApiPrice(Base, TimestampMixin):
    """第三方 API 调用价基准（方案 C 预填，CNY / 百万 token，税前）。"""

    __tablename__ = "benchmark_api_price"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "model_code", name="uq_benchmark_api_price_key"
        ),
        Index("ix_benchmark_api_price_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_code: Mapped[str] = mapped_column(String(96), nullable=False)
    price_in_cny_per_m: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price_out_cny_per_m: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price_cache_cny_per_m: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    meta: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<BenchmarkApiPrice {self.provider}/{self.model_code}>"
