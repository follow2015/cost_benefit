"""增量能力单测（P3）：① 融资结构 ② 分时电价 TOU ③ 多因素联合敏感性 + 自定义情景 ④ 需求增长。
验证「开启态」正确性与「默认退化态」与现状逐位一致。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all, compute_core
from ai_roi.domain.calc.parameters import ScenarioParams, default_params
from ai_roi.domain.calc.scenario import CustomScenarioSpec
from ai_roi.domain.calc.sensitivity import JOINT_DEFAULT_VARS


def _rel(actual: Decimal, expected: Decimal) -> Decimal:
    diff = abs(actual - expected)
    return diff if expected == 0 else diff / abs(expected)


def test_finance_degenerate_equals_baseline() -> None:
    """debt_ratio=0 ⇒ 无融资，现金流/权益 CF/NPV/IRR 与现状逐位一致。"""
    base = default_params()
    payload_base = compute_all(base)
    financing = payload_base["financials"]["financing"]
    assert financing["debt_ratio"] == 0
    assert financing["debt"] == 0
    assert financing["equity"] == payload_base["derived"]["I0"]
    assert financing["interest_total"] == 0
    assert financing["principal_total"] == 0
    assert financing["levered_npv"] == payload_base["financials"]["npv"]
    assert financing["levered_irr"] == payload_base["financials"]["irr"]["irr_annual"]
    rows = payload_base["financials"]["cashflows"]
    assert all(row["interest"] == 0 and row["principal"] == 0 for row in rows)


def test_finance_levered_cashflows_and_kpis() -> None:
    """debt_ratio=0.5 ⇒ 债务/权益拆分、月利息/本金递推、杠杆 KPI。"""
    params = (
        default_params()
        .with_override("finance.T_horizon", D(60))
        .with_override("finance.debt_ratio", D("0.5"))
        .with_override("finance.debt_rate", D("0.05"))
        .with_override("finance.loan_term_months", D(48))
    )
    payload = compute_all(params)
    fin = payload["financials"]
    financing = fin["financing"]
    i0 = payload["derived"]["I0"]
    assert financing["debt_ratio"] == D("0.5")
    assert financing["debt"] == i0 * D("0.5")
    assert financing["equity"] == i0 * D("0.5")

    rows = fin["cashflows"]
    expected_first_interest = financing["debt"] * D("0.05") / D(12)
    assert _rel(rows[0]["interest"], expected_first_interest) <= Decimal("1e-12")
    expected_first_principal = financing["debt"] / D(48)
    assert _rel(rows[0]["principal"], expected_first_principal) <= Decimal("1e-12")
    assert rows[47]["principal"] > ZERO
    assert rows[48]["interest"] == 0 and rows[48]["principal"] == 0
    assert financing["interest_total"] == sum((r["interest"] for r in rows), ZERO)
    assert _rel(financing["principal_total"], financing["debt"]) <= Decimal("1e-12")
    assert financing["levered_npv"] == fin["npv"]
    assert payload["kpis"][12]["key"] == "debt_ratio"
    assert payload["kpis"][12]["value"] == D("0.5")
    assert payload["kpis"][13]["key"] == "interest_coverage"
    assert payload["kpis"][14]["key"] == "roe"


def test_finance_tax_shield_lowers_tax() -> None:
    """taxed=True 时利息税盾使 total_tax 低于无息同口径情形。"""
    base_taxed = ScenarioParams(
        hw=default_params().hw,
        power=default_params().power,
        perf=default_params().perf,
        demand=default_params().demand,
        pricing=default_params().pricing,
        finance=default_params().finance,
        bench=default_params().bench,
        conventions=default_params().conventions.with_taxed(True),
    )
    no_debt = compute_all(base_taxed)
    with_debt = compute_all(base_taxed.with_override("finance.debt_ratio", D("0.4")))
    assert with_debt["financials"]["total_tax"] < no_debt["financials"]["total_tax"]
    assert with_debt["financials"]["financing"]["interest_coverage"] is not None


def test_tou_degenerate_equals_baseline() -> None:
    """各档 = E_price、峰谷占比 = 0 ⇒ weighted = E_price，C_var_per_U/b_A 与现状一致。"""
    base = compute_all(default_params())
    params = (
        default_params()
        .with_override("power.e_price_peak", D("0.8"))
        .with_override("power.e_price_flat", D("0.8"))
        .with_override("power.e_price_valley", D("0.8"))
        .with_override("power.tou_peak_share", ZERO)
        .with_override("power.tou_valley_share", ZERO)
    )
    payload = compute_all(params)
    assert payload["derived"]["weighted_e_price"] == D("0.8")
    assert payload["derived"]["C_var_per_U"] == base["derived"]["C_var_per_U"]
    assert payload["cost_models"][0]["b"] == base["cost_models"][0]["b"]


def test_tou_weighted_price_drives_cost_chain() -> None:
    """异价 + 占比 ⇒ 加权价正确，并驱动 C_var_per_U、b_A、单位成本与盈亏平衡分母。"""
    params = (
        default_params()
        .with_override("power.e_price_peak", D("1.2"))
        .with_override("power.e_price_flat", D("0.8"))
        .with_override("power.e_price_valley", D("0.4"))
        .with_override("power.tou_peak_share", D("0.3"))
        .with_override("power.tou_valley_share", D("0.2"))
    )
    payload = compute_all(params)
    weighted = D("0.4") * D("0.2") + D("0.8") * D("0.5") + D("1.2") * D("0.3")
    assert payload["derived"]["weighted_e_price"] == weighted
    expected_cvar = (
        payload["derived"]["P_sys"] * default_params().power.PUE * weighted * D(720)
    )
    assert _rel(payload["derived"]["C_var_per_U"], expected_cvar) <= Decimal("1e-12")
    assert _rel(
        payload["cost_models"][0]["b"],
        payload["derived"]["C_var_per_U"] / payload["derived"]["Q_cap_M"],
    ) <= Decimal("1e-12")
    base = compute_all(default_params())
    assert payload["unit_cost"]["cost_per_m_capacity"] != base["unit_cost"]["cost_per_m_capacity"]


def test_joint_sensitivity_grid_and_decomposition() -> None:
    """U + E_price 两变量 ±20%：2² 网格 → min/max/P50 + 主效应 + 二阶交互。"""
    opts = EngineOptions(
        include_joint=True,
        joint_vars=["U", "E_price"],
        joint_delta=D("0.2"),
    )
    payload = compute_all(default_params(), opts)
    joint = payload["joint"]
    assert joint is not None
    assert joint["npv_min"] <= joint["npv_max"]
    assert joint["percentiles"]["p50"] is not None
    assert joint["main_effects"]["U"] > ZERO
    assert joint["main_effects"]["E_price"] > ZERO
    assert "UE_price" in joint["interactions"]


def test_custom_scenarios_k_any() -> None:
    """任意 K=3 组参数覆盖 → 并列 KPI，feasible 正确。"""
    specs = [
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
    opts = EngineOptions(include_custom_scenarios=True, custom_scenario_specs=specs)
    payload = compute_all(default_params(), opts)
    custom = payload["custom_scenarios"]
    assert custom is not None
    assert len(custom["cases"]) == 3
    keys = [case["key"] for case in custom["cases"]]
    assert keys == ["conservative_price", "high_elec", "high_leverage"]
    assert all(case["feasible"] for case in custom["cases"])
    assert all(case["kpis"]["npv"] is not None for case in custom["cases"])
    default_payload = compute_all(default_params())
    assert default_payload["joint"] is None
    assert default_payload["custom_scenarios"] is None


def test_demand_growth_degenerate_equals_baseline() -> None:
    """g_demand=0 ⇒ 收入/成本/现金流与现状一致。"""
    base = compute_all(default_params())
    params = default_params().with_override("demand.g_demand", ZERO)
    payload = compute_all(params)
    base_rows = base["financials"]["cashflows"]
    rows = payload["financials"]["cashflows"]
    assert len(rows) == len(base_rows)
    for a, b in zip(rows, base_rows):
        assert a["revenue"] == b["revenue"]
        assert a["opex_cash"] == b["opex_cash"]
        assert a["net_cf"] == b["net_cf"]
    assert payload["financials"]["npv"] == base["financials"]["npv"]


def test_demand_growth_ramps_revenue_and_npv() -> None:
    """g_demand=0.10 ⇒ 后期收入/变动成本随 D_t 上升；NPV 高于 g=0 基准。"""
    base = compute_all(default_params())
    params = default_params().with_override("demand.g_demand", D("0.10"))
    payload = compute_all(params)
    rows = payload["financials"]["cashflows"]
    assert rows[12]["revenue"] > rows[0]["revenue"]
    assert rows[23]["revenue"] > rows[11]["revenue"]
    base_rows = base["financials"]["cashflows"]
    assert rows[12]["opex_cash"] > base_rows[12]["opex_cash"]
    assert payload["financials"]["npv"] > base["financials"]["npv"]
    assert payload["kpis"][11]["key"] == "recommended_plan"
