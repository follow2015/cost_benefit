"""成员管理 CRUD 守卫逻辑单测（mock 仓储，不碰真实 DB）。

覆盖：创建（邮箱唯一/角色校验/密码哈希）、更新（跨租户 404/改自己角色拒绝/
最后 owner 保护/重置密码/空更新拒绝）、删除（删自己拒绝/最后 owner 保护）。

scan-secrets: fixtures-allowed —— 本文件故意写入假口令（如 "123456"、"secret6"），
用途是验证密码哈希与重置路径；全部是测试夹具，不是真实凭据。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_roi.domain.errors import NotFoundError, ValidationFailedError
from ai_roi.domain.roles import ROLE_OWNER, ROLE_VIEWER
from ai_roi.infrastructure.db.models.tenant import User
from ai_roi.infrastructure.security import verify_password
from ai_roi.application.schemas.auth import UserCreateIn, UserUpdateIn
from ai_roi.application.use_cases.auth_service import AuthService


def _user(**overrides) -> User:
    """构造最小 User 实体（不落库）。"""
    base = dict(
        id=1, tenant_id=1, email="owner@test.dev", display_name="Owner",
        password_hash="x", role=ROLE_OWNER, extra_permissions=[], is_active=True,
        is_super=False, last_login_at=None,
    )
    base.update(overrides)
    u = User(**base)
    return u


def _no_dup(service, email: str = "a@b.dev") -> None:
    """session.execute → scalars().first() 返回 None（execute 异步、scalars/first 同步）。"""
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    service.session.execute = AsyncMock(return_value=result)


@pytest.fixture
def service() -> AuthService:
    uow = MagicMock()
    uow.session = AsyncMock()
    s = AuthService(uow)
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    repo.count_owners = AsyncMock(return_value=2)
    s.users = repo
    return s


class TestCreateMember:
    async def test_role_invalid(self, service) -> None:
        with pytest.raises(ValidationFailedError):
            await service.create_member(_user(), UserCreateIn(email="a@b.dev", password="123456", role="hacker"))

    async def test_email_duplicate(self, service) -> None:
        dup = _user(id=9, email="a@b.dev")
        result = MagicMock()
        result.scalars.return_value.first.return_value = dup
        service.session.execute = AsyncMock(return_value=result)
        with pytest.raises(ValidationFailedError, match="已在本租户存在"):
            await service.create_member(_user(), UserCreateIn(email="A@B.DEV", password="123456"))

    async def test_create_hashes_password(self, service) -> None:
        _no_dup(service)
        created = _user(id=7, email="new@test.dev")
        service.users.create = AsyncMock(return_value=created)
        out = await service.create_member(_user(), UserCreateIn(email="new@test.dev", password="secret6", display_name="新人", role=ROLE_VIEWER))
        assert out.id == 7
        args, _ = service.users.create.call_args
        assert args[0] == 1
        assert args[1] == "new@test.dev"
        assert args[3] == "新人"
        assert args[4] == ROLE_VIEWER
        assert verify_password("secret6", args[2])


class TestUpdateMember:
    async def test_target_missing(self, service) -> None:
        service.users.get = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await service.update_member(_user(), 99, UserUpdateIn(display_name="x"))

    async def test_cross_tenant_rejected(self, service) -> None:
        service.users.get = AsyncMock(return_value=_user(id=5, tenant_id=2))
        with pytest.raises(NotFoundError):
            await service.update_member(_user(tenant_id=1), 5, UserUpdateIn(display_name="x"))

    async def test_self_role_change_rejected(self, service) -> None:
        me = _user(id=1, tenant_id=1)
        service.users.get = AsyncMock(return_value=me)
        with pytest.raises(ValidationFailedError, match="自己的角色"):
            await service.update_member(me, 1, UserUpdateIn(role=ROLE_VIEWER))

    async def test_last_owner_demote_rejected(self, service) -> None:
        service.users.get = AsyncMock(return_value=_user(id=3, tenant_id=1, role=ROLE_OWNER))
        service.users.count_owners = AsyncMock(return_value=1)
        with pytest.raises(ValidationFailedError, match="owner"):
            await service.update_member(_user(), 3, UserUpdateIn(role=ROLE_VIEWER))

    async def test_reset_password_hashes(self, service) -> None:
        target = _user(id=3, tenant_id=1, role=ROLE_VIEWER)
        service.users.get = AsyncMock(return_value=target)
        service.users.update = AsyncMock(return_value=target)
        await service.update_member(_user(), 3, UserUpdateIn(password="newpass6"))
        _, kwargs = service.users.update.call_args
        assert verify_password("newpass6", kwargs["password_hash"])

    async def test_no_fields_rejected(self, service) -> None:
        service.users.get = AsyncMock(return_value=_user(id=3, tenant_id=1, role=ROLE_VIEWER))
        with pytest.raises(ValidationFailedError, match="无可更新字段"):
            await service.update_member(_user(), 3, UserUpdateIn())


class TestDeleteMember:
    async def test_delete_self_rejected(self, service) -> None:
        me = _user(id=1)
        with pytest.raises(ValidationFailedError, match="不能删除自己"):
            await service.delete_member(me, 1)

    async def test_last_owner_rejected(self, service) -> None:
        service.users.get = AsyncMock(return_value=_user(id=3, tenant_id=1, role=ROLE_OWNER))
        service.users.count_owners = AsyncMock(return_value=1)
        with pytest.raises(ValidationFailedError, match="owner"):
            await service.delete_member(_user(), 3)

    async def test_delete_ok(self, service) -> None:
        service.users.get = AsyncMock(return_value=_user(id=3, tenant_id=1, role=ROLE_VIEWER))
        service.users.count_owners = AsyncMock(return_value=1)
        service.users.delete = AsyncMock(return_value=True)
        await service.delete_member(_user(), 3)
        service.users.delete.assert_awaited_once_with(3, 1)
