"""P3-3 推荐方案可行性分级：viable / loss（亏损告警）/ no_demand（真正无解）。

背景：此前 `recommended_plan` 仅在 Q_eq<0 时为 None（UI 渲染「无解」），
但历史上出现过「亏损场景显示无解」的误导。本测试固化新分级：
- Q_eq ≤ 0 → `status='no_demand'`、`value=None`（真正无可行方案）；
- 需求有效但毛利率为负 → `status='loss'`、`value=成本最优方案名`、附告警文案；
- 毛利非负 → `status='viable'`。
"""

from __future__ import annotations

from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import default_params


OPTS = EngineOptions(include_sensitivity=False, include_scenarios=False, include_crossover=True)


def _recommended(payload: dict) -> dict:
    return next(k for k in payload["kpis"] if k["key"] == "recommended_plan")


def test_recommended_loss_scenario_keeps_plan_with_warning() -> None:
    """定价压到极低 → 毛利率必为负：仍给成本最优方案 + loss 告警，不再显示无解。"""
    params = (
        default_params()
        .with_override("pricing.p_in", D("0.01"))
        .with_override("pricing.p_out", D("0.01"))
    )
    payload = compute_all(params, OPTS)
    rp = _recommended(payload)
    assert rp["value"] is not None, "亏损场景仍应给出成本最优方案"
    assert rp["status"] == "loss"
    assert rp["note"], "loss 场景必须附告警文案"


def test_recommended_no_demand_returns_null() -> None:
    """月需求量 = 0 → 真正无可行方案：value=None、status='no_demand'。"""
    params = default_params().with_override("demand.D_eq", D(0))
    payload = compute_all(params, OPTS)
    rp = _recommended(payload)
    assert rp["value"] is None
    assert rp["status"] == "no_demand"
    assert rp["note"]


def test_recommended_has_plan_when_demand_positive() -> None:
    """需求有效（默认 D_eq=3888）时推荐方案必非空：不再出现无解的误导。"""
    payload = compute_all(default_params(), OPTS)
    rp = _recommended(payload)
    assert rp["value"] is not None
    assert rp["status"] in ("viable", "loss")
