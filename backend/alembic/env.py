"""Alembic 运行环境。

使用同步 psycopg/pg8000 驱动会引入额外依赖，因此这里统一走 **asyncpg + 异步 engine**，
由 `run_async_migrations` 驱动，避免为迁移单独安装同步驱动。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from ai_roi.shared.config import settings
from ai_roi.infrastructure.db.base import Base

import ai_roi.infrastructure.db.models  # noqa: F401  pylint: disable=unused-import

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    """跳过 cashflow_row 的哈希分区子表（由手写 DDL 管理，不参与 autogenerate）。"""
    if type_ == "table" and name and name.startswith("cashflow_row_p"):
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式：输出 SQL 而不连库。"""
    context.configure(
        url=settings.DATABASE_URL.replace("+asyncpg", ""),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在给定连接上执行迁移。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步在线迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
