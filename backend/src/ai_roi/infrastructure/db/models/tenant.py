"""租户与用户模型。

角色（P0 简化为字符串枚举，权限点存 JSONB，便于后续细化到资源级）：
    - owner  : 租户所有者，可管理成员与全部方案
    - editor : 可创建/编辑/计算方案
    - viewer : 只读
平台超管由 `User.is_super` 标记（不属于任何租户业务数据，仅用于运维）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_roi.infrastructure.db.base import Base, TimestampMixin

from ai_roi.domain.roles import (  # noqa: F401  pylint: disable=unused-import
    ALL_ROLES,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_PERMISSIONS,
    ROLE_VIEWER,
)


class Tenant(Base, TimestampMixin):
    """租户（企业/团队）。"""

    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    settings: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    users: Mapped[List["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug!r}>"


class User(Base, TimestampMixin):
    """用户。同一邮箱在同一租户内唯一（允许跨租户复用邮箱）。"""

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_VIEWER)
    extra_permissions: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_super: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users", lazy="joined")

    @property
    def permissions(self) -> List[str]:
        """角色默认权限 ∪ 额外权限。"""
        base = set(ROLE_PERMISSIONS.get(self.role, []))
        base.update(self.extra_permissions or [])
        return sorted(base)

    def has_permission(self, permission: str) -> bool:
        """是否具备指定权限点（超管全放行）。"""
        if self.is_super:
            return True
        return permission in self.permissions

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
