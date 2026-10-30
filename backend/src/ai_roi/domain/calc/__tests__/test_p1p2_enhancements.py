"""P1/P2 引擎增强单测（InferenceX 校准链 Phase 6）：C-4 / E-5 / E-6 / E-9 / E-10。

锁定以下新增/修订行为的数值契约，确保黄金向量（默认参数）零回归：
- C-4 长上下文成本曲线：uplift=1+K·max(Ctx/8192−1,0)·(1−h)；
- E-5 KV cache 容量约束：effective_b_max = min(B_max, floor((vram−Mem_w)/(kv·Ctx)))；
- E-6 投机解码 SLA：spec_method 放宽 TPOT 约束 → 更大 batch；
- E-9 AgentX 预设：rho≈200 / h≈0.96 / Ctx≈128k；
- E-10 标杆告警环：自建设本偏离 cost_benchmark > ±50% 触发「标杆告警」。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import ONE
from ai_roi.domain.calc.engine import compute_core
from ai_roi.domain.calc.parameters import (
    SHORT_CTX_PRESET_CTX,
    AGENTX_PRESET_CTX,
    AGENTX_PRESET_H,
    AGENTX_PRESET_RHO,
    SPEC_METHOD_EAGLE,
    SPEC_METHOD_NONE,
    ScenarioParams,
    agentx_params,
    default_params,
    derive,
    replace,
)
from ai_roi.domain.calc.throughput import (
    available_batch_limit,
    derive_throughput_calc,
    effective_b_max,
    kv_cache_batch_limit,
)
from ai_roi.domain.calc.unit_cost import (
    CTX_UPLIFT_K,
    _SHORT_CTX,
    compute as unit_cost_compute,
    context_uplift_factor,
)


def _with(perf_overrides: dict) -> ScenarioParams:
    """构造覆盖 perf 组后的参数对象。"""
    params = default_params()
    new_perf = params.perf.__class__(**{**params.perf.__dict__, **perf_overrides})
    return params.__class__(**{**params.__dict__, "perf": new_perf})


def _with_derived(params: ScenarioParams):
    return params, derive(params)


def test_c4_short_ctx_uplift_is_one() -> None:
    """短链（Ctx≤8192）uplift=1，黄金向量零回归。"""
    assert context_uplift_factor(default_params()) == ONE


def test_c4_agentx_uplift_formula() -> None:
    """AgentX 长上下文 uplift 严格按公式 = 1 + K·(Ctx/8192−1)·(1−h)。"""
    p = agentx_params()
    uplift = context_uplift_factor(p)
    expected = ONE + CTX_UPLIFT_K * (AGENTX_PRESET_CTX / _SHORT_CTX - ONE) * (ONE - AGENTX_PRESET_H)
    assert abs(uplift - expected) <= Decimal("1e-12")
    assert abs(uplift - Decimal("1.585")) <= Decimal("1e-9")


def test_c4_agentx_cost_above_short() -> None:
    """同利用率/产出假设下，AgentX 长上下文成本高于短链（仅通过 uplift 上浮）。"""
    d_default = derive(default_params())
    d_agentx = derive(agentx_params())
    uc_default = unit_cost_compute(default_params(), d_default)
    uc_agentx = unit_cost_compute(agentx_params(), d_agentx)
    assert uc_agentx.context_uplift > ONE
    assert uc_agentx.cost_per_m_capacity > uc_default.cost_per_m_capacity
    ratio = uc_agentx.cost_per_m_capacity / uc_default.cost_per_m_capacity
    assert abs(ratio - uc_agentx.context_uplift) <= Decimal("1e-9")


def test_c4_higher_hit_rate_dampens_uplift() -> None:
    """缓存命中率越高，长上下文上浮越小（h 摊薄重算成本）。"""
    low_hit = _with({"Ctx": AGENTX_PRESET_CTX, "vram_total_gb": Decimal("0"), "kv_cache_per_token_gb": Decimal("0")})
    base = default_params()
    cmp_low = replace(base, perf=replace(base.perf, Ctx=AGENTX_PRESET_CTX), demand=replace(base.demand, h=Decimal("0.20")))
    cmp_high = replace(base, perf=replace(base.perf, Ctx=AGENTX_PRESET_CTX), demand=replace(base.demand, h=Decimal("0.96")))
    assert context_uplift_factor(cmp_high) < context_uplift_factor(cmp_low)


def test_e5_default_fallback_to_b_max() -> None:
    """默认 kv/vram=0 ⇒ 未启用 ⇒ effective_b_max = B_max（黄金向量零回归）。"""
    base = default_params()
    assert kv_cache_batch_limit(base.perf) is None
    assert effective_b_max(base.perf) == base.perf.B_max


def test_e5_room_capacity_tightens_batch() -> None:
    """充足显存：vram=400, Mem_w=140, kv=0.001/token, Ctx=8192 ⇒ floor(260/8.192)=31。"""
    roomy = _with({"vram_total_gb": Decimal("400"), "kv_cache_per_token_gb": Decimal("0.001"), "B_max": Decimal("64")})
    kv = kv_cache_batch_limit(roomy.perf)
    assert kv is not None
    assert kv == Decimal("31")
    assert effective_b_max(roomy.perf) == Decimal("31")


def test_e5_negative_kv_budget_floor_one() -> None:
    """权重已占满显存（vram<Mem_w）⇒ kv_budget≤0 ⇒ 仅能承载极小 batch（floor→1）。"""
    tight = _with({"vram_total_gb": Decimal("80"), "kv_cache_per_token_gb": Decimal("0.001")})
    assert effective_b_max(tight.perf) == Decimal("1")


def test_e5_effective_b_max_feeds_throughput() -> None:
    """KV 约束后的有效 batch 上限经 derive 主入口生效：B_limit ≤ 容量约束。"""
    roomy = _with({"vram_total_gb": Decimal("400"), "kv_cache_per_token_gb": Decimal("0.001"), "B_max": Decimal("64")})
    result = derive_throughput_calc(*_with_derived(roomy))
    assert result.B_max == Decimal("31")
    assert result.B_limit <= Decimal("31")


def test_e6_speculative_decoding_relaxes_batch() -> None:
    """E-6：TTFT 宽松使 TPOT 绑定时，spec_method=EAGLE 的 batch 上限 > none。"""
    none = _with({"B_max": Decimal("64"), "SLA_ttft": Decimal("1000"), "SLA_tpot": Decimal("50"), "spec_method": SPEC_METHOD_NONE})
    eagle = _with({"B_max": Decimal("64"), "SLA_ttft": Decimal("1000"), "SLA_tpot": Decimal("50"), "spec_method": SPEC_METHOD_EAGLE})
    none_limit = available_batch_limit(none.perf.B_max, none.perf.SLA_ttft, none.perf.SLA_tpot, none.perf.spec_method)
    eagle_limit = available_batch_limit(eagle.perf.B_max, eagle.perf.SLA_ttft, eagle.perf.SLA_tpot, eagle.perf.spec_method)
    assert eagle_limit >= none_limit
    assert eagle_limit > none_limit
    r_none = derive_throughput_calc(*_with_derived(none))
    r_eagle = derive_throughput_calc(*_with_derived(eagle))
    assert r_eagle.B_limit >= r_none.B_limit


def test_e6_none_is_golden_identical() -> None:
    """spec_method='none'（默认）数值与修订前完全一致（spec_mult=1.0）。"""
    params = _with({"B_max": Decimal("64"), "SLA_ttft": Decimal("500"), "SLA_tpot": Decimal("50")})
    limit = available_batch_limit(params.perf.B_max, params.perf.SLA_ttft, params.perf.SLA_tpot, SPEC_METHOD_NONE)
    assert limit == Decimal("32")


def test_e9_agentx_preset_values() -> None:
    """agentx_params() 预设 rho≈200 / h≈0.96 / Ctx≈128k。"""
    p = agentx_params()
    assert p.demand.rho == AGENTX_PRESET_RHO
    assert p.demand.h == AGENTX_PRESET_H
    assert p.perf.Ctx == AGENTX_PRESET_CTX
    d = default_params()
    assert d.demand.rho != AGENTX_PRESET_RHO
    assert d.perf.Ctx == SHORT_CTX_PRESET_CTX


def test_e10_benchmark_alert_fires_when_off_by_50pct() -> None:
    """自建设本偏离 cost_benchmark > ±50% 时触发「标杆告警」。"""
    p = default_params()
    cpm = unit_cost_compute(p, derive(p)).cost_per_m_capacity
    p_low = p.with_override("pricing.cost_benchmark", cpm / Decimal("3"))
    r = compute_core(p_low)
    assert any("标杆告警" in w for w in r.warnings)


def test_e10_benchmark_alert_silent_within_band() -> None:
    """自建设本与 cost_benchmark 一致（偏离 0%）时不触发「标杆告警」。"""
    p = default_params()
    cpm = unit_cost_compute(p, derive(p)).cost_per_m_capacity
    p_ok = p.with_override("pricing.cost_benchmark", cpm)
    r = compute_core(p_ok)
    assert not any("标杆告警" in w for w in r.warnings)


def test_e10_disabled_when_no_benchmark() -> None:
    """cost_benchmark=None（默认）不触发「标杆告警」。"""
    r = compute_core(default_params())
    assert not any("标杆告警" in w for w in r.warnings)
