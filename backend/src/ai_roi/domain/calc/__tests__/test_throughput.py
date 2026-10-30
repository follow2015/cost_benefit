"""P2-1 吞吐计算器单测（REQ-17）。

验证：
1. SLA 越严（阈值越小）→ 可用 batch 上限越小 → 有效吞吐（T_eff 建议值）越低；
2. 折算系数 k ≈ T_dc / T_pf（吞吐比来源）；
3. batch 上限夹在 [1, B_max]，放松 SLA 不放大超过 B_max。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.parameters import ScenarioParams, default_params, effective_active_params_b
from ai_roi.domain.calc.throughput import (
    ThroughputCalcResult,
    available_batch_limit,
    derive_throughput_calc,
    model_efficiency,
)


def _with(perf_overrides: dict) -> ScenarioParams:
    """构造覆盖 perf 组后的参数对象。"""
    params = default_params()
    new_perf = params.perf.__class__(**{**params.perf.__dict__, **perf_overrides})
    return params.__class__(**{**params.__dict__, "perf": new_perf})


def _with_derived(params: ScenarioParams):
    from ai_roi.domain.calc.parameters import derive

    return params, derive(params)


def test_stricter_sla_reduces_batch_and_throughput() -> None:
    """SLA 严格 → batch 上限下降 → T_eff 建议值下降。"""
    relaxed = _with({"SLA_ttft": D(1000), "SLA_tpot": D(100), "B_max": D(64)})
    strict = _with({"SLA_ttft": D(250), "SLA_tpot": D(25), "B_max": D(64)})

    r_relaxed = derive_throughput_calc(*_with_derived(relaxed))
    r_strict = derive_throughput_calc(*_with_derived(strict))

    assert r_strict.B_limit < r_relaxed.B_limit, "更严格 SLA 应得到更小的 batch 上限"
    assert r_strict.T_eff_suggestion < r_relaxed.T_eff_suggestion, "更严格 SLA 应得到更低的有效吞吐"


def test_available_batch_limit_bounds() -> None:
    """batch 上限夹在 [1, B_max]，放松 SLA 不超过 B_max。"""
    assert available_batch_limit(D(64), D(1000), D(100)) == D(64)
    assert available_batch_limit(D(64), D(500), D(50)) == D(32)
    assert available_batch_limit(D(64), D(1), D(1)) >= D(1)
    assert available_batch_limit(D(64), D(5000), D(500)) == D(64)


def test_k_equals_throughput_ratio() -> None:
    """吞吐比来源下，k ≈ T_dc_mid / T_pf_mid。"""
    params = _with({"SLA_ttft": D(1000), "SLA_tpot": D(100), "B_max": D(64)})
    result: ThroughputCalcResult = derive_throughput_calc(*_with_derived(params))
    assert result.k_source == "throughput_ratio"
    expected = result.T_dc_mid / result.T_pf_mid
    assert abs(result.k - expected) <= Decimal("1e-9")
    assert result.k_low <= result.k <= result.k_high


def test_measured_k_passthrough() -> None:
    """实测 k 优先于吞吐比。"""
    params = _with({"k_override": D("0.25"), "SLA_ttft": D(1000), "SLA_tpot": D(100)})
    result = derive_throughput_calc(*_with_derived(params))
    assert result.k_source == "measured"
    assert result.k == D("0.25")


def test_quant_fp4_boosts_efficiency() -> None:
    """低精度 → 更高吞吐效率因子（FP4/MXFP4 > FP8）。"""
    fp8 = model_efficiency(D(70), "FP8")
    fp4 = model_efficiency(D(70), "FP4")
    mxfp4 = model_efficiency(D(70), "MXFP4")
    nvfp4 = model_efficiency(D(70), "NVFP4")
    assert fp4 > fp8
    assert mxfp4 > fp4
    assert nvfp4 == mxfp4
    assert model_efficiency(D(70), "UNKNOWN") == fp8


def test_spec_method_multiplier() -> None:
    """投机解码方法按接受长度倍率提升有效吞吐（C-3 订正）。"""
    none = model_efficiency(D(70), "FP8", "none")
    mtp = model_efficiency(D(70), "FP8", "MTP")
    stp = model_efficiency(D(70), "FP8", "STP")
    eagle = model_efficiency(D(70), "FP8", "EAGLE")
    assert mtp == none * D("1.3")
    assert stp == none * D("1.5")
    assert eagle == none * D("1.8")
    assert model_efficiency(D(70), "FP4", "EAGLE") == model_efficiency(D(70), "FP4") * D("1.8")


def test_effective_active_params_b_fallback() -> None:
    """active_params_b 缺失时回退 M_param（稠密语义，黄金向量零回归）。"""
    dense = default_params().perf
    assert effective_active_params_b(dense) == dense.M_param
    moe = dense.__class__(**{**dense.__dict__, "M_param": D(1600), "active_params_b": D(49)})
    assert effective_active_params_b(moe) == D(49)


def test_moe_active_params_raises_throughput() -> None:
    """MoE 激活参数（49B）远小于总参数（1.6T）→ 有效吞吐高于同口径稠密 70B。"""
    dense = _with({"M_param": D(70), "active_params_b": None, "SLA_ttft": D(1000), "SLA_tpot": D(100)})
    moe = _with({"M_param": D(1600), "active_params_b": D(49), "SLA_ttft": D(1000), "SLA_tpot": D(100)})
    r_dense = derive_throughput_calc(*_with_derived(dense))
    r_moe = derive_throughput_calc(*_with_derived(moe))
    assert r_moe.T_eff_suggestion > r_dense.T_eff_suggestion
