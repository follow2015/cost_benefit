"""失败限流器（`ports.RateLimiter` 的实现）。

只统计**失败**次数（登录密码错误等），成功不计入——避免误伤正常用户。
fail-open：Redis 异常时放行（可用性优先），由业务层的账户锁定策略兜底。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from ai_roi.application.ports import RateLimiter


class InMemoryRateLimiter(RateLimiter):
    """进程内滑动窗口（无 Redis 时的降级实现）。"""

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = {}

    def _window(self, key: str, window_seconds: int) -> List[float]:
        now = time.time()
        hits = [ts for ts in self._hits.get(key, []) if now - ts < window_seconds]
        self._hits[key] = hits
        return hits

    async def hit(self, key: str, window_seconds: int) -> int:
        hits = self._window(key, window_seconds)
        hits.append(time.time())
        return len(hits)

    async def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        return len(self._window(key, window_seconds)) >= limit


class RedisRateLimiter(RateLimiter):
    """Redis 计数窗口（INCR + EXPIRE，跨进程共享）。"""

    _PREFIX = "ratelimit:fail:"

    def __init__(self, client) -> None:
        self._client = client

    async def hit(self, key: str, window_seconds: int) -> int:
        redis_key = self._PREFIX + key
        try:
            count = await self._client.incr(redis_key)
            if count == 1:
                await self._client.expire(redis_key, int(window_seconds))
            return int(count)
        except Exception:
            return 0

    async def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        try:
            count = await self._client.get(self._PREFIX + key)
            return int(count or 0) >= limit
        except Exception:
            return False


_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """依赖注入入口。"""
    global _limiter
    if _limiter is None:
        from ai_roi.infrastructure.redis.client import get_redis

        client = await get_redis()
        _limiter = RedisRateLimiter(client) if client is not None else InMemoryRateLimiter()
    return _limiter


def reset_for_testing() -> None:
    """测试辅助。"""
    global _limiter
    _limiter = None


__all__ = [
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "get_rate_limiter",
    "reset_for_testing",
]
