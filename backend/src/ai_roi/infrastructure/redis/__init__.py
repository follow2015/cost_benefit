"""Redis 适配器四件套：客户端 / 令牌黑名单 / 失败限流 / 试算缓存。

均实现 `ai_roi.application.ports` 声明的对应端口；
未配置 `REDIS_URL` 时自动退化为进程内实现，接口签名不变。
"""

from ai_roi.infrastructure.redis.cache import (
    DEFAULT_TTL,
    InMemoryResultCache,
    RedisResultCache,
    get_result_cache,
)
from ai_roi.infrastructure.redis.client import (
    close_redis,
    get_redis,
    redis_enabled,
)
from ai_roi.infrastructure.redis.rate_limiter import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
)
from ai_roi.infrastructure.redis.token_store import (
    InMemoryTokenStore,
    RedisTokenStore,
    get_token_store,
)

__all__ = [
    "DEFAULT_TTL",
    "InMemoryResultCache",
    "RedisResultCache",
    "get_result_cache",
    "close_redis",
    "get_redis",
    "redis_enabled",
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "get_rate_limiter",
    "InMemoryTokenStore",
    "RedisTokenStore",
    "get_token_store",
]
