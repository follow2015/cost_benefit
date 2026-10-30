"""鉴权路由（登录/刷新/成员管理 CRUD）。"""

from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Request

from ai_roi.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ai_roi.interfaces.api.deps import CurrentUser, PublicUoW, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import ACTION_LOGIN, ACTION_MEMBER_DELETE, ACTION_MEMBER_INVITE, ACTION_MEMBER_UPDATE
from ai_roi.infrastructure.db.models.tenant import User
from ai_roi.infrastructure.redis.rate_limiter import get_rate_limiter
from ai_roi.infrastructure.redis.token_store import get_token_store
from ai_roi.application.ports import RateLimiter, TokenStore
from ai_roi.application.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from ai_roi.application.schemas.common import ApiResponse
from ai_roi.application.use_cases.auth_service import AuthService, to_user_out
from ai_roi.domain.errors import UnauthorizedError
from ai_roi.interfaces.api.errors import RateLimitedError
from ai_roi.shared.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_MEMBER_WRITE = Depends(require_permission("member:manage"))


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    uow: PublicUoW,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> ApiResponse[TokenResponse]:
    """登录并签发令牌。

    防爆破：同一 IP+邮箱组合的**失败**次数超限返回 429（成功不计入，
    不误伤正常用户；窗口与阈值见 `settings.LOGIN_RATE_*`）。
    """
    client_host = request.client.host if request.client else ""
    rate_key = f"{client_host}|{str(payload.email).strip().lower()}"
    if await limiter.is_limited(
        rate_key, settings.LOGIN_RATE_MAX_FAILURES, settings.LOGIN_RATE_WINDOW_SECONDS
    ):
        raise RateLimitedError("登录失败次数过多，请稍后再试")

    service = AuthService(uow)
    try:
        tokens = await service.login(payload)
    except UnauthorizedError:
        await limiter.hit(rate_key, settings.LOGIN_RATE_WINDOW_SECONDS)
        raise

    audit = uow.audit
    await audit.write(
        tenant_id=tokens.user.tenant.id if tokens.user.tenant else 0,
        action=ACTION_LOGIN,
        actor_id=tokens.user.id,
        actor_email=tokens.user.email,
        target_type="user",
        target_id=tokens.user.id,
        detail={"role": tokens.user.role},
        ip=request.headers.get("x-forwarded-for", client_host),
        user_agent=request.headers.get("user-agent", "")[:512],
    )
    return ApiResponse.ok(tokens, "登录成功")


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh(
    payload: RefreshRequest,
    uow: PublicUoW,
    token_store: Annotated[TokenStore, Depends(get_token_store)],
) -> ApiResponse[TokenResponse]:
    """刷新访问令牌（一次性轮换：旧 refresh 即效失效）。"""
    service = AuthService(uow, token_store=token_store)
    tokens = await service.refresh(payload.refresh_token)
    return ApiResponse.ok(tokens)


@router.get("/me", response_model=ApiResponse[UserOut])
async def me(user: CurrentUser) -> ApiResponse[UserOut]:
    """当前登录用户。"""
    return ApiResponse.ok(to_user_out(user))


@router.get("/members", response_model=ApiResponse[List[UserOut]])
async def members(
    user: CurrentUser,
    uow: UoW,
) -> ApiResponse[List[UserOut]]:
    """列出同租户成员（P0 只读，成员管理留给 P1）。"""
    repo = uow.users
    records: List[User] = await repo.list_by_tenant(user.tenant_id)
    return ApiResponse.ok([to_user_out(item) for item in records])


@router.post("/members", response_model=ApiResponse[UserOut], dependencies=[_MEMBER_WRITE])
async def create_member(
    payload: UserCreateIn,
    user: CurrentUser,
    uow: UoW,
    request: Request,
) -> ApiResponse[UserOut]:
    """新增成员（仅 owner）。"""
    service = AuthService(uow)
    created = await service.create_member(user, payload)
    await _audit_member(uow, user, ACTION_MEMBER_INVITE, created.id, created.email, "create")
    return ApiResponse.ok(to_user_out(created), "成员已创建")


@router.put("/members/{member_id}", response_model=ApiResponse[UserOut], dependencies=[_MEMBER_WRITE])
async def update_member(
    member_id: int,
    payload: UserUpdateIn,
    user: CurrentUser,
    uow: UoW,
    request: Request,
) -> ApiResponse[UserOut]:
    """更新成员（角色/启用/显示名/重置密码；仅 owner，含守卫）。"""
    service = AuthService(uow)
    updated = await service.update_member(user, member_id, payload)
    await _audit_member(uow, user, ACTION_MEMBER_UPDATE, updated.id, updated.email, payload.model_dump(exclude_none=True))
    return ApiResponse.ok(to_user_out(updated), "成员已更新")


@router.delete("/members/{member_id}", response_model=ApiResponse[dict], dependencies=[_MEMBER_WRITE])
async def delete_member(
    member_id: int,
    user: CurrentUser,
    uow: UoW,
    request: Request,
) -> ApiResponse[dict]:
    """删除成员（仅 owner，含守卫：不能删自己 / 最后一个 owner）。"""
    service = AuthService(uow)
    target = await uow.users.get(member_id)
    await service.delete_member(user, member_id)
    await _audit_member(uow, user, ACTION_MEMBER_DELETE, member_id, target.email if target else str(member_id), "delete")
    return ApiResponse.ok({"ok": True}, "成员已删除")


async def _audit_member(
    uow: SqlAlchemyUnitOfWork,
    actor: User,
    action: str,
    target_id: int,
    target_email: str,
    detail: object,
) -> None:
    """成员管理审计（与登录审计同一仓储）。"""
    audit = uow.audit
    await audit.write(
        tenant_id=actor.tenant_id,
        action=action,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="user",
        target_id=target_id,
        detail={"email": target_email, "payload": detail} if isinstance(detail, dict) else {"email": target_email},
    )
