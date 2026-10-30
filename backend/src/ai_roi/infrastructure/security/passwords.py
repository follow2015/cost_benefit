"""密码哈希适配器（pbkdf2_sha256）。

使用 stdlib `hashlib.pbkdf2_hmac`（sha256, 200k 迭代），避免 passlib/bcrypt
的版本兼容问题，保证 `pip install -r requirements.txt` 后即可运行。
哈希串格式：`pbkdf2_sha256$<iterations>$<salt_hex>$<dk_hex>`。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO_TAG = "pbkdf2_sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """生成密码哈希。"""
    if not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO_TAG}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """校验密码（常量时间比较）。"""
    try:
        tag, iterations, salt_hex, dk_hex = hashed.split("$")
    except ValueError:
        return False
    if tag != _ALGO_TAG:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(dk.hex(), dk_hex)
