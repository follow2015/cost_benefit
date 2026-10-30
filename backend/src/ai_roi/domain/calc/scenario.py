"""情景分析：保守 / 基准 / 乐观（架构 §3.11，PRD 附录 H）。

情景 = 一组参数乘子（保守：U↓、成本↑、售价↓、折现率↑；乐观相反）。
乘子表前后端共享，保证同一方案在两端得到同一组情景结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence

from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.parameters import ScenarioParams

SCENARIO_CONSERVATIVE = "conservative"
SCENARIO_BASE = "base"
SCENARIO_OPTIMISTIC = "optimistic"

SCENARIO_LABELS: Dict[str, str] = {
    SCENARIO_CONSERVATIVE: "保守",
    SCENARIO_BASE: "基准",
    SCENARIO_OPTIMISTIC: "乐观",
}

SCENARIO_MULTIPLIERS: Dict[str, Dict[str, Decimal]] = {
    SCENARIO_CONSERVATIVE: {
        "demand.U": D("0.8"),
        "demand.D_eq": D("0.8"),
        "power.E_price": D("1.15"),
        "hw.P_gpu": D("1.1"),
        "hw.P_aux": D("1.1"),
        "perf.T_eff": D("0.85"),
        "pricing.p_out": D("0.9"),
        "pricing.p_in": D("0.9"),
        "pricing.Rent_gpu": D("1.1"),
        "finance.r_w": D("1.25"),
    },
    SCENARIO_BASE: {},
    SCENARIO_OPTIMISTIC: {
        "demand.U": D("1.15"),
        "demand.D_eq": D("1.15"),
        "power.E_price": D("0.9"),
        "hw.P_gpu": D("0.92"),
        "hw.P_aux": D("0.92"),
        "perf.T_eff": D("1.15"),
        "pricing.p_out": D("1.1"),
        "pricing.p_in": D("1.1"),
        "pricing.Rent_gpu": D("0.92"),
        "finance.r_w": D("0.85"),
    },
}


@dataclass(frozen=True)
class ScenarioCase:
    """单个情景的结论。"""

    key: str
    label: str
    multipliers: Dict[str, Decimal]
    kpis: Dict[str, Optional[Decimal]]
    feasible: bool
    note: str = ""


@dataclass(frozen=True)
class ScenarioSetResult:
    """三情景并列结果。"""

    cases: List[ScenarioCase] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


KpiEvaluator = Callable[[ScenarioParams], Dict[str, Optional[Decimal]]]


def apply_multipliers(params: ScenarioParams, multipliers: Dict[str, Decimal]) -> ScenarioParams:
    """应用情景乘子，返回新参数对象。"""
    result = params
    for path, factor in multipliers.items():
        result = result.scale(path, factor)
    return result


def build_case_params(params: ScenarioParams, key: str) -> ScenarioParams:
    """构造某情景的参数（供后端/前端复用）。"""
    if key not in SCENARIO_MULTIPLIERS:
        raise KeyError(f"未知情景：{key}")
    return apply_multipliers(params, SCENARIO_MULTIPLIERS[key])


def compute(params: ScenarioParams, evaluator: KpiEvaluator) -> ScenarioSetResult:
    """并列计算三情景 KPI。

    Args:
        params: 基准参数。
        evaluator: `params -> {kpi 名 → 值|None}`。
    """
    cases: List[ScenarioCase] = []
    for key in (SCENARIO_CONSERVATIVE, SCENARIO_BASE, SCENARIO_OPTIMISTIC):
        case_params = build_case_params(params, key)
        kpis = evaluator(case_params)
        feasible = kpis.get("npv") is not None
        cases.append(
            ScenarioCase(
                key=key,
                label=SCENARIO_LABELS[key],
                multipliers=SCENARIO_MULTIPLIERS[key],
                kpis=kpis,
                feasible=feasible,
                note="" if feasible else "该情景下方案不可行（无盈亏平衡点或产能不足）。",
            )
        )
    return ScenarioSetResult(cases=cases, notes=[])


@dataclass(frozen=True)
class CustomScenarioSpec:
    """单个自定义情景定义（覆盖式）。"""

    key: str
    label: str
    overrides: Dict[str, Decimal]


@dataclass(frozen=True)
class CustomScenario:
    """单个自定义情景结论（结构对齐 `ScenarioCase`）。"""

    key: str
    label: str
    overrides: Dict[str, Decimal]
    kpis: Dict[str, Optional[Decimal]]
    feasible: bool
    note: str = ""


@dataclass(frozen=True)
class CustomScenarioSet:
    """自定义情景并列结果。"""

    cases: List[CustomScenario] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _apply_overrides(params: ScenarioParams, overrides: Dict[str, Decimal]) -> ScenarioParams:
    """应用一组覆盖值（路径 → 数值），返回新参数对象。"""
    result = params
    for path, value in overrides.items():
        result = result.with_override(path, value)
    return result


def compute_custom(
    params: ScenarioParams,
    specs: Sequence[CustomScenarioSpec],
    evaluator: KpiEvaluator,
) -> CustomScenarioSet:
    """并列计算任意 K 个自定义情景 KPI（复用 `evaluate_kpis`）。

    Args:
        params: 基准参数。
        specs: 自定义情景定义列表（K 任意）。
        evaluator: `params -> {kpi 名 → 值|None}`（即 `engine.evaluate_kpis`）。
    """
    cases: List[CustomScenario] = []
    for spec in specs:
        case_params = _apply_overrides(params, spec.overrides)
        kpis = evaluator(case_params)
        feasible = kpis.get("npv") is not None
        cases.append(
            CustomScenario(
                key=spec.key,
                label=spec.label,
                overrides=dict(spec.overrides),
                kpis=kpis,
                feasible=feasible,
                note="" if feasible else "该情景下方案不可行（无盈亏平衡点或产能不足）。",
            )
        )
    return CustomScenarioSet(cases=cases, notes=[])
