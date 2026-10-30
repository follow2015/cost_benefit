"""P1 迁移：合并 alembic 双 head（0003_benchmark_model_moe + 0003_network_catalog）。

背景：两个分支同源于 0002_benchmark_version，分别落地基准库 MoE 字段与组网目录表，
互不冲突。本迁移仅作为拓扑合并点，消除 `alembic upgrade head` 的多 head 歧义，
upgrade/downgrade 均为 no-op（实际表变更已由 0003_* 各自落地）。

合并后链路：0001 → 0002 → 0003_benchmark_model_moe ┐
                                              0003_network_catalog ┘ → 0004_merge_heads
"""

from __future__ import annotations

from alembic import op

revision = "0004_merge_heads"
down_revision = ("0003_benchmark_model_moe", "0003_network_catalog")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
