"""投资财务指标：现金流 / NPV / TCO / ROI / 回本（架构 §3.7 §3.8）。

关键口径（避免重复计入，架构 §3.7）：
- `I0 = CAPEX + 上线前费用`，作为 t=0 现金流出进入 NPV；
- **折旧是非现金费用，不进经营现金流**，只用于利润表与税盾；
- `CF_t = R_t − OPEX_cash_t − Tax_t`，其中 `OPEX_cash_t` 不含折旧；
- 期末残值 `SV = CAPEX·S%` 计入 `CF_T`；
- `TCO = CAPEX + Σ OPEX_cash_t`（税费为利润相关支出，不计入 TCO，见 README 口径说明）；
- 月折现率 `r_m = (1+r_w)^(1/12) − 1`，`NPV = −I0 + Σ CF_t/(1+r_m)^t`。

增量能力（见 `docs/03-Incremental-Design.md`）：
① 融资结构（债务杠杆）：债务余额递推 → 利息/本金/税盾/权益 CF；`npv`/`irr` 自然延伸为杠杆后口径；
④ 需求逐年增长（g_demand）：月序列 `D_t = D·(1+g_demand)^floor((t−1)/12)` 缩放收入与变动成本。
上述两项在默认参数下完全退化为现状（debt_ratio=0、g_demand=0）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from ai_roi.domain.calc import irr as irr_module
from ai_roi.domain.calc.decimal_config import (
    D,
    MONTHS_PER_YEAR,
    ONE,
    ZERO,
    dmax,
    dpow,
    dsum,
    safe_div,
)
from ai_roi.domain.calc.parameters import DerivedParams, ScenarioParams
from ai_roi.domain.calc.revenue import RevenueResult

PERIOD_MONTH = "month"
PERIOD_YEAR = "year"


@dataclass(frozen=True)
class CashflowRow:
    """现金流序列的一行（对应类图 CashflowRow）。"""

    period: int
    period_type: str
    revenue: Decimal
    opex_cash: Decimal
    depreciation: Decimal
    ebt: Decimal
    interest: Decimal
    principal: Decimal
    tax: Decimal
    net_cf: Decimal
    cum_cf: Decimal
    discount_factor: Decimal
    discount_ratio: Decimal
    discounted_cf: Decimal
    cum_discounted_cf: Decimal


@dataclass(frozen=True)
class FinancingResult:
    """融资结构结果（债务杠杆）。债务占比 = 0 时全部退化为现状。"""

    debt_ratio: Decimal
    debt: Decimal
    equity: Decimal
    interest_total: Decimal
    principal_total: Decimal
    interest_coverage: Optional[Decimal]
    roe: Decimal
    levered_npv: Decimal
    levered_irr: Optional[Decimal]


@dataclass(frozen=True)
class FinancialResult:
    """财务指标结果（对应类图 FinancialResult）。"""

    I0: Decimal
    SV: Decimal
    r_m: Decimal
    npv: Decimal
    roi: Decimal
    tco: Decimal
    total_revenue: Decimal
    total_opex_cash: Decimal
    total_tax: Decimal
    total_net_cf: Decimal
    sla_provision_total: Decimal
    payback_static: Optional[Decimal]
    payback_discounted: Optional[Decimal]
    irr: irr_module.IrrResult
    financing: FinancingResult
    cashflows: List[CashflowRow] = field(default_factory=list)
    cashflows_yearly: List[CashflowRow] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _ramp_factor(period: int, params: ScenarioParams) -> Decimal:
    """建设期收入爬坡因子。

    默认关闭（`finance.revenue_ramp=False`）→ 恒为 1。
    开启时：前 `T_deploy` 个月线性爬坡 `t / T_deploy`。
    """
    if not params.finance.revenue_ramp:
        return ONE
    t_deploy = params.hw.T_deploy
    if t_deploy <= ZERO or D(period) > t_deploy:
        return ONE
    return D(period) / t_deploy


def _year_bucket(rows: List[CashflowRow], r_m: Decimal) -> List[CashflowRow]:
    """把月度序列聚合为年度序列（每 12 个月一档）。"""
    yearly: List[CashflowRow] = []
    cum_cf = ZERO
    cum_disc = ZERO
    bucket: List[CashflowRow] = []
    one_plus_rm = ONE + r_m
    for row in rows:
        bucket.append(row)
        if len(bucket) == int(MONTHS_PER_YEAR) or row is rows[-1]:
            year_index = len(yearly) + 1
            revenue = dsum(item.revenue for item in bucket)
            opex = dsum(item.opex_cash for item in bucket)
            dep = dsum(item.depreciation for item in bucket)
            ebt = dsum(item.ebt for item in bucket)
            interest = dsum(item.interest for item in bucket)
            principal = dsum(item.principal for item in bucket)
            tax = dsum(item.tax for item in bucket)
            net_cf = dsum(item.net_cf for item in bucket)
            disc = dsum(item.discounted_cf for item in bucket)
            cum_cf += net_cf
            cum_disc += disc
            yearly.append(
                CashflowRow(
                    period=year_index,
                    period_type=PERIOD_YEAR,
                    revenue=revenue,
                    opex_cash=opex,
                    depreciation=dep,
                    ebt=ebt,
                    interest=interest,
                    principal=principal,
                    tax=tax,
                    net_cf=net_cf,
                    cum_cf=cum_cf,
                    discount_factor=ONE / dpow(one_plus_rm, D(MONTHS_PER_YEAR * year_index)),
                    discount_ratio=safe_div(disc, net_cf, ONE),
                    discounted_cf=disc,
                    cum_discounted_cf=cum_disc,
                )
            )
            bucket = []
    return yearly


def _interpolate_payback(
    threshold: Decimal, cumulative: List[tuple[int, Decimal, Decimal]]
) -> Optional[Decimal]:
    """线性插值求回本月数。

    Args:
        threshold: 需要达到的累计值（静态回本为 I0，折现回本为 0 的偏移量已在调用侧处理）。
        cumulative: `[(期数, 期末累计值, 该期现金流)]`。
    """
    previous = ZERO
    for period, cum_value, flow in cumulative:
        if cum_value >= threshold:
            if flow == ZERO:
                return D(period)
            fraction = (threshold - previous) / flow
            if fraction < ZERO:
                fraction = ZERO
            if fraction > ONE:
                fraction = ONE
            return D(period - 1) + fraction
        previous = cum_value
    return None


def compute(
    params: ScenarioParams,
    derived: DerivedParams,
    rev: RevenueResult,
) -> FinancialResult:
    """计算全部投资财务指标与现金流序列（纯函数）。"""
    finance = params.finance
    horizon = int(finance.T_horizon)
    notes: List[str] = []

    debt_ratio = finance.debt_ratio
    debt = derived.I0 * debt_ratio
    equity = derived.I0 * (ONE - debt_ratio)
    debt_rate_month = finance.debt_rate / MONTHS_PER_YEAR
    loan_term = int(finance.loan_term_months)
    bal = debt

    rows: List[CashflowRow] = []
    cum_cf = ZERO
    cum_disc = ZERO
    one_plus_rm = ONE + derived.r_m

    interest_total = ZERO
    principal_total = ZERO
    coverage_candidates: List[Decimal] = []

    price_base = ONE + params.pricing.g_price
    infl_base = ONE + finance.infl
    learn_base = ONE - params.finance.cost_learning_rate
    scale_clamped = price_base <= ZERO or infl_base <= ZERO or learn_base <= ZERO
    safe_price_base = price_base if price_base > ZERO else D("1e-6")
    safe_infl_base = infl_base if infl_base > ZERO else D("1e-6")
    safe_learn_base = learn_base if learn_base > ZERO else D("1e-6")

    for period in range(1, horizon + 1):
        ramp = _ramp_factor(period, params)
        exponent = D(period - 1) / MONTHS_PER_YEAR
        g_price = params.pricing.g_price
        price_scale = dpow(safe_price_base, exponent) if g_price != ZERO else ONE
        infl_scale = dpow(safe_infl_base, exponent) if finance.infl != ZERO else ONE

        year_index = D(period - 1) // MONTHS_PER_YEAR
        demand_growth = dpow(ONE + params.demand.g_demand, year_index)

        learning_factor = (
            dpow(safe_learn_base, exponent) if params.finance.cost_learning_rate != ZERO else ONE
        )

        revenue = rev.R * demand_growth * price_scale * ramp
        opex_cash = (
            derived.C_fix_cash
            + derived.C_var_per_U * derived.U * demand_growth * learning_factor
        ) * infl_scale + revenue * params.perf.SLA_penalty_rate

        interest = bal * debt_rate_month if bal > ZERO else ZERO
        if period <= loan_term and loan_term > 0 and debt > ZERO:
            if period == loan_term:
                principal = bal
            else:
                principal = debt / D(loan_term)
        else:
            principal = ZERO

        depreciation = derived.Dep_m if D(period) <= derived.dep_months else ZERO
        ebt = revenue - opex_cash - depreciation - interest
        tax = dmax(ZERO, ebt) * finance.Tax if params.conventions.taxed else ZERO
        net_cf = revenue - opex_cash - interest - principal - tax
        if period == horizon:
            net_cf += derived.SV

        bal = bal - principal if bal > ZERO else ZERO

        if interest > ZERO:
            ebit = ebt + interest
            coverage_candidates.append(safe_div(ebit, interest))

        interest_total += interest
        principal_total += principal

        cum_cf += net_cf
        discount_factor = ONE / dpow(one_plus_rm, D(period))
        discounted = net_cf * discount_factor
        cum_disc += discounted

        rows.append(
            CashflowRow(
                period=period,
                period_type=PERIOD_MONTH,
                revenue=revenue,
                opex_cash=opex_cash,
                depreciation=depreciation,
                ebt=ebt,
                interest=interest,
                principal=principal,
                tax=tax,
                net_cf=net_cf,
                cum_cf=cum_cf,
                discount_factor=discount_factor,
                discount_ratio=safe_div(discounted, net_cf, ONE),
                discounted_cf=discounted,
                cum_discounted_cf=cum_disc,
            )
        )

    if scale_clamped:
        notes.append(
            "年化缩放因子底数出现非正（年价格变动/通胀率 ≤ −100%，或学习曲线年降幅 ≥ 100%），"
            "已夹紧至 1e-6 计算，结果仅作下限参考，请修正参数后重算。"
        )

    total_revenue = dsum(row.revenue for row in rows)
    total_opex = dsum(row.opex_cash for row in rows)
    total_tax = dsum(row.tax for row in rows)
    total_cf = dsum(row.net_cf for row in rows)
    sla_provision_total = total_revenue * params.perf.SLA_penalty_rate

    npv = -equity + cum_disc
    tco = derived.CAPEX + total_opex
    roi = safe_div(total_cf - derived.I0, derived.I0)

    payback_static = _interpolate_payback(
        derived.I0, [(row.period, row.cum_cf, row.net_cf) for row in rows]
    )
    payback_discounted = _interpolate_payback(
        derived.I0,
        [(row.period, row.cum_discounted_cf, row.discounted_cf) for row in rows],
    )
    if payback_static is None:
        notes.append(f"分析周期 {horizon} 个月内未收回期初投资（静态回本 > 周期）。")
    if payback_discounted is None:
        notes.append(f"分析周期 {horizon} 个月内折现累计现金流未转正（折现回本 > 周期）。")
    if not params.conventions.taxed:
        notes.append("当前为税前口径（Taxed=false）：现金流未扣税，亦未计折旧税盾。")

    equity_cf_0 = -equity
    equity_cashflows: List[Decimal] = [equity_cf_0] + [row.net_cf for row in rows]
    irr_result = irr_module.compute(
        equity_cashflows,
        finance_rate=derived.r_m,
        reinvest_rate=derived.r_m,
    )
    roe = safe_div(total_cf, equity)
    interest_coverage = min(coverage_candidates) if coverage_candidates else None

    financing = FinancingResult(
        debt_ratio=debt_ratio,
        debt=debt,
        equity=equity,
        interest_total=interest_total,
        principal_total=principal_total,
        interest_coverage=interest_coverage,
        roe=roe,
        levered_npv=npv,
        levered_irr=irr_result.irr_annual,
    )

    return FinancialResult(
        I0=derived.I0,
        SV=derived.SV,
        r_m=derived.r_m,
        npv=npv,
        roi=roi,
        tco=tco,
        total_revenue=total_revenue,
        total_opex_cash=total_opex,
        total_tax=total_tax,
        total_net_cf=total_cf,
        sla_provision_total=sla_provision_total,
        payback_static=payback_static,
        payback_discounted=payback_discounted,
        irr=irr_result,
        financing=financing,
        cashflows=rows,
        cashflows_yearly=_year_bucket(rows, derived.r_m),
        notes=notes,
    )
