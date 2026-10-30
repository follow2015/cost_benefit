"""基准库 ORM → DTO 序列化（适配器逻辑，隶属基础设施层）。

路由层写入路径（create/update）也直接用这里的 `*_out` / `entity_summary`
把落库后的实体转成响应/审计摘要——映射是传输细节，不属于应用层用例。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from ai_roi.application.schemas.benchmark import (
    ApiPriceOut,
    CloudPriceOut,
    GpuOut,
    ModelOut,
)
from ai_roi.domain.benchmark import (
    BENCHMARK_LABELS,
    BENCHMARK_UNIQUE_KEYS,
    resolve_rent_inc,
)
from ai_roi.domain.calc.decimal_config import dec_str
from ai_roi.infrastructure.db.models.benchmark import (
    BenchmarkApiPrice,
    BenchmarkCloudPrice,
    BenchmarkGpu,
    BenchmarkModel,
)


def _s(value: Optional[object]) -> Optional[str]:
    """数值 → 字符串（None 透传）。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return dec_str(value)
    return str(value)


def _s0(value: Optional[object]) -> str:
    """数值 → 字符串（None → "0"）。"""
    result = _s(value)
    return result if result is not None else "0"


def gpu_out(item: BenchmarkGpu) -> GpuOut:
    """GPU ORM → DTO。"""
    return GpuOut(
        id=item.id,
        code=item.code,
        name=item.name,
        vendor=item.vendor,
        price_cny=_s0(item.price_cny),
        tdp_w=_s0(item.tdp_w),
        vram_gb=_s0(item.vram_gb),
        rent_cny_per_hour=_s(item.rent_cny_per_hour),
        meta=dict(item.meta or {}),
        source=item.source,
        as_of=item.as_of,
        version=int(item.version or 1),
        is_builtin=item.tenant_id is None,
    )


def model_out(item: BenchmarkModel) -> ModelOut:
    """模型 ORM → DTO。"""
    return ModelOut(
        id=item.id,
        code=item.code,
        name=item.name,
        params_b=_s0(item.params_b),
        active_params_b=_s(item.active_params_b),
        is_moe=bool(item.is_moe),
        throughput_prefill=_s(item.throughput_prefill),
        throughput_decode=_s(item.throughput_decode),
        throughput_effective=_s(item.throughput_effective),
        k_ratio=_s(item.k_ratio),
        vram_required_gb=_s0(item.vram_required_gb),
        quant=item.quant,
        ctx_default=item.ctx_default,
        spec_method=item.spec_method,
        disagg_support=bool(item.disagg_support),
        meta=dict(item.meta or {}),
        source=item.source,
        as_of=item.as_of,
        version=int(item.version or 1),
        is_builtin=item.tenant_id is None,
    )


def cloud_out(item: BenchmarkCloudPrice) -> CloudPriceOut:
    """云租赁价 ORM → DTO。"""
    return CloudPriceOut(
        id=item.id,
        provider=item.provider,
        gpu_code=item.gpu_code,
        region=item.region,
        price_cny_per_hour=_s0(item.price_cny_per_hour),
        include_power=item.include_power,
        include_hosting=item.include_hosting,
        billing_mode=item.billing_mode,
        rent_inc=resolve_rent_inc(item.include_power, item.include_hosting),
        meta=dict(item.meta or {}),
        source=item.source,
        as_of=item.as_of,
        version=int(item.version or 1),
        is_builtin=item.tenant_id is None,
    )


def api_out(item: BenchmarkApiPrice) -> ApiPriceOut:
    """第三方 API 价 ORM → DTO。"""
    return ApiPriceOut(
        id=item.id,
        provider=item.provider,
        model_code=item.model_code,
        price_in_cny_per_m=_s0(item.price_in_cny_per_m),
        price_out_cny_per_m=_s0(item.price_out_cny_per_m),
        price_cache_cny_per_m=_s(item.price_cache_cny_per_m),
        meta=dict(item.meta or {}),
        source=item.source,
        as_of=item.as_of,
        version=int(item.version or 1),
        is_builtin=item.tenant_id is None,
    )


def entity_summary(kind: str, row: Any) -> Dict[str, Any]:
    """抽取业务唯一键 + 版本，作为审计 detail（避免整行大 JSON 入审计表）。"""
    summary: Dict[str, Any] = {
        "kind": kind,
        "kind_label": BENCHMARK_LABELS.get(kind, kind),
        "id": row.id,
        "version": int(row.version or 1),
        "is_builtin": row.tenant_id is None,
    }
    for key in BENCHMARK_UNIQUE_KEYS.get(kind, []):
        summary[key] = getattr(row, key, None)
    return summary


__all__ = [
    "gpu_out",
    "model_out",
    "cloud_out",
    "api_out",
    "entity_summary",
]
