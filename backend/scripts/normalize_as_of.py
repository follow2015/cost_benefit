"""把基准库的 `as_of` 从「占位常量」修正为「可辩护的日期」（幂等）。

背景见 `ai_roi.domain.as_of` 模块文档：种子数据把 69 条基准的生效日期全写成
`date(2026, 8, 1)`，那是个占位值，导致界面上所有行都显示同一天、
「这条数据有多老」无从判断。

本脚本按 `domain.as_of.infer_as_of` 的规则重算人工来源的行：

| source 形态 | 处理 |
|---|---|
| `inferencex:` / `authority:` 前缀 | **跳过**（自动链路的 as_of 是真采集日） |
| 含 `YYYY-MM-DD` | 取该日 |
| 只含 `YYYY-MM` | 取该月末（「不晚于该月末」） |
| `seed` 等无日期 | 置空（界面显示「未核实」） |

幂等键：`meta.as_of_inferred = "as_of.v1"`，已处理过的行直接跳过；
规则变化时递增版本即可再跑一轮。

只影响平台内置（`tenant_id IS NULL`），租户自建条目不动。

运行（backend/ 下）：

    python -m scripts.normalize_as_of --dry-run
    python -m scripts.normalize_as_of
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from ai_roi.domain.as_of import has_explicit_day, infer_as_of, is_auto_source
from ai_roi.infrastructure.db.models.benchmark import (
    BenchmarkApiPrice,
    BenchmarkCloudPrice,
    BenchmarkGpu,
    BenchmarkModel,
)
from ai_roi.infrastructure.db.uow import unit_of_work

AS_OF_VERSION = "as_of.v1"

TABLES = (
    ("GPU 基准", BenchmarkGpu),
    ("模型基准", BenchmarkModel),
    ("云价基准", BenchmarkCloudPrice),
    ("API 价基准", BenchmarkApiPrice),
)


async def run(dry_run: bool = False) -> dict[str, int]:
    stats = {
        "total": 0,
        "skipped": 0,
        "auto": 0,
        "to_month_end": 0,
        "to_exact": 0,
        "to_null": 0,
        "unchanged": 0,
    }

    async with unit_of_work(is_super=True) as uow:
        for label, model in TABLES:
            rows = (
                (
                    await uow.session.execute(
                        select(model).where(model.tenant_id.is_(None)).order_by(model.id)
                    )
                )
                .unique()
                .scalars()
                .all()
            )
            stats["total"] += len(rows)
            print(f"\n=== {label}（{len(rows)} 行）===")

            for row in rows:
                meta = dict(row.meta or {})

                if is_auto_source(row.source):
                    stats["auto"] += 1
                    print(f"  [自动] {_key(row):22s} {row.source} → 保持 {row.as_of}")
                    continue

                if meta.get("as_of_inferred") == AS_OF_VERSION:
                    stats["skipped"] += 1
                    continue

                before = row.as_of
                after = infer_as_of(row.source)

                if after == before:
                    stats["unchanged"] += 1
                    if not dry_run:
                        meta["as_of_inferred"] = AS_OF_VERSION
                        row.meta = meta
                    continue

                if after is None:
                    kind, stats_key = "置空(未核实)", "to_null"
                elif has_explicit_day(row.source):
                    kind, stats_key = "按文本还原(到日)", "to_exact"
                else:
                    kind, stats_key = "按月还原(取月末)", "to_month_end"
                stats[stats_key] += 1

                if not dry_run:
                    row.as_of = after
                    meta["as_of_inferred"] = AS_OF_VERSION
                    meta["as_of_previous"] = before.isoformat() if before else None
                    meta["as_of_inferred_at"] = datetime.now(timezone.utc).isoformat()
                    row.meta = meta
                    row.version = (row.version or 1) + 1

                print(
                    f"  → {_key(row):22s} {before} → {after}  [{kind}]  "
                    f"source={str(row.source)[:42]}"
                )

        if dry_run:
            print("\n[dry-run] 未落库")
        else:
            await uow.session.flush()

    return stats


def _key(row: object) -> str:
    """行标识：四张表主键字段名不同，统一取一个可读键。"""
    for attr in ("code", "model_code"):
        value = getattr(row, attr, None)
        if value:
            return str(value)
    return f"id={getattr(row, 'id', '?')}"


def main() -> None:
    ap = argparse.ArgumentParser(description="修正基准库生效日期（as_of）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    print(f"=== 修正生效日期（{AS_OF_VERSION}）===")
    stats = asyncio.run(run(dry_run=args.dry_run))
    print(
        f"\n完成：共 {stats['total']} 行 / 自动链路跳过 {stats['auto']}"
        f" / 已处理跳过 {stats['skipped']} / 无需变更 {stats['unchanged']}"
        f"\n      改为月末 {stats['to_month_end']} / 改为确切日 {stats['to_exact']}"
        f" / 置空(未核实) {stats['to_null']}"
    )


if __name__ == "__main__":
    main()
