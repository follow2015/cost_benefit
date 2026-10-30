"""P1 迁移：基准库四表新增 `version` 修订号列。

背景（PRD REQ-13）：基准库条目需带「生效日期 / 来源 / 版本」三件套。
`as_of`（生效日期）与 `source`（来源）在 0001 已存在，本迁移补齐 `version`。

语义：条目创建为 1，每次写入自增；历史方案参数为「值快照」，不受基准库改动影响。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0002_benchmark_version"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLES = (
    "benchmark_gpu",
    "benchmark_model",
    "benchmark_cloud_price",
    "benchmark_api_price",
)


def upgrade() -> None:
    """为四张基准表补 `version` 列（非空，默认 1）。

    幂等：0001 通过 ``Base.metadata.create_all`` 落地模型，若模型已含该列则跳过，
    避免与自动建表重复导致 ``DuplicateColumnError``。
    """
    bind = op.get_bind()
    for table in _TABLES:
        exists = bind.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'version'"
            ),
            {"t": table},
        ).scalar()
        if not exists:
            op.add_column(
                table,
                sa.Column(
                    "version",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                ),
            )


def downgrade() -> None:
    """回滚：删除 `version` 列（幂等）。"""
    for table in _TABLES:
        op.execute(
            text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "version"')
        )

