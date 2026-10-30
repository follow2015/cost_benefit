"""Redis 客户端管理（连接池单例 + 优雅降级）。

`REDIS_URL` 未配置时 `get_redis()` 返回 None，各适配器自动退化为
进程内实现（见各模块的 In-Memory 变体）——开发/单测零依赖，
生产配置 Redis 后自动获得跨进程共享能力。
"""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from ai_roi.shared.config import settings

_client: Optional[aioredis.Redis] = None
_probe_failed: bool = False


def redis_enabled() -> bool:
    """是否配置了 Redis 连接串。"""
    return bool(settings.REDIS_URL)


async def get_redis() -> Optional[aioredis.Redis]:
    """返回共享连接池客户端；未配置或探测失败时返回 None（调用方走降级路径）。"""
    global _client, _probe_failed
    if not redis_enabled() or _probe_failed:
        return None
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
        try:
            await _client.ping()
        except Exception:
            try:
                await _client.aclose()
            except Exception:
                pass
            _client = None
            _probe_failed = True
            return None
    return _client


async def close_redis() -> None:
    """关闭连接池（应用 shutdown 时调用）。"""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


def reset_for_testing() -> None:
    """测试辅助：重置单例与失败标记。"""
    global _client, _probe_failed
    _client = None
    _probe_failed = False


__all__ = [
    "redis_enabled",
    "get_redis",
    "close_redis",
    "reset_for_testing",
]
