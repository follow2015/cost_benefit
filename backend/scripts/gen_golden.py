"""生成前后端共享的黄金向量 `goldenVectors.json`。

用法（在 backend/ 目录下）：
    python -m scripts.gen_golden

产物同时写入：
    backend/src/ai_roi/domain/calc/goldenVectors.json
    frontend/src/calc-engine/goldenVectors.json

后端为权威实现，向量由后端生成；前端一致性测试读取同一文件比对，偏差 ≤0.1% 视为通过。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from ai_roi.domain.calc.codec import params_to_dict
from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION
from ai_roi.domain.calc.decimal_config import D, ZERO, to_jsonable
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import (
    RENT_INC_NONE,
    UTIL_MODE_DEMAND_FROM_U,
    ScenarioParams,
    default_params,
)
from ai_roi.domain.calc.path_resolve import resolve
from ai_roi.domain.calc.scenario import CustomScenarioSpec
from ai_roi.domain.calc.sensitivity import TARGET_COST_ADVANTAGE, TARGET_COST_PER_M, TARGET_NPV

TOLERANCE = "0.001"

ASSERT_PATHS: List[str] = [
    "derived.CAPEX",
    "derived.P_sys",
    "derived.Dep_m",
    "derived.C_fix_cash",
    "derived.C_fix_acct",
    "derived.C_var_per_U",
    "derived.Q_cap_M",
    "derived.k",
    "derived.k_source",
    "derived.factor",
    "derived.D_out",
    "derived.D_in",
    "derived.Q_eq",
    "derived.U",
    "derived.I0",
    "derived.SV",
    "derived.r_m",
    "unit_cost.C_var",
    "unit_cost.C_total",
    "unit_cost.C_total_cash",
    "unit_cost.Q_out_M",
    "unit_cost.cost_per_m_capacity",
    "unit_cost.cost_per_m_demand",
    "unit_cost.c_unit",
    "revenue.R",
    "revenue.revenue_in",
    "revenue.revenue_out",
    "revenue.p_eq",
    "revenue.p_in_blended",
    "revenue.G",
    "revenue.GM_pct",
    "breakeven.feasible",
    "breakeven.M_U",
    "breakeven.U_be",
    "breakeven.Q_be",
    "breakeven.p_be",
    "cost_models[0].a",
    "cost_models[0].b",
    "cost_models[1].a",
    "cost_models[1].b",
    "cost_models[2].a",
    "cost_models[2].b",
    "cost_models[0].cost_at_demand",
    "cost_models[1].cost_at_demand",
    "cost_models[2].cost_at_demand",
    "crossover.crossovers[0].Q",
    "crossover.crossovers[0].status",
    "crossover.crossovers[0].active",
    "crossover.crossovers[1].Q",
    "crossover.crossovers[1].status",
    "crossover.crossovers[2].Q",
    "crossover.crossovers[2].status",
    "crossover.recommended[0].best_plan",
    "crossover.recommended[0].to_Q",
    "crossover.recommended[1].best_plan",
    "crossover.recommended[1].to_Q",
    "crossover.recommended[2].best_plan",
    "crossover.capacity_wall",
    "throughput.over_capacity",
    "throughput.k_source_label",
    "kpis[11].key",
    "kpis[11].value",
    "financials.npv",
    "financials.roi",
    "financials.tco",
    "financials.total_revenue",
    "financials.total_opex_cash",
    "financials.total_tax",
    "financials.total_net_cf",
    "financials.payback_static",
    "financials.payback_discounted",
    "financials.irr.solution",
    "financials.irr.method",
    "financials.irr.irr_monthly",
    "financials.irr.irr_annual",
    "financials.cashflows[0].revenue",
    "financials.cashflows[0].opex_cash",
    "financials.cashflows[0].net_cf",
    "financials.cashflows[0].discounted_cf",
    "financials.cashflows_yearly[0].net_cf",
    "sensitivity.base",
    "sensitivity.items[0].param",
    "sensitivity.items[0].swing",
    "sensitivity.items[1].param",
    "sensitivity.items[1].swing",
    "scenarios.cases[0].kpis.npv",
    "scenarios.cases[1].kpis.npv",
    "scenarios.cases[2].kpis.npv",
    "scenarios.cases[0].kpis.cost_per_m",
    "scenarios.cases[2].kpis.cost_per_m",
    "derived.weighted_e_price",
    "financials.financing.debt_ratio",
    "financials.financing.debt",
    "financials.financing.equity",
    "financials.financing.interest_total",
    "financials.financing.principal_total",
    "financials.financing.roe",
    "financials.financing.interest_coverage",
    "financials.financing.levered_npv",
    "financials.cashflows[0].interest",
    "financials.cashflows[0].principal",
    "kpis[12].key",
    "kpis[12].value",
    "joint.npv_min",
    "joint.npv_max",
    "joint.percentiles.p50",
    "joint.main_effects.U",
    "joint.main_effects.E_price",
    "joint.interactions.UE_price",
    "custom_scenarios.cases[0].kpis.npv",
    "custom_scenarios.cases[2].kpis.npv",
]


def _case(
    case_id: str, name: str, note: str, params: ScenarioParams, options: EngineOptions
) -> Dict[str, Any]:
    """计算单个用例并生成断言。"""
    payload = compute_all(params, options)
    expect: Dict[str, Any] = {}
    for path in ASSERT_PATHS:
        value = resolve(payload, path)
        if value is None:
            expect[path] = None
        elif isinstance(value, Decimal):
            expect[path] = to_jsonable(value)
        elif isinstance(value, bool):
            expect[path] = value
        else:
            expect[path] = value
    return {
        "id": case_id,
        "name": name,
        "note": note,
        "params": to_jsonable(params_to_dict(params)),
        "options": {
            "include_sensitivity": options.include_sensitivity,
            "include_scenarios": options.include_scenarios,
            "include_crossover": options.include_crossover,
            "sensitivity_target": options.sensitivity_target,
            "sensitivity_delta": to_jsonable(options.sensitivity_delta),
            "include_joint": options.include_joint,
            "joint_target": options.joint_target,
            "joint_delta": to_jsonable(options.joint_delta),
            "joint_vars": list(options.joint_vars) if options.joint_vars else None,
            "include_custom_scenarios": options.include_custom_scenarios,
            "custom_scenario_specs": (
                [
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "overrides": to_jsonable(dict(spec.overrides)),
                    }
                    for spec in options.custom_scenario_specs
                ]
                if options.custom_scenario_specs
                else None
            ),
        },
        "expect": expect,
    }


def build_cases() -> List[Dict[str, Any]]:
    """构造覆盖正常路径 + 边界/无解路径的用例集。"""
    cases: List[Dict[str, Any]] = []
    base_options = EngineOptions()

    cases.append(
        _case(
            "GV01",
            "基准默认参数（H100×8 / 70B / U=60%）",
            "四大能力主路径；推荐区间 C→B→A，Q_AC 为非活跃交点。",
            default_params(),
            base_options,
        )
    )

    high = (
        default_params()
        .with_override("perf.T_eff", D(5_000))
        .with_override("perf.T_pf", D(40_000))
        .with_override("perf.T_dc", D(4_000))
        .with_override("demand.D_eq", D(12_000))
        .with_override("demand.U", D("0.95"))
    )
    cases.append(
        _case("GV02", "高吞吐高需求（T_eff=5000, U=95%）", "验证产能放大后的单位成本下降与交点右移。", high, base_options)
    )

    low_price = (
        default_params()
        .with_override("pricing.p_in", D("0.25"))
        .with_override("pricing.p_out", D(1))
        .with_override("pricing.p_cache", D("0.025"))
        .with_override("hw.S_pct", D(0))
    )
    cases.append(
        _case(
            "GV03",
            "售价低于单位可变成本（无盈亏平衡点）",
            "M_U ≤ 0 → U_be 无解；现金流全负 → IRR 无解，仅返回 MIRR/说明。",
            low_price,
            base_options,
        )
    )

    taxed_params = default_params()
    taxed_params = ScenarioParams(
        hw=taxed_params.hw,
        power=taxed_params.power,
        perf=taxed_params.perf,
        demand=taxed_params.demand,
        pricing=taxed_params.pricing,
        finance=taxed_params.finance,
        bench=taxed_params.bench,
        conventions=taxed_params.conventions.with_taxed(True),
    )
    taxed_params = (
        taxed_params.with_override("finance.infl", D("0.03"))
        .with_override("pricing.g_price", D("-0.05"))
        .with_override("finance.Tax", D("0.25"))
    )
    cases.append(
        _case(
            "GV04",
            "含税口径 + 通胀 3% + 价格年降 5%",
            "验证税盾/税费、通胀与价格漂移的逐期缩放（非整数幂 exp(ln(x)·y)）。",
            taxed_params,
            base_options,
        )
    )

    rent_params = (
        default_params()
        .with_override("pricing.rent_inc", RENT_INC_NONE)
        .with_override("pricing.rent_fixed_monthly", D(20_000))
        .with_override("pricing.Rent_gpu", D(12))
        .with_override("perf.k_override", D("0.25"))
    )
    cases.append(
        _case(
            "GV05",
            "租赁不含电/托管 + 包月固定 + k 实测=0.25",
            "验证方案 B 系数分支与 k 优先级（实测优先于吞吐比）。",
            rent_params,
            EngineOptions(sensitivity_target=TARGET_COST_ADVANTAGE),
        )
    )

    small = (
        default_params()
        .with_override("demand.D_eq", D(120))
        .with_override("demand.U", D("0.02"))
    )
    cases.append(
        _case(
            "GV06",
            "小需求（120 Mtok/月）",
            "推荐方案落在 API 区间；自建现金流不足以回本 → 回本期为 null。",
            small,
            EngineOptions(sensitivity_target=TARGET_COST_PER_M),
        )
    )

    over = (
        default_params()
        .with_override("demand.D_eq", D(20_000))
        .with_override("demand.U", D("1.0"))
    )
    cases.append(
        _case(
            "GV07",
            "需求超过满负荷产能（容量墙）",
            "验证 over_capacity 判定与交点越界标注。",
            over,
            base_options,
        )
    )

    long_horizon = (
        default_params()
        .with_override("finance.T_horizon", D(120))
        .with_override("finance.r_w", D("0.15"))
        .with_override("hw.S_pct", D(0))
        .with_override("hw.Y_dep", D(6))
        .with_override("demand.util_mode", UTIL_MODE_DEMAND_FROM_U)
        .with_override("demand.U", D("0.75"))
    )
    cases.append(
        _case(
            "GV08",
            "120 期 / WACC 15% / 无残值 / D_eq 由 U 派生",
            "验证长周期折现累积精度与 util_mode 分支。",
            long_horizon,
            EngineOptions(sensitivity_target=TARGET_NPV),
        )
    )

    finance_gv09 = (
        default_params()
        .with_override("finance.debt_ratio", D("0.5"))
        .with_override("finance.debt_rate", D("0.05"))
        .with_override("finance.loan_term_months", D(48))
    )
    cases.append(
        _case(
            "GV09",
            "融资结构（债务杠杆 50%）",
            "验证利息/本金递推、权益 CF、杠杆后 NPV/IRR 与资产负债率/ROE。",
            finance_gv09,
            base_options,
        )
    )

    gv10_base = default_params()
    gv10_taxed = ScenarioParams(
        hw=gv10_base.hw,
        power=gv10_base.power,
        perf=gv10_base.perf,
        demand=gv10_base.demand,
        pricing=gv10_base.pricing,
        finance=gv10_base.finance,
        bench=gv10_base.bench,
        conventions=gv10_base.conventions.with_taxed(True),
    )
    gv10 = gv10_taxed.with_override("finance.debt_ratio", D("0.4"))
    cases.append(
        _case(
            "GV10",
            "融资 + 含税口径（债务杠杆 40%）",
            "验证利息税盾使 total_tax 低于无息情形，并验证利息覆盖倍数。",
            gv10,
            base_options,
        )
    )

    gv11 = (
        default_params()
        .with_override("power.e_price_peak", D("1.2"))
        .with_override("power.e_price_flat", D("0.8"))
        .with_override("power.e_price_valley", D("0.4"))
        .with_override("power.tou_peak_share", D("0.3"))
        .with_override("power.tou_valley_share", D("0.2"))
    )
    cases.append(
        _case(
            "GV11",
            "分时电价（峰1.2/平0.8/谷0.4，峰30%/谷20%）",
            "验证加权月电价驱动 C_var_per_U、b_A 与单位成本随加权价变化。",
            gv11,
            base_options,
        )
    )

    gv12 = (
        default_params()
        .with_override("power.e_price_peak", D("0.8"))
        .with_override("power.e_price_flat", D("0.8"))
        .with_override("power.e_price_valley", D("0.8"))
        .with_override("power.tou_peak_share", ZERO)
        .with_override("power.tou_valley_share", ZERO)
    )
    cases.append(
        _case(
            "GV12",
            "分时电价退化（三档=E_price, 占比=0）",
            "锁定 derived.C_var_per_U / cost_models[0].b 与 GV01 逐位一致（退化验证）。",
            gv12,
            base_options,
        )
    )

    gv13 = default_params().with_override("demand.g_demand", D("0.10"))
    cases.append(
        _case(
            "GV13",
            "需求逐年增长（g_demand=10%/年）",
            "验证后期收入/变动成本随 D_t 上升，NPV 高于 g=0 基准。",
            gv13,
            base_options,
        )
    )

    joint_options = EngineOptions(
        include_joint=True,
        joint_vars=["U", "E_price"],
        joint_delta=D("0.2"),
        joint_target=TARGET_NPV,
    )
    cases.append(
        _case(
            "GV14",
            "联合敏感性（U + E_price ±20%，2^2 网格）",
            "验证 NPV 联合 min/max/P50、主效应 S_U/S_E_price 与交互 I_UE。",
            default_params(),
            joint_options,
        )
    )

    custom_specs = [
        CustomScenarioSpec(
            key="conservative_price",
            label="保守价",
            overrides={"pricing.p_out": D(27), "pricing.p_in": D("6.75")},
        ),
        CustomScenarioSpec(
            key="high_elec",
            label="高电价",
            overrides={"power.E_price": D("1.5")},
        ),
        CustomScenarioSpec(
            key="high_leverage",
            label="高杠杆",
            overrides={"finance.debt_ratio": D("0.6"), "finance.debt_rate": D("0.06")},
        ),
    ]
    custom_options = EngineOptions(
        include_custom_scenarios=True,
        custom_scenario_specs=custom_specs,
    )
    cases.append(
        _case(
            "GV15",
            "自定义情景（保守价 / 高电价 / 高杠杆）",
            "验证任意 K 组参数覆盖下的 KPI 并列与可行性。",
            default_params(),
            custom_options,
        )
    )

    return cases


def main() -> None:
    """生成并写入两端的 goldenVectors.json。"""
    document = {
        "version": FORMULA_SPEC_VERSION,
        "generated_by": ENGINE_VERSION,
        "tolerance": TOLERANCE,
        "description": (
            "前后端计算引擎一致性黄金向量。后端 Python decimal 为权威实现，"
            "前端 decimal.js 镜像实现须在 0.1% 相对偏差内复现全部断言。"
        ),
        "assert_paths": ASSERT_PATHS,
        "cases": build_cases(),
    }
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"

    backend_path = (
        Path(__file__).resolve().parents[1] / "src" / "ai_roi" / "domain" / "calc" / "goldenVectors.json"
    )
    frontend_path = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "calc-engine" / "goldenVectors.json"
    )
    for target in (backend_path, frontend_path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        print(f"written: {target}")
    print(f"cases={len(document['cases'])} asserts/case={len(ASSERT_PATHS)}")


if __name__ == "__main__":
    main()
