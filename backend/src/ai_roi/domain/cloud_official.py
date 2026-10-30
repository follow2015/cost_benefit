"""云厂商**官方挂牌价**的解析与归一（Azure 零售价格接口 + AWS 批量价目表）。

## 与 ``rental_market`` 的分工

- ``rental_market``：第三方行情数据集（GetDeploying），给的是「市场上这个型号普遍多少钱」，
  写入 ``benchmark_gpu.rent_cny_per_hour``（型号级，不分云厂商）；
- 本模块：云厂商**自己官网**的挂牌价，写入 ``benchmark_cloud_price``（厂商 × 型号级）。

两者口径不同，不能互相替代：行情中位数回答「租一台 H100 大概什么价」，
官价回答「在 Azure 上开一台 H100 具体多少」。测算里选哪家云，看的是后者。

## 为什么能采到的厂商这么少（2026-10-29 逐条实测，勿凭印象复述）

| 云 | 实测结果 | 结论 |
|---|---|---|
| Azure | Retail Prices API 匿名可调、分页 ``NextPageLink`` | ✅ 已接 |
| AWS | 官网 b0 静态价目表，单区 679KB / 2.5s，匿名、带 ``manifest`` 元信息 | ✅ 已接 |
| GCP | 本环境 ``cloud.google.com`` **Network is unreachable**；Billing Catalog 另需 API key | ❌ 双重阻塞 |
| 阿里云 / 腾讯云 | 定价页是 lowcode SPA，HTML 里零内联 API；官方 ``DescribePrice`` 需签名 | ❌ 只留人工值 |
| 火山引擎 | ``/api/v1/price/list`` 返回「未授权访问」 | ❌ |
| AutoDL | 4 个候选接口全部 404，市场页 3KB SPA | ❌ |

结论：剩下来的厂商拦在**鉴权与可达性**，不是「HTML 不好解析」——
所以引入爬虫框架/无头浏览器也解决不了，反而多一个随时被改版打断的故障点。

## AWS 的规格映射为何只收 4 个

b0 里 ``Instance Family = GPU instance`` 的规格有 60 多个，但单卡折算价能自洽的只有这几个：

| 实例 | 卡数 | 整机 USD/h | 单卡 USD/h |
|---|---|---|---|
| p5.4xlarge | 1 | 6.88 | 6.88 |
| p5.48xlarge | 8 | 55.04 | 6.88 |
| p4d.24xlarge | 8 | 21.96 | 2.74 |
| p4de.24xlarge | 8 | 27.45 | 3.43 |

同一族里两个规格折算到同一个单卡价，才说明卡数没数错。反例是 ``g6e``（L40S）：
8 个规格折算出来从 $1.89 到 $4.53，相差 2.4 倍——要么 feed 里有错价，要么卡数不是
公开规格那样分，取最小值会得到一个自己都不信的数字，故整族不收录（见 ``AWS_BLOCKED_FAMILIES``）。

## 单位口径：必须折成「单卡」

Azure 按 **VM 规格**计价，一台 ``Standard_ND96isr_H100_v5`` 是 8 张卡一起卖。
直接拿整机价填进 ``price_cny_per_hour`` 会让单价虚高 8 倍，因此每个 SKU 都必须
带上「这张卡有几块 GPU」，折算后才入库。同一个型号往往有 1 卡 / 2 卡 / 8 卡多种规格，
本模块取**单卡折算价最低**的那个按需规格 —— 对应「这家云上跑这块卡最省的方式」。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D

SOURCE_ID = "cloud-sync"
SOURCE_NAME = "云厂商官方价格"
SOURCE_SITE = "https://azure.microsoft.com/pricing/details/virtual-machines/linux/"
SOURCE_ROW_PREFIX = "cloud-sync:"

PROVIDER_AZURE = "Azure"
PROVIDER_AWS = "AWS"

SOURCE_SITES: Dict[str, str] = {
    PROVIDER_AZURE: "https://azure.microsoft.com/pricing/details/virtual-machines/linux/",
    PROVIDER_AWS: "https://aws.amazon.com/ec2/pricing/on-demand/",
}


def source_site(provider: str) -> str:
    """厂商官网价格页；未知厂商回落到通用价格页。"""
    return SOURCE_SITES.get(str(provider), SOURCE_SITE)

UNIT_HOURLY = "1 Hour"
PRICE_TYPE_CONSUMPTION = "Consumption"

AZURE_VM_SIZES: Dict[str, Tuple[str, int]] = {
    "Standard_NC40ads_H100_v5": ("H100", 1),
    "Standard_NC80adis_H100_v5": ("H100", 2),
    "Standard_ND96isr_H100_v5": ("H100", 8),
    "Standard_ND96is_H100_v5": ("H100", 8),
    "Standard_ND96isrf_H100_v5": ("H100", 8),
    "Standard_NC24ads_A100_v4": ("A100", 1),
    "Standard_NC48ads_A100_v4": ("A100", 2),
    "Standard_NC96ads_A100_v4": ("A100", 4),
    "Standard_ND96asr_v4": ("A100", 8),
    "Standard_NV6ads_A10_v5": ("L40S", 1),
}

BLOCKED_VM_SIZES: Tuple[str, ...] = ("Standard_NV6ads_A10_v5",)

EXCLUDE_SKU_MARKERS: Tuple[str, ...] = ("spot", "low priority", "lowpriority")

AWS_REGION_PATHS: Dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
}

AWS_INSTANCE_TYPES: Dict[str, Tuple[str, int]] = {
    "p5.4xlarge": ("H100", 1),
    "p5.48xlarge": ("H100", 8),
    "p4d.24xlarge": ("A100", 8),
    "p4de.24xlarge": ("A100", 8),
}

AWS_BLOCKED_FAMILIES: Tuple[str, ...] = ("g6e",)

GPU_INSTANCE_FAMILY = "GPU instance"


@dataclass(frozen=True)
class CloudQuote:
    """一条云厂商官方按需报价（已折算到单卡）。"""

    provider: str
    gpu_code: str
    region: str
    vm_size: str
    gpu_count: int
    usd_per_hour_total: Decimal

    @property
    def usd_per_gpu_hour(self) -> Decimal:
        """单卡折算价；``gpu_count`` 已由映射表保证 ≥ 1。"""
        return self.usd_per_hour_total / Decimal(max(1, self.gpu_count))

    def to_meta(self, fx_usd_cny: Decimal) -> Dict[str, object]:
        return {
            "cloud_official_source": source_site(self.provider),
            "cloud_official_region": self.region,
            "cloud_official_vm_size": self.vm_size,
            "cloud_official_gpu_count": self.gpu_count,
            "cloud_official_usd_total": str(self.usd_per_hour_total),
            "cloud_official_usd_per_gpu": str(
                self.usd_per_gpu_hour.quantize(Decimal("0.0001"))
            ),
            "cloud_official_fx_usd_cny": str(fx_usd_cny),
        }


def _is_ondemand(item: Mapping[str, Any]) -> bool:
    """是否为「按需 + 按小时 + USD」的可用报价行。"""
    if str(item.get("type") or "") != PRICE_TYPE_CONSUMPTION:
        return False
    if str(item.get("priceType") or PRICE_TYPE_CONSUMPTION) != PRICE_TYPE_CONSUMPTION:
        return False
    if str(item.get("unitOfMeasure") or "") != UNIT_HOURLY:
        return False
    if str(item.get("currencyCode") or "USD") != "USD":
        return False
    if item.get("reservationTerm"):
        return False
    sku = str(item.get("skuName") or "").lower()
    return not any(marker in sku for marker in EXCLUDE_SKU_MARKERS)


def _positive_price(raw: Any) -> Optional[Decimal]:
    """把上游给的价（可能是字符串）转成正的 Decimal；NaN / 0 / 负值一律当作无效。"""
    if raw is None or raw == "":
        return None
    try:
        value = D(str(raw))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def _price(item: Mapping[str, Any]) -> Optional[Decimal]:
    return _positive_price(item.get("retailPrice"))


def parse_azure_items(
    items: Iterable[Mapping[str, Any]],
    *,
    provider: str = PROVIDER_AZURE,
) -> List[CloudQuote]:
    """把 Azure 零售价格条目转成 ``CloudQuote`` 列表。

    未在映射表内的 SKU、非按需价、缺价格的行一律跳过（不猜、不补）。
    """
    out: List[CloudQuote] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        vm_size = str(item.get("armSkuName") or "").strip()
        if vm_size in BLOCKED_VM_SIZES:
            continue
        mapped = AZURE_VM_SIZES.get(vm_size)
        if mapped is None:
            continue
        if not _is_ondemand(item):
            continue
        price = _price(item)
        if price is None:
            continue
        gpu_code, gpu_count = mapped
        out.append(
            CloudQuote(
                provider=provider,
                gpu_code=gpu_code,
                region=str(item.get("armRegionName") or "").strip(),
                vm_size=vm_size,
                gpu_count=gpu_count,
                usd_per_hour_total=price,
            )
        )
    return out


def parse_aws_entries(
    payload: Mapping[str, Any],
    *,
    region: str,
    provider: str = PROVIDER_AWS,
) -> List[CloudQuote]:
    """把 AWS b0 价目表（已取回的单区 JSON）转成 ``CloudQuote`` 列表。

    结构：``{"manifest": {...}, "regions": {"US East (N. Virginia)": {键: 条目}}}``，
    条目里 ``Instance Type`` 才是可靠的规格名（键名把 ``p5.48xlarge`` 写成
    ``p5 48xlarge US East N. Virginia Linux``，拿键做匹配会在换地区时全崩）。

    与 Azure 不同，b0 这份文件已经筛掉了竞价/预留（路径里带
    ``ec2-ondemand-without-sec-sel``），所以这里只查卡数映射，不再判计费方式。
    """
    regions = payload.get("regions")
    if not isinstance(regions, Mapping):
        return []
    out: List[CloudQuote] = []
    for entries in regions.values():
        if not isinstance(entries, Mapping):
            continue
        for entry in entries.values():
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("Instance Family") or "") != GPU_INSTANCE_FAMILY:
                continue
            instance_type = str(entry.get("Instance Type") or "").strip()
            if instance_type.split(".")[0] in AWS_BLOCKED_FAMILIES:
                continue
            mapped = AWS_INSTANCE_TYPES.get(instance_type)
            if mapped is None:
                continue
            price = _positive_price(entry.get("price"))
            if price is None:
                continue
            gpu_code, gpu_count = mapped
            out.append(
                CloudQuote(
                    provider=provider,
                    gpu_code=gpu_code,
                    region=region,
                    vm_size=instance_type,
                    gpu_count=gpu_count,
                    usd_per_hour_total=price,
                )
            )
    return out


def cheapest_per_gpu(quotes: Iterable[CloudQuote]) -> Dict[Tuple[str, str], CloudQuote]:
    """按 ``(provider, gpu_code)`` 取「单卡折算价最低」的那条。

    同型号有 1 卡 / 2 卡 / 8 卡多种规格，最低价代表这家云上跑该型号最省的方案；
    记录里保留 ``vm_size``，人随时能看出这个价是哪台机器折出来的。
    """
    best: Dict[Tuple[str, str], CloudQuote] = {}
    for q in quotes:
        key = (q.provider, q.gpu_code)
        current = best.get(key)
        if current is None or q.usd_per_gpu_hour < current.usd_per_gpu_hour:
            best[key] = q
    return best


def usd_to_cny(usd: Decimal, fx_usd_cny: Decimal) -> Decimal:
    """USD/GPU/小时 → CNY/GPU/小时，保留 4 位（与库内 ``Numeric(18,4)`` 对齐）。"""
    return (usd * fx_usd_cny).quantize(Decimal("0.0001"))


AUTO_PROVIDERS: Tuple[str, ...] = (PROVIDER_AZURE, PROVIDER_AWS)


def provider_status(provider: str) -> str:
    """厂商的采集可得性：``auto`` / ``manual``（无公开接口，只能人工维护）。"""
    return "auto" if str(provider) in AUTO_PROVIDERS else "manual"


__all__ = [
    "AUTO_PROVIDERS",
    "AWS_BLOCKED_FAMILIES",
    "AWS_INSTANCE_TYPES",
    "AWS_REGION_PATHS",
    "AZURE_VM_SIZES",
    "BLOCKED_VM_SIZES",
    "CloudQuote",
    "EXCLUDE_SKU_MARKERS",
    "GPU_INSTANCE_FAMILY",
    "PROVIDER_AWS",
    "PROVIDER_AZURE",
    "SOURCE_ID",
    "SOURCE_NAME",
    "SOURCE_ROW_PREFIX",
    "SOURCE_SITE",
    "SOURCE_SITES",
    "cheapest_per_gpu",
    "parse_aws_entries",
    "parse_azure_items",
    "provider_status",
    "source_site",
    "usd_to_cny",
]
