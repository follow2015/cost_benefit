"""应用层请求上下文（审计/日志用，纯数据结构）。

原定义在接口层 `deps`，但审计用例（`use_cases/audit_service`）需要它，
放在这里可避免 application → interfaces 的反向依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RequestContext:
    """请求级上下文，供审计与日志使用。"""

    user_id: Optional[int] = None
    user_email: str = ""
    tenant_id: Optional[int] = None
    role: str = ""
    ip: str = ""
    user_agent: str = ""


__all__ = ["RequestContext"]
