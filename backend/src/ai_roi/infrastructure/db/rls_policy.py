"""PostgreSQL 行级安全（RLS）策略 DDL 生成。

统一在此维护策略语句，Alembic 迁移与测试 fixture 共用，避免两处漂移。

策略语义：
- 业务表（scenario / scenario_snapshot / calc_result / cashflow_row / audit_log / app_user）：
  `tenant_id = current_setting('app.tenant_id')::bigint`，或 `app.is_super = on` 时放行。
- 基准表（benchmark_*）：额外放行 `tenant_id IS NULL`（平台内置数据全租户可读）；
  写入仅限本租户（内置数据不可被租户改写）。
- `tenant` 表：仅可见自身租户行。

注意：表属主默认绕过 RLS，故迁移中对业务表执行 `FORCE ROW LEVEL SECURITY`，
保证应用连接（即使是属主）同样受策略约束。
"""

from __future__ import annotations

from typing import List

TENANT_SCOPED_TABLES: List[str] = [
    "app_user",
    "scenario",
    "scenario_snapshot",
    "calc_result",
    "cashflow_row",
    "audit_log",
]

SHARED_READ_TABLES: List[str] = [
    "benchmark_gpu",
    "benchmark_model",
    "benchmark_cloud_price",
    "benchmark_api_price",
    "network_catalog",
    "inferencex_sync_run",
]

_CURRENT_TENANT = (
    "NULLIF(current_setting('app.tenant_id', true), '')::bigint"
)
_IS_SUPER = "COALESCE(current_setting('app.is_super', true), 'off') = 'on'"


def _enable(table: str) -> List[str]:
    """启用并强制 RLS。"""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]


def tenant_scoped_policies(table: str) -> List[str]:
    """生成严格租户隔离策略。"""
    statements = _enable(table)
    statements.append(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    return statements


def shared_read_policies(table: str) -> List[str]:
    """生成基准表策略：读放行内置数据，写仅限本租户。"""
    statements = _enable(table)
    statements.append(
        f"CREATE POLICY {table}_read ON {table} FOR SELECT "
        f"USING (tenant_id IS NULL OR tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    statements.append(
        f"CREATE POLICY {table}_write ON {table} FOR INSERT "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    statements.append(
        f"CREATE POLICY {table}_update ON {table} FOR UPDATE "
        f"USING (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    statements.append(
        f"CREATE POLICY {table}_delete ON {table} FOR DELETE "
        f"USING (tenant_id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    return statements


def tenant_table_policies() -> List[str]:
    """`tenant` 表自身：仅可见/可改自身行。"""
    statements = _enable("tenant")
    statements.append(
        f"CREATE POLICY tenant_self_isolation ON tenant "
        f"USING (id = {_CURRENT_TENANT} OR {_IS_SUPER}) "
        f"WITH CHECK (id = {_CURRENT_TENANT} OR {_IS_SUPER});"
    )
    return statements


def upgrade_statements() -> List[str]:
    """迁移 upgrade 阶段应执行的全部 RLS 语句。"""
    statements: List[str] = []
    statements.extend(tenant_table_policies())
    for table in TENANT_SCOPED_TABLES:
        statements.extend(tenant_scoped_policies(table))
    for table in SHARED_READ_TABLES:
        statements.extend(shared_read_policies(table))
    return statements


def downgrade_statements() -> List[str]:
    """迁移 downgrade 阶段应执行的清理语句。"""
    statements: List[str] = ["DROP POLICY IF EXISTS tenant_self_isolation ON tenant;"]
    for table in TENANT_SCOPED_TABLES:
        statements.append(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    for table in SHARED_READ_TABLES:
        for suffix in ("read", "write", "update", "delete"):
            statements.append(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table};")
    for table in ["tenant", *TENANT_SCOPED_TABLES, *SHARED_READ_TABLES]:
        statements.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return statements


CASHFLOW_PARTITIONS: int = 8


def cashflow_partition_statements() -> List[str]:
    """创建 cashflow_row 的哈希分区（分区本身继承父表 RLS）。"""
    statements: List[str] = []
    for index in range(CASHFLOW_PARTITIONS):
        statements.append(
            f"CREATE TABLE IF NOT EXISTS cashflow_row_p{index} "
            f"PARTITION OF cashflow_row "
            f"FOR VALUES WITH (MODULUS {CASHFLOW_PARTITIONS}, REMAINDER {index});"
        )
    return statements
