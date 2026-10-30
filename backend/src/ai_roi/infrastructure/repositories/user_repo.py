"""租户与用户仓储。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.infrastructure.db.models.tenant import ROLE_OWNER, ROLE_VIEWER, Tenant, User


class TenantRepository:
    """租户仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: int) -> Optional[Tenant]:
        """按主键取租户。"""
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.unique().scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[Tenant]:
        """按 slug 取租户。"""
        result = await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.unique().scalar_one_or_none()

    async def create(self, name: str, slug: str, settings_json: Optional[dict] = None) -> Tenant:
        """创建租户。"""
        tenant = Tenant(name=name, slug=slug, settings=settings_json or {})
        self.session.add(tenant)
        await self.session.flush()
        return tenant


class UserRepository:
    """用户仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> Optional[User]:
        """按主键取用户。"""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.unique().scalar_one_or_none()

    async def find_by_email(self, email: str, tenant_slug: Optional[str] = None) -> List[User]:
        """按邮箱查用户（可选按租户 slug 收窄）。返回列表以支持多租户消歧。"""
        stmt = select(User).where(User.email == email, User.is_active.is_(True))
        if tenant_slug:
            stmt = stmt.join(Tenant, Tenant.id == User.tenant_id).where(Tenant.slug == tenant_slug)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())

    async def list_by_tenant(self, tenant_id: int) -> List[User]:
        """列出租户成员。"""
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id).order_by(User.id)
        )
        return list(result.unique().scalars().all())

    async def create(
        self,
        tenant_id: int,
        email: str,
        password_hash: str,
        display_name: str = "",
        role: str = ROLE_VIEWER,
        is_super: bool = False,
    ) -> User:
        """创建用户。"""
        user = User(
            tenant_id=tenant_id,
            email=email,
            password_hash=password_hash,
            display_name=display_name or email.split("@")[0],
            role=role,
            is_super=is_super,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def touch_login(self, user_id: int) -> None:
        """更新最后登录时间。"""
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.now(tz=timezone.utc))
        )

    async def update_role(self, user_id: int, role: str) -> None:
        """更新角色。"""
        await self.session.execute(update(User).where(User.id == user_id).values(role=role))

    async def update(
        self, user_id: int, tenant_id: int, **fields: Any
    ) -> Optional[User]:
        """更新成员字段（限同租户）；返回更新后的实体。"""
        await self.session.execute(
            update(User)
            .where(User.id == user_id, User.tenant_id == tenant_id)
            .values(**fields)
        )
        await self.session.flush()
        return await self.get(user_id)

    async def delete(self, user_id: int, tenant_id: int) -> bool:
        """删除成员（限同租户）。返回是否删除成功。"""
        result = await self.session.execute(
            delete(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
        await self.session.flush()
        return result.rowcount > 0

    async def count_owners(self, tenant_id: int) -> int:
        """租户内 owner 数量（最后一个 owner 保护用）。"""
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant_id, User.role == ROLE_OWNER, User.is_active.is_(True))
        )
        return int(result.scalar() or 0)
