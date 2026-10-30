"""试算结果缓存（`ports.ResultCache` 的实现）。

键 = 参数指纹（`calc_service.params_fingerprint`：参数 + 选项 + 引擎版本 +
公式 spec 版本），值 = JSON 化载荷。同键必同值（纯函数），因此缓存命中
不会改变任何计算结果，只省一次 CPU（引擎重算）。
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from ai_roi.application.ports import RESULT_CACHE_DEFAULT_TTL, ResultCache

DEFAULT_TTL = RESULT_CACHE_DEFAULT_TTL


class InMemoryResultCache(ResultCache):
    """进程内 LRU 简化版（有界字典 + TTL，无 Redis 时的降级实现）。"""

    def __init__(self, max_entries: int = 256) -> None:
        self._max = max_entries
        self._store: Dict[str, tuple] = {}

    def _gc(self) -> None:
        import time

        now = time.time()
        for key, (_, expires_at) in list(self._store.items()):
            if expires_at <= now:
                del self._store[key]

    async def get(self, key: str) -> Optional[Dict[str, object]]:
        self._gc()
        item = self._store.get(key)
        return item[0] if item else None

    async def set(self, key: str, value: Dict[str, object], ttl_seconds: int) -> None:
        import time

        self._gc()
        if len(self._store) >= self._max and key not in self._store:
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = (value, time.time() + max(1, ttl_seconds))


class RedisResultCache(ResultCache):
    """Redis 缓存（JSON 序列化，跨进程共享）。

    fail-open：Redis 故障时读返回 None（回落重算）、写静默失败——
    缓存是纯 CPU 优化，任何故障都不得影响试算结果正确性。
    """

    _PREFIX = "calc:preview:"

    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> Optional[Dict[str, object]]:
        try:
            raw = await self._client.get(self._PREFIX + key)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: Dict[str, object], ttl_seconds: int) -> None:
        try:
            await self._client.set(
                self._PREFIX + key,
                json.dumps(value, ensure_ascii=False),
                ex=max(1, int(ttl_seconds)),
            )
        except Exception:
            pass


_cache: Optional[ResultCache] = None


async def get_result_cache() -> ResultCache:
    """依赖注入入口。"""
    global _cache
    if _cache is None:
        from ai_roi.infrastructure.redis.client import get_redis

        client = await get_redis()
        _cache = RedisResultCache(client) if client is not None else InMemoryResultCache()
    return _cache


def reset_for_testing() -> None:
    """测试辅助。"""
    global _cache
    _cache = None


__all__ = [
    "DEFAULT_TTL",
    "InMemoryResultCache",
    "RedisResultCache",
    "get_result_cache",
    "reset_for_testing",
]
