"""P1 迁移：新增组网配套目录表 `network_catalog`（配件库）。

背景（2026-08-19 用户决策）：BOM 展示页需要算力/存储/管理交换机分层 + 线缆明细 +
配套价格表。价格来源策略为「默认维持代码经验常量；配件库有数据时用库内价格」。
本表与 benchmark 同构：平台内置（tenant_id IS NULL）全租户可读、仅超管可写；
租户自建仅租户可读（RLS 已在 benchmark 策略中放行 network_catalog 表）。

幂等（对齐 0002/0003_moe 惯例）：全新库上 0001 的 ``create_all`` 与 RLS 语句
已包含本表与策略，故建表与建策略均做存在性检查——旧库（0001 执行早于模型存在）
补齐、新库跳过，``alembic upgrade head`` 可从零重复执行。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from ai_roi.infrastructure.db.rls_policy import downgrade_statements as rls_downgrade
from ai_roi.infrastructure.db.rls_policy import shared_read_policies

revision = "0003_network_catalog"
down_revision = "0002_benchmark_version"
branch_labels = None
depends_on = None


def _table_exists(bind, table: str) -> bool:
    """表存在性检查（与 0002 逐列检查同风格：新库上 0001 的 create_all 已含本表）。"""
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
    """把 CREATE POLICY 包成幂等 DO 块（策略已存在则跳过）。

    背景：`rls_policy.upgrade_statements()`（0001 执行）的 SHARED_READ_TABLES
    已包含 network_catalog——全新库上策略由 0001 落地，本迁移仅对「0001 执行于
    模型存在之前」的旧库补齐。ALTER TABLE ... ENABLE/FORCE RLS 本身幂等，原样透传。
    """
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
    if not _table_exists(bind, "network_catalog"):
        op.create_table(
            "network_catalog",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("price_cny", sa.Numeric(18, 2), nullable=False),
            sa.Column("unit", sa.String(32), nullable=False, server_default="台"),
            sa.Column("spec", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("source", sa.String(255), nullable=False, server_default=""),
            sa.Column("as_of", sa.Date(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "category", "code", name="uq_network_catalog_tenant_category_code"),
            sa.Index("ix_network_catalog_tenant", "tenant_id"),
        )
    for statement in shared_read_policies("network_catalog"):
        op.execute(text(_ensure_policy(statement)))


def downgrade() -> None:
    for statement in rls_downgrade():
        if "network_catalog" in statement:
            op.execute(text(statement))
    op.execute(text("DROP TABLE IF EXISTS network_catalog"))
