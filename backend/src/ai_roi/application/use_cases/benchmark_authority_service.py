"""基准库权威同步：多源采集 → 投票裁决 → 预览 → 人工确认后应用。

**为什么强制「预览 + 确认」两段式**：实测权威源之间会成倍分歧（`deepseek-v4-pro`
在 LiteLLM 记 $1.32，在 models.dev 记 $0.66），任何「自动取一个源覆盖」的做法
都可能把错误静默写进基准库，进而污染所有测算。因此本用例：

- `preview()` 纯只读：采集 + 投票 + 算出差异，**一行不写**；
- `apply()` 只接受调用方显式给出的目标值，逐条留审计快照（可回滚）。

**汇率与价格分开追溯**：库内既有的 CNY 价是按某个历史汇率折算的死值，
事后无法区分「厂商调价」与「汇率变动」。本用例把 USD 原价与所用汇率一并写入
`meta`，CNY 转为派生值——两者可从同一处还原，也可按新汇率无歧义重算。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import structlog

from ai_roi.domain.benchmark_authority import (
    CONFIDENCE_LOW,
    Observation,
    SOURCE_AUTHORITY_PREFIX,
    VERDICT_CONFLICT,
    VERDICT_EMPTY,
    VERDICT_LABELS,
    VERDICT_SINGLE,
    Vote,
    format_change,
    lookup,
    relative_change,
    vote,
)

logger = structlog.get_logger(__name__)

CNY_Q = Decimal("0.0001")
USD_Q = Decimal("0.0001")

SETTLED_RATIO = Decimal("0.005")

META_USD = "api_price_usd"
META_FX = "fx_usd_cny"
META_SYNCED_AT = "authority_synced_at"
META_VOTED_BY = "authority_voted_by"


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


_RE_FX_IN_SOURCE = re.compile(r"[×x]\s*(\d+(?:\.\d+)?)")


def _infer_library_fx(rows: Sequence[Any], default: Decimal) -> Decimal:
    """推断库内数据实际使用的折算汇率（取 source 里出现最多的那个）。

    历史数据没有结构化汇率字段，只把 `×6.76` 写在 source 里。
    取众数而非平均：个别条目写法不同（如 `seed`）不应带偏整体口径。
    """
    counts: Dict[str, int] = {}
    for row in rows:
        m = _RE_FX_IN_SOURCE.search(getattr(row, "source", "") or "")
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        return default
    top = max(counts.items(), key=lambda kv: kv[1])[0]
    try:
        rate = Decimal(top)
    except Exception:  # noqa: BLE001  解析异常时退回默认值
        return default
    return rate if rate > 0 else default


@dataclass
class FxPreview:
    """汇率现状与权威值对比。"""

    current: Decimal
    authoritative: Optional[Decimal]
    vote: Vote

    @property
    def drifted(self) -> bool:
        return (
            self.authoritative is not None
            and self.current != 0
            and abs(self.authoritative - self.current) / self.current > Decimal("0.005")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current": str(self.current),
            "authoritative": str(self.authoritative) if self.authoritative is not None else None,
            "change": format_change(self.current, self.authoritative),
            "drifted": self.drifted,
            "verdict": self.vote.verdict,
            "confidence": self.vote.confidence,
            "observations": [
                {"source": o.source, "url": o.url, "value": str(o.input_value)}
                for o in self.vote.observations
                if o.input_value != 0
            ],
        }


@dataclass
class PricePreview:
    """单条 API 价的权威比对结果。"""

    id: int
    provider: str
    model_code: str
    current_in_cny: Decimal
    current_out_cny: Decimal
    current_cache_cny: Optional[Decimal]
    current_as_of: Optional[date]
    current_source: str
    version: int
    vote: Vote
    proposed_in_cny: Optional[Decimal] = None
    proposed_out_cny: Optional[Decimal] = None

    @property
    def verdict(self) -> str:
        return self.vote.verdict

    @property
    def change_ratio(self) -> Optional[Decimal]:
        return relative_change(self.current_in_cny, self.proposed_in_cny)

    @property
    def settled(self) -> bool:
        """权威值与库内值实质相同，同步只是把折算汇率归一到当前口径。

        为什么值得单独标出来：19 条 API 价里通常有十几条是这种「价格没动、
        只是当初按 6.76 / 7.2 折算、现在统一到 6.68」的条目，数值变化不到 0.1%。
        混在待处理列表里会让人以为有大面积调价，实际全是汇率尾巴。
        前端据此默认不勾选，只留真正需要决策的条目。
        """
        if self.proposed_in_cny is None:
            return False
        ratio = self.change_ratio
        return ratio is not None and abs(ratio) <= SETTLED_RATIO

    def _cache_of_agreeing(self) -> Optional[str]:
        """取采信源里的缓存价（各源命名不一，优先第一个非空值）。"""
        for obs in self.vote.observations:
            if obs.source in self.vote.agreeing_sources:
                cache = obs.extra.get("cache")
                if cache not in (None, "", "None"):
                    return str(cache)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": "api-prices",
            "provider": self.provider,
            "model_code": self.model_code,
            "current": {
                "in_cny": str(self.current_in_cny),
                "out_cny": str(self.current_out_cny),
                "cache_cny": str(self.current_cache_cny) if self.current_cache_cny is not None else None,
                "as_of": self.current_as_of.isoformat() if self.current_as_of else None,
                "source": self.current_source,
                "version": self.version,
            },
            "verdict": self.vote.verdict,
            "confidence": self.vote.confidence,
            "applicable": self.vote.applicable,
            "needs_review": self.vote.needs_review,
            "partial": self.vote.partial,
            "input_verdict": self.vote.in_verdict,
            "output_verdict": self.vote.out_verdict,
            "input_verdict_label": VERDICT_LABELS.get(self.vote.in_verdict, self.vote.in_verdict),
            "output_verdict_label": VERDICT_LABELS.get(self.vote.out_verdict, self.vote.out_verdict),
            "input_agreeing": list(self.vote.input_agreeing),
            "output_agreeing": list(self.vote.output_agreeing),
            "settled": self.settled,
            "agreement_ratio": round(self.vote.agreement_ratio, 3),
            "proposed": {
                "in_cny": str(self.proposed_in_cny) if self.proposed_in_cny is not None else None,
                "out_cny": str(self.proposed_out_cny) if self.proposed_out_cny is not None else None,
                "usd_in": str(self.vote.input_value) if self.vote.input_value is not None else None,
                "usd_out": str(self.vote.output_value) if self.vote.output_value is not None else None,
                "usd_cache": self._cache_of_agreeing(),
            },
            "change": format_change(self.current_in_cny, self.proposed_in_cny),
            "observations": [
                {
                    "source": o.source,
                    "url": o.url,
                    "usd_in": str(o.input_value),
                    "usd_out": str(o.output_value) if o.output_value is not None else None,
                    "usd_cache": o.extra.get("cache"),
                    "context": o.extra.get("context"),
                }
                for o in self.vote.observations
            ],
        }


@dataclass
class PreviewResult:
    fx: FxPreview
    items: List[PricePreview] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    fetched_at: Optional[str] = None

    def summary(self) -> Dict[str, int]:
        out = {"consensus": 0, "single_source": 0, "conflict": 0, "no_data": 0, "total": len(self.items)}
        for it in self.items:
            out[it.verdict] = out.get(it.verdict, 0) + 1
        settled = sum(1 for it in self.items if it.settled)
        out["settled"] = settled
        out["needs_decision"] = sum(
            1 for it in self.items if it.vote.needs_review and not it.settled
        )
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fx": self.fx.to_dict(),
            "summary": self.summary(),
            "sources": self.sources,
            "fetched_at": self.fetched_at,
            "items": [it.to_dict() for it in self.items],
        }


class BenchmarkAuthorityService:
    """基准库权威同步编排。"""

    def __init__(
        self,
        uow: Any,
        client: Any,
        current_fx: Decimal = Decimal("6.68"),
    ) -> None:
        self.uow = uow
        self.client = client
        self.current_fx = current_fx

    async def preview(self) -> PreviewResult:
        snapshots = await self.client.fetch_all()
        fx_obs = await self.client.fetch_fx()
        fx_vote = vote(fx_obs)
        fx_rate = fx_vote.input_value if fx_vote.input_value else self.current_fx

        rows = await self.uow.benchmarks.list_api_prices(None)

        library_fx = _infer_library_fx(rows, self.current_fx)
        fx_preview = FxPreview(
            current=library_fx,
            authoritative=fx_vote.input_value if fx_vote.verdict != VERDICT_EMPTY else None,
            vote=fx_vote,
        )

        items: List[PricePreview] = []
        for row in rows:
            obs = self._lookup(snapshots, row.provider, row.model_code)
            v = vote(obs)
            p_in = p_out = None
            if v.input_value is not None:
                p_in = (v.input_value * fx_rate).quantize(CNY_Q)
                p_out = (v.output_value * fx_rate).quantize(CNY_Q) if v.output_value is not None else None
            items.append(
                PricePreview(
                    id=row.id,
                    provider=row.provider,
                    model_code=row.model_code,
                    current_in_cny=_dec(row.price_in_cny_per_m),
                    current_out_cny=_dec(row.price_out_cny_per_m),
                    current_cache_cny=_dec(row.price_cache_cny_per_m)
                    if row.price_cache_cny_per_m is not None
                    else None,
                    current_as_of=row.as_of,
                    current_source=row.source,
                    version=row.version,
                    vote=v,
                    proposed_in_cny=p_in,
                    proposed_out_cny=p_out,
                )
            )

        return PreviewResult(
            fx=fx_preview,
            items=items,
            sources=[
                {
                    "source": s.source,
                    "url": s.url,
                    "ok": s.ok,
                    "entries": len(s.entries),
                    "ambiguous": len(s.ambiguous),
                    "error": s.error,
                }
                for s in snapshots
            ],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _lookup(snapshots: Sequence[Any], provider: str, model_code: str) -> List[Observation]:
        return lookup(snapshots, provider, model_code)

    async def status(self) -> Dict[str, Any]:
        """权威价格的当前覆盖情况（纯读库，不访问外网）。

        与 `preview()` 的区别：preview 要下载三源才知差异（约 6~20 秒），
        而按钮旁边只需要「上次同步到哪天、还有多少条是人工值」，这类问题
        必须即时回答，因此单独走一条只读本库的路径。
        """
        rows = await self.uow.benchmarks.list_api_prices(None)
        total = len(rows)
        from_authority = 0
        synced_at: List[str] = []
        as_of: List[date] = []
        for row in rows:
            meta = row.meta or {}
            if str(row.source or "").startswith(SOURCE_AUTHORITY_PREFIX):
                from_authority += 1
            stamp = meta.get(META_SYNCED_AT)
            if stamp:
                synced_at.append(str(stamp))
            if row.as_of is not None:
                as_of.append(row.as_of)
        return {
            "fx_usd_cny": str(self.current_fx),
            "total": total,
            "from_authority": from_authority,
            "manual": total - from_authority,
            "last_synced_at": max(synced_at) if synced_at else None,
            "as_of": max(as_of).isoformat() if as_of else None,
        }

    async def apply(
        self,
        selections: Sequence[Dict[str, Any]],
        fx_usd_cny: Optional[Decimal] = None,
        tenant_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        actor_email: str = "",
    ) -> Dict[str, Any]:
        """写入选中条目。

        `selections` 每项：`{id, usd_in, usd_out?, usd_cache?, source_label?}`。
        值以 **USD / 百万 token** 给出，本方法按 `fx_usd_cny` 折算为 CNY，
        并把 USD 原价一并存入 `meta`，便于日后区分调价与汇率变动。
        """
        rate = fx_usd_cny if fx_usd_cny is not None else self.current_fx
        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for sel in selections:
            row_id = sel.get("id")
            if row_id is None:
                skipped.append({"id": None, "reason": "缺少 id"})
                continue
            row = await self.uow.benchmarks.get_api_price(None, int(row_id))
            if row is None:
                skipped.append({"id": row_id, "reason": "条目不存在或非平台内置"})
                continue

            try:
                usd_in = Decimal(str(sel["usd_in"]))
            except Exception:
                skipped.append({"id": row_id, "reason": "usd_in 非法"})
                continue
            usd_out_raw = sel.get("usd_out")
            usd_out = Decimal(str(usd_out_raw)) if usd_out_raw not in (None, "") else None
            usd_cache_raw = sel.get("usd_cache")
            usd_cache = Decimal(str(usd_cache_raw)) if usd_cache_raw not in (None, "") else None

            before = {
                "in_cny": str(row.price_in_cny_per_m),
                "out_cny": str(row.price_out_cny_per_m),
                "cache_cny": str(row.price_cache_cny_per_m)
                if row.price_cache_cny_per_m is not None
                else None,
                "source": row.source,
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "version": row.version,
            }

            values: Dict[str, Any] = {
                "price_in_cny_per_m": (usd_in * rate).quantize(CNY_Q),
                "source": f"{SOURCE_AUTHORITY_PREFIX}{sel.get('source_label') or 'multi-source'} ×{rate}",
                "as_of": now.date(),
                "version": (row.version or 1) + 1,
                "meta": {
                    **(row.meta or {}),
                    META_USD: {
                        "input": str(usd_in),
                        "output": str(usd_out) if usd_out is not None else None,
                        "cache": str(usd_cache) if usd_cache is not None else None,
                    },
                    META_FX: str(rate),
                    META_SYNCED_AT: now.isoformat(),
                    META_VOTED_BY: sel.get("source_label") or "multi-source",
                },
            }
            if usd_out is not None:
                values["price_out_cny_per_m"] = (usd_out * rate).quantize(CNY_Q)
            if usd_cache is not None:
                values["price_cache_cny_per_m"] = (usd_cache * rate).quantize(CNY_Q)

            await self.uow.benchmarks.apply_update(row, values)

            applied.append(
                {
                    "id": row_id,
                    "provider": row.provider,
                    "model_code": row.model_code,
                    "before": before,
                    "after": {
                        "in_cny": str(values["price_in_cny_per_m"]),
                        "out_cny": str(values.get("price_out_cny_per_m", row.price_out_cny_per_m)),
                        "source": values["source"],
                        "version": values["version"],
                    },
                }
            )

        if applied and tenant_id is not None:
            await self.uow.audit.write(
                tenant_id=tenant_id,
                action="benchmark.authority",
                actor_id=actor_id,
                actor_email=actor_email,
                target_type="benchmark_api_price",
                detail={
                    "fx_usd_cny": str(rate),
                    "applied_count": len(applied),
                    "skipped_count": len(skipped),
                    "snapshot": applied,
                },
            )

        logger.info(
            "authority.apply",
            applied=len(applied),
            skipped=len(skipped),
            fx=str(rate),
        )
        return {
            "applied": applied,
            "skipped": skipped,
            "fx_usd_cny": str(rate),
            "applied_count": len(applied),
        }


__all__ = [
    "BenchmarkAuthorityService",
    "FxPreview",
    "PreviewResult",
    "PricePreview",
    "META_FX",
    "META_USD",
]
