"""租赁价格采集用例：GPU 行情（GetDeploying）与云厂商官价（Azure + AWS）的预览与写回。

## 为什么是「预览 → 人工确认 → 应用」，而不是直接覆盖

价格基准是测算的输入端，一动就换一批结论。实测过一次差距：

    库内 Azure H100 人工值   ¥23.7 / 卡 / 小时（= $3.5）
    Azure 官方按需挂牌价     $6.98 / 卡 / 小时 ≈ ¥46.6

差一倍。这种量级的差异有两种可能 —— 要么人工值抄错了，要么当初填的是
「大客户折扣价 / 市场均价」而不是「官网挂牌价」。机器无法区分，只有人能判断。
所以采集只负责**把两边摆在一起**，写库必须由人点确认。

## 两条链路的口径不同

| 链路 | 源 | 写哪张表 | 粒度 | as_of 语义 |
|---|---|---|---|---|
| GPU 行情 | GetDeploying | ``benchmark_gpu.rent_cny_per_hour`` | 型号级（不分云） | 数据所属周的周一 |
| 云官价 | Azure 零售价格 | ``benchmark_cloud_price.price_cny_per_hour`` | 厂商 × 型号 | 采集当日 |

前者回答「这型号现在市场价多少」，后者回答「这家云上开一台多少钱」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from ai_roi.domain.benchmark_authority import relative_change
from ai_roi.domain.cloud_official import (
    AWS_REGION_PATHS,
    AZURE_VM_SIZES,
    PROVIDER_AWS,
    PROVIDER_AZURE,
    SOURCE_ID as CLOUD_SOURCE_ID,
    SOURCE_ROW_PREFIX as CLOUD_ROW_PREFIX,
    SOURCE_SITE as CLOUD_SOURCE_SITE,
    CloudQuote,
    cheapest_per_gpu,
    parse_aws_entries,
    parse_azure_items,
    provider_status,
    usd_to_cny as cloud_usd_to_cny,
)
from ai_roi.domain.errors import DomainError, UpstreamUnavailableError
from ai_roi.domain.rental_market import (
    SOURCE_ID as RENTAL_SOURCE_ID,
    SOURCE_ROW_PREFIX as RENTAL_ROW_PREFIX,
    GPU_TO_SLUG,
    RentalQuote,
    latest_by_slug,
    market_status,
    parse_weekly_csv,
    usd_to_cny as rental_usd_to_cny,
)

logger = structlog.get_logger(__name__)

SETTLED_RATIO = Decimal("0.005")

KIND_GPU = "gpu-rental"
KIND_CLOUD = "cloud-official"

KIND_LABELS: Dict[str, str] = {
    KIND_GPU: "GPU 租赁行情",
    KIND_CLOUD: "云厂商官方价",
}


@dataclass
class MarketItem:
    """一条待决策的租赁价变更。"""

    kind: str
    row_id: int
    label: str
    current_cny: Optional[Decimal]
    proposed_cny: Optional[Decimal]
    current_source: str
    as_of: Optional[date]
    meta: Dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def change_ratio(self) -> Optional[Decimal]:
        return relative_change(self.current_cny, self.proposed_cny)

    @property
    def settled(self) -> bool:
        """变动仅在汇率/口径噪声范围内。"""
        change = self.change_ratio
        return change is not None and abs(change) <= SETTLED_RATIO

    @property
    def direction(self) -> str:
        change = self.change_ratio
        if change is None:
            return "new"
        if self.settled:
            return "settled"
        return "up" if change > 0 else "down"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.row_id,
            "label": self.label,
            "current_cny": _s(self.current_cny),
            "proposed_cny": _s(self.proposed_cny),
            "current_source": self.current_source,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "change": None if self.change_ratio is None else f"{self.change_ratio * 100:+.2f}%",
            "direction": self.direction,
            "settled": self.settled,
            "note": self.note,
        }


@dataclass
class MarketPreview:
    """一次预览的完整结果。"""

    kind: str
    items: List[MarketItem]
    missing: List[str] = field(default_factory=list)
    manual_only: List[str] = field(default_factory=list)
    unmatched: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    as_of: Optional[date] = None
    fx_usd_cny: Decimal = Decimal(0)
    source_name: str = ""
    source_url: str = ""

    @property
    def summary(self) -> Dict[str, int]:
        up = sum(1 for i in self.items if i.direction == "up")
        down = sum(1 for i in self.items if i.direction == "down")
        settled = sum(1 for i in self.items if i.settled)
        return {
            "total": len(self.items),
            "up": up,
            "down": down,
            "settled": settled,
            "missing": len(self.missing),
            "manual_only": len(self.manual_only),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "label": KIND_LABELS.get(self.kind, self.kind),
            "summary": self.summary,
            "items": [i.to_dict() for i in self.items],
            "missing": self.missing,
            "manual_only": self.manual_only,
            "unmatched": self.unmatched,
            "warnings": self.warnings,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "fx_usd_cny": str(self.fx_usd_cny),
            "source_name": self.source_name,
            "source_url": self.source_url,
        }


def _s(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _dec(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError, TypeError):
        return None


class MarketSyncService:
    """租赁价采集用例（预览 / 应用）。

    网络客户端由调用方注入，便于离线单测与换源；
    本类只负责编排「拉 → 匹配 → 比对 → 写库 → 留痕」。
    """

    def __init__(
        self,
        uow: Any,
        *,
        fx_usd_cny: Decimal = Decimal("6.68"),
        regional_client: Any = None,
        cloud_client: Any = None,
        aws_client: Any = None,
    ) -> None:
        self.uow = uow
        self.fx_usd_cny = fx_usd_cny
        self.regional_client = regional_client
        self.cloud_client = cloud_client
        self.aws_client = aws_client

    async def preview_gpu_rental(self, tenant_id: Optional[int] = None) -> MarketPreview:
        """拉取行情数据集，与库内 ``rent_cny_per_hour`` 逐型号比对。"""
        if self.regional_client is None:
            raise DomainError("未配置 GPU 行情采集客户端")

        csv_text = await self.regional_client.fetch_weekly_csv()
        quotes = parse_weekly_csv(csv_text)
        if not quotes:
            raise DomainError("行情数据集解析后为空，上游结构可能已变更")

        latest, as_of = latest_by_slug(quotes)
        rows = await self.uow.benchmarks.list_gpus(tenant_id)

        items: List[MarketItem] = []
        missing: List[str] = []
        manual: List[str] = []

        for row in rows:
            code = str(row.code)
            if market_status(code) != "auto":
                manual.append(code)
                continue
            slug = GPU_TO_SLUG[code]
            quote = latest.get(slug)
            if quote is None:
                missing.append(code)
                continue
            items.append(self._gpu_item(row, quote))

        return MarketPreview(
            kind=KIND_GPU,
            items=items,
            missing=missing,
            manual_only=manual,
            unmatched=sorted(
                {s for s in latest if s not in set(GPU_TO_SLUG.values())}
            )[:20],
            as_of=as_of,
            fx_usd_cny=self.fx_usd_cny,
            source_name="GetDeploying GPU 价格数据集（CC BY 4.0）",
            source_url="https://getdeploying.com/dataset/gpu-prices",
        )

    def _gpu_item(self, row: Any, quote: RentalQuote) -> MarketItem:
        proposed = rental_usd_to_cny(quote.median_usd or Decimal(0), self.fx_usd_cny)
        note = f"仅 {quote.provider_count} 家云报价" if quote.is_thin else ""
        return MarketItem(
            kind=KIND_GPU,
            row_id=int(row.id),
            label=str(row.code),
            current_cny=_dec(row.rent_cny_per_hour),
            proposed_cny=proposed,
            current_source=str(row.source or ""),
            as_of=quote.week,
            meta=quote.to_meta(self.fx_usd_cny),
            note=note,
        )

    async def apply_gpu_rental(
        self,
        row_ids: Sequence[int],
        *,
        as_of: Optional[date] = None,
        tenant_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        actor_email: str = "",
        proposals: Optional[Dict[int, Decimal]] = None,
        metas: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """把选中型号的行情价写回 ``benchmark_gpu``。

        ``proposals`` 由预览结果带来（id → 目标 CNY 价）；缺失时拒绝写入 ——
        不能让「应用」在拿不到本次采集值的情况下凭当前值自我覆盖。

        ``as_of`` 是上游数据所属周（预览时已确定），必须由调用方带回来：
        用库内旧值会让 ``source`` 里的日期停留在上一次采集，看起来像没更新。

        ``metas`` 携带行情明细（USD 原值、min/max、报价家数），并入行 meta，
        便于日后核算「当时是拿什么汇率、从几家云的中位数算出来的」。
        """
        if proposals is None:
            raise DomainError("缺少本次采集结果，无法应用（请先重新预览）")
        effective = as_of or date.today()

        now = datetime.now(timezone.utc)
        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for row_id in row_ids:
            proposed = proposals.get(int(row_id))
            if proposed is None:
                skipped.append({"id": row_id, "reason": "本次采集未覆盖该型号"})
                continue
            row = await self.uow.benchmarks.get_gpu(None, int(row_id))
            if row is None:
                skipped.append({"id": row_id, "reason": "条目不存在或非平台内置"})
                continue

            before = {
                "rent_cny_per_hour": _s(row.rent_cny_per_hour),
                "source": row.source,
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "version": row.version,
            }
            values = {
                "rent_cny_per_hour": proposed,
                "source": f"{RENTAL_ROW_PREFIX}{effective.isoformat()}",
                "as_of": effective,
                "version": (row.version or 1) + 1,
                "meta": {**(row.meta or {}), **((metas or {}).get(int(row_id)) or {})},
            }
            await self.uow.benchmarks.apply_update(row, values)
            applied.append(
                {
                    "id": int(row.id),
                    "code": row.code,
                    "before": before,
                    "after": {
                        "rent_cny_per_hour": str(proposed),
                        "source": values["source"],
                        "version": values["version"],
                    },
                }
            )

        if applied and tenant_id is not None:
            await self.uow.audit.write(
                tenant_id=tenant_id,
                action="benchmark.market_sync",
                actor_id=actor_id,
                actor_email=actor_email,
                target_type="benchmark_gpu",
                detail={
                    "kind": KIND_GPU,
                    "fx_usd_cny": str(self.fx_usd_cny),
                    "applied": applied,
                    "skipped": skipped,
                },
            )
        logger.info(
            "market.sync.applied", kind=KIND_GPU, applied=len(applied), skipped=len(skipped)
        )
        return {"kind": KIND_GPU, "applied": applied, "skipped": skipped}

    async def _collect_cloud_quotes(
        self,
    ) -> Tuple[List[CloudQuote], List[str], List[str]]:
        """依次拉各厂商官方价，返回 ``(报价, 成功的源, 警告)``。

        单源失败只记 warning：AWS 挂了不该让 Azure 已经拿到的报价一起作废，
        否则用户看到的是「整批采集失败」，实际只坏了一路。
        """
        quotes: List[CloudQuote] = []
        sources: List[str] = []
        warnings: List[str] = []

        if self.cloud_client is not None:
            try:
                raw = await self.cloud_client.fetch_items(list(AZURE_VM_SIZES.keys()))
                azure_quotes = parse_azure_items(raw)
                if azure_quotes:
                    quotes.extend(azure_quotes)
                    sources.append(f"{PROVIDER_AZURE} 零售价格接口")
                else:
                    warnings.append("Azure 报价解析后为空：SKU 映射可能已失效")
            except UpstreamUnavailableError as exc:
                warnings.append(f"Azure 采集失败：{exc}")

        if self.aws_client is not None:
            for region_code, region_path in AWS_REGION_PATHS.items():
                try:
                    payload = await self.aws_client.fetch_region(region_path)
                except UpstreamUnavailableError as exc:
                    warnings.append(f"AWS({region_code}) 采集失败：{exc}")
                    continue
                region_quotes = parse_aws_entries(payload, region=region_code)
                if not region_quotes:
                    warnings.append(
                        f"AWS({region_code}) 未匹配到任何已收录规格：实例映射可能已失效"
                    )
                    continue
                quotes.extend(region_quotes)
                if f"{PROVIDER_AWS} 批量价目表" not in sources:
                    sources.append(f"{PROVIDER_AWS} 批量价目表")

        return quotes, sources, warnings

    async def preview_cloud_official(self, tenant_id: Optional[int] = None) -> MarketPreview:
        """拉取各厂商官方按需价，与库内云租赁价逐行比对。"""
        if self.cloud_client is None and self.aws_client is None:
            raise DomainError("未配置云厂商价格采集客户端")

        quotes, sources, warnings = await self._collect_cloud_quotes()
        if not quotes:
            detail = "；".join(warnings) if warnings else "上游结构可能已变更"
            raise DomainError(f"所有云厂商官方价都没有采到：{detail}")

        best = cheapest_per_gpu(quotes)
        rows = await self.uow.benchmarks.list_cloud_prices(tenant_id)
        row_keys = {(str(row.provider or ""), str(row.gpu_code or "")) for row in rows}

        items: List[MarketItem] = []
        manual: List[str] = []
        missing: List[str] = []

        for row in rows:
            provider = str(row.provider or "")
            gpu_code = str(row.gpu_code or "")
            if provider_status(provider) != "auto":
                manual.append(f"{provider}·{gpu_code}")
                continue
            quote = best.get((provider, gpu_code))
            if quote is None:
                missing.append(f"{provider}·{gpu_code}")
                continue
            items.append(self._cloud_item(row, quote))

        return MarketPreview(
            kind=KIND_CLOUD,
            items=items,
            missing=missing,
            manual_only=manual,
            unmatched=sorted(f"{p}·{g}" for (p, g) in best if (p, g) not in row_keys)[:20],
            warnings=warnings,
            as_of=date.today(),
            fx_usd_cny=self.fx_usd_cny,
            source_name=" + ".join(sources) + "（官方公开）",
            source_url=CLOUD_SOURCE_SITE,
        )

    def _cloud_item(self, row: Any, quote: CloudQuote) -> MarketItem:
        proposed = cloud_usd_to_cny(quote.usd_per_gpu_hour, self.fx_usd_cny)
        return MarketItem(
            kind=KIND_CLOUD,
            row_id=int(row.id),
            label=f"{quote.provider} · {quote.gpu_code}",
            current_cny=_dec(row.price_cny_per_hour),
            proposed_cny=proposed,
            current_source=str(row.source or ""),
            as_of=date.today(),
            meta=quote.to_meta(self.fx_usd_cny),
            note=f"{quote.vm_size}（{quote.gpu_count} 卡整机折算）",
        )

    async def apply_cloud_official(
        self,
        row_ids: Sequence[int],
        *,
        tenant_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        actor_email: str = "",
        proposals: Optional[Dict[int, Decimal]] = None,
        metas: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """把选中行的官方价写回 ``benchmark_cloud_price``。"""
        if proposals is None:
            raise DomainError("缺少本次采集结果，无法应用（请先重新预览）")

        now = datetime.now(timezone.utc)
        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for row_id in row_ids:
            proposed = proposals.get(int(row_id))
            if proposed is None:
                skipped.append({"id": row_id, "reason": "本次采集未覆盖该条目"})
                continue
            row = await self.uow.benchmarks.get_cloud_price(None, int(row_id))
            if row is None:
                skipped.append({"id": row_id, "reason": "条目不存在或非平台内置"})
                continue

            before = {
                "price_cny_per_hour": _s(row.price_cny_per_hour),
                "source": row.source,
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "version": row.version,
            }
            values = {
                "price_cny_per_hour": proposed,
                "source": f"{CLOUD_ROW_PREFIX}{now.date().isoformat()}",
                "as_of": now.date(),
                "version": (row.version or 1) + 1,
                "meta": {**(row.meta or {}), **((metas or {}).get(int(row_id)) or {})},
            }
            await self.uow.benchmarks.apply_update(row, values)
            applied.append(
                {
                    "id": int(row.id),
                    "provider": row.provider,
                    "gpu_code": row.gpu_code,
                    "before": before,
                    "after": {
                        "price_cny_per_hour": str(proposed),
                        "source": values["source"],
                        "version": values["version"],
                    },
                }
            )

        if applied and tenant_id is not None:
            await self.uow.audit.write(
                tenant_id=tenant_id,
                action="benchmark.market_sync",
                actor_id=actor_id,
                actor_email=actor_email,
                target_type="benchmark_cloud_price",
                detail={
                    "kind": KIND_CLOUD,
                    "fx_usd_cny": str(self.fx_usd_cny),
                    "applied": applied,
                    "skipped": skipped,
                },
            )
        logger.info(
            "market.sync.applied", kind=KIND_CLOUD, applied=len(applied), skipped=len(skipped)
        )
        return {"kind": KIND_CLOUD, "applied": applied, "skipped": skipped}


def _d(value: Optional[date]) -> str:
    """日期 → ISO 字符串；缺省用今天（写进 source 文本，永不落空）。"""
    return value.isoformat() if value else date.today().isoformat()


__all__ = [
    "KIND_CLOUD",
    "KIND_GPU",
    "KIND_LABELS",
    "MarketItem",
    "MarketPreview",
    "MarketSyncService",
]
