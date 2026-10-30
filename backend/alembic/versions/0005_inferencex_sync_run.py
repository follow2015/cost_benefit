"""迁移：新增 InferenceX 采集运行记录表 `inferencex_sync_run`。

背景：基准库的 InferenceX 成本标杆此前靠人工跑 ``scripts/seed_inferencex.py``
更新（数据日期停在 2026-08-01）。本表支撑「每 7 天自动采集 + 前台手动触发」：
每次采集（含失败/跳过）都留一条记录，前端据此展示「上次何时采、采到几条、
为什么失败」。

为什么不复用 ``audit_log``：该表 ``tenant_id`` 为 NOT NULL + FK，定时任务（无租户）
写不进去；且审计是租户可见性模型，不适合当系统任务日志。

幂等（对齐 0002/0003 惯例）：全新库上 0001 的 ``create_all`` 与 RLS 语句已包含本表
与策略（``rls_policy.SHARED_READ_TABLES`` 已登记），故建表与建策略均做存在性检查。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from ai_roi.infrastructure.db.rls_policy import downgrade_statements as rls_downgrade
from ai_roi.infrastructure.db.rls_policy import shared_read_policies

revision = "0005_inferencex_sync_run"
down_revision = "0004_merge_heads"
branch_labels = None
depends_on = None


def _table_exists(bind, table: str) -> bool:
    """表存在性检查（新库上 0001 的 create_all 已含本表）。"""
    return bool(
        bind.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = current_schema()"
            ),
            {"t": table},
        ).scalar()
    )


def _ensure_policy(statement: str) -> str:
    """把 CREATE POLICY 包成幂等 DO 块（策略已存在则跳过）。"""
    stripped = statement.strip()
    if not stripped.startswith("CREATE POLICY"):
        return statement
    name = stripped.split("CREATE POLICY ", 1)[1].split(" ON ", 1)[0]
    body = stripped.rstrip(";")
    return (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = '{name}') THEN "
        f"{body}; END IF; END $$;"
    )


def upgrade() -> None:
    """建表 + 共享读 RLS（整体幂等）。"""
    bind = op.get_bind()
    if not _table_exists(bind, "inferencex_sync_run"):
        op.create_table(
            "inferencex_sync_run",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.BigInteger(),
                sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("source", sa.String(64), nullable=False, server_default="inferencex"),
            sa.Column("endpoint", sa.String(255), nullable=False, server_default=""),
            sa.Column("trigger", sa.String(16), nullable=False, server_default="scheduled"),
            sa.Column("status", sa.String(16), nullable=False, server_default="running"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("as_of", sa.Date(), nullable=True),
            sa.Column("model_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("platform_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("added", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unchanged", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "detail",
                sa.dialects.postgresql.JSONB(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Index("ix_inferencex_sync_run_started", "started_at"),
            sa.Index("ix_inferencex_sync_run_tenant", "tenant_id"),
        )
    for statement in shared_read_policies("inferencex_sync_run"):
        op.execute(text(_ensure_policy(statement)))


def downgrade() -> None:
    for statement in rls_downgrade():
        if "inferencex_sync_run" in statement:
            op.execute(text(statement))
    op.execute(text("DROP TABLE IF EXISTS inferencex_sync_run"))
