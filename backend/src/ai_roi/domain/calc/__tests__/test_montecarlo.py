"""P2-4 蒙特卡洛单测（REQ-18）。

验证：
1. 确定性输入（分布方差为 0）→ 蒙特卡洛均值 ≈ 确定性 NPV（容差 1%）；
2. 明显盈利场景 → P(NPV>0) ≈ 1；明显亏损场景 → P(NPV>0) ≈ 0；
3. 分位数单调、直方图分箱计数和 = N。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.montecarlo import montecarlo_compute
from ai_roi.domain.calc.parameters import ScenarioParams, default_params


def _override(params: ScenarioParams, **kwargs) -> ScenarioParams:
    """批量覆盖 perf/pricing 等字段（仅用于构造极端场景）。"""
    from ai_roi.domain.calc.parameters import derive

    _ = derive
    out = params
    for key, value in kwargs.items():
        group, field = key.split("_", 1)
        out = out.with_override(f"{group}.{field}", D(value))
    return out


def test_deterministic_regression() -> None:
    """分布方差为 0 时均值≈确定性 NPV（容差 0.5%，n=500 加固以捕获 spread 误用 bug）。"""
    import ai_roi.domain.calc.montecarlo as mc
    params = default_params()
    spreads = {p: 0.0 for p, _, _ in mc._SAMPLING_VARS}
    result = montecarlo_compute(params, n=500, seed=42, spreads=spreads)
    assert abs(result.mean_npv - result.deterministic_npv) <= abs(result.deterministic_npv) * 0.005 + 1e-9


def test_clearly_profitable_p_npv_positive() -> None:
    """明显盈利 → P(NPV>0) ≈ 1。"""
    params = default_params()
    rich = _override(params, pricing_p_out=500, pricing_p_in=1, pricing_Rent_gpu=1, pricing_API_out=1)
    result = montecarlo_compute(rich, n=500, seed=7)
    assert result.deterministic_npv > 0
    assert result.p_npv_positive >= 0.99


def test_clearly_lossy_p_npv_positive() -> None:
    """明显亏损 → P(NPV>0) ≈ 0。"""
    params = default_params()
    poor = _override(params, pricing_p_out=0)
    result = montecarlo_compute(poor, n=500, seed=7)
    assert result.deterministic_npv < 0
    assert result.p_npv_positive <= 0.01


def test_quantiles_and_histogram() -> None:
    """分位数单调递增，直方图分箱计数和 = N。"""
    params = default_params()
    result = montecarlo_compute(params, n=600, seed=3)
    p = result.percentiles_npv
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]
    total = sum(b["count"] for b in result.histogram)
    assert total == result.n
