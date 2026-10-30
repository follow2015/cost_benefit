"""单位 token 成本推导链（架构 §3.3，PRD 附录 A）。

链路：硬件 CAPEX/OPEX → 月成本结构 → 满负荷产能 → 实际产出 → 每百万 token 成本。

两种口径同时输出（避免 U 与 D_eq 双录入时的歧义）：
- `cost_per_m_capacity` = C_total(U) / (Q_cap_M·U)  ← 主口径（架构 §3.3）
- `cost_per_m_demand`   = C_total(U) / D_eq         ← 按实际需求摊薄
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from ai_roi.domain.calc.decimal_config import MONTHS_PER_YEAR, MTOK, ONE, ZERO, safe_div
from ai_roi.domain.calc.parameters import DerivedParams, POWER_MODE_BUNDLE, ScenarioParams


CTX_UPLIFT_K: Decimal = Decimal("1.0")
_SHORT_CTX: Decimal = Decimal("8192")


def context_uplift_factor(params: ScenarioParams) -> Decimal:
    """C-4：长上下文成本上浮因子（≥1）。纯函数。"""
    perf = params.perf
    if perf.Ctx <= _SHORT_CTX:
        return ONE
    long_ratio = perf.Ctx / _SHORT_CTX - ONE
    miss = ONE - params.demand.h
    return ONE + CTX_UPLIFT_K * long_ratio * miss


@dataclass(frozen=True)
class CostBreakdownItem:
    """成本结构占比明细（成本结构环图用）。"""

    key: str
    label: str
    amount: Decimal
    share: Decimal


@dataclass(frozen=True)
class UnitCostResult:
    """单位成本推导结果。"""

    C_fix_acct: Decimal
    C_fix_cash: Decimal
    C_var: Decimal
    C_total: Decimal
    C_total_cash: Decimal
    Q_out_M: Decimal
    cost_per_m_capacity: Decimal
    cost_per_m_demand: Decimal
    c_unit: Decimal
    context_uplift: Decimal
    breakdown: List[CostBreakdownItem]


def compute(params: ScenarioParams, derived: DerivedParams) -> UnitCostResult:
    """计算单位 token 成本与成本结构（纯函数）。"""
    c_var = derived.C_var_per_U * derived.U
    c_total = derived.C_fix_acct + c_var
    c_total_cash = derived.C_fix_cash + c_var
    q_out = derived.Q_cap_M * derived.U

    uplift = context_uplift_factor(params)
    cost_per_m_capacity = safe_div(c_total, q_out) * uplift
    cost_per_m_demand = safe_div(c_total, derived.Q_eq) * uplift

    bundle = params.power.power_mode == POWER_MODE_BUNDLE
    coloc_label = "包柜包电" if bundle else "机柜托管"
    coloc_amount = derived.bundle_rack_cost_m if bundle else params.power.Co_loc
    raw: Dict[str, tuple[str, Decimal]] = {
        "depreciation": ("折旧摊销", derived.Dep_m),
        "power": ("电费", c_var),
        "power_idle": ("待机功耗", derived.C_power_idle_m),
        "colocation": (coloc_label, coloc_amount),
        "network": ("网络带宽", params.power.Co_net),
        "storage": ("存储", params.power.Co_stor),
        "ops": ("运维人力", params.power.Co_ops / MONTHS_PER_YEAR),
        "eng": ("研发与平台人力", params.power.Co_eng / MONTHS_PER_YEAR),
        "sales_admin": ("销售与管理费用", params.power.Co_sales_admin / MONTHS_PER_YEAR),
        "other": ("其他运营费用", params.power.Co_other / MONTHS_PER_YEAR),
        "software": ("软件许可", params.hw.L_sw / MONTHS_PER_YEAR),
    }
    breakdown = [
        CostBreakdownItem(
            key=key,
            label=label,
            amount=amount,
            share=safe_div(amount, c_total),
        )
        for key, (label, amount) in raw.items()
        if amount != ZERO
    ]

    return UnitCostResult(
        C_fix_acct=derived.C_fix_acct,
        C_fix_cash=derived.C_fix_cash,
        C_var=c_var,
        C_total=c_total,
        C_total_cash=c_total_cash,
        Q_out_M=q_out,
        cost_per_m_capacity=cost_per_m_capacity,
        cost_per_m_demand=cost_per_m_demand,
        c_unit=cost_per_m_capacity / MTOK,
        context_uplift=uplift,
        breakdown=breakdown,
    )
