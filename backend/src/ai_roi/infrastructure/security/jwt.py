"""JWT 适配器：access/refresh 令牌签发与校验。

属于基础设施层：只认识 `ai_roi.domain.errors`（领域异常）与 `ai_roi.shared.config`，
不依赖 FastAPI / HTTP 概念。密码哈希见同包 `passwords` 模块。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from ai_roi.domain.errors import UnauthorizedError
from ai_roi.shared.config import settings


def create_token(
    subject: str,
    tenant_id: Optional[int],
    role: str,
    permissions: Optional[Dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
    token_type: str = "access",
) -> str:
    """签发 JWT。`tenant_id` 会被中间件用于 RLS 注入（架构 §4.2）。

    `jti`（token id）是刷新轮换的吊销载体：refresh 换新时旧 jti 进黑名单，
    令牌自然过期后黑名单条目同步失效（TTL = 剩余有效期）。
    """
    now = datetime.now(tz=timezone.utc)
    ttl = expires_minutes or (
        settings.ACCESS_TOKEN_EXPIRE_MINUTES
        if token_type == "access"
        else settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )
    payload: Dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "permissions": permissions or {},
        "type": token_type,
        "jti": secrets.token_hex(8),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> Dict[str, Any]:
    """校验并解析 JWT，失败抛 `UnauthorizedError`。"""
    try:
        payload: Dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("无效的凭证") from exc
    if payload.get("type") != expected_type:
        raise UnauthorizedError("凭证类型不匹配")
    return payload
