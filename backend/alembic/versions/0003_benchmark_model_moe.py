"""C-2/C-3 迁移：benchmark_model 新增 MoE / 量化 / 上下文 / PD 分离字段。

背景（inferencex-analysis-recommendations.md C-2/C-3/E-8）：
- active_params_b：MoE 激活参数（NULL ⇒ 回退 params_b 稠密语义）；
- is_moe：是否混合专家模型；
- quant：量化/精度（FP4/FP8/...，对齐 VALID_QUANTS）；
- ctx_default：默认上下文长度（token），联动长上下文成本曲线（C-4）；
- spec_method：投机解码方法（MTP/STP/EAGLE/none）；
- disagg_support：是否支持 prefill/decode 分离（E-11）。

幂等：逐列检查 information_schema，已存在则跳过，避免重复加列报错。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0003_benchmark_model_moe"
down_revision = "0002_benchmark_version"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("active_params_b", sa.Numeric(12, 2), True, None),
    ("is_moe", sa.Boolean(), False, "false"),
    ("quant", sa.String(16), True, None),
    ("ctx_default", sa.Integer(), True, None),
    ("spec_method", sa.String(16), True, None),
    ("disagg_support", sa.Boolean(), False, "false"),
)


def upgrade() -> None:
    """为 benchmark_model 补 C-2/C-3/E-8 字段（幂等，新增列一律可空）。"""
    bind = op.get_bind()
    existing = set(
        r[0]
        for r in bind.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'benchmark_model'"
            )
        ).fetchall()
    )
    for name, col_type, _not_null, default in _COLUMNS:
        if name in existing:
            continue
        op.add_column("benchmark_model", sa.Column(name, col_type, nullable=True))
        if default is not None:
            op.execute(
                text(f'ALTER TABLE "benchmark_model" ALTER COLUMN "{name}" SET DEFAULT {default}')
            )
            op.execute(
                text(f'UPDATE "benchmark_model" SET "{name}" = {default} WHERE "{name}" IS NULL')
            )


def downgrade() -> None:
    """回滚：删除新增列（幂等）。"""
    for name, _col_type, _not_null, _default in _COLUMNS:
        op.execute(
            text(f'ALTER TABLE "benchmark_model" DROP COLUMN IF EXISTS "{name}"')
        )
