"""鉴权相关 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """登录请求。`tenant_slug` 可选：同邮箱存在多租户时用于消歧。"""

    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    tenant_slug: Optional[str] = None


class TenantBrief(BaseModel):
    """租户摘要。"""

    id: int
    name: str
    slug: str


class UserOut(BaseModel):
    """当前用户信息。"""

    id: int
    email: str
    display_name: str = ""
    role: str
    permissions: List[str] = Field(default_factory=list)
    is_super: bool = False
    is_active: bool = True
    tenant: Optional[TenantBrief] = None
    last_login_at: Optional[datetime] = None


class UserCreateIn(BaseModel):
    """新增成员（仅 owner，member:manage）。"""

    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    role: str = "viewer"


class UserUpdateIn(BaseModel):
    """更新成员：显示名 / 角色 / 启用状态；password 提供时重置密码。"""

    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class TokenResponse(BaseModel):
    """登录成功返回。"""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 0
    user: UserOut


class RefreshRequest(BaseModel):
    """刷新令牌请求。"""

    refresh_token: str
