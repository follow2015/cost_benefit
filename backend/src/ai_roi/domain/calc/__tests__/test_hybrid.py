"""P2-3 混合部署第四方案单测。

验证：
1. 线性化性质：C_hybrid(Q) = w_A·C_A(Q) + w_B·C_B(Q) + w_C·C_C(Q)；
2. 权重归一化（和=1，全 0 退化为三等分）；
3. compute_hybrid 叠加 H 后得到四方案下包络（4 条曲线）。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.cost_model import (
    ApiCost,
    HybridCost,
    RentCost,
    SelfBuildCost,
    build_hybrid,
    normalize_weights,
)
from ai_roi.domain.calc.crossover import compute_hybrid
from ai_roi.domain.calc.decimal_config import D, ONE, ZERO, safe_div
from ai_roi.domain.calc.parameters import default_params


def _three_models() -> list:
    a = SelfBuildCost(C_fix_acct=D(1000), C_var_per_U=D(200), Q_cap_M=D(1000))
    b = RentCost(fixed=D(300), Rent_gpu=D(10), N_gpu=D(8), Q_cap_M=D(1000))
    c = ApiCost(API_in=D(5), API_out=D(20), API_cache=D(1), rho=D(1) / 3, h=D("0.2"), factor=D(1))
    return [a, b, c]


def test_linearization_property() -> None:
    """加权线性组合仍满足 C_hybrid(Q) = Σ w_i·C_i(Q)。"""
    models = _three_models()
    weights = (D("0.5"), D("0.3"), D("0.2"))
    hybrid = build_hybrid(weights, models)

    for q in (D(0), D(10), D(500), D(1000)):
        expected = (
            weights[0] * models[0].cost(q)
            + weights[1] * models[1].cost(q)
            + weights[2] * models[2].cost(q)
        )
        assert abs(hybrid.cost(q) - expected) <= Decimal("1e-9")


def test_normalize_weights() -> None:
    assert normalize_weights(D(1), D(1), D(1)) == (ONE / 3, ONE / 3, ONE / 3)
    w = normalize_weights(D(2), D(0), D(2))
    assert abs(sum(w) - ONE) <= Decimal("1e-12")
    z = normalize_weights(ZERO, ZERO, ZERO)
    assert z == (ONE / 3, ONE / 3, ONE / 3)


def test_hybrid_is_cost_model() -> None:
    """HybridCost 复用 CostModel 抽象（a/b/cost/unit_cost）。"""
    models = _three_models()
    hybrid = build_hybrid((D("0.4"), D("0.4"), D("0.2")), models)
    assert isinstance(hybrid, HybridCost)
    a_h = (
        D("0.4") * models[0].a
        + D("0.4") * models[1].a
        + D("0.2") * models[2].a
    )
    assert abs(hybrid.a - a_h) <= Decimal("1e-12")
    q = D(800)
    assert abs(hybrid.unit_cost(q) - safe_div(hybrid.cost(q), q)) <= Decimal("1e-12")


def test_compute_hybrid_four_curves() -> None:
    """compute_hybrid 叠加 H 后产生四方案下包络（4 条曲线）。"""
    models = _three_models()
    hybrid = build_hybrid((D("0.34"), D("0.33"), D("0.33")), models)
    result = compute_hybrid(models, hybrid, demand_q=D(500), capacity_wall=D(1000))
    assert len(result.curves) == 4
    plans = {curve.plan for curve in result.curves}
    assert plans == {"self_build", "rent", "api", "hybrid"}
    assert len(result.crossovers) == 6


def test_invalid_weights_warn_not_silent() -> None:
    """enabled 但权重非法：引擎降级三方案，校验层必须给出 warning（不得静默）。"""
    from ai_roi.domain.validation.params import build_report

    params = (
        default_params()
        .with_override("hybrid.enabled", True)
        .with_override("hybrid.w_A", D("0.5"))
        .with_override("hybrid.w_B", D("0.5"))
        .with_override("hybrid.w_C", D("0.5"))
    )
    report = build_report(params)
    assert report.ok, "权重非法不应阻塞计算（优雅降级），只应告警"
    hybrid_warnings = [w for w in report.warnings if w.path == "hybrid.w_*"]
    assert hybrid_warnings, "权重非法时必须产生 hybrid.w_* 告警，禁止静默降级"


def test_valid_weights_no_warning() -> None:
    """enabled 且权重合法：不产生 hybrid 告警。"""
    from ai_roi.domain.validation.params import build_report

    params = (
        default_params()
        .with_override("hybrid.enabled", True)
        .with_override("hybrid.w_A", D("0.5"))
        .with_override("hybrid.w_B", D("0.3"))
        .with_override("hybrid.w_C", D("0.2"))
    )
    report = build_report(params)
    assert not [w for w in report.warnings if w.path == "hybrid.w_*"]
