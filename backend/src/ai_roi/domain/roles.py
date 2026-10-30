"""角色与权限（RBAC 领域词汇）。

原定义在 ORM 模型 `models/tenant.py`；角色/权限点是纯领域概念，
提升到 domain 后应用层与基础设施层均可依赖，模型仅做再导出兼容。
"""

from __future__ import annotations

from typing import Dict, List

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ALL_ROLES: List[str] = [ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER]

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    ROLE_OWNER: [
        "scenario:read",
        "scenario:write",
        "scenario:delete",
        "scenario:calc",
        "benchmark:read",
        "benchmark:write",
        "member:manage",
        "audit:read",
    ],
    ROLE_EDITOR: [
        "scenario:read",
        "scenario:write",
        "scenario:calc",
        "benchmark:read",
    ],
    ROLE_VIEWER: ["scenario:read", "benchmark:read"],
}

__all__ = [
    "ROLE_OWNER",
    "ROLE_EDITOR",
    "ROLE_VIEWER",
    "ALL_ROLES",
    "ROLE_PERMISSIONS",
]
