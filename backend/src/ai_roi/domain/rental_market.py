"""GPU 租赁行情基准：GetDeploying 公开数据集的解析与归一规则。

## 为什么是这条源

``benchmark_gpu.rent_cny_per_hour`` 原先全靠人工抄，抄完就没有下一次了。
实测下来能自动采的源极少：

| 源 | 结论 |
|---|---|
| Lambda Labs / RunPod / Vast.ai 官方 API | 401 / 400 / 403，全部要商业凭证 |
| Computable GPU Index | 可匿名访问，但许可是 **CC BY-NC**（禁商用），不能进产品 |
| **GetDeploying** | CC BY 4.0，**103 个型号 × 88 家云**，每日更新，CSV 直取 |

所以选 GetDeploying。它的口径是「各云厂商公开挂牌按需价的**中位数**」，
单位 USD/GPU/小时 —— 与本项目「云租赁单价」的语义一致，只差汇率折算。

## 覆盖边界（必须在界面上说清，不能假装全覆盖）

本库 14 个 GPU 型号里，国际市场上**只有 6 个能被租到**：
H100 / A100 / A800 / L40S / RTX5090 / RTX4090。

H800、H20、L20 是中国特供型号，昇腾/寒武纪/海光/沐曦是国产卡，
海外云厂商不挂这些 SKU —— 不是「暂时没采到」，是**根本没有这个市场**。
这些行继续由人工维护，前端显式标注「无权威源」，而不是拿一个编出来的数填上。

## 只做纯函数

解析、归一、取最新周、汇率折算全部在此，不触网不触库，便于离线单测。
HTTP 在 ``infrastructure.collectors.gpu_rental``，落库在用例层。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D

SOURCE_ID = "gpu-rental"
SOURCE_NAME = "GetDeploying GPU 价格数据集"
SOURCE_SITE = "https://getdeploying.com/gpus"
SOURCE_URL = "https://getdeploying.com/dataset/gpu-prices/weekly.csv"
SOURCE_LICENSE = "CC BY 4.0（署名：GetDeploying, https://getdeploying.com/gpus）"

SOURCE_ROW_PREFIX = "gpu-rental:"

BILLING_ON_DEMAND = "ON_DEMAND"

SLUG_VENDOR_PREFIXES: Dict[str, str] = {
    "nvidia-": "NVIDIA",
    "amd-": "AMD",
    "intel-": "Intel",
}

GPU_TO_SLUG: Dict[str, str] = {
    "H100": "nvidia-h100",
    "A100": "nvidia-a100",
    "A800": "nvidia-a800",
    "L40S": "nvidia-l40s",
    "RTX5090": "nvidia-rtx-5090",
    "RTX4090": "nvidia-rtx-4090",
    "H200": "nvidia-h200",
    "B200": "nvidia-b200",
    "B300": "nvidia-b300",
    "L4": "nvidia-l4",
    "MI300X": "amd-mi300x",
    "MI355X": "amd-mi355x",
}

SLUG_TO_GPU: Dict[str, str] = {v: k for k, v in GPU_TO_SLUG.items()}

THIN_MARKET_PROVIDERS = 3


@dataclass(frozen=True)
class RentalQuote:
    """某型号某周的租赁行情（上游一行）。"""

    gpu_slug: str
    week: date
    billing_type: str
    min_usd: Optional[Decimal]
    median_usd: Optional[Decimal]
    max_usd: Optional[Decimal]
    provider_count: int
    offering_count: int

    @property
    def is_thin(self) -> bool:
        """报价方过少：数值可用，但不足以称为市场行情。"""
        return self.provider_count < THIN_MARKET_PROVIDERS

    def to_meta(self, fx_usd_cny: Decimal) -> Dict[str, object]:
        """折算成库内 meta 片段（保留 USD 原值，便于事后核对汇率口径）。"""
        return {
            "gpu_rental_source": SOURCE_SITE,
            "gpu_rental_week": self.week.isoformat(),
            "gpu_rental_billing": self.billing_type,
            "gpu_rental_usd_per_hour": _s(self.median_usd),
            "gpu_rental_min_usd": _s(self.min_usd),
            "gpu_rental_max_usd": _s(self.max_usd),
            "gpu_rental_providers": self.provider_count,
            "gpu_rental_offerings": self.offering_count,
            "gpu_rental_thin_market": self.is_thin,
            "gpu_rental_fx_usd_cny": str(fx_usd_cny),
            "gpu_rental_license": SOURCE_LICENSE,
        }


def _s(value: Optional[Decimal]) -> Optional[str]:
    """Decimal → 字符串（JSONB 里存字符串，避免浮点误差与序列化差异）。"""
    return None if value is None else str(value)


def _dec(raw: object) -> Optional[Decimal]:
    """上游数值 → Decimal；空串/非数/非正值一律 None（不猜）。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = D(text)
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def _int(raw: object) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def _date(raw: object) -> Optional[date]:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_weekly_csv(text: str) -> List[RentalQuote]:
    """解析 ``weekly.csv`` 全量内容。

    容错优先：单行缺日期/缺价格就跳过该行，不让一条脏数据毁掉整次采集
    （上游每天重新生成该文件，偶发空值比整批失败更常见）。
    """
    if not text or not text.strip():
        return []

    quotes: List[RentalQuote] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        week = _date(row.get("date"))
        median = _dec(row.get("median_price"))
        if week is None or median is None:
            continue
        slug = str(row.get("gpu_slug") or "").strip()
        if not slug:
            continue
        quotes.append(
            RentalQuote(
                gpu_slug=slug,
                week=week,
                billing_type=str(row.get("billing_type") or "").strip().upper(),
                min_usd=_dec(row.get("min_price")),
                median_usd=median,
                max_usd=_dec(row.get("max_price")),
                provider_count=_int(row.get("provider_count")),
                offering_count=_int(row.get("offering_count")),
            )
        )
    return quotes


def latest_by_slug(
    quotes: Iterable[RentalQuote], billing_type: str = BILLING_ON_DEMAND
) -> Tuple[Dict[str, RentalQuote], Optional[date]]:
    """取每个型号在指定计费方式下的**最新一周**。

    不取「最新日期那一行」而是「每个型号各自的最新周」：
    上游某些型号可能某周断更，若按全局最新日期筛，会把断更型号整批丢掉。

    Returns:
        ``({slug: quote}, 全局最新周)``
    """
    wanted = billing_type.strip().upper()
    best: Dict[str, RentalQuote] = {}
    latest: Optional[date] = None
    for q in quotes:
        if q.billing_type != wanted:
            continue
        current = best.get(q.gpu_slug)
        if current is None or q.week > current.week:
            best[q.gpu_slug] = q
        if latest is None or q.week > latest:
            latest = q.week
    return best, latest


def usd_to_cny(usd: Decimal, fx_usd_cny: Decimal) -> Decimal:
    """USD/GPU/小时 → CNY/GPU/小时，保留 4 位（与库内 ``Numeric(18,4)`` 对齐）。"""
    return (usd * fx_usd_cny).quantize(Decimal("0.0001"))


def vendor_of(slug: str) -> str:
    """从 slug 前缀推断厂商；未知前缀返回空串（不硬编码猜测）。"""
    for prefix, vendor in SLUG_VENDOR_PREFIXES.items():
        if slug.startswith(prefix):
            return vendor
    return ""


NO_MARKET_GPUS: Tuple[str, ...] = (
    "H800",
    "H20",
    "L20",
    "ASCEND910B",
    "ASCEND910C",
    "CAMB590",
    "HYGON_K100",
    "MUXI_C500",
)


def market_status(gpu_code: str) -> str:
    """型号的采集可得性：``auto``（有权威源）/ ``manual``（国际无此 SKU）。"""
    return "auto" if str(gpu_code) in GPU_TO_SLUG else "manual"


__all__ = [
    "BILLING_ON_DEMAND",
    "GPU_TO_SLUG",
    "NO_MARKET_GPUS",
    "SLUG_TO_GPU",
    "SOURCE_ID",
    "SOURCE_LICENSE",
    "SOURCE_NAME",
    "SOURCE_ROW_PREFIX",
    "SOURCE_SITE",
    "SOURCE_URL",
    "THIN_MARKET_PROVIDERS",
    "RentalQuote",
    "latest_by_slug",
    "market_status",
    "parse_weekly_csv",
    "usd_to_cny",
    "vendor_of",
]
