"""后台定时任务：InferenceX 基准每 7 天自动采集一次。

为什么不用外部 cron / 系统定时器：
- 项目当前是单服务形态（uvicorn 直接跑），引入系统 crontab 会把部署要求从
  「一条命令起服务」抬高到「配 crontab + 保证 PATH/venv 一致」，与安装器目标冲突；
- 采集逻辑本来就依赖应用配置、DB 连接与 RLS 上下文，放在进程内可直接复用。

多进程/多副本下的重复执行由 PG advisory lock 兜底（见用例层），本模块只负责
「按时唤醒」——唤醒后是否真采，由用例层按「上次真正执行时间 + 周期」判定，
因此重启、扩容、手动触发都不会造成重复采集或漏采。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog

from ai_roi.application.use_cases.inferencex_sync_service import (
    InferencexSyncService,
)
from ai_roi.domain.inferencex import (
    DEFAULT_INTERVAL_DAYS,
    STATUS_SKIPPED,
    TRIGGER_SCHEDULED,
)
from ai_roi.infrastructure.collectors.inferencex import InferencexClient
from ai_roi.infrastructure.db.uow import unit_of_work
from ai_roi.shared.config import settings

logger = structlog.get_logger(__name__)

MAX_SLEEP_SECONDS = 3600
MIN_SLEEP_SECONDS = 60


class InferencexScheduler:
    """常驻采集调度器（随应用生命周期启停）。"""

    def __init__(
        self,
        *,
        interval_days: int = DEFAULT_INTERVAL_DAYS,
        base_url: Optional[str] = None,
        fx_usd_cny: Optional[Decimal] = None,
        enabled: bool = True,
    ) -> None:
        self.interval_days = max(1, int(interval_days))
        self.base_url = base_url or settings.INFERENCEX_BASE_URL
        self.fx_usd_cny = fx_usd_cny or Decimal(settings.inferencex_fx)
        self.enabled = enabled
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = False

    async def start(self) -> None:
        """启动后台循环（不阻塞应用启动）。"""
        if not self.enabled:
            logger.info("inferencex.scheduler.disabled")
            return
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="inferencex-scheduler")
        logger.info("inferencex.scheduler.started", interval_days=self.interval_days)

    async def stop(self) -> None:
        """停止后台循环（应用关闭时调用，等待任务退出）。"""
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 —— 关闭阶段不因清理日志失败而中断
            logger.exception("inferencex.scheduler.stop_error")
        finally:
            self._task = None

    async def _loop(self) -> None:
        """循环：唤醒 → 判定 → 按需采集 → 计算下次休眠。"""
        while not self._stopping:
            delay = MIN_SLEEP_SECONDS
            try:
                delay = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 —— 单次失败不能杀死循环
                logger.exception("inferencex.scheduler.tick_error")
            await asyncio.sleep(max(MIN_SLEEP_SECONDS, min(delay, MAX_SLEEP_SECONDS)))

    async def _tick(self) -> int:
        """执行一次判定 +（必要时）采集，返回建议的下次休眠秒数。"""
        async with unit_of_work(is_super=True) as uow:
            service = InferencexSyncService(
                uow,
                InferencexClient(self.base_url),
                fx_usd_cny=self.fx_usd_cny,
                interval_days=self.interval_days,
                base_url=self.base_url,
            )
            outcome = await service.run(trigger=TRIGGER_SCHEDULED, force=False)

        if outcome.status == STATUS_SKIPPED and outcome.next_run_at is not None:
            remaining = (
                outcome.next_run_at - datetime.now(timezone.utc)
            ).total_seconds()
            logger.info(
                "inferencex.scheduler.not_due", next_run_at=outcome.next_run_at.isoformat()
            )
            return int(max(remaining, MIN_SLEEP_SECONDS))
        return int(self.interval_days * 86400)


_scheduler: Optional[InferencexScheduler] = None


def get_scheduler() -> InferencexScheduler:
    """进程内单例（lifespan 启停同一实例）。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = InferencexScheduler(
            interval_days=settings.INFERENCEX_SYNC_INTERVAL_DAYS,
            base_url=settings.INFERENCEX_BASE_URL,
            enabled=settings.INFERENCEX_SYNC_ENABLED,
        )
    return _scheduler


__all__ = ["InferencexScheduler", "get_scheduler"]
