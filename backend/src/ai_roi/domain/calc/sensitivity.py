"""单因素敏感性分析 · 龙卷风图（架构 §3.11）。

- 默认 8 个变量（≥6 满足 REQ-06）：`U, E_price, Rent_gpu, API_out, CAPEX, T_eff, r_w, p_out`；
- 每个变量在 `±Δ%`（默认 ±20%）重算目标指标（NPV 或 每百万 token 成本）；
- 按 `swing = |high − low|` 降序排列，即龙卷风图从宽到窄；
- 重算不可行（如贡献边际 ≤0）→ 该点标 `feasible=False` 并截断。

引擎解耦：目标评估函数由调用方注入（`evaluator`），使本模块保持纯函数、可单测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence

from ai_roi.domain.calc.decimal_config import D, ONE, ZERO, dsum, safe_div
from ai_roi.domain.calc.parameters import ScenarioParams

TARGET_NPV = "npv"
TARGET_COST_PER_M = "cost_per_m"
TARGET_COST_ADVANTAGE = "cost_advantage"

TARGET_LABELS = {
    TARGET_NPV: "NPV（元）",
    TARGET_COST_PER_M: "每百万 token 成本（元/Mtok）",
    TARGET_COST_ADVANTAGE: "自建相对最优替代方案的月成本优势（元/月）",
}
TARGETS = (TARGET_NPV, TARGET_COST_PER_M, TARGET_COST_ADVANTAGE)


@dataclass(frozen=True)
class SensitivityVar:
    """敏感性变量定义（前后端共享同一注册表，保证结果可比）。"""

    key: str
    label: str
    paths: List[str]
    note: str = ""


DEFAULT_VARS: List[SensitivityVar] = [
    SensitivityVar(
        key="U",
        label="有效利用率 U",
        paths=["demand.U", "demand.D_eq"],
        note="利用率与月需求量同比例变动，保持「负载—收入」口径一致。",
    ),
    SensitivityVar(key="E_price", label="电价 E_price", paths=["power.E_price"]),
    SensitivityVar(key="Rent_gpu", label="云租赁单价 Rent_gpu", paths=["pricing.Rent_gpu"]),
    SensitivityVar(key="API_out", label="第三方 API 输出价", paths=["pricing.API_out"]),
    SensitivityVar(
        key="CAPEX",
        label="整机 CAPEX",
        paths=["hw.P_gpu", "hw.P_aux"],
        note="GPU 采购价与配套价同比例变动。",
    ),
    SensitivityVar(key="T_eff", label="有效吞吐 T_eff", paths=["perf.T_eff"]),
    SensitivityVar(key="r_w", label="折现率 WACC", paths=["finance.r_w"]),
    SensitivityVar(key="p_out", label="输出 token 单价 p_out", paths=["pricing.p_out"]),
    SensitivityVar(key="Co_eng", label="研发人力 Co_eng", paths=["power.Co_eng"]),
    SensitivityVar(
        key="Co_sales_admin", label="销管费用 Co_sales_admin", paths=["power.Co_sales_admin"]
    ),
    SensitivityVar(key="Co_other", label="其他费用 Co_other", paths=["power.Co_other"]),
    SensitivityVar(key="SLA_penalty_rate", label="SLA 计提率", paths=["perf.SLA_penalty_rate"]),
    SensitivityVar(
        key="cost_learning_rate", label="学习曲线年降幅", paths=["finance.cost_learning_rate"]
    ),
]


@dataclass(frozen=True)
class SensitivityItem:
    """单变量敏感性结果（对应类图 SensitivityItem）。"""

    param: str
    label: str
    base: Decimal
    low: Optional[Decimal]
    high: Optional[Decimal]
    delta_low: Optional[Decimal]
    delta_high: Optional[Decimal]
    swing: Decimal
    swing_pct: Decimal
    low_feasible: bool
    high_feasible: bool
    note: str


@dataclass(frozen=True)
class SensitivityResult:
    """敏感性结果（对应类图 SensitivityResult）。"""

    target: str
    target_label: str
    delta: Decimal
    base: Decimal
    items: List[SensitivityItem] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


Evaluator = Callable[[ScenarioParams, str], Optional[Decimal]]


def _scaled(params: ScenarioParams, var: SensitivityVar, factor: Decimal) -> ScenarioParams:
    """按因子缩放变量涉及的全部参数路径。"""
    result = params
    for path in var.paths:
        result = result.scale(path, factor)
    return result


def compute(
    params: ScenarioParams,
    evaluator: Evaluator,
    target: str = TARGET_NPV,
    delta: Decimal = D("0.2"),
    variables: Optional[Sequence[SensitivityVar]] = None,
) -> SensitivityResult:
    """执行单因素敏感性分析。

    Args:
        params: 基准参数。
        evaluator: `(params, target) -> 目标值 | None`（None 表示该点不可行）。
        target: `npv` 或 `cost_per_m`。
        delta: 变动幅度（比率，默认 0.2 = ±20%）。
        variables: 变量集，缺省用 `DEFAULT_VARS`。
    """
    var_list = list(variables) if variables else list(DEFAULT_VARS)
    base_value = evaluator(params, target)
    if base_value is None:
        return SensitivityResult(
            target=target,
            target_label=TARGET_LABELS.get(target, target),
            delta=delta,
            base=ZERO,
            items=[],
            notes=["基准情形不可行，无法开展敏感性分析。"],
        )

    items: List[SensitivityItem] = []
    for var in var_list:
        low_value = evaluator(_scaled(params, var, ONE - delta), target)
        high_value = evaluator(_scaled(params, var, ONE + delta), target)
        if low_value is None and high_value is None:
            swing = ZERO
        elif low_value is None:
            swing = abs(high_value - base_value)  # type: ignore[operator]
        elif high_value is None:
            swing = abs(low_value - base_value)
        else:
            swing = abs(high_value - low_value)

        notes: List[str] = [var.note] if var.note else []
        if low_value is None:
            notes.append(f"{var.label} −{delta * D(100)}% 时方案不可行，已截断。")
        if high_value is None:
            notes.append(f"{var.label} +{delta * D(100)}% 时方案不可行，已截断。")

        items.append(
            SensitivityItem(
                param=var.key,
                label=var.label,
                base=base_value,
                low=low_value,
                high=high_value,
                delta_low=None if low_value is None else low_value - base_value,
                delta_high=None if high_value is None else high_value - base_value,
                swing=swing,
                swing_pct=safe_div(swing, abs(base_value)),
                low_feasible=low_value is not None,
                high_feasible=high_value is not None,
                note="；".join(notes),
            )
        )

    items.sort(key=lambda item: item.swing, reverse=True)
    return SensitivityResult(
        target=target,
        target_label=TARGET_LABELS.get(target, target),
        delta=delta,
        base=base_value,
        items=items,
        notes=[],
    )


def var_registry() -> Dict[str, SensitivityVar]:
    """变量注册表（key → 定义），供 API/前端查询。"""
    return {var.key: var for var in DEFAULT_VARS}


JOINT_DEFAULT_VARS: List[SensitivityVar] = [
    SensitivityVar(key="U", label="有效利用率 U", paths=["demand.U", "demand.D_eq"]),
    SensitivityVar(key="E_price", label="电价 E_price", paths=["power.E_price"]),
    SensitivityVar(key="Rent_gpu", label="云租赁单价 Rent_gpu", paths=["pricing.Rent_gpu"]),
    SensitivityVar(key="API_out", label="第三方 API 输出价", paths=["pricing.API_out"]),
    SensitivityVar(key="CAPEX", label="整机 CAPEX", paths=["hw.P_gpu", "hw.P_aux"]),
    SensitivityVar(key="T_eff", label="有效吞吐 T_eff", paths=["perf.T_eff"]),
    SensitivityVar(key="r_w", label="折现率 WACC", paths=["finance.r_w"]),
    SensitivityVar(key="p_out", label="输出 token 单价 p_out", paths=["pricing.p_out"]),
]


@dataclass(frozen=True)
class JointSensitivityResult:
    """多因素联合敏感性结果（确定性边界与方差分解）。"""

    npv_min: Decimal
    npv_max: Decimal
    percentiles: Dict[str, Decimal]
    main_effects: Dict[str, Decimal]
    interactions: Dict[str, Decimal]
    notes: List[str] = field(default_factory=list)


def _percentile(sorted_vals: List[Decimal], q: Decimal) -> Decimal:
    """确定性分位数（线性插值），`q` ∈ [0,1]。前后端须同法。"""
    n = len(sorted_vals)
    if n == 0:
        return ZERO
    if n == 1:
        return sorted_vals[0]
    rank = q * D(n - 1)
    lo = int(rank.to_integral_value(rounding="ROUND_FLOOR"))
    hi = min(lo + 1, n - 1)
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - D(lo)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def compute_joint(
    params: ScenarioParams,
    evaluator: Evaluator,
    target: str = TARGET_NPV,
    delta: Decimal = D("0.2"),
    variables: Optional[Sequence[SensitivityVar]] = None,
) -> JointSensitivityResult:
    """执行多因素联合敏感性分析（确定性，非随机）。

    Args:
        params: 基准参数。
        evaluator: `(params, target) -> 目标值 | None`（同单因素）。
        target: 目标指标（默认 npv）。
        delta: 每变量 ±Δ%（默认 0.2）。
        variables: 变量集（缺省用 `JOINT_DEFAULT_VARS` 前 2 个：U + E_price）。
    """
    var_list = list(variables) if variables else JOINT_DEFAULT_VARS[:2]
    n = len(var_list)

    npv_grid: List[Decimal] = []
    grid_params: List[ScenarioParams] = []
    for mask in range(1 << n):
        scaled = params
        for i, var in enumerate(var_list):
            factor = ONE + delta if (mask >> i) & 1 else ONE - delta
            scaled = _scaled(scaled, var, factor)
        grid_params.append(scaled)
        value = evaluator(scaled, target)
        if value is not None:
            npv_grid.append(value)

    notes: List[str] = []
    if not npv_grid:
        notes.append("联合敏感性所有网格点均不可行，无法给出边界。")
        return JointSensitivityResult(
            npv_min=ZERO, npv_max=ZERO,
            percentiles={"p5": ZERO, "p50": ZERO, "p95": ZERO},
            main_effects={var.key: ZERO for var in var_list},
            interactions={},
            notes=notes,
        )

    npv_sorted = sorted(npv_grid)
    npv_min = npv_sorted[0]
    npv_max = npv_sorted[-1]
    percentiles = {
        "p5": _percentile(npv_sorted, D("0.05")),
        "p50": _percentile(npv_sorted, D("0.5")),
        "p95": _percentile(npv_sorted, D("0.95")),
    }

    main_effects: Dict[str, Decimal] = {}
    for i, var in enumerate(var_list):
        high_vals: List[Decimal] = []
        low_vals: List[Decimal] = []
        for mask in range(1 << n):
            if (mask >> i) & 1:
                v = evaluator(grid_params[mask], target)
                if v is not None:
                    high_vals.append(v)
            else:
                v = evaluator(grid_params[mask], target)
                if v is not None:
                    low_vals.append(v)
        if high_vals and low_vals:
            mean_high = dsum(high_vals) / D(len(high_vals))
            mean_low = dsum(low_vals) / D(len(low_vals))
            main_effects[var.key] = abs(mean_high - mean_low)
        else:
            main_effects[var.key] = ZERO

    interactions: Dict[str, Decimal] = {}
    for i in range(n):
        for j in range(i + 1, n):
            key = f"{var_list[i].key}{var_list[j].key}"

            def _corner(a_high: bool, b_high: bool) -> Optional[Decimal]:
                mask = 0
                if a_high:
                    mask |= 1 << i
                if b_high:
                    mask |= 1 << j
                return evaluator(grid_params[mask], target)

            hi_hi = _corner(True, True)
            hi_lo = _corner(True, False)
            lo_hi = _corner(False, True)
            lo_lo = _corner(False, False)
            if None not in (hi_hi, hi_lo, lo_hi, lo_lo):
                interactions[key] = (
                    hi_hi - hi_lo - lo_hi + lo_lo  # type: ignore[operator]
                )
            else:
                interactions[key] = ZERO

    return JointSensitivityResult(
        npv_min=npv_min,
        npv_max=npv_max,
        percentiles=percentiles,
        main_effects=main_effects,
        interactions=interactions,
        notes=notes,
    )
