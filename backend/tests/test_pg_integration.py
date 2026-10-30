"""真 PG 集成测试：UoW 事务策略 + RLS 租户隔离 + 新连接读回。

scan-secrets: fixtures-allowed —— 本文件故意写入测试用假口令（ITEST_PWD 等），
用途是验证 RLS 与鉴权路径；全部是测试夹具，不是真实凭据。

定位：套件其余部分零 DB 依赖（mock 级）；本文件对**真实 PostgreSQL** 验证
Phase 2 落地的两项硬契约：

1. **UoW 唯一事务策略**：正常退出即提交（新连接能读到）；用例抛异常即回滚
   （新连接读不到）——连接级 BEGIN/COMMIT/ROLLBACK 语义正确；
2. **RLS 行级隔离**（FORCE ROW LEVEL SECURITY）：租户 A 上下文看不到租户 B
   的行；无上下文拒绝一切；超管放行跨租户读。

运行前提（缺任一条件自动 skip，不阻塞无库 CI）：
    TEST_DATABASE_URL=postgresql+asyncpg://user:pwd@localhost:5432/db \
        python -m pytest tests/test_pg_integration.py -q
且目标库已执行 `alembic upgrade head`（检测不到 tenant 表即 skip）。

数据卫生：每个用例用 uuid 后缀建租户/用户，finally 里以超管上下文按 id 删除。
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_roi.application.schemas.scenario import ScenarioCreate, ScenarioUpdate
from ai_roi.application.use_cases.scenario_service import ScenarioService
from ai_roi.domain.roles import ROLE_VIEWER
from ai_roi.infrastructure.db.models.tenant import Tenant, User
from ai_roi.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ai_roi.infrastructure.security import hash_password

DATABASE_URL: Optional[str] = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL"
)

_ITEST_ROLE = "ai_roi_itest"
_ITEST_PWD = "ai_roi_itest_pwd"


async def _probe() -> Optional[str]:
    """探测集成库可用且已迁移；不可用返回 None（调用方 skip）。"""
    if not DATABASE_URL:
        return None
    try:
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            has_tenant = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'tenant'"
                    )
                )
            ).scalar()
        await engine.dispose()
        return DATABASE_URL if has_tenant else None
    except Exception:
        return None


async def _restricted_url(url: str) -> Optional[str]:
    """返回以受限角色连接的 URL；无法创建角色时返回 None（调用方 skip）。

    超级用户（含 rolbypassrls）绕过 RLS，因此集成测试统一降权到专用角色：
    建角色（幂等）+ 授予 schema/表/序列权限。已是非超管角色则原样使用。
    """
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            is_super = (
                await conn.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                )
            ).scalar()
            if not is_super:
                return url
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ITEST_ROLE}') THEN "
                    f"CREATE ROLE {_ITEST_ROLE} LOGIN PASSWORD '{_ITEST_PWD}'; "
                    "END IF; END $$;"
                )
            )
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_ITEST_ROLE}"))
            await conn.execute(
                text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {_ITEST_ROLE}")
            )
            await conn.execute(
                text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {_ITEST_ROLE}")
            )
            await conn.commit()
        return (
            make_url(url)
            .set(username=_ITEST_ROLE, password=_ITEST_PWD)
            .render_as_string(hide_password=False)
        )
    except Exception:
        return None
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def itest_url():
    """模块级：可用且带受限角色的集成库 URL（不可用则 skip 整个模块）。"""
    url = await _probe()
    if url is None:
        pytest.skip(
            "PG 不可达或未迁移（设置 TEST_DATABASE_URL 并执行 alembic upgrade head）"
        )
    restricted = await _restricted_url(url)
    if restricted is None:
        pytest.skip("无法创建集成测试受限角色（需要对库的 CREATE ROLE 权限）")
    return restricted


def _sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


async def _seed_tenant(make_session, name: str, slug: str) -> int:
    """以超管上下文建租户（tenant 表策略要求 is_super 才能插入新行）。"""
    async with make_session() as session:
        async with SqlAlchemyUnitOfWork(session, is_super=True) as uow:
            tenant = Tenant(name=name, slug=slug)
            uow.session.add(tenant)
            await uow.session.flush()
            return tenant.id


async def _seed_user(make_session, tenant_id: int, email: str) -> int:
    """以租户上下文建用户（经 users 仓储 + UoW 提交）。"""
    async with make_session() as session:
        async with SqlAlchemyUnitOfWork(session, tenant_id=tenant_id) as uow:
            user = await uow.users.create(
                tenant_id, email, hash_password("pwd-123456"), "IT", ROLE_VIEWER
            )
            return user.id


async def _cleanup(engine: AsyncEngine, tenant_ids: list, user_ids: list) -> None:
    """超管上下文按 id 清理（finally 调用，失败不掩盖用例结论）。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.is_super', 'on', false)")
            )
            if user_ids:
                await conn.execute(
                    text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": user_ids}
                )
            if tenant_ids:
                await conn.execute(
                    text("DELETE FROM tenant WHERE id = ANY(:ids)"), {"ids": tenant_ids}
                )
            await conn.commit()
    except Exception:
        pass


@pytest.fixture()
async def pg(itest_url):
    """一套（写引擎 + 读引擎）+ 会话工厂 + 用例级清理注册表（均以受限角色连接）。"""
    write_engine = create_async_engine(itest_url, pool_pre_ping=True)
    read_engine = create_async_engine(itest_url, pool_pre_ping=True)
    registry: dict = {"tenants": [], "users": []}
    yield {
        "write": write_engine,
        "read": read_engine,
        "make_session": lambda: _sessionmaker(write_engine)(),
        "registry": registry,
    }
    await _cleanup(write_engine, registry["tenants"], registry["users"])
    await write_engine.dispose()
    await read_engine.dispose()


class TestUnitOfWorkCommit:
    async def test_commit_visible_from_new_connection(self, pg) -> None:
        """UoW 正常退出 → 提交 → 全新连接能读到用户行。"""
        tenant_id = await _seed_tenant(pg["make_session"], f"it-{uuid.uuid4().hex[:8]}", f"it-{uuid.uuid4().hex[:8]}")
        pg["registry"]["tenants"].append(tenant_id)
        email = f"u-{uuid.uuid4().hex[:8]}@it.dev"
        user_id = await _seed_user(pg["make_session"], tenant_id, email)
        pg["registry"]["users"].append(user_id)

        async with pg["read"].connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :v, false)"),
                {"v": str(tenant_id)},
            )
            row = (
                await conn.execute(
                    text("SELECT email FROM app_user WHERE id = :i"), {"i": user_id}
                )
            ).first()
        assert row is not None and row[0] == email

    async def test_rollback_hides_uncommitted_rows(self, pg) -> None:
        """用例内抛异常 → UoW 回滚 → 新连接读不到该用户。"""
        tenant_id = await _seed_tenant(pg["make_session"], f"it-{uuid.uuid4().hex[:8]}", f"it-{uuid.uuid4().hex[:8]}")
        pg["registry"]["tenants"].append(tenant_id)
        email = f"rb-{uuid.uuid4().hex[:8]}@it.dev"

        class _Boom(Exception):
            pass

        with pytest.raises(_Boom):
            async with _sessionmaker(pg["write"])() as session:
                async with SqlAlchemyUnitOfWork(session, tenant_id=tenant_id) as uow:
                    user = await uow.users.create(
                        tenant_id, email, hash_password("pwd-123456"), "RB", ROLE_VIEWER
                    )
                    raise _Boom("用例中途失败")

        async with pg["read"].connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.is_super', 'on', false)")
            )
            row = (
                await conn.execute(
                    text("SELECT id FROM app_user WHERE email = :e"), {"e": email}
                )
            ).first()
        assert row is None

    async def test_tenant_context_scoped_to_transaction(self, pg) -> None:
        """SET LOCAL 语义：UoW 退出后连接归还池，租户上下文不残留。"""
        tenant_id = await _seed_tenant(pg["make_session"], f"it-{uuid.uuid4().hex[:8]}", f"it-{uuid.uuid4().hex[:8]}")
        pg["registry"]["tenants"].append(tenant_id)
        async with _sessionmaker(pg["write"])() as session:
            async with SqlAlchemyUnitOfWork(session, tenant_id=tenant_id) as uow:
                pass
            value = (
                await session.execute(
                    text("SELECT current_setting('app.tenant_id', true)")
                )
            ).scalar()
        assert value in (None, "")


class TestScenarioUpdateWritePath:
    """方案更新的真实落库行为。

    回归背景：`updated_at` 是 `onupdate=func.now()` 的数据库生成列，UPDATE 刷库后
    该属性被 expire；异步会话里直接读取会走惰性加载并抛 `MissingGreenlet`，表现为
    `PUT /scenarios/{id}` 恒 500。此前套件全部走 mock 仓储，从不真正执行 UPDATE，
    因此 211 个用例全绿也没发现——本类专门用真 PG 覆盖这条路径。
    """

    async def test_update_persists_and_returns_fresh_timestamp(self, pg) -> None:
        """改参数 → 版本自增、快照落 diff、updated_at 真实回读（不得抛 MissingGreenlet）。"""
        tenant_id = await _seed_tenant(pg["make_session"], f"it-{uuid.uuid4().hex[:8]}", f"it-{uuid.uuid4().hex[:8]}")
        pg["registry"]["tenants"].append(tenant_id)
        user_id = await _seed_user(pg["make_session"], tenant_id, f"u-{uuid.uuid4().hex[:8]}@it.dev")
        pg["registry"]["users"].append(user_id)

        async with _sessionmaker(pg["write"])() as session:
            async with SqlAlchemyUnitOfWork(session, tenant_id=tenant_id) as uow:
                service = ScenarioService(uow)
                created, _ = await service.create(
                    tenant_id, user_id, ScenarioCreate(name="IT 更新用例")
                )
                assert created.version == 1
                created_updated_at = created.updated_at

                params = {k: dict(v) if isinstance(v, dict) else v
                          for k, v in (created.params or {}).items()}
                hw = params.setdefault("hw", {})
                before_n_gpu = hw.get("N_gpu")
                hw["N_gpu"] = "24" if str(before_n_gpu) != "24" else "32"

                updated, _warnings, changes = await service.update(
                    tenant_id,
                    user_id,
                    created.id,
                    ScenarioUpdate(params=params, note="IT 变更 N_gpu"),
                )

        assert changes, "参数有实质变更时必须产出 diff"
        assert updated.version == created.version + 1
        assert updated.updated_at >= created_updated_at, "updated_at 应为数据库刷新后的新值"

        async with pg["read"].connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :v, false)"), {"v": str(tenant_id)}
            )
            row = (
                await conn.execute(
                    text("SELECT version, params->'hw'->>'N_gpu' FROM scenario WHERE id = :i"),
                    {"i": created.id},
                )
            ).first()
            snapshot = (
                await conn.execute(
                    text(
                        "SELECT diff FROM scenario_snapshot "
                        "WHERE scenario_id = :i AND version = 2"
                    ),
                    {"i": created.id},
                )
            ).first()
        assert row is not None
        assert row[0] == created.version + 1
        assert row[1] == str(hw["N_gpu"])
        assert snapshot is not None and snapshot[0], "v2 快照必须带 diff"


class TestRlsTenantIsolation:
    async def test_cross_tenant_rows_invisible(self, pg) -> None:
        """A 租户上下文只见本租户用户；B 的用户行不可见（FORCE RLS 生效）。"""
        slug_a, slug_b = f"a-{uuid.uuid4().hex[:8]}", f"b-{uuid.uuid4().hex[:8]}"
        tenant_a = await _seed_tenant(pg["make_session"], "IT-A", slug_a)
        tenant_b = await _seed_tenant(pg["make_session"], "IT-B", slug_b)
        pg["registry"]["tenants"].extend([tenant_a, tenant_b])
        email_a = f"ua-{uuid.uuid4().hex[:8]}@it.dev"
        email_b = f"ub-{uuid.uuid4().hex[:8]}@it.dev"
        user_a = await _seed_user(pg["make_session"], tenant_a, email_a)
        user_b = await _seed_user(pg["make_session"], tenant_b, email_b)
        pg["registry"]["users"].extend([user_a, user_b])

        async with pg["read"].connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :v, false)"),
                {"v": str(tenant_a)},
            )
            visible = {
                row[0]
                for row in (
                    await conn.execute(text("SELECT id FROM app_user WHERE id = ANY(:ids)"), {"ids": [user_a, user_b]})
                ).all()
            }
        assert visible == {user_a}

    async def test_super_sees_all_tenants(self, pg) -> None:
        """超管上下文（is_super=on）放行跨租户读取。"""
        slug_a, slug_b = f"a-{uuid.uuid4().hex[:8]}", f"b-{uuid.uuid4().hex[:8]}"
        tenant_a = await _seed_tenant(pg["make_session"], "IT-A", slug_a)
        tenant_b = await _seed_tenant(pg["make_session"], "IT-B", slug_b)
        pg["registry"]["tenants"].extend([tenant_a, tenant_b])
        user_a = await _seed_user(pg["make_session"], tenant_a, f"ua-{uuid.uuid4().hex[:8]}@it.dev")
        user_b = await _seed_user(pg["make_session"], tenant_b, f"ub-{uuid.uuid4().hex[:8]}@it.dev")
        pg["registry"]["users"].extend([user_a, user_b])

        async with pg["read"].connect() as conn:
            await conn.execute(text("SELECT set_config('app.is_super', 'on', false)"))
            visible = {
                row[0]
                for row in (
                    await conn.execute(text("SELECT id FROM app_user WHERE id = ANY(:ids)"), {"ids": [user_a, user_b]})
                ).all()
            }
        assert visible == {user_a, user_b}

    async def test_no_context_sees_nothing(self, pg) -> None:
        """无租户上下文（未认证）：RLS 拒绝一切行。"""
        tenant_id = await _seed_tenant(pg["make_session"], f"it-{uuid.uuid4().hex[:8]}", f"it-{uuid.uuid4().hex[:8]}")
        pg["registry"]["tenants"].append(tenant_id)
        user_id = await _seed_user(pg["make_session"], tenant_id, f"u-{uuid.uuid4().hex[:8]}@it.dev")
        pg["registry"]["users"].append(user_id)

        async with pg["read"].connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT id FROM app_user WHERE id = :i"), {"i": user_id}
                )
            ).first()
        assert row is None
