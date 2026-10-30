"""收入与毛利（架构 §3.4，**已修正 PRD 附录 C 的量纲错误**）。

修正点：PRD 原式 `R = (D_in×p_in + D_out×p_out − …)/1e6` 在 D 以「百万 token」为单位时
会把收入缩小 1e6 倍。统一「百万 token」口径后正确式为：

    R = D_in·((1−h)·p_in + h·p_cache) + D_out·p_out        [元/月]

其中 D_in / D_out 单位为 Mtok/月，p_* 单位为 元/Mtok，量纲自洽。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ai_roi.domain.calc.decimal_config import MTOK, ONE, ZERO, safe_div
from ai_roi.domain.calc.parameters import DerivedParams, ScenarioParams


@dataclass(frozen=True)
class RevenueResult:
    """收入与毛利结果。"""

    R: Decimal
    revenue_in: Decimal
    revenue_out: Decimal
    p_eq: Decimal
    p_in_blended: Decimal
    G: Decimal
    GM_pct: Decimal
    g_per_m: Decimal
    g_per_token: Decimal
    cost_benchmark_total: Optional[Decimal] = None
    G_benchmark: Optional[Decimal] = None
    GM_pct_benchmark: Optional[Decimal] = None
    loss_vs_benchmark: bool = False


def blended_input_price(params: ScenarioParams) -> Decimal:
    """输入侧混合单价：`(1−h)·p_in + h·p_cache`（元/Mtok）。"""
    pricing = params.pricing
    h = params.demand.h
    return (ONE - h) * pricing.p_in + h * pricing.p_cache_effective


def monthly_revenue(params: ScenarioParams, derived: DerivedParams) -> Decimal:
    """月收入 R（元/月），修正后的百万 token 口径。"""
    return derived.D_in * blended_input_price(params) + derived.D_out * params.pricing.p_out


def compute(
    params: ScenarioParams, derived: DerivedParams, c_total: Decimal
) -> RevenueResult:
    """计算收入、毛利与等效单价。

    Args:
        params: 方案参数。
        derived: 派生量。
        c_total: 月总成本（会计口径，来自 unit_cost）。
    """
    p_in_blended = blended_input_price(params)
    revenue_in = derived.D_in * p_in_blended
    revenue_out = derived.D_out * params.pricing.p_out
    total = revenue_in + revenue_out

    p_eq = safe_div(total, derived.Q_eq)
    gross = total - c_total
    cb = params.pricing.cost_benchmark
    cost_benchmark_total = None
    gross_benchmark = None
    gm_benchmark = None
    loss_vs_benchmark = False
    if cb is not None and cb > ZERO and derived.Q_eq > ZERO:
        cost_benchmark_total = derived.Q_eq * cb
        gross_benchmark = total - cost_benchmark_total
        gm_benchmark = safe_div(gross_benchmark, total)
        loss_vs_benchmark = p_eq < cb
    return RevenueResult(
        R=total,
        revenue_in=revenue_in,
        revenue_out=revenue_out,
        p_eq=p_eq,
        p_in_blended=p_in_blended,
        G=gross,
        GM_pct=safe_div(gross, total),
        g_per_m=safe_div(gross, derived.Q_eq),
        g_per_token=safe_div(gross, derived.Q_eq) / MTOK,
        cost_benchmark_total=cost_benchmark_total,
        G_benchmark=gross_benchmark,
        GM_pct_benchmark=gm_benchmark,
        loss_vs_benchmark=loss_vs_benchmark,
    )
