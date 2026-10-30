"""安全基础设施：JWT 令牌 + 密码哈希。

两个适配器各自独立、可单测：
- `passwords`：pbkdf2_sha256 密码哈希（stdlib 实现，无第三方依赖）；
- `jwt`：access/refresh 令牌签发与校验。

本包 `__init__` 向后兼容地再导出两模块的全部公开符号，
调用方统一 `from ai_roi.infrastructure.security import ...` 即可。
"""

from ai_roi.infrastructure.security.jwt import create_token, decode_token
from ai_roi.infrastructure.security.passwords import hash_password, verify_password

__all__ = [
    "create_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
