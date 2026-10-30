"""审计日志。

记录写操作（方案创建/更新/删除、计算、基准库维护、报告导出、成员变更、登录）。
P0 只写不读 UI；P1 起 `audit:read` 权限开放 `GET /audit` 只读列表（版本与审计页 P7）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_roi.infrastructure.db.base import Base, TimestampMixin

ACTION_LOGIN = "auth.login"
ACTION_SCENARIO_CREATE = "scenario.create"
ACTION_SCENARIO_UPDATE = "scenario.update"
ACTION_SCENARIO_DELETE = "scenario.delete"
ACTION_SCENARIO_CALC = "scenario.calc"
ACTION_MEMBER_INVITE = "member.invite"
ACTION_MEMBER_UPDATE = "member.update"
ACTION_MEMBER_DELETE = "member.delete"
ACTION_BENCHMARK_CREATE = "benchmark.create"
ACTION_BENCHMARK_UPDATE = "benchmark.update"
ACTION_BENCHMARK_DELETE = "benchmark.delete"
ACTION_BENCHMARK_PUBLISH = "benchmark.publish"
ACTION_BENCHMARK_ROLLBACK = "benchmark.rollback"
ACTION_BENCHMARK_SYNC = "benchmark.sync"
ACTION_BENCHMARK_AUTHORITY = "benchmark.authority"
ACTION_BENCHMARK_MARKET_SYNC = "benchmark.market_sync"
ACTION_REPORT_EXPORT = "report.export"

ACTION_LABELS: Dict[str, str] = {
    ACTION_LOGIN: "登录",
    ACTION_SCENARIO_CREATE: "创建方案",
    ACTION_SCENARIO_UPDATE: "更新方案",
    ACTION_SCENARIO_DELETE: "删除方案",
    ACTION_SCENARIO_CALC: "执行测算",
    ACTION_MEMBER_INVITE: "邀请成员",
    ACTION_MEMBER_UPDATE: "变更成员",
    ACTION_MEMBER_DELETE: "删除成员",
    ACTION_BENCHMARK_CREATE: "新增基准",
    ACTION_BENCHMARK_UPDATE: "更新基准",
    ACTION_BENCHMARK_DELETE: "删除基准",
    ACTION_BENCHMARK_PUBLISH: "发布基准库版本",
    ACTION_BENCHMARK_ROLLBACK: "回滚基准库版本",
    ACTION_BENCHMARK_SYNC: "采集基准数据",
    ACTION_BENCHMARK_AUTHORITY: "权威价同步",
    ACTION_BENCHMARK_MARKET_SYNC: "租赁价采集应用",
    ACTION_REPORT_EXPORT: "导出报告",
}


class AuditLog(Base, TimestampMixin):
    """审计条目。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_target", "tenant_id", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} target={self.target_type}:{self.target_id}>"
