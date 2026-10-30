"""回填基准库模型的 MoE 结构化字段（一次性数据修正，幂等）。

背景：`BenchmarkModel` 在 C-2 订正中新增 `is_moe` / `active_params_b`，
但种子数据只把这两项信息写在 `name` 描述里（如「Kimi K3（2.8T MoE/104B 激活）」），
字段本身留空。引擎 `effective_active_params_b()` 在激活参数为空时回退 `M_param`
（总参数），导致 2.8T 级 MoE 被当稠密 2800B 推导显存与吞吐，量级严重失真。

修正方式：从 `name` 还原（`domain.model_spec.infer_model_spec`），
**只认描述中显式载明的信息**——只写「MoE」不给激活参数的条目仅置 `is_moe`。

幂等键：`meta.spec_inferred = "model_spec.v1"`，已处理过的行直接跳过。
只影响平台内置（`tenant_id IS NULL`），租户自建条目不动。

运行（backend/ 下）：`python -m scripts.backfill_model_spec [--dry-run]`
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from ai_roi.domain.model_spec import infer_model_spec
from ai_roi.infrastructure.db.models.benchmark import BenchmarkModel
from ai_roi.infrastructure.db.uow import unit_of_work

SPEC_VERSION = "model_spec.v1"


async def run(dry_run: bool = False) -> dict[str, int]:
    stats = {"total": 0, "skipped": 0, "moe_set": 0, "active_set": 0, "no_evidence": 0}

    async with unit_of_work(is_super=True) as uow:
        rows = (
            (
                await uow.session.execute(
                    select(BenchmarkModel)
                    .where(BenchmarkModel.tenant_id.is_(None))
                    .order_by(BenchmarkModel.code)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        stats["total"] = len(rows)

        for row in rows:
            meta = dict(row.meta or {})
            if meta.get("spec_inferred") == SPEC_VERSION:
                stats["skipped"] += 1
                continue

            guess = infer_model_spec(row.name)
            if not guess.has_any:
                stats["no_evidence"] += 1
                print(f"  [跳过] {row.code:20s} 描述无 MoE 信息：{row.name!r}")
                continue

            changed: list[str] = []

            if guess.is_moe is not None and bool(row.is_moe) != guess.is_moe:
                if not dry_run:
                    row.is_moe = guess.is_moe
                changed.append(f"is_moe {row.is_moe}→{guess.is_moe}")
                stats["moe_set"] += 1

            if guess.active_params_b is not None and row.active_params_b is None:
                if not dry_run:
                    row.active_params_b = guess.active_params_b
                changed.append(f"active_params_b None→{guess.active_params_b}")
                stats["active_set"] += 1

            if not dry_run:
                meta["spec_inferred"] = SPEC_VERSION
                meta["spec_evidence"] = guess.evidence
                meta["spec_inferred_at"] = datetime.now(timezone.utc).isoformat()
                row.meta = meta
                if changed:
                    row.version = (row.version or 1) + 1

            marker = "→" if changed else "="
            print(f"  {marker} {row.code:20s} {'; '.join(changed) or '无变化（仅打标记）'}")

        if dry_run:
            print("\n[dry-run] 未落库")
        else:
            await uow.session.flush()

    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="回填基准库模型 MoE 结构化字段")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    print(f"=== 回填 MoE 字段（{SPEC_VERSION}）===")
    stats = asyncio.run(run(dry_run=args.dry_run))
    print(
        f"\n完成：共 {stats['total']} 行 / 跳过 {stats['skipped']}（已处理）"
        f" / is_moe 修正 {stats['moe_set']} / active_params_b 回填 {stats['active_set']}"
        f" / 无依据 {stats['no_evidence']}"
    )


if __name__ == "__main__":
    main()
