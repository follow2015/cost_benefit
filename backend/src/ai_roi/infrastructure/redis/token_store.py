"""刷新令牌黑名单（`ports.TokenStore` 的实现）。

语义：refresh 令牌一次性使用（rotation）。签发新令牌对时把旧 refresh
的 `jti` 拉黑，TTL = 该令牌剩余有效期；刷新/鉴权链路先查黑名单。
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from ai_roi.application.ports import TokenStore


class InMemoryTokenStore(TokenStore):
    """进程内黑名单（无 Redis 时的降级实现；多 worker 不共享）。"""

    def __init__(self) -> None:
        self._revoked: Dict[str, float] = {}

    def _gc(self) -> None:
        now = time.time()
        for jti, expires_at in list(self._revoked.items()):
            if expires_at <= now:
                del self._revoked[jti]

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        self._gc()
        self._revoked[jti] = time.time() + max(1, ttl_seconds)

    async def is_revoked(self, jti: str) -> bool:
        self._gc()
        return jti in self._revoked


class RedisTokenStore(TokenStore):
    """Redis 黑名单（SET key EX ttl，跨进程/多 worker 共享）。

    fail-open：Redis 故障时 revoke 静默失败（旧令牌自然过期兜底）、
    is_revoked 返回 False（不误伤正常刷新）——可用性优先，安全性由
    refresh 令牌自身短 TTL 与轮换机制共同保证。
    """

    _PREFIX = "auth:revoked:refresh:"

    def __init__(self, client) -> None:
        self._client = client

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        try:
            await self._client.set(self._PREFIX + jti, "1", ex=max(1, int(ttl_seconds)))
        except Exception:
            pass

    async def is_revoked(self, jti: str) -> bool:
        try:
            return bool(await self._client.exists(self._PREFIX + jti))
        except Exception:
            return False


_store: Optional[TokenStore] = None


async def get_token_store() -> TokenStore:
    """依赖注入入口：有 Redis 用 Redis 实现，否则进程内实现。"""
    global _store
    if _store is None:
        from ai_roi.infrastructure.redis.client import get_redis

        client = await get_redis()
        _store = RedisTokenStore(client) if client is not None else InMemoryTokenStore()
    return _store


def reset_for_testing() -> None:
    """测试辅助。"""
    global _store
    _store = None


__all__ = [
    "InMemoryTokenStore",
    "RedisTokenStore",
    "get_token_store",
    "reset_for_testing",
]
