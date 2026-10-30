"""鉴权服务：登录、令牌刷新、成员管理（CRUD + 权限守卫）、当前用户 DTO 映射。"""

from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy import select

from ai_roi.application.ports import TokenStore, UnitOfWork, UserRepository
from ai_roi.application.schemas.auth import (
    LoginRequest,
    TenantBrief,
    TokenResponse,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from ai_roi.domain.errors import NotFoundError, UnauthorizedError, ValidationFailedError
from ai_roi.domain.roles import ALL_ROLES, ROLE_OWNER
from ai_roi.infrastructure.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from ai_roi.shared.config import settings

User = Any


class AuthService:
    """鉴权服务。

    `token_store`（可选）：刷新令牌黑名单端口。传入时 refresh 走一次性轮换
    （旧 jti 即效失效）；缺省（如成员管理单测）不做吊销检查。
    """

    def __init__(self, uow: UnitOfWork, token_store: Optional[TokenStore] = None) -> None:
        self.uow = uow
        self.session = uow.session
        self.users: UserRepository = uow.users
        self.token_store = token_store

    async def login(self, payload: LoginRequest) -> TokenResponse:
        """邮箱 + 密码登录。"""
        candidates = await self.users.find_by_email(str(payload.email), payload.tenant_slug)
        if not candidates:
            raise UnauthorizedError("邮箱或密码不正确")
        if len(candidates) > 1 and not payload.tenant_slug:
            raise ValidationFailedError(
                "该邮箱关联多个租户，请指定 tenant_slug",
                {
                    "tenants": [
                        {"slug": user.tenant.slug, "name": user.tenant.name}
                        for user in candidates
                        if user.tenant is not None
                    ]
                },
            )

        user = next(
            (item for item in candidates if verify_password(payload.password, item.password_hash)),
            None,
        )
        if user is None:
            raise UnauthorizedError("邮箱或密码不正确")

        await self.users.touch_login(user.id)
        return self.issue_tokens(user)

    def issue_tokens(self, user: User) -> TokenResponse:
        """签发 access + refresh 令牌。"""
        access = create_token(
            subject=str(user.id),
            tenant_id=user.tenant_id,
            role=user.role,
            permissions={"list": user.permissions},
            token_type="access",
        )
        refresh = create_token(
            subject=str(user.id),
            tenant_id=user.tenant_id,
            role=user.role,
            token_type="refresh",
        )
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=to_user_out(user),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """用 refresh token 换新令牌（一次性轮换）。

        轮换语义：旧 refresh 的 `jti` 在签发新令牌对后立即进黑名单
        （TTL = 旧令牌剩余有效期），已使用过的旧令牌再次刷新即被拒绝——
        泄露的旧令牌至多再成功一次，且天然受 TTL 约束。
        """
        payload = decode_token(refresh_token, expected_type="refresh")
        subject = payload.get("sub")
        if subject is None:
            raise UnauthorizedError("刷新令牌缺少 subject")
        jti = payload.get("jti")
        if jti is not None and self.token_store is not None:
            if await self.token_store.is_revoked(str(jti)):
                raise UnauthorizedError("刷新令牌已失效，请重新登录")
        user = await self.users.get(int(subject))
        if user is None or not user.is_active:
            raise UnauthorizedError("用户不存在或已停用")
        tokens = self.issue_tokens(user)
        if jti is not None and self.token_store is not None:
            remaining = int(payload.get("exp", 0)) - int(time.time())
            await self.token_store.revoke(str(jti), max(1, remaining))
        return tokens

    async def create_member(self, operator: User, payload: UserCreateIn) -> User:
        """新增成员（路由层已校验 member:manage=仅 owner）。"""
        if payload.role not in ALL_ROLES:
            raise ValidationFailedError(f"角色非法，应为 {ALL_ROLES} 之一")
        email = str(payload.email).strip().lower()
        from ai_roi.infrastructure.db.models.tenant import User as _User

        existing = (
            await self.session.execute(
                select(_User).where(
                    _User.tenant_id == operator.tenant_id, _User.email == email
                )
            )
        ).scalars().first()
        if existing is not None:
            raise ValidationFailedError("该邮箱已在本租户存在")
        return await self.users.create(
            operator.tenant_id,
            email,
            hash_password(payload.password),
            payload.display_name,
            payload.role,
        )

    async def update_member(self, operator: User, member_id: int, payload: UserUpdateIn) -> User:
        """更新成员：显示名 / 角色 / 启用 / 重置密码（含守卫）。"""
        if payload.role is not None and payload.role not in ALL_ROLES:
            raise ValidationFailedError(f"角色非法，应为 {ALL_ROLES} 之一")
        target = await self.users.get(member_id)
        if target is None or target.tenant_id != operator.tenant_id:
            raise NotFoundError("成员不存在")
        if target.id == operator.id and (payload.role is not None or payload.is_active is not None):
            raise ValidationFailedError("不能修改自己的角色或启用状态（防止锁死）")
        demote = payload.role is not None and payload.role != ROLE_OWNER
        disable = payload.is_active is False
        if (
            target.role == ROLE_OWNER
            and target.is_active
            and (demote or disable)
            and await self.users.count_owners(operator.tenant_id) <= 1
        ):
            raise ValidationFailedError("租户至少保留一个启用的 owner")
        fields: dict = {}
        if payload.display_name is not None:
            fields["display_name"] = payload.display_name
        if payload.role is not None:
            fields["role"] = payload.role
        if payload.is_active is not None:
            fields["is_active"] = payload.is_active
        if payload.password is not None:
            fields["password_hash"] = hash_password(payload.password)
        if not fields:
            raise ValidationFailedError("无可更新字段")
        updated = await self.users.update(member_id, operator.tenant_id, **fields)
        if updated is None:
            raise NotFoundError("成员不存在")
        return updated

    async def delete_member(self, operator: User, member_id: int) -> None:
        """删除成员（含守卫）。"""
        if member_id == operator.id:
            raise ValidationFailedError("不能删除自己")
        target = await self.users.get(member_id)
        if target is None or target.tenant_id != operator.tenant_id:
            raise NotFoundError("成员不存在")
        if (
            target.role == ROLE_OWNER
            and target.is_active
            and await self.users.count_owners(operator.tenant_id) <= 1
        ):
            raise ValidationFailedError("租户至少保留一个启用的 owner")
        if not await self.users.delete(member_id, operator.tenant_id):
            raise NotFoundError("成员不存在")


def to_user_out(user: User) -> UserOut:
    """User ORM → DTO。"""
    tenant: Optional[TenantBrief] = None
    try:
        if user.tenant is not None:
            tenant = TenantBrief(id=user.tenant.id, name=user.tenant.name, slug=user.tenant.slug)
    except Exception:
        tenant = None
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        permissions=user.permissions,
        is_super=user.is_super,
        is_active=user.is_active,
        tenant=tenant,
        last_login_at=user.last_login_at,
    )
