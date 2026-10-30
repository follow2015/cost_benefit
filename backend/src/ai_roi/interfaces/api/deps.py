"""FastAPI 依赖：数据库工作单元、当前用户、权限校验、请求上下文。

请求链路（架构 §4.2 序列图）：
    Bearer token → decode_token → 取用户（超管会话读取）→ 开事务 → 注入 RLS 上下文 → 业务查询

事务策略唯一实现在 `ai_roi.infrastructure.db.uow.SqlAlchemyUnitOfWork`：
本模块只负责把「已认证用户」翻译成对应 RLS 上下文的工作单元，
用例与路由不得自行 commit/rollback。

为避免"鸡生蛋"问题（读用户本身也受 RLS 约束），`_load_user` 使用一次
`is_super=True` 的短事务按主键读取用户，随后再以该用户的 tenant_id 建立业务会话。
"""

from __future__ import annotations

from typing import Annotated, AsyncIterator, Callable, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from ai_roi.application.context import RequestContext
from ai_roi.infrastructure.db.models.tenant import User
from ai_roi.infrastructure.db.session import SessionFactory, set_tenant_context
from ai_roi.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ai_roi.infrastructure.security import decode_token
from ai_roi.interfaces.api.errors import PermissionDeniedError, UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


async def _load_user(user_id: int) -> User:
    """以超管上下文按主键读取用户（绕过 RLS 的唯一入口）。"""
    async with SessionFactory() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id=None, user_id=None, is_super=True)
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.unique().scalar_one_or_none()
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已停用")
    return user


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
) -> User:
    """解析 Bearer token 并返回当前用户。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("缺少访问凭证")
    payload = decode_token(credentials.credentials, expected_type="access")
    subject = payload.get("sub")
    if subject is None:
        raise UnauthorizedError("凭证缺少 subject")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("凭证 subject 非法") from exc
    return await _load_user(user_id)


async def get_db(
    user: Annotated[User, Depends(get_current_user)],
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """业务工作单元：已开启事务并注入当前租户 RLS 上下文。"""
    async with SessionFactory() as session:
        async with SqlAlchemyUnitOfWork(
            session,
            tenant_id=user.tenant_id,
            user_id=user.id,
            is_super=user.is_super,
        ) as uow:
            yield uow


async def get_public_db() -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """无认证工作单元（仅登录接口使用，超管上下文按邮箱查用户）。"""
    async with SessionFactory() as session:
        async with SqlAlchemyUnitOfWork(
            session, tenant_id=None, user_id=None, is_super=True
        ) as uow:
            yield uow


def get_context(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> RequestContext:
    """构造请求上下文。"""
    client_host = request.client.host if request.client else ""
    return RequestContext(
        user_id=user.id,
        user_email=user.email,
        tenant_id=user.tenant_id,
        role=user.role,
        ip=request.headers.get("x-forwarded-for", client_host),
        user_agent=request.headers.get("user-agent", ""),
    )


def require_permission(permission: str) -> Callable:
    """生成权限校验依赖。

    用法：
        @router.post("", dependencies=[Depends(require_permission("scenario:write"))])
    """

    async def _checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not user.has_permission(permission):
            raise PermissionDeniedError(
                f"当前角色（{user.role}）缺少权限：{permission}",
                {"required": permission, "role": user.role},
            )
        return user

    return _checker


CurrentUser = Annotated[User, Depends(get_current_user)]
UoW = Annotated[SqlAlchemyUnitOfWork, Depends(get_db)]
PublicUoW = Annotated[SqlAlchemyUnitOfWork, Depends(get_public_db)]
Ctx = Annotated[RequestContext, Depends(get_context)]
