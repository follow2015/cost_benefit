"""异步引擎与会话工厂。

RLS 关键点：每个请求在同一连接上先执行
    SET LOCAL app.tenant_id = '<id>';
    SET LOCAL app.user_id   = '<id>';
    SET LOCAL app.is_super  = 'on|off';
再执行业务 SQL。因此 **必须** 在事务内设置（`SET LOCAL` 随事务结束自动失效），
避免连接归还池后串号。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_roi.shared.config import settings

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
    connect_args={"server_settings": {"search_path": f"{settings.DB_SCHEMA}, public"}},
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def set_tenant_context(
    session: AsyncSession,
    tenant_id: Optional[int],
    user_id: Optional[int] = None,
    is_super: bool = False,
) -> None:
    """在当前事务内注入 RLS 上下文变量。

    Args:
        session: 处于事务中的会话。
        tenant_id: 当前租户；`None` 表示未认证（RLS 将拒绝一切行）。
        user_id: 当前用户，用于审计触发器与策略细化。
        is_super: 平台超管标记，`on` 时策略放行跨租户读取。
    """
    tenant_value = str(tenant_id) if tenant_id is not None else ""
    user_value = str(user_id) if user_id is not None else ""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :v, true)"), {"v": tenant_value}
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :v, true)"), {"v": user_value}
    )
    await session.execute(
        text("SELECT set_config('app.is_super', :v, true)"),
        {"v": "on" if is_super else "off"},
    )


@asynccontextmanager
async def session_scope(
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    is_super: bool = False,
) -> AsyncIterator[AsyncSession]:
    """脚本/后台任务用的会话上下文（自动开事务 + 注入 RLS + 提交/回滚）。"""
    async with SessionFactory() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id, user_id, is_super)
            yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：产出未注入租户的会话。

    租户上下文由 `ai_roi.interfaces.api.deps.get_db` 在拿到当前用户后注入，
    这里只负责生命周期与事务边界。
    """
    async with SessionFactory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """关闭连接池（应用 shutdown 时调用）。"""
    await engine.dispose()
