"""P2-3 混合部署第四方案：后端 `compute_all` 接入校验。

验证：
1. 默认/禁用混合（`params.hybrid.enabled=False`）→ 输出与三方案完全一致（3 方案，不追加 hybrid）；
2. 启用且权重合法 → `cost_models` 产出 4 方案（第 4 个 plan = 'hybrid'），
   `crossover` 经 `compute_hybrid` 计算（4 条曲线、C(4,2)=6 个交点），`recommended` 为四方案下包络；
3. 启用但权重非法（和≠1）→ 安全回退三方案并附告警；
4. 混合权重经 codec 往返不丢失（修复保存/导出重算丢第 4 方案）。
"""

from __future__ import annotations

from ai_roi.domain.calc.codec import params_from_dict, params_to_dict
from ai_roi.domain.calc.cost_model import PLAN_HYBRID
from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import default_params


def _enabled_hybrid(w_A: str = "0.5", w_B: str = "0.3", w_C: str = "0.2"):
    """构造启用混合部署的参数（默认权重和=1）。"""
    return (
        default_params()
        .with_override("hybrid.enabled", True)
        .with_override("hybrid.w_A", D(w_A))
        .with_override("hybrid.w_B", D(w_B))
        .with_override("hybrid.w_C", D(w_C))
    )


def test_compute_all_disabled_keeps_three_schemes() -> None:
    """默认/禁用混合时，cost_models 仍为 3 方案，不追加 hybrid。"""
    params = default_params()
    payload = compute_all(params, EngineOptions(include_sensitivity=False, include_scenarios=False))
    assert len(payload["cost_models"]) == 3
    assert all(m["plan"] != PLAN_HYBRID for m in payload["cost_models"])
    assert len(payload["crossover"]["curves"]) == 3
    assert len(payload["crossover"]["crossovers"]) == 3


def test_compute_all_hybrid_enabled_four_schemes() -> None:
    """enabled=true 且权重合法 → cost_models 4 方案，第 4 个 plan='hybrid'。"""
    params = _enabled_hybrid()
    payload = compute_all(params, EngineOptions(include_sensitivity=False, include_scenarios=False))
    models = payload["cost_models"]
    assert len(models) == 4
    assert models[3]["plan"] == PLAN_HYBRID
    assert models[3]["label"] == "方案D 混合部署"
    assert len(payload["crossover"]["curves"]) == 4
    assert len(payload["crossover"]["crossovers"]) == 6
    assert isinstance(payload["crossover"]["recommended"], list)
    assert len(payload["crossover"]["recommended"]) >= 1
    assert models[3]["a"] is not None and models[3]["b"] is not None


def test_compute_all_hybrid_invalid_weights_fallback() -> None:
    """enabled=true 但权重非法（和=1.7≠1）→ 回退三方案并附告警。"""
    params = _enabled_hybrid(w_A="0.5", w_B="0.3", w_C="0.9")
    payload = compute_all(params, EngineOptions(include_sensitivity=False, include_scenarios=False))
    assert len(payload["cost_models"]) == 3
    assert any("混合部署" in w for w in payload["warnings"])


def test_hybrid_codec_roundtrip() -> None:
    """混合权重经 codec 往返不丢失（修复保存/导出重算丢失第 4 方案）。"""
    params = _enabled_hybrid()
    dumped = params_to_dict(params)
    assert dumped["hybrid"]["enabled"] is True
    restored = params_from_dict(dumped)
    assert restored.hybrid.enabled is True
    assert restored.hybrid.w_A == D("0.5")
    assert restored.hybrid.w_B == D("0.3")
    assert restored.hybrid.w_C == D("0.2")
