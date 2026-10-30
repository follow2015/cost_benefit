"""InferenceX 采集运行记录仓储。"""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select, text

from ai_roi.domain.inferencex import STATUS_FAILED, STATUS_SKIPPED
from ai_roi.infrastructure.db.models.inferencex_sync import InferencexSyncRun


class InferencexSyncRepository:
    """采集留痕读写（平台级：``tenant_id IS NULL`` 的行为系统任务）。"""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def record(self, **values: Any) -> InferencexSyncRun:
        """写入一条运行记录（调用方负责填 started_at/status）。"""
        row = InferencexSyncRun(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest(self, *, include_skipped: bool = True) -> Optional[InferencexSyncRun]:
        """最近一次运行（含失败；默认也含跳过，用于前端展示「刚检查过」）。"""
        query = select(InferencexSyncRun).order_by(InferencexSyncRun.started_at.desc())
        if not include_skipped:
            query = query.where(InferencexSyncRun.status != STATUS_SKIPPED)
        result = await self.session.execute(query.limit(1))
        return result.unique().scalar_one_or_none()

    async def latest_effective(self) -> Optional[InferencexSyncRun]:
        """最近一次**真正执行过采集**的运行（成功或失败），用于周期判定。

        跳过的记录不算数：否则「没到周期」这个结论会被自己反复续期，
        数据永远不会再更新。
        """
        result = await self.session.execute(
            select(InferencexSyncRun)
            .where(InferencexSyncRun.status.not_in([STATUS_SKIPPED]))
            .order_by(InferencexSyncRun.started_at.desc())
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def latest_success(self) -> Optional[InferencexSyncRun]:
        """最近一次成功采集（决定 ``as_of`` 与「下次采集时间」）。"""
        result = await self.session.execute(
            select(InferencexSyncRun)
            .where(InferencexSyncRun.status != STATUS_FAILED)
            .where(InferencexSyncRun.status.not_in([STATUS_SKIPPED]))
            .order_by(InferencexSyncRun.started_at.desc())
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> List[InferencexSyncRun]:
        """最近若干次运行（前端抽屉展示）。"""
        result = await self.session.execute(
            select(InferencexSyncRun)
            .order_by(InferencexSyncRun.started_at.desc())
            .limit(max(1, min(int(limit or 20), 100)))
        )
        return list(result.unique().scalars().all())

    async def try_lock(self, key: int) -> bool:
        """尝试获取会话级 advisory lock；返回 False 表示已有实例在跑。

        用 PG 会话锁而不是进程内锁：多 worker / 多副本部署下只有一个进程能采，
        否则同一时刻 N 个进程各写一遍并被彼此的版本冲突打断。
        """
        result = await self.session.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": int(key)}
        )
        return bool(result.scalar())

    async def unlock(self, key: int) -> None:
        """释放会话级 advisory lock（连接断开时 PG 也会自动释放）。"""
        await self.session.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": int(key)}
        )


__all__ = ["InferencexSyncRepository"]
