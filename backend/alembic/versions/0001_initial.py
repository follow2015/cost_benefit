"""初始迁移：建表 + RLS 策略 + cashflow_row 哈希分区。

通过 `Base.metadata.create_all` 一次性落地全部模型（含分区父表 cashflow_row），
随后应用 `ai_roi.infrastructure.db.rls_policy` 中的租户隔离策略与基准表共享读策略，
最后创建 cashflow_row 的 8 个 HASH 分区子表。
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from ai_roi.infrastructure.db.base import Base
from ai_roi.infrastructure.db import models  # noqa: F401  确保模型注册到 Base.metadata
from ai_roi.infrastructure.db.rls_policy import (
    CASHFLOW_PARTITIONS,
    cashflow_partition_statements,
    downgrade_statements,
    upgrade_statements,
)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    for stmt in upgrade_statements():
        op.execute(text(stmt))
    for stmt in cashflow_partition_statements():
        op.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    for index in range(CASHFLOW_PARTITIONS):
        op.execute(text(f"DROP TABLE IF EXISTS cashflow_row_p{index};"))
    for stmt in downgrade_statements():
        op.execute(text(stmt))
    Base.metadata.drop_all(bind)
