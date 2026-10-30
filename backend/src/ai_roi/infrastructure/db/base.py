"""ORM 基类与公共 Mixin。

约定（架构 §4.2 多租户）：
- 所有业务表带 `tenant_id`，并启用 PostgreSQL RLS，策略读取会话变量 `app.tenant_id`。
- 所有表带 `created_at` / `updated_at`（timestamptz）。
- 主键统一使用 BIGSERIAL（`BigInteger` + identity），避免 UUID 索引膨胀。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import BigInteger, DateTime, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: Dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """声明式基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> Dict[str, Any]:
        """浅层转字典（用于审计日志快照与调试）。"""
        result: Dict[str, Any] = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name, None)
            result[column.name] = value.isoformat() if isinstance(value, datetime) else value
        return result


class TimestampMixin:
    """创建/更新时间戳。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """租户隔离键。RLS 策略以该列与会话变量 `app.tenant_id` 比对。"""

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def pk_column() -> Mapped[int]:
    """标准自增主键列。"""
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)
