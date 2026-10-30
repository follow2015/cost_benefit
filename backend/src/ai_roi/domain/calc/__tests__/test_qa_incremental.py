"""QA 独立验证（P3 增量能力）——严过关（Yan）。

与工程师 `test_incremental.py` 互补，侧重「手工公式核对」与「黄金向量新路径存在性」：
- ① 融资：24 期手工核算 interest/principal/税盾；杠杆 NPV ≠ 全权益 NPV 且退化相等；无息时 interest_coverage=None。
- ② 分时电价：1.5×/0.7× + 20%/30% 手算加权价；未启用退化且 E_price 敏感性保持。
- ④ 需求增长：g=0.5 时第 13 月 D_t=D×1.5、收入/变动成本缩放；g=0 退化。
- ③ 联合敏感性：2 变量 4 网格手工重算主效应/交互/分位；自定义情景 K=3 字段齐全。
- ⑤ 黄金向量：GV09–GV15 新断言路径 + formula_spec F061–F066 + 版本号存在性。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all, evaluate_target
from ai_roi.domain.calc.parameters import ScenarioParams, default_params
from ai_roi.domain.calc.scenario import CustomScenarioSpec

_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "goldenVectors.json"


def _rel(actual: Decimal, expected: Decimal) -> Decimal:
    diff = abs(actual - expected)
    return diff if expected == 0 else diff / abs(expected)


def test_qa_finance_24m_manual_interest_principal() -> None:
    """debt_ratio=0.5, debt_rate=0.05, loan_term=24：手工核算首月利息/本金与直线摊销。"""
    params = (
        default_params()
        .with_override("finance.T_horizon", D(36))
        .with_override("finance.debt_ratio", D("0.5"))
        .with_override("finance.debt_rate", D("0.05"))
        .with_override("finance.loan_term_months", D(24))
    )
    payload = compute_all(params)
    fin = payload["financials"]
    fin_struct = fin["financing"]
    i0 = payload["derived"]["I0"]

    assert fin_struct["debt"] == i0 * D("0.5")
    assert fin_struct["equity"] == i0 * D("0.5")

    rows = fin["cashflows"]
    expected_interest = i0 * D("0.5") * D("0.05") / D(12)
    assert _rel(rows[0]["interest"], expected_interest) <= Decimal("1e-15")
    expected_principal = i0 * D("0.5") / D(24)
    assert _rel(rows[0]["principal"], expected_principal) <= Decimal("1e-15")
    for t in range(1, 24):
        assert _rel(rows[t - 1]["principal"], expected_principal) <= Decimal("1e-15")
    assert rows[23]["principal"] > ZERO
    assert rows[24]["interest"] == 0 and rows[24]["principal"] == 0
    assert _rel(fin_struct["principal_total"], fin_struct["debt"]) <= Decimal("1e-12")
    assert fin_struct["interest_total"] == sum((r["interest"] for r in rows), ZERO)


def test_qa_finance_taxed_tax_shield_formula() -> None:
    """taxed=True 时：EBT 含利息扣除；tax=max(0,EBT)×Tax；利息税盾=interest×Tax（EBT>0）。"""
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

    rows_debt = with_debt["financials"]["cashflows"]
    rows_nodebt = no_debt["financials"]["cashflows"]
    assert rows_debt[0]["interest"] > ZERO
    tax_rate = base_taxed.finance.Tax
    for row in rows_debt:
        expected_ebt = (
            row["revenue"] - row["opex_cash"] - row["depreciation"] - row["interest"]
        )
        assert _rel(row["ebt"], expected_ebt) <= Decimal("1e-12")
        expected_tax = (expected_ebt if expected_ebt > ZERO else ZERO) * tax_rate
        assert _rel(row["tax"], expected_tax) <= Decimal("1e-12")
    assert with_debt["financials"]["total_tax"] < no_debt["financials"]["total_tax"]
    for a, b in zip(rows_debt, rows_nodebt):
        if a["interest"] > ZERO and a["ebt"] > ZERO:
            tax_shield = a["interest"] * tax_rate
            assert _rel(b["tax"] - a["tax"], tax_shield) <= Decimal("1e-9")


def test_qa_finance_levered_npv_differs_and_degenerate() -> None:
    """杠杆 NPV ≠ 全权益 NPV（debt_ratio>0）；debt_ratio=0 时逐位退化相等。"""
    base = default_params()
    unlevered = compute_all(base)
    levered = compute_all(base.with_override("finance.debt_ratio", D("0.5")))
    assert levered["financials"]["npv"] != unlevered["financials"]["npv"]
    assert levered["financials"]["financing"]["levered_npv"] == levered["financials"]["npv"]
    assert unlevered["financials"]["financing"]["levered_npv"] == unlevered["financials"]["npv"]
    assert levered["financials"]["financing"]["levered_irr"] != unlevered["financials"]["irr"]["irr_annual"]
    assert unlevered["financials"]["financing"]["levered_irr"] == unlevered["financials"]["irr"]["irr_annual"]


def test_qa_finance_interest_coverage_null_when_no_debt() -> None:
    """debt_ratio=0 ⇒ 无息月份不参与，interest_coverage=None（∞ 语义）；KPI 仍输出 null。"""
    payload = compute_all(default_params())
    assert payload["financials"]["financing"]["interest_coverage"] is None
    assert payload["kpis"][13]["key"] == "interest_coverage"
    assert payload["kpis"][13]["value"] is None


def test_qa_tou_weighted_manual_15x_07x() -> None:
    """峰价 1.5×、谷价 0.7×、峰 20%/谷 30%：手工核对加权价与成本链跟随。"""
    base = default_params()
    e_price = base.power.E_price
    params = (
        base.with_override("power.e_price_peak", D("1.5") * e_price)
        .with_override("power.e_price_flat", e_price)
        .with_override("power.e_price_valley", D("0.7") * e_price)
        .with_override("power.tou_peak_share", D("0.2"))
        .with_override("power.tou_valley_share", D("0.3"))
    )
    payload = compute_all(params)
    derived = payload["derived"]
    weighted_manual = (
        D("0.56") * D("0.3") + D("0.8") * D("0.5") + D("1.2") * D("0.2")
    )
    assert _rel(derived["weighted_e_price"], weighted_manual) <= Decimal("1e-15")
    expected_cvar = derived["P_sys"] * base.power.PUE * weighted_manual * D(720)
    assert _rel(derived["C_var_per_U"], expected_cvar) <= Decimal("1e-12")
    assert _rel(
        payload["cost_models"][0]["b"],
        derived["C_var_per_U"] / derived["Q_cap_M"],
    ) <= Decimal("1e-12")
    base_payload = compute_all(base)
    assert payload["breakeven"]["M_U"] != base_payload["breakeven"]["M_U"]


def test_qa_tou_degenerate_and_e_price_sensitivity() -> None:
    """未启用 TOU：weighted=E_price，且 E_price 单独变化时 weighted 跟随（E_price 敏感性保持）。"""
    payload = compute_all(default_params())
    assert payload["derived"]["weighted_e_price"] == default_params().power.E_price
    changed = default_params().with_override("power.E_price", D("1.5"))
    changed_payload = compute_all(changed)
    assert changed_payload["derived"]["weighted_e_price"] == D("1.5")
    assert changed_payload["derived"]["C_var_per_U"] != payload["derived"]["C_var_per_U"]


def test_qa_demand_growth_t13_factor_15() -> None:
    """g_demand=0.5：第 13 月 D_t = D×1.5、第 25 月 D_t = D×2.25；收入/变动成本缩放；g=0 退化。"""
    base = default_params()
    params = base.with_override("demand.g_demand", D("0.5"))
    payload = compute_all(params)
    rows = payload["financials"]["cashflows"]

    rev_r = payload["revenue"]["R"]
    assert _rel(rows[0]["revenue"], rev_r) <= Decimal("1e-12")
    assert _rel(rows[12]["revenue"], rev_r * D("1.5")) <= Decimal("1e-12")
    assert _rel(rows[24]["revenue"], rev_r * D("2.25")) <= Decimal("1e-12")
    c_var_per_u = payload["derived"]["C_var_per_U"]
    u = payload["derived"]["U"]
    c_fix_cash = payload["derived"]["C_fix_cash"]
    assert _rel(
        rows[12]["opex_cash"], c_fix_cash + c_var_per_u * u * D("1.5")
    ) <= Decimal("1e-12")

    base_payload = compute_all(base)
    degenerate_payload = compute_all(base.with_override("demand.g_demand", ZERO))
    degenerate_rows = degenerate_payload["financials"]["cashflows"]
    base_rows = base_payload["financials"]["cashflows"]
    for a, b in zip(degenerate_rows, base_rows):
        assert a["revenue"] == b["revenue"]
        assert a["opex_cash"] == b["opex_cash"]
        assert a["net_cf"] == b["net_cf"]


def test_qa_joint_manual_4point() -> None:
    """U + E_price ±20%：4 网格手工重算 min/max/p50、主效应、二阶交互。"""
    base = default_params()
    opts = EngineOptions(
        include_joint=True,
        joint_vars=["U", "E_price"],
        joint_delta=D("0.2"),
    )
    payload = compute_all(base, opts)
    joint = payload["joint"]
    assert joint is not None

    def scaled(params: ScenarioParams, u_high: bool, e_high: bool) -> ScenarioParams:
        p = params.scale("demand.U", D("1.2") if u_high else D("0.8"))
        p = p.scale("demand.D_eq", D("1.2") if u_high else D("0.8"))
        p = p.scale("power.E_price", D("1.2") if e_high else D("0.8"))
        return p

    npv_ll = evaluate_target(scaled(base, False, False), "npv")
    npv_hl = evaluate_target(scaled(base, True, False), "npv")
    npv_lh = evaluate_target(scaled(base, False, True), "npv")
    npv_hh = evaluate_target(scaled(base, True, True), "npv")
    assert None not in (npv_ll, npv_hl, npv_lh, npv_hh)
    vals = sorted([npv_ll, npv_hl, npv_lh, npv_hh])  # type: ignore[list-item]
    assert joint["npv_min"] == vals[0]
    assert joint["npv_max"] == vals[-1]
    expected_p50 = vals[1] + (vals[2] - vals[1]) * D("0.5")
    assert _rel(joint["percentiles"]["p50"], expected_p50) <= Decimal("1e-12")
    s_u_manual = abs(((npv_hl + npv_hh) / 2) - ((npv_ll + npv_lh) / 2))
    assert _rel(joint["main_effects"]["U"], s_u_manual) <= Decimal("1e-12")
    s_e_manual = abs(((npv_lh + npv_hh) / 2) - ((npv_ll + npv_hl) / 2))
    assert _rel(joint["main_effects"]["E_price"], s_e_manual) <= Decimal("1e-12")
    i_manual = npv_hh - npv_hl - npv_lh + npv_ll
    assert _rel(joint["interactions"]["UE_price"], i_manual) <= Decimal("1e-12")


def test_qa_custom_scenarios_3cases_fields() -> None:
    """任意 K=3 组覆盖 → cases 并列，KPI 字段齐全（7 字段），overrides 回显。"""
    specs = [
        CustomScenarioSpec(
            key="low_demand",
            label="低需求",
            overrides={"demand.U": D("0.4"), "demand.D_eq": D("2000")},
        ),
        CustomScenarioSpec(
            key="high_price",
            label="高售价",
            overrides={"pricing.p_out": D(40), "pricing.p_in": D(10)},
        ),
        CustomScenarioSpec(
            key="full_debt",
            label="高杠杆",
            overrides={"finance.debt_ratio": D("0.8"), "finance.debt_rate": D("0.08")},
        ),
    ]
    opts = EngineOptions(include_custom_scenarios=True, custom_scenario_specs=specs)
    payload = compute_all(default_params(), opts)
    custom = payload["custom_scenarios"]
    assert custom is not None
    assert len(custom["cases"]) == 3
    kpi_fields = {
        "npv", "irr", "roi", "cost_per_m", "payback_static", "gross_margin", "U_be"
    }
    for case in custom["cases"]:
        assert set(case["kpis"].keys()) == kpi_fields
        assert case["kpis"]["npv"] is not None
        assert case["feasible"] is True
        assert case["overrides"]
    base_payload = compute_all(default_params())
    full_debt_npv = custom["cases"][2]["kpis"]["npv"]
    assert full_debt_npv != base_payload["financials"]["npv"]


def test_qa_golden_gv09_15_new_paths() -> None:
    """GV09–GV15 断言覆盖新公式 ID/新 KPI 路径；formula_spec F061–F066 与版本号存在。"""
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    new_ids = {f"GV{i:02d}" for i in range(9, 16)}
    new_case_expects = {c["id"]: c["expect"] for c in doc["cases"] if c["id"] in new_ids}
    assert len(new_case_expects) == 7

    required_paths = [
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
    for cid, expect in new_case_expects.items():
        for path in required_paths:
            assert path in expect, f"{cid} 缺少断言路径 {path}"
    gv14 = new_case_expects["GV14"]
    assert gv14["joint.npv_min"] is not None
    assert gv14["joint.main_effects.U"] is not None
    gv15 = new_case_expects["GV15"]
    assert gv15["custom_scenarios.cases[0].kpis.npv"] is not None
    assert gv15["custom_scenarios.cases[2].kpis.npv"] is not None
    for cid in (f"GV{i:02d}" for i in range(1, 9)):
        expect = next(c["expect"] for c in doc["cases"] if c["id"] == cid)
        assert expect["derived.weighted_e_price"] is not None
        assert expect["financials.financing.debt_ratio"] == "0"
        assert expect["financials.cashflows[0].interest"] == "0"
        assert expect["joint.npv_min"] is None
        assert expect["custom_scenarios.cases[0].kpis.npv"] is None


def test_qa_formula_spec_f061_066_and_versions() -> None:
    """formula_spec 追加 F061–F066（不改旧 ID）；context 版本 bump 为 0.2.0 / 1.2.0。"""
    from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION
    from ai_roi.domain.calc.formula_spec import FORMULA_INDEX, spec_as_dict

    assert ENGINE_VERSION == "calc-py-0.2.0"
    assert FORMULA_SPEC_VERSION == "1.2.0"
    for fid in ("F061", "F062", "F063", "F064", "F065", "F066"):
        assert fid in FORMULA_INDEX
    for fid in ("F100", "F101"):
        assert fid in FORMULA_INDEX
    for fid in ("F001", "F043", "F054", "F060"):
        assert fid in FORMULA_INDEX
    spec = spec_as_dict()
    assert len(spec["formulas"]) == len(FORMULA_INDEX)
    groups = {f["id"]: f["group"] for f in spec["formulas"]}
    assert groups["F061"] == "cost_chain"
    assert groups["F062"] == "finance"
    assert groups["F063"] == "finance"
    assert groups["F064"] == "revenue"
    assert groups["F065"] == "compare"
    assert groups["F066"] == "compare"
