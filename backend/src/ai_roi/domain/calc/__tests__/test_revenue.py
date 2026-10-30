"""C-1 成本侧/收入侧口径分离：双口径毛利 + 亏损告警。

验证 `p_in/p_out`（售价，收入侧）与 `cost_benchmark`（市场公允成本标杆，成本侧）严格分离：
- cost_benchmark=None（默认）⇒ 双口径字段为 None、不亏损、不告警、KPI 不出现；
- cost_benchmark 录入 ⇒ 计算 G_benchmark（售价 − 标杆成本），等价单价 p_eq < 标杆 ⇒ 亏损告警。
"""

from ai_roi.domain.calc import engine as engine_module
from ai_roi.domain.calc import revenue as revenue_module
from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.parameters import default_params, derive


def _case(cost_benchmark=None):
    params = default_params()
    if cost_benchmark is not None:
        params = params.with_override("pricing.cost_benchmark", cost_benchmark)
    derived = derive(params)
    c_total = D("100000")
    return params, derived, revenue_module.compute(params, derived, c_total)


def test_no_benchmark_returns_none() -> None:
    """默认（未录入成本标杆）：双口径字段全 None、不亏损。"""
    _params, _derived, rev = _case()
    assert rev.G_benchmark is None
    assert rev.cost_benchmark_total is None
    assert rev.GM_pct_benchmark is None
    assert rev.loss_vs_benchmark is False


def test_benchmark_gross_and_no_loss() -> None:
    """录入低成本标杆（≈InferenceX DeepSeek AgentX 经汇率换算）：不亏损、双口径为正。"""
    _params, derived, rev = _case(D("0.08"))
    assert rev.cost_benchmark_total == derived.Q_eq * D("0.08")
    assert rev.loss_vs_benchmark is False
    assert rev.G_benchmark is not None and rev.G_benchmark > ZERO
    assert rev.GM_pct_benchmark is not None and rev.GM_pct_benchmark > ZERO


def test_benchmark_loss_alert() -> None:
    """标杆高于售价（极端）：亏损判定为真、毛利为负、引擎告警、KPI 出现。"""
    params, _derived, rev = _case(D("40"))
    assert rev.loss_vs_benchmark is True
    assert rev.G_benchmark is not None and rev.G_benchmark < ZERO
    payload = engine_module.compute_all(params)
    assert any("口径告警" in w for w in payload["warnings"])
    keys = [k["key"] for k in payload["kpis"]]
    assert "gross_margin_benchmark" in keys


def test_no_benchmark_kpi_absent() -> None:
    """未录入标杆时，双口径 KPI 不应出现在载荷（避免污染默认场景）。"""
    params = default_params()
    payload = engine_module.compute_all(params)
    keys = [k["key"] for k in payload["kpis"]]
    assert "gross_margin_benchmark" not in keys
