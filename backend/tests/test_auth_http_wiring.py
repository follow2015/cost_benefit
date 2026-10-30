"""HTTP 层接线冒烟：登录失败限流（429）/ 刷新拒绝 / 错误响应体契约。

scan-secrets: fixtures-allowed —— 本文件故意写入假口令（如 "wrong-pwd"），
用途是验证鉴权失败路径；全部是测试夹具，不是真实凭据。

不碰真实 DB（`get_public_db` 以 mock 覆盖）；限流器强制绑定进程内实现，
使断言不受环境里是否配置了真实 Redis 影响（Redis 计数窗口的语义由
`test_redis_wiring.py` 单独覆盖），验证依赖注入接线与统一错误出口。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from ai_roi.infrastructure.redis.rate_limiter import (
    InMemoryRateLimiter,
    get_rate_limiter,
    reset_for_testing,
)
from ai_roi.interfaces.api.deps import get_public_db
from ai_roi.main import app
from ai_roi.shared.config import settings


def _mock_uow() -> MagicMock:
    """mock UoW：users 仓储为 AsyncMock（find_by_email 返回空 → 登录必失败）。"""
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_email = AsyncMock(return_value=[])
    uow.users = repo
    return uow


@pytest.fixture()
def client():
    app.dependency_overrides[get_public_db] = _mock_uow
    limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    reset_for_testing()


def _login(client: TestClient):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@x.dev", "password": "wrong-pwd"},
    )


class TestLoginFailureRateLimit:
    def test_wrong_password_returns_401_with_error_code(self, client) -> None:
        """密码错误：401 + 统一错误体（error_code=UNAUTHORIZED）。"""
        resp = _login(client)
        assert resp.status_code == 401
        body = resp.json()
        assert body["error_code"] == "UNAUTHORIZED"
        assert body["code"] == "UNAUTHORIZED"

    def test_failures_are_counted_and_throttled_with_429(self, client) -> None:
        """连续失败达阈值后返回 429（只计失败；成功不计入的语义见单测）。"""
        limit = settings.LOGIN_RATE_MAX_FAILURES
        statuses = [_login(client).status_code for _ in range(limit)]
        assert statuses == [401] * limit
        assert _login(client).status_code == 429

        body = _login(client).json()
        assert body["error_code"] == "RATE_LIMITED"

    def test_429_response_is_not_counted_as_new_failure(self, client) -> None:
        """已超限后的请求直接 429，不继续累加（窗口内维持拒绝）。"""
        for _ in range(settings.LOGIN_RATE_MAX_FAILURES):
            _login(client)
        assert _login(client).status_code == 429
        assert _login(client).status_code == 429


class TestRefreshRejection:
    def test_garbage_refresh_token_returns_401(self, client) -> None:
        """无效 refresh 令牌：401 + error_code=UNAUTHORIZED（令牌存储 DI 正常解析）。"""
        resp = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"}
        )
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "UNAUTHORIZED"
