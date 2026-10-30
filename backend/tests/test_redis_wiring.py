"""Redis 四件套 wiring 回归：刷新轮换 / 失败限流 / 试算缓存 / fail-open。

覆盖 Phase 2 三处接线：
1. `AuthService.refresh` 一次性轮换（旧 jti 即效失效，链式轮换同样吊销）；
2. `RateLimiter` 双方法语义（只计失败、超限拒绝、窗口过期自动恢复）；
3. `CalcService.calculate` 的 `result_cache` 旁路（命中跳过引擎重算，载荷一致）；
4. Redis 适配器 fail-open（连接故障不阻断刷新/试算）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_roi.application.schemas.calc import CalcOptionsIn
from ai_roi.application.use_cases import calc_service as calc_service_module
from ai_roi.application.use_cases.auth_service import AuthService
from ai_roi.application.use_cases.calc_service import CalcService
from ai_roi.domain.calc.codec import params_to_dict
from ai_roi.domain.calc.parameters import default_params
from ai_roi.domain.errors import UnauthorizedError
from ai_roi.infrastructure.redis.cache import InMemoryResultCache, RedisResultCache
from ai_roi.infrastructure.redis.rate_limiter import InMemoryRateLimiter
from ai_roi.infrastructure.redis.token_store import InMemoryTokenStore, RedisTokenStore
from ai_roi.infrastructure.security import decode_token


def _user() -> SimpleNamespace:
    """最小 User 实体（不落库；permissions 为权限列表，tenant 关系已加载）。"""
    return SimpleNamespace(
        id=7,
        tenant_id=3,
        email="a@b.dev",
        display_name="A",
        password_hash="x",
        role="owner",
        permissions=["scenario:calc"],
        is_active=True,
        is_super=False,
        last_login_at=None,
        tenant=SimpleNamespace(id=3, name="T", slug="t"),
    )


def _auth_service(token_store=None) -> AuthService:
    """装配 AuthService（mock UoW + mock users 仓储）。"""
    uow = MagicMock()
    uow.session = AsyncMock()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=_user())
    uow.users = repo
    return AuthService(uow, token_store=token_store)


class TestRefreshRotation:
    async def test_refresh_token_carries_jti(self) -> None:
        """签发的 refresh 令牌必须带 jti（轮换吊销载体）。"""
        service = _auth_service()
        tokens = service.issue_tokens(_user())
        payload = decode_token(tokens.refresh_token, expected_type="refresh")
        assert payload.get("jti")
        access_payload = decode_token(tokens.access_token, expected_type="access")
        assert access_payload.get("jti")

    async def test_old_token_revoked_after_rotation(self) -> None:
        """轮换后旧 refresh 立即失效（防重放）。"""
        service = _auth_service(token_store=InMemoryTokenStore())
        tokens = service.issue_tokens(_user())

        rotated = await service.refresh(tokens.refresh_token)
        assert rotated.refresh_token != tokens.refresh_token
        with pytest.raises(UnauthorizedError):
            await service.refresh(tokens.refresh_token)

    async def test_chained_rotation_revokes_each_generation(self) -> None:
        """链式轮换：每一代旧令牌都被吊销，只有最新一代可用。"""
        service = _auth_service(token_store=InMemoryTokenStore())
        gen1 = service.issue_tokens(_user())
        gen2 = await service.refresh(gen1.refresh_token)
        gen3 = await service.refresh(gen2.refresh_token)

        with pytest.raises(UnauthorizedError):
            await service.refresh(gen1.refresh_token)
        with pytest.raises(UnauthorizedError):
            await service.refresh(gen2.refresh_token)
        gen4 = await service.refresh(gen3.refresh_token)
        assert gen4.access_token

    async def test_revoked_ttl_matches_remaining_lifetime(self) -> None:
        """吊销 TTL = 旧令牌剩余有效期（过期后条目无查询价值，自然清理）。"""
        store = InMemoryTokenStore()
        service = _auth_service(token_store=store)
        tokens = service.issue_tokens(_user())
        payload = decode_token(tokens.refresh_token, expected_type="refresh")

        await service.refresh(tokens.refresh_token)
        import time

        assert await store.is_revoked(payload["jti"])
        remaining = store._revoked[payload["jti"]] - time.time()
        token_remaining = payload["exp"] - time.time()
        assert abs(remaining - token_remaining) < 5

    async def test_refresh_without_store_allows_reuse(self) -> None:
        """未注入 token_store 的兼容路径（成员管理等内部调用）：旧令牌可重复使用。"""
        service = _auth_service()
        tokens = service.issue_tokens(_user())
        await service.refresh(tokens.refresh_token)
        await service.refresh(tokens.refresh_token)

    async def test_inactive_user_rejected_on_refresh(self) -> None:
        """用户被停用后刷新即拒（即便令牌本身有效）。"""
        service = _auth_service(token_store=InMemoryTokenStore())
        attrs = {**_user().__dict__, "is_active": False}
        service.users.get = AsyncMock(return_value=SimpleNamespace(**attrs))
        tokens = service.issue_tokens(_user())
        with pytest.raises(UnauthorizedError):
            await service.refresh(tokens.refresh_token)


class TestFailureRateLimiter:
    async def test_counts_failures_only(self) -> None:
        """hit 计失败次数；is_limited 达阈值才超限；成功不调用 hit 故不计入。"""
        limiter = InMemoryRateLimiter()
        assert await limiter.is_limited("ip|a@b.dev", 3, 60) is False
        assert await limiter.hit("ip|a@b.dev", 60) == 1
        assert await limiter.is_limited("ip|a@b.dev", 3, 60) is False
        assert await limiter.hit("ip|a@b.dev", 60) == 2
        assert await limiter.is_limited("ip|a@b.dev", 3, 60) is False
        assert await limiter.hit("ip|a@b.dev", 60) == 3
        assert await limiter.is_limited("ip|a@b.dev", 3, 60) is True

    async def test_keys_are_isolated(self) -> None:
        """不同 key 独立计数（一个 IP+邮箱组合的超限不影响其他用户）。"""
        limiter = InMemoryRateLimiter()
        for _ in range(3):
            await limiter.hit("ip1|a@b.dev", 60)
        assert await limiter.is_limited("ip1|a@b.dev", 3, 60) is True
        assert await limiter.is_limited("ip1|c@d.dev", 3, 60) is False
        assert await limiter.is_limited("ip2|a@b.dev", 3, 60) is False

    async def test_expired_window_does_not_limit(self) -> None:
        """窗口过期后计数自动清除（滑动窗口语义）。"""
        limiter = InMemoryRateLimiter()
        await limiter.hit("k", 0)
        assert await limiter.is_limited("k", 1, 0) is False


class TestPreviewResultCache:
    def _service(self) -> CalcService:
        uow = MagicMock()
        return CalcService(uow)

    async def _calculate(self, service: CalcService, cache) -> object:
        return await service.calculate(
            tenant_id=1,
            user_id=1,
            params_dict=params_to_dict(default_params()),
            options=CalcOptionsIn(),
            scenario_id=None,
            persist=False,
            result_cache=cache,
        )

    async def test_cache_hit_skips_engine_and_matches_payload(self, monkeypatch) -> None:
        """同参数指纹第二次试算命中缓存：不调引擎、载荷一致、params_hash 一致。"""
        cache = InMemoryResultCache()
        service = self._service()

        calls: list = []
        original = calc_service_module.compute_all

        def counting(params, options):
            calls.append(params)
            return original(params, options)

        monkeypatch.setattr(calc_service_module, "compute_all", counting)

        first = await self._calculate(service, cache)
        assert len(calls) == 1
        assert await cache.get(first.params_hash) is not None

        second = await self._calculate(service, cache)
        assert len(calls) == 1
        assert second.payload == first.payload
        assert second.params_hash == first.params_hash
        assert second.kpi_summary == first.kpi_summary
        assert second.duration_ms == 0

    async def test_cache_ignored_when_persisting(self, monkeypatch) -> None:
        """落库路径（persist=True）不走试算缓存：每次都权威重算。"""
        cache = InMemoryResultCache()
        service = self._service()

        calls: list = []
        original = calc_service_module.compute_all

        def counting(params, options):
            calls.append(params)
            return original(params, options)

        monkeypatch.setattr(calc_service_module, "compute_all", counting)

        service.results = MagicMock()
        service.results.create = AsyncMock(return_value=SimpleNamespace(id=1))
        service.cashflows = MagicMock()
        service.cashflows.bulk_insert = AsyncMock()

        await service.calculate(
            tenant_id=1,
            user_id=1,
            params_dict=params_to_dict(default_params()),
            options=CalcOptionsIn(),
            scenario_id=5,
            persist=True,
            result_cache=cache,
        )
        await service.calculate(
            tenant_id=1,
            user_id=1,
            params_dict=params_to_dict(default_params()),
            options=CalcOptionsIn(),
            scenario_id=5,
            persist=True,
            result_cache=cache,
        )
        assert len(calls) == 2
        assert await cache.get(service.results.create.call_args.kwargs["params_hash"]) is None


class TestRedisAdaptersFailOpen:
    async def test_result_cache_fail_open_on_connection_error(self) -> None:
        """Redis 故障：读回落 None（重算）、写静默失败——不影响试算。"""
        broken = MagicMock()
        broken.get = AsyncMock(side_effect=ConnectionError("redis down"))
        broken.set = AsyncMock(side_effect=ConnectionError("redis down"))
        cache = RedisResultCache(broken)

        assert await cache.get("k") is None
        await cache.set("k", {"a": 1}, 60)

    async def test_token_store_fail_open_on_connection_error(self) -> None:
        """Redis 故障：吊销静默失败、查询不误判——可用性优先。"""
        broken = MagicMock()
        broken.set = AsyncMock(side_effect=ConnectionError("redis down"))
        broken.exists = AsyncMock(side_effect=ConnectionError("redis down"))
        store = RedisTokenStore(broken)

        await store.revoke("jti", 60)
        assert await store.is_revoked("jti") is False
