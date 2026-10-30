"""计算引擎编排（后端权威实现）。

职责：把 `calc/` 下的纯函数模块串成一条完整推导链，并产出与前端结构完全一致的结果载荷。
- 纯函数、零 IO、零 DB（可直接单测）；
- 输出中的 Decimal 由调用方（API 层）用 `to_jsonable` 统一转字符串；
- `authoritative=True`（后端权威）；前端镜像实现返回 False。

前端对应文件：`frontend/src/calc-engine/index.ts`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from ai_roi.domain.calc import benchmark_alerts as benchmark_alerts_module
from ai_roi.domain.calc import breakeven as breakeven_module
from ai_roi.domain.calc import cost_model as cost_model_module
from ai_roi.domain.calc import crossover as crossover_module
from ai_roi.domain.calc import financials as financials_module
from ai_roi.domain.calc import revenue as revenue_module
from ai_roi.domain.calc import scenario as scenario_module
from ai_roi.domain.calc import sensitivity as sensitivity_module
from ai_roi.domain.calc.scenario import CustomScenarioSpec
from ai_roi.domain.calc import throughput as throughput_module
from ai_roi.domain.calc import unit_cost as unit_cost_module
from ai_roi.domain.calc.codec import params_to_dict
from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION
from ai_roi.domain.calc.decimal_config import D, MTOK, MONTHS_PER_YEAR, ONE, ZERO, dec_str, dpow, safe_div
from ai_roi.domain.calc.parameters import DerivedParams, ScenarioParams, derive


@dataclass(frozen=True)
class EngineOptions:
    """计算选项。"""

    include_sensitivity: bool = True
    include_scenarios: bool = True
    include_crossover: bool = True
    sensitivity_target: str = sensitivity_module.TARGET_NPV
    sensitivity_delta: Decimal = D("0.2")
    include_joint: bool = False
    joint_target: str = sensitivity_module.TARGET_NPV
    joint_delta: Decimal = D("0.2")
    joint_vars: Optional[List[str]] = None
    include_custom_scenarios: bool = False
    custom_scenario_specs: Optional[List[CustomScenarioSpec]] = None


@dataclass(frozen=True)
class CoreResult:
    """核心推导链结果（不含敏感性/情景，供其递归调用）。"""

    derived: DerivedParams
    throughput: throughput_module.ThroughputInfo
    unit_cost: unit_cost_module.UnitCostResult
    revenue: revenue_module.RevenueResult
    breakeven: breakeven_module.BreakevenResult
    cost_models: List[cost_model_module.CostModel]
    financials: financials_module.FinancialResult
    warnings: List[str] = field(default_factory=list)


def compute_core(params: ScenarioParams) -> CoreResult:
    """执行核心推导链：派生量 → 吞吐 → 单位成本 → 收入 → 盈亏平衡 → 三方案 → 财务。"""
    derived = derive(params)
    throughput_info = throughput_module.analyze(params, derived)
    unit_cost_result = unit_cost_module.compute(params, derived)
    revenue_result = revenue_module.compute(params, derived, unit_cost_result.C_total)
    breakeven_result = breakeven_module.compute(derived, revenue_result)
    models = cost_model_module.build_all(params, derived)
    financial_result = financials_module.compute(params, derived, revenue_result)

    warnings: List[str] = list(throughput_info.warnings)
    if not breakeven_result.feasible:
        warnings.append(breakeven_result.note)
    warnings.extend(financial_result.notes)
    if derived.k_source != "measured":
        warnings.append(
            f"等效折算系数 k = {dec_str(derived.k)} 来源为「{throughput_info.k_source_label}」，"
            "非实测值，结论请结合敏感性分析解读。"
        )

    warnings.extend(
        benchmark_alerts_module.benchmark_alerts(params, revenue_result, unit_cost_result)
    )

    return CoreResult(
        derived=derived,
        throughput=throughput_info,
        unit_cost=unit_cost_result,
        revenue=revenue_result,
        breakeven=breakeven_result,
        cost_models=models,
        financials=financial_result,
        warnings=warnings,
    )


def is_feasible(derived: DerivedParams) -> bool:
    """基本可行性：产能与需求量必须为正，否则推导链退化。"""
    return derived.Q_cap_M > ZERO and derived.U > ZERO and derived.Q_eq > ZERO


def evaluate_target(params: ScenarioParams, target: str) -> Optional[Decimal]:
    """敏感性目标评估器：返回目标指标值，不可行返回 None。"""
    derived = derive(params)
    if not is_feasible(derived):
        return None
    unit_cost_result = unit_cost_module.compute(params, derived)
    if target == sensitivity_module.TARGET_COST_PER_M:
        return unit_cost_result.cost_per_m_capacity
    if target == sensitivity_module.TARGET_COST_ADVANTAGE:
        models = cost_model_module.build_all(params, derived)
        demand_q = derived.Q_eq
        self_build = next(
            (
                model
                for model in models
                if model.plan == cost_model_module.PLAN_SELF_BUILD
            ),
            models[0],
        )
        self_build_cost = self_build.cost(demand_q)
        alternative = min(
            model.cost(demand_q)
            for model in models
            if model.plan != cost_model_module.PLAN_SELF_BUILD
        )
        return alternative - self_build_cost
    revenue_result = revenue_module.compute(params, derived, unit_cost_result.C_total)
    financial_result = financials_module.compute(params, derived, revenue_result)
    if target == sensitivity_module.TARGET_NPV:
        return financial_result.npv
    raise KeyError(f"未知敏感性目标：{target}")


def evaluate_npv_irr(
    params: ScenarioParams,
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """蒙特卡洛专用精简求值：只跑到 financials，不构建 KPI/成本模型/序列化载荷。

    数值路径（derive → unit_cost → revenue → financials）与 `compute_all` 完全一致，
    只是跳过了 KPI 列表、三方案模型字典、现金流逐字段字典化等即算即弃结构，
    避免 N 次抽样 × T_horizon 期 × 高精度 Decimal 的无效分配（P1-2 性能优化，零口径风险）。

    Returns:
        (npv, irr_annual)；不可行时返回 (None, None)。
    """
    derived = derive(params)
    if not is_feasible(derived):
        return None, None
    unit_cost_result = unit_cost_module.compute(params, derived)
    revenue_result = revenue_module.compute(params, derived, unit_cost_result.C_total)
    financial_result = financials_module.compute(params, derived, revenue_result)
    return financial_result.npv, financial_result.irr.irr_annual


def evaluate_kpis(params: ScenarioParams) -> Dict[str, Optional[Decimal]]:
    """情景分析 KPI 评估器：返回一组关键指标。"""
    derived = derive(params)
    if not is_feasible(derived):
        return {
            "npv": None,
            "irr": None,
            "roi": None,
            "cost_per_m": None,
            "payback_static": None,
            "gross_margin": None,
            "U_be": None,
        }
    unit_cost_result = unit_cost_module.compute(params, derived)
    revenue_result = revenue_module.compute(params, derived, unit_cost_result.C_total)
    breakeven_result = breakeven_module.compute(derived, revenue_result)
    financial_result = financials_module.compute(params, derived, revenue_result)
    return {
        "npv": financial_result.npv,
        "irr": financial_result.irr.irr_annual,
        "roi": financial_result.roi,
        "cost_per_m": unit_cost_result.cost_per_m_capacity,
        "payback_static": financial_result.payback_static,
        "gross_margin": revenue_result.G,
        "U_be": breakeven_result.U_be,
    }


def _kpi(
    key: str,
    label: str,
    value: Optional[Decimal],
    unit: str,
    formula_id: str,
    kind: str,
) -> Dict[str, Any]:
    """构造单个 KPI（含可追溯公式 id，供 UI ⓘ 抽屉使用）。"""
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "formula_id": formula_id,
        "kind": kind,
    }


def _build_kpis(
    params: ScenarioParams,
    core: CoreResult,
    crossover_result: Optional[crossover_module.CrossoverResult],
) -> List[Dict[str, Any]]:
    """构造 KPI 列表（顺序即 UI 指标卡顺序）。"""
    fin = core.financials
    n_gpu = params.hw.N_gpu
    months_per_year = D(12)
    days_per_month = D(30)
    hours_per_month = D(720)
    rev_per_gpu_day = safe_div(core.revenue.R, n_gpu * days_per_month)
    cost_per_gpu_day = safe_div(core.unit_cost.C_total, n_gpu * days_per_month)
    monthly_token = core.unit_cost.Q_out_M * MTOK
    effective_power = core.derived.P_sys * (
        params.power.P_idle_ratio + core.derived.U * (ONE - params.power.P_idle_ratio)
    )
    monthly_kwh = effective_power * params.power.PUE * hours_per_month
    token_per_kwh = safe_div(monthly_token, monthly_kwh) if monthly_kwh > ZERO else None
    recommended = None
    recommended_status = "no_solution"
    recommended_note = ""
    if crossover_result and crossover_result.recommended:
        current_q = core.derived.Q_eq
        if current_q <= ZERO:
            recommended_status = "no_demand"
            recommended_note = "当前月需求量 ≤ 0，无法给出推荐方案。"
        else:
            for segment in crossover_result.recommended:
                upper = segment.to_Q
                if current_q >= segment.from_Q and (upper is None or current_q < upper):
                    recommended = segment.best_label
                    if core.revenue.G is not None and core.revenue.G < ZERO:
                        recommended_status = "loss"
                        recommended_note = (
                            "该方案为当前成本最优，但毛利率为负（等效单价低于单位成本），"
                            "当前定价下不可行，建议重新议价或调整需求结构。"
                        )
                    else:
                        recommended_status = "viable"
                    break
    return [
        _kpi(
            "cost_per_m",
            "每百万 token 成本",
            core.unit_cost.cost_per_m_capacity,
            "元/Mtok",
            "F009",
            "cost",
        ),
        _kpi("gross_margin", "月毛利", core.revenue.G, "元/月", "F022", "money"),
        _kpi("gm_pct", "毛利率", core.revenue.GM_pct, "比率", "F022", "ratio"),
        *(
            [
                _kpi(
                    "gross_margin_benchmark",
                    "月毛利(对标市场成本)",
                    core.revenue.G_benchmark,
                    "元/月",
                    "F022",
                    "money",
                )
            ]
            if params.pricing.cost_benchmark is not None
            else []
        ),
        _kpi("npv", "NPV", fin.npv, "元", "F043", "money"),
        _kpi("irr", "IRR（年化）", fin.irr.irr_annual, "比率/年", "F046", "ratio"),
        _kpi("roi", "ROI", fin.roi, "比率", "F045", "ratio"),
        _kpi("tco", "TCO（全周期）", fin.tco, "元", "F044", "money"),
        _kpi("payback_static", "静态回本", fin.payback_static, "月", "F047", "months"),
        _kpi("payback_discounted", "折现回本", fin.payback_discounted, "月", "F047", "months"),
        _kpi("U_be", "盈亏平衡利用率", core.breakeven.U_be, "比率", "F031", "ratio"),
        _kpi("p_eq", "等效单价", core.revenue.p_eq, "元/Mtok", "F021", "cost"),
        {
            "key": "recommended_plan",
            "label": "当前需求下推荐方案",
            "value": recommended,
            "unit": "",
            "formula_id": "F054",
            "kind": "text",
            "status": recommended_status,
            "note": recommended_note,
        },
        _kpi(
            "debt_ratio",
            "资产负债率",
            core.financials.financing.debt_ratio,
            "比率",
            "F062",
            "ratio",
        ),
        _kpi(
            "interest_coverage",
            "利息覆盖倍数",
            core.financials.financing.interest_coverage,
            "倍",
            "F063",
            "number",
        ),
        _kpi(
            "roe",
            "权益回报率 ROE",
            core.financials.financing.roe,
            "比率",
            "F063",
            "ratio",
        ),
        _kpi(
            "levered_npv",
            "杠杆后 NPV",
            core.financials.financing.levered_npv,
            "元",
            "F063",
            "money",
        ),
        _kpi(
            "levered_irr",
            "杠杆后 IRR",
            core.financials.financing.levered_irr,
            "比率/年",
            "F063",
            "ratio",
        ),
        _kpi(
            "rev_per_gpu_day",
            "每卡每天收入",
            rev_per_gpu_day,
            "元/卡/天",
            "F071",
            "money",
        ),
        _kpi(
            "cost_per_gpu_day",
            "每卡每天成本(全)",
            cost_per_gpu_day,
            "元/卡/天",
            "F072",
            "money",
        ),
        _kpi(
            "token_per_kwh",
            "每度电产出 Token",
            token_per_kwh,
            "Token/度",
            "F073",
            "count",
        ),
        _kpi(
            "sla_provision_monthly",
            "SLA 赔偿计提(月)",
            core.revenue.R * params.perf.SLA_penalty_rate,
            "元/月",
            "F081",
            "money",
        ),
        _kpi(
            "sla_provision_total",
            "SLA 赔偿计提(全周期)",
            core.financials.total_revenue * params.perf.SLA_penalty_rate,
            "元",
            "F081",
            "money",
        ),
        *_deferred_revenue_kpis(params, core),
        _kpi(
            "idle_power_cost",
            "待机功耗固定成本(月)",
            core.derived.C_power_idle_m,
            "元/月",
            "F091",
            "money",
        ),
        _kpi(
            "learning_terminal_factor",
            "学习曲线期末系数",
            dpow(ONE - params.finance.cost_learning_rate, params.finance.T_horizon / MONTHS_PER_YEAR)
            if params.finance.cost_learning_rate != ZERO
            else ONE,
            "比率",
            "F092",
            "ratio",
        ),
        _kpi(
            "racks_count",
            "机柜数",
            core.derived.racks,
            "柜",
            "F093",
            "count",
        ),
        _kpi(
            "bundle_rack_cost_m",
            "包柜包电月成本",
            core.derived.bundle_rack_cost_m,
            "元/月",
            "F094",
            "money",
        ),
    ]


def _deferred_revenue_kpis(
    params: ScenarioParams, core: CoreResult
) -> List[Dict[str, Any]]:
    """P1 资源包/递延收入（合同负债）报告型 KPI：预收费→消耗→确认→合同负债余额链路。

    仅在 pkg_enabled 且消耗周期>0、预付费>0 时计算；否则返回空列表（UI 显示「—」）。
    """
    p = params.pricing
    if not p.pkg_enabled or p.pkg_consume_months <= ZERO or p.pkg_prepaid <= ZERO:
        return []
    prepaid = p.pkg_prepaid
    consume_months = p.pkg_consume_months
    recognized_monthly = prepaid / consume_months
    monthly_consumption = p.pkg_tokens / consume_months
    t = params.finance.T_horizon / consume_months
    unearned_share = ONE - t
    if unearned_share < ZERO:
        unearned_share = ZERO
    deferred_end = prepaid * unearned_share
    cash_months = safe_div(prepaid, core.revenue.R) if core.revenue.R > ZERO else None
    out = [
        _kpi("deferred_revenue", "合同负债(初始)", prepaid, "元", "F082", "money"),
        _kpi("rev_recognized_monthly", "每月确认收入", recognized_monthly, "元/月", "F082", "money"),
        _kpi("cash_prepaid", "预收现金(一次性)", prepaid, "元", "F082", "money"),
        _kpi("deferred_revenue_end", "期末合同负债", deferred_end, "元", "F082", "money"),
        _kpi("unearned_share", "未确认占比", unearned_share, "比率", "F082", "ratio"),
        _kpi("monthly_consumption", "每月消耗Token", monthly_consumption, "Mtok/月", "F082", "count"),
    ]
    if cash_months is not None:
        out.append(_kpi("prepaid_cash_months", "预付费现金跑道", cash_months, "月", "F082", "months"))
    return out


def _derived_dict(derived: DerivedParams) -> Dict[str, Any]:
    return {
        "CAPEX": derived.CAPEX,
        "P_sys": derived.P_sys,
        "Dep_m": derived.Dep_m,
        "C_fix_cash": derived.C_fix_cash,
        "C_fix_acct": derived.C_fix_acct,
        "C_var_per_U": derived.C_var_per_U,
        "C_power_idle_m": derived.C_power_idle_m,
        "bundle_rack_cost_m": derived.bundle_rack_cost_m,
        "racks": derived.racks,
        "power_mode": derived.power_mode,
        "weighted_e_price": derived.weighted_e_price,
        "Q_cap_M": derived.Q_cap_M,
        "k": derived.k,
        "k_source": derived.k_source,
        "factor": derived.factor,
        "D_out": derived.D_out,
        "D_in": derived.D_in,
        "Q_eq": derived.Q_eq,
        "U": derived.U,
        "U_implied": derived.U_implied,
        "I0": derived.I0,
        "SV": derived.SV,
        "r_m": derived.r_m,
        "dep_months": derived.dep_months,
    }


def _cashflow_dict(row: financials_module.CashflowRow) -> Dict[str, Any]:
    return {
        "period": row.period,
        "period_type": row.period_type,
        "revenue": row.revenue,
        "opex_cash": row.opex_cash,
        "depreciation": row.depreciation,
        "ebt": row.ebt,
        "interest": row.interest,
        "principal": row.principal,
        "tax": row.tax,
        "net_cf": row.net_cf,
        "cum_cf": row.cum_cf,
        "discount_factor": row.discount_factor,
        "discount_ratio": row.discount_ratio,
        "discounted_cf": row.discounted_cf,
        "cum_discounted_cf": row.cum_discounted_cf,
    }


def _financials_dict(fin: financials_module.FinancialResult) -> Dict[str, Any]:
    fin_struct = fin.financing
    return {
        "I0": fin.I0,
        "SV": fin.SV,
        "r_m": fin.r_m,
        "npv": fin.npv,
        "roi": fin.roi,
        "tco": fin.tco,
        "total_revenue": fin.total_revenue,
        "total_opex_cash": fin.total_opex_cash,
        "total_tax": fin.total_tax,
        "total_net_cf": fin.total_net_cf,
        "sla_provision_total": fin.sla_provision_total,
        "payback_static": fin.payback_static,
        "payback_discounted": fin.payback_discounted,
        "irr": {
            "solution": fin.irr.solution,
            "irr_monthly": fin.irr.irr_monthly,
            "irr_annual": fin.irr.irr_annual,
            "roots_monthly": fin.irr.roots_monthly,
            "mirr_monthly": fin.irr.mirr_monthly,
            "mirr_annual": fin.irr.mirr_annual,
            "method": fin.irr.method,
            "note": fin.irr.note,
            "iterations": fin.irr.iterations,
        },
        "financing": {
            "debt_ratio": fin_struct.debt_ratio,
            "debt": fin_struct.debt,
            "equity": fin_struct.equity,
            "interest_total": fin_struct.interest_total,
            "principal_total": fin_struct.principal_total,
            "interest_coverage": fin_struct.interest_coverage,
            "roe": fin_struct.roe,
            "levered_npv": fin_struct.levered_npv,
            "levered_irr": fin_struct.levered_irr,
        },
        "cashflows": [_cashflow_dict(row) for row in fin.cashflows],
        "cashflows_yearly": [_cashflow_dict(row) for row in fin.cashflows_yearly],
        "notes": fin.notes,
    }


def _crossover_dict(result: crossover_module.CrossoverResult) -> Dict[str, Any]:
    return {
        "curves": [
            {
                "plan": curve.plan,
                "label": curve.label,
                "a": curve.a,
                "b": curve.b,
                "points": curve.points,
            }
            for curve in result.curves
        ],
        "crossovers": [
            {
                "plans": item.plans,
                "Q": item.Q,
                "active": item.active,
                "status": item.status,
                "note": item.note,
            }
            for item in result.crossovers
        ],
        "recommended": [
            {
                "from_Q": segment.from_Q,
                "to_Q": segment.to_Q,
                "best_plan": segment.best_plan,
                "best_label": segment.best_label,
            }
            for segment in result.recommended
        ],
        "q_max": result.q_max,
        "capacity_wall": result.capacity_wall,
        "notes": result.notes,
    }


def _sensitivity_dict(result: sensitivity_module.SensitivityResult) -> Dict[str, Any]:
    return {
        "target": result.target,
        "target_label": result.target_label,
        "delta": result.delta,
        "base": result.base,
        "items": [
            {
                "param": item.param,
                "label": item.label,
                "base": item.base,
                "low": item.low,
                "high": item.high,
                "delta_low": item.delta_low,
                "delta_high": item.delta_high,
                "swing": item.swing,
                "swing_pct": item.swing_pct,
                "low_feasible": item.low_feasible,
                "high_feasible": item.high_feasible,
                "note": item.note,
            }
            for item in result.items
        ],
        "notes": result.notes,
    }


def _scenarios_dict(result: scenario_module.ScenarioSetResult) -> Dict[str, Any]:
    return {
        "cases": [
            {
                "key": case.key,
                "label": case.label,
                "multipliers": case.multipliers,
                "kpis": case.kpis,
                "feasible": case.feasible,
                "note": case.note,
            }
            for case in result.cases
        ],
        "notes": result.notes,
    }


def _joint_dict(result: sensitivity_module.JointSensitivityResult) -> Dict[str, Any]:
    return {
        "npv_min": result.npv_min,
        "npv_max": result.npv_max,
        "percentiles": result.percentiles,
        "main_effects": result.main_effects,
        "interactions": result.interactions,
        "notes": result.notes,
    }


def _custom_scenarios_dict(result: scenario_module.CustomScenarioSet) -> Dict[str, Any]:
    return {
        "cases": [
            {
                "key": case.key,
                "label": case.label,
                "overrides": case.overrides,
                "kpis": case.kpis,
                "feasible": case.feasible,
                "note": case.note,
            }
            for case in result.cases
        ],
        "notes": result.notes,
    }


def _hybrid_weights_valid(weights: Sequence[Decimal]) -> bool:
    """混合权重合法性校验：权重非负且和≈1（容差 1e-9）。

    与前端 `calc-engine/costModel.ts` `normalizeWeights` 语义对齐：仅在「和≈1 且非负」
    时后端才将其视为有效混合方案；否则回退三方案，不影响历史/3 方案结果一致性。
    """
    total = ZERO
    for w in weights:
        if w is None or w < ZERO:
            return False
        total += w
    return abs(total - ONE) <= D("1e-9")


def compute_all(
    params: ScenarioParams, options: Optional[EngineOptions] = None
) -> Dict[str, Any]:
    """完整计算，返回与前端结构一致的结果载荷（内含 Decimal，未量化）。"""
    opts = options or EngineOptions()
    core = compute_core(params)

    hybrid_model: Optional[cost_model_module.CostModel] = None
    hybrid_notes: List[str] = []
    if params.hybrid.enabled:
        weights = (params.hybrid.w_A, params.hybrid.w_B, params.hybrid.w_C)
        if _hybrid_weights_valid(weights):
            hybrid_model = cost_model_module.build_hybrid(weights, core.cost_models)
        else:
            hybrid_notes.append(
                "混合部署已启用，但权重不合法（需非负且和≈1），已回退为 A/B/C 三方案。"
            )

    crossover_result: Optional[crossover_module.CrossoverResult] = None
    if opts.include_crossover:
        if hybrid_model is not None:
            crossover_result = crossover_module.compute_hybrid(
                core.cost_models,
                hybrid_model,
                demand_q=core.derived.Q_eq,
                capacity_wall=core.derived.Q_cap_M,
            )
        else:
            crossover_result = crossover_module.compute(
                core.cost_models,
                demand_q=core.derived.Q_eq,
                capacity_wall=core.derived.Q_cap_M,
            )

    output_models = (
        core.cost_models + [hybrid_model] if hybrid_model is not None else core.cost_models
    )

    sensitivity_result: Optional[sensitivity_module.SensitivityResult] = None
    if opts.include_sensitivity:
        sensitivity_result = sensitivity_module.compute(
            params,
            evaluator=evaluate_target,
            target=opts.sensitivity_target,
            delta=opts.sensitivity_delta,
        )

    scenarios_result: Optional[scenario_module.ScenarioSetResult] = None
    if opts.include_scenarios:
        scenarios_result = scenario_module.compute(params, evaluator=evaluate_kpis)

    joint_result: Optional[sensitivity_module.JointSensitivityResult] = None
    if opts.include_joint:
        from ai_roi.domain.calc.sensitivity import var_registry

        registry = var_registry()
        joint_vars = [registry[k] for k in (opts.joint_vars or ["U", "E_price"]) if k in registry]
        if not joint_vars:
            joint_vars = sensitivity_module.JOINT_DEFAULT_VARS[:2]
        joint_result = sensitivity_module.compute_joint(
            params,
            evaluator=evaluate_target,
            target=opts.joint_target,
            delta=opts.joint_delta,
            variables=joint_vars,
        )

    custom_scenarios_result: Optional[scenario_module.CustomScenarioSet] = None
    if opts.include_custom_scenarios and opts.custom_scenario_specs:
        custom_scenarios_result = scenario_module.compute_custom(
            params,
            specs=opts.custom_scenario_specs,
            evaluator=evaluate_kpis,
        )

    demand_q = core.derived.Q_eq
    return {
        "engine_version": ENGINE_VERSION,
        "formula_spec_version": FORMULA_SPEC_VERSION,
        "authoritative": True,
        "conventions": params.conventions.to_dict(),
        "params": params_to_dict(params),
        "derived": _derived_dict(core.derived),
        "throughput": {
            "T_eff": core.throughput.T_eff,
            "Q_cap_M": core.throughput.Q_cap_M,
            "Q_out_M": core.throughput.Q_out_M,
            "k": core.throughput.k,
            "k_source": core.throughput.k_source,
            "k_source_label": core.throughput.k_source_label,
            "capacity_headroom": core.throughput.capacity_headroom,
            "over_capacity": core.throughput.over_capacity,
        },
        "unit_cost": {
            "C_fix_acct": core.unit_cost.C_fix_acct,
            "C_fix_cash": core.unit_cost.C_fix_cash,
            "C_var": core.unit_cost.C_var,
            "C_total": core.unit_cost.C_total,
            "C_total_cash": core.unit_cost.C_total_cash,
            "Q_out_M": core.unit_cost.Q_out_M,
            "cost_per_m_capacity": core.unit_cost.cost_per_m_capacity,
            "cost_per_m_demand": core.unit_cost.cost_per_m_demand,
            "c_unit": core.unit_cost.c_unit,
            "breakdown": [
                {
                    "key": item.key,
                    "label": item.label,
                    "amount": item.amount,
                    "share": item.share,
                }
                for item in core.unit_cost.breakdown
            ],
        },
        "revenue": {
            "R": core.revenue.R,
            "revenue_in": core.revenue.revenue_in,
            "revenue_out": core.revenue.revenue_out,
            "p_eq": core.revenue.p_eq,
            "p_in_blended": core.revenue.p_in_blended,
            "G": core.revenue.G,
            "GM_pct": core.revenue.GM_pct,
            "g_per_m": core.revenue.g_per_m,
            "g_per_token": core.revenue.g_per_token,
            "cost_benchmark_total": core.revenue.cost_benchmark_total,
            "G_benchmark": core.revenue.G_benchmark,
            "GM_pct_benchmark": core.revenue.GM_pct_benchmark,
            "loss_vs_benchmark": core.revenue.loss_vs_benchmark,
        },
        "breakeven": {
            "feasible": core.breakeven.feasible,
            "M_U": core.breakeven.M_U,
            "U_be": core.breakeven.U_be,
            "Q_be": core.breakeven.Q_be,
            "p_be": core.breakeven.p_be,
            "note": core.breakeven.note,
            "curve": [
                {"U": point.U, "revenue": point.revenue, "cost": point.cost}
                for point in core.breakeven.curve
            ],
        },
        "cost_models": [
            {
                "plan": model.plan,
                "label": model.name(),
                "a": model.a,
                "b": model.b,
                "cost_at_demand": model.cost(demand_q),
                "unit_cost_at_demand": safe_div(model.cost(demand_q), demand_q),
            }
            for model in output_models
        ],
        "crossover": _crossover_dict(crossover_result) if crossover_result else None,
        "financials": _financials_dict(core.financials),
        "sensitivity": _sensitivity_dict(sensitivity_result) if sensitivity_result else None,
        "scenarios": _scenarios_dict(scenarios_result) if scenarios_result else None,
        "joint": _joint_dict(joint_result) if joint_result else None,
        "custom_scenarios": (
            _custom_scenarios_dict(custom_scenarios_result) if custom_scenarios_result else None
        ),
        "kpis": _build_kpis(params, core, crossover_result),
        "warnings": core.warnings + hybrid_notes,
        "disclaimer": (
            "本平台测算结果完全基于用户输入假设与行业基准，不构成任何投资承诺或建议；"
            "实际决策须结合尽调与专业意见。"
        ),
    }


def flat_kpi_map(payload: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    """从结果载荷抽取 `key → value` 的扁平 KPI 映射（写库物化列用）。"""
    result: Dict[str, Optional[Decimal]] = {}
    for item in payload.get("kpis", []):
        value = item.get("value")
        result[str(item["key"])] = value if isinstance(value, Decimal) else None
    return result


def unit_cost_per_token(payload: Dict[str, Any]) -> Decimal:
    """便捷方法：每 token 成本（元/token）。"""
    cost_per_m = payload["unit_cost"]["cost_per_m_capacity"]
    return D(cost_per_m) / MTOK
