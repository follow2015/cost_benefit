"""命令行手动采集一次 InferenceX 基准（与后台定时任务走同一用例）。

用法（backend/ 下）：
    python -m scripts.sync_inferencex            # 强制采集（忽略 7 天周期）
    python -m scripts.sync_inferencex --period   # 按周期判定，未到期则跳过

与 ``scripts.seed_inferencex`` 的分工：
- ``seed_inferencex``：一次性人工校准（含模型规格、GPU 代际等非成本字段），
  数据写死，仅在初次建库/口径变更时执行，**重跑会把 as_of 打回人工日期**；
- 本脚本：只刷新成本标杆（``meta.inferencex_cost_usd_per_mtok``），可随时安全重跑。

日常更新无需跑 CLI：服务启动后每 7 天自动采集一次，基准库页也有「立即采集」按钮。
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from typing import Any

from ai_roi.application.use_cases.inferencex_sync_service import InferencexSyncService
from ai_roi.infrastructure.collectors.inferencex import InferencexClient
from ai_roi.infrastructure.db.uow import unit_of_work
from ai_roi.shared.config import settings


async def _sync(force: bool) -> Any:
    async with unit_of_work(is_super=True) as uow:
        service = InferencexSyncService(
            uow,
            InferencexClient(settings.INFERENCEX_BASE_URL),
            fx_usd_cny=Decimal(settings.INFERENCEX_FX_USD_CNY),
            interval_days=settings.INFERENCEX_SYNC_INTERVAL_DAYS,
            base_url=settings.INFERENCEX_BASE_URL,
        )
        return await service.run(trigger="manual", force=force)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    force = "--period" not in args
    outcome = asyncio.run(_sync(force))

    print(f"[sync_inferencex] 状态：{outcome.status}（trigger={outcome.trigger}）")
    if outcome.status == "skipped":
        print(f"[sync_inferencex] {outcome.error}")
        if outcome.next_run_at:
            print(f"[sync_inferencex] 下次计划：{outcome.next_run_at.isoformat()}")
        return 0
    print(
        f"[sync_inferencex] 成本点 {outcome.point_count} 个 / 命中模型 {outcome.matched_count} 个"
        f"（新增 {outcome.added}、更新 {outcome.updated}、未变 {outcome.unchanged}）"
    )
    if outcome.as_of:
        print(f"[sync_inferencex] 数据生效日：{outcome.as_of.isoformat()}")
    if outcome.unmatched:
        print(f"[sync_inferencex] 未匹配模型：{', '.join(outcome.unmatched)}")
    for warning in outcome.warnings:
        print(f"[sync_inferencex] 提示：{warning}")
    if outcome.error:
        print(f"[sync_inferencex] 错误：{outcome.error}")
    return 0 if outcome.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
