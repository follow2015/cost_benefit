"""InferenceX 基准采集用例：拉取 → 解析 → 合并写回 → 留痕。

职责边界：
- 网络与解析细节都不在本层：客户端由调用方注入（端口 + 适配器），
  解析/合并规则是 ``domain.benchmark.inferencex`` 的纯函数；
- 本层只编排「该不该跑 → 加锁 → 采 → 写 → 记账」。

两条重要设计决定：
1. **周期判定依据「最近一次真正执行」而非「最近一次记录」**：若把 skipped 也算进
   去，「没到周期」的结论会被自己不断续期，数据永远不更新；
2. **采集不 bump 条目 version**：version 表示人工维护口径的修订号，自动刷新属于
   数据同步，留痕在采集记录里；否则基准库页面的版本历史会被自动任务刷成噪音。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from ai_roi.domain.inferencex import (
    COVERAGE_COVERED,
    COVERAGE_LABELS,
    META_COST_CNY,
    META_MANUAL_SOURCE,
    META_UPSTREAM_MODELS,
    SOURCE_ENDPOINT,
    SOURCE_ID,
    SOURCE_ROW_PREFIX,
    SOURCE_SITE,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
    build_upstream_inventory,
    classify_model_coverage,
    group_by_model,
    inventory_from_dicts,
    merge_model_meta,
    parse_overview,
)
from ai_roi.domain.errors import DomainError, UpstreamUnavailableError

logger = structlog.get_logger(__name__)

SYNC_LOCK_KEY = 20261001


@dataclass
class SyncOutcome:
    """一次采集的结果（前端直接消费，字段名即契约）。"""

    status: str
    trigger: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    as_of: Optional[date] = None
    model_count: int = 0
    platform_count: int = 0
    point_count: int = 0
    matched_count: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    error: str = ""
    unmatched: List[str] = field(default_factory=list)
    upstream_models: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    run_id: Optional[int] = None
    endpoint: str = ""
    next_run_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """接口层序列化（日期/时间一律 ISO 字符串）。"""
        return {
            "status": self.status,
            "trigger": self.trigger,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "model_count": self.model_count,
            "platform_count": self.platform_count,
            "point_count": self.point_count,
            "matched_count": self.matched_count,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "error": self.error,
            "unmatched": list(self.unmatched),
            "upstream_models": [dict(item) for item in self.upstream_models],
            "warnings": list(self.warnings),
            "run_id": self.run_id,
            "endpoint": self.endpoint,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
        }


class InferencexSyncService:
    """采集编排。`client` 只要求有 ``fetch_overview()`` 与 ``endpoint``。"""

    def __init__(
        self,
        uow: Any,
        client: Any,
        *,
        fx_usd_cny: Decimal = Decimal("6.68"),
        interval_days: int = 7,
        base_url: str = SOURCE_SITE,
        now: Optional[datetime] = None,
    ) -> None:
        self.uow = uow
        self.client = client
        self.fx_usd_cny = fx_usd_cny
        self.interval_days = max(1, int(interval_days))
        self.base_url = base_url.rstrip("/")
        self._now = now

    def _now_utc(self) -> datetime:
        """当前时间（测试可注入固定时钟）。"""
        return self._now or datetime.now(timezone.utc)

    @property
    def endpoint(self) -> str:
        """接口地址（客户端可覆盖，缺省拼站点默认路径）。"""
        return getattr(self.client, "endpoint", f"{self.base_url}{SOURCE_ENDPOINT}")

    async def _last_effective(self) -> Optional[Any]:
        return await self.uow.inferencex_runs.latest_effective()

    def _next_run_at(self, last_started: Optional[datetime]) -> Optional[datetime]:
        """下一轮计划时间：上次执行 + 周期。"""
        if last_started is None:
            return None
        return last_started + timedelta(days=self.interval_days)

    async def status(self) -> Dict[str, Any]:
        """采集状态总览（前端卡片/抽屉用）。"""
        repo = self.uow.inferencex_runs
        latest = await repo.latest()
        last_effective = await repo.latest_effective()
        last_success = await repo.latest_success()
        recent = await repo.list_recent(5)

        now = self._now_utc()
        next_run = self._next_run_at(
            last_effective.started_at if last_effective is not None else None
        )
        due = next_run is None or now >= next_run
        return {
            "source": SOURCE_ID,
            "source_name": "InferenceX（SemiAnalysis）",
            "source_url": self.base_url,
            "endpoint": self.endpoint,
            "interval_days": self.interval_days,
            "fx_usd_cny": str(self.fx_usd_cny),
            "due": due,
            "next_run_at": (next_run.isoformat() if next_run and not due else None),
            "last": self._run_brief(latest),
            "last_success": self._run_brief(last_success),
            "recent": [self._run_brief(row) for row in recent],
        }

    @staticmethod
    def _run_brief(row: Optional[Any]) -> Optional[Dict[str, Any]]:
        """把运行行压成前端需要的精简结构。"""
        if row is None:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "trigger": row.trigger,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "as_of": row.as_of.isoformat() if row.as_of else None,
            "point_count": row.point_count,
            "matched_count": row.matched_count,
            "added": row.added,
            "updated": row.updated,
            "error": row.error or "",
        }

    async def model_coverage(self, tenant_id: Optional[int]) -> Dict[str, Any]:
        """逐行判定模型基准的采集覆盖：哪些已采到、哪些上游不测。

        为什么不能用 ``/sync-status`` 反推：状态里只有「命中 3 个模型」这一个数，
        反推不出剩下那些行到底是不测还是本次缺数——而这正是用户要的答案。
        判据是最近一次**成功**采集记录里的上游模型清单（含 0 成本点的模型）。
        """
        models = await self.uow.benchmarks.list_models(tenant_id)
        run = await self.uow.inferencex_runs.latest_success()
        detail: Dict[str, Any] = dict(getattr(run, "detail", None) or {})
        inventory = inventory_from_dicts(detail.get(META_UPSTREAM_MODELS))
        judgeable = bool(inventory)

        rows = [
            (str(row.code), bool((row.meta or {}).get(META_COST_CNY))) for row in models
        ]
        verdicts = classify_model_coverage(rows, inventory, judgeable=judgeable)
        counts = {status: 0 for status in COVERAGE_LABELS}
        for verdict in verdicts:
            counts[verdict.status] = counts.get(verdict.status, 0) + 1

        return {
            "as_of": run.as_of.isoformat() if run is not None and run.as_of else None,
            "run_id": getattr(run, "id", None),
            "upstream": {
                "model_count": len(inventory),
                "with_value": sum(1 for item in inventory if item.point_count > 0),
                "without_value": [
                    item.slug for item in inventory if item.point_count == 0
                ],
                "unmatched": [str(item) for item in (detail.get("unmatched") or [])],
                "models": [item.to_dict() for item in inventory],
            },
            "judgeable": judgeable,
            "summary": {"total": len(verdicts), **counts},
            "rows": [verdict.to_dict() for verdict in verdicts],
        }

    async def run(
        self,
        *,
        trigger: str = TRIGGER_MANUAL,
        force: bool = True,
        tenant_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        actor_email: str = "",
        ip: str = "",
        user_agent: str = "",
    ) -> SyncOutcome:
        """执行一次采集。

        - ``force=False``（定时任务用）时先判断周期，未到则返回 skipped 且**不落库**；
        - 采集失败不抛异常，而是返回 ``status=failed``：这是「任务结果」而非
          「请求失败」，前端要能拿到原因并提示「沿用上次数据」。
        """
        started = self._now_utc()
        outcome = SyncOutcome(
            status=STATUS_SKIPPED,
            trigger=trigger,
            started_at=started,
            endpoint=self.endpoint,
        )

        if not force:
            last = await self._last_effective()
            next_run = self._next_run_at(last.started_at if last is not None else None)
            if next_run is not None and started < next_run:
                outcome.next_run_at = next_run
                outcome.error = (
                    f"未到采集周期（每 {self.interval_days} 天），"
                    f"下次计划 {next_run.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC"
                )
                return outcome

        repo = self.uow.inferencex_runs
        locked = await repo.try_lock(SYNC_LOCK_KEY)
        if not locked:
            outcome.error = "另一个采集任务正在执行，本次跳过"
            return outcome

        run_row: Optional[Any] = None
        try:
            run_row = await repo.record(
                tenant_id=tenant_id,
                source=SOURCE_ID,
                endpoint=self.endpoint,
                trigger=trigger,
                status=STATUS_RUNNING,
                started_at=started,
                detail={},
            )
            outcome.run_id = run_row.id

            payload = await self.client.fetch_overview()
            parsed = parse_overview(payload)
            outcome.model_count = parsed.model_count
            outcome.platform_count = parsed.platform_count
            outcome.point_count = len(parsed.points)
            outcome.skipped = parsed.skipped
            outcome.warnings = list(parsed.warnings)
            inventory = build_upstream_inventory(parsed)
            outcome.upstream_models = [item.to_dict() for item in inventory]
            if any(item.point_count == 0 for item in inventory):
                empty = [item.slug for item in inventory if item.point_count == 0]
                outcome.warnings.append(
                    f"{len(empty)} 个上游模型本次无可用成本值（在测但没给数）："
                    + "、".join(empty[:6])
                )

            if not parsed.points:
                outcome.status = STATUS_FAILED
                outcome.error = "上游未返回任何可用成本数据（接口结构可能已变更）"
                await self._finish(run_row, outcome, started)
                return outcome

            matched, unmatched, latest, counts = await self._write_back(
                parsed.points, started
            )
            outcome.matched_count = matched
            outcome.unmatched = unmatched
            outcome.as_of = latest
            outcome.added, outcome.updated, outcome.unchanged = counts

            if matched == 0:
                outcome.status = STATUS_FAILED
                outcome.error = (
                    "上游模型与基准库无交集：请先在基准库补录对应模型 code"
                )
            else:
                outcome.status = STATUS_SUCCESS
                if unmatched:
                    outcome.warnings.append(
                        f"{len(unmatched)} 个上游模型在基准库无同名 code（未写入）："
                        + "、".join(unmatched[:8])
                    )
                if parsed.skipped:
                    outcome.warnings.append(
                        f"{parsed.skipped} 个平台本次无成本值（上游数据缺口，保留旧值）"
                    )

            await self._finish(run_row, outcome, started)
            await self._audit(outcome, tenant_id, actor_id, actor_email, ip, user_agent)
            logger.info(
                "inferencex.sync",
                status=outcome.status,
                points=outcome.point_count,
                matched=outcome.matched_count,
                added=outcome.added,
                updated=outcome.updated,
            )
            return outcome
        except UpstreamUnavailableError as exc:
            outcome.status = STATUS_FAILED
            outcome.error = exc.message
            outcome.warnings.append(str(exc.detail.get("reason") or ""))
            await self._finish(run_row, outcome, started)
            logger.warning("inferencex.sync.upstream_down", reason=exc.detail)
            return outcome
        except DomainError as exc:
            outcome.status = STATUS_FAILED
            outcome.error = exc.message
            await self._finish(run_row, outcome, started)
            logger.warning("inferencex.sync.domain_error", error=exc.message)
            return outcome
        except Exception as exc:  # noqa: BLE001 —— 采集失败不得拖垮请求/调度循环
            outcome.status = STATUS_FAILED
            outcome.error = f"采集异常：{type(exc).__name__}: {exc}"
            await self._finish(run_row, outcome, started)
            logger.exception("inferencex.sync.error")
            return outcome
        finally:
            await repo.unlock(SYNC_LOCK_KEY)

    async def _write_back(
        self, points: Any, synced_at: datetime
    ) -> "tuple[int, List[str], Optional[date], tuple[int, int, int]]":
        """把观测点写回平台内置模型。

        Returns:
            ``(匹配模型数, 未匹配模型 code, 最新证据日期, (新增, 更新, 未变))``
        """
        matched = 0
        unmatched: List[str] = []
        latest: Optional[date] = None
        added = updated = unchanged = 0
        for model_code, group in group_by_model(points).items():
            row = await self.uow.benchmarks.find_builtin_model(model_code)
            if row is None:
                unmatched.append(model_code)
                continue
            merged = merge_model_meta(
                row.meta,
                group,
                fx_usd_cny=self.fx_usd_cny,
                synced_at=synced_at,
                source_url=self.base_url,
            )
            meta = merged.meta
            if merged.as_of is not None:
                row.as_of = merged.as_of
                previous = (row.source or "").strip()
                if previous and not previous.startswith(SOURCE_ROW_PREFIX):
                    meta.setdefault(META_MANUAL_SOURCE, previous)
                row.source = f"{SOURCE_ROW_PREFIX}{merged.as_of.isoformat()}"
                if latest is None or merged.as_of > latest:
                    latest = merged.as_of
            row.meta = meta
            added += merged.added
            updated += merged.updated
            unchanged += merged.unchanged
            matched += 1
        await self.uow.session.flush()
        return matched, unmatched, latest, (added, updated, unchanged)

    async def _finish(
        self, run_row: Optional[Any], outcome: SyncOutcome, started: datetime
    ) -> None:
        """收尾：把计数与结论写进本次运行记录。"""
        finished = self._now_utc()
        outcome.finished_at = finished
        if run_row is None:
            return
        run_row.status = outcome.status
        run_row.finished_at = finished
        run_row.as_of = outcome.as_of
        run_row.model_count = outcome.model_count
        run_row.platform_count = outcome.platform_count
        run_row.point_count = outcome.point_count
        run_row.matched_count = outcome.matched_count
        run_row.added = outcome.added
        run_row.updated = outcome.updated
        run_row.unchanged = outcome.unchanged
        run_row.skipped = outcome.skipped
        run_row.error = outcome.error[:2000]
        run_row.detail = {
            "unmatched": outcome.unmatched,
            META_UPSTREAM_MODELS: outcome.upstream_models,
            "warnings": [item for item in outcome.warnings if item],
            "source_url": self.base_url,
        }
        await self.uow.session.flush()

    async def _audit(
        self,
        outcome: SyncOutcome,
        tenant_id: Optional[int],
        actor_id: Optional[int],
        actor_email: str,
        ip: str,
        user_agent: str,
    ) -> None:
        """手动触发记审计（定时任务无租户，只留采集记录）。"""
        if tenant_id is None:
            return
        await self.uow.audit.write(
            tenant_id=tenant_id,
            action="benchmark.sync",
            actor_id=actor_id,
            actor_email=actor_email,
            target_type="benchmark_source",
            target_id=outcome.run_id,
            detail={
                "status": outcome.status,
                "as_of": outcome.as_of.isoformat() if outcome.as_of else None,
                "point_count": outcome.point_count,
                "matched_count": outcome.matched_count,
                "added": outcome.added,
                "updated": outcome.updated,
                "source_url": self.base_url,
            },
            ip=ip,
            user_agent=user_agent,
        )


__all__ = ["InferencexSyncService", "SyncOutcome", "SYNC_LOCK_KEY"]
