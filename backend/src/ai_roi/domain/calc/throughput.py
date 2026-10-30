"""吞吐与容量推导（架构 §3.3 / §3.5）。

P0 允许用户直接录入 `T_eff`；本模块负责：
1. 满负荷月产能 `Q_cap_M = T_eff·SEC/MTOK`（Mtok/月）；
2. 实际月产出 `Q_out_M(U) = Q_cap_M·U`；
3. 等效折算系数 k 的来源解释（供 UI「数据来源」标记与 ⓘ 可追溯抽屉）；
4. 容量墙校验（需求是否超过满负荷产能）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List

from ai_roi.domain.calc.decimal_config import D, MTOK, ONE, SEC, ZERO, safe_div
from ai_roi.domain.calc.parameters import (
    DerivedParams,
    PerfParams,
    ScenarioParams,
    SPEC_METHOD_NONE,
    effective_active_params_b,
)

K_SOURCE_LABELS = {
    "measured": "实测/用户录入",
    "throughput_ratio": "吞吐比 T_dc / T_pf",
    "benchmark": "基准库查表",
    "default": "默认经验值 0.1（估算）",
}


@dataclass(frozen=True)
class ThroughputInfo:
    """吞吐能力信息。"""

    T_eff: Decimal
    Q_cap_M: Decimal
    Q_out_M: Decimal
    k: Decimal
    k_source: str
    k_source_label: str
    capacity_headroom: Decimal
    over_capacity: bool
    warnings: List[str]


def month_capacity_mtok(t_eff: Decimal) -> Decimal:
    """满负荷月产能（Mtok/月）：`T_eff · SEC / MTOK`。"""
    return D(t_eff) * SEC / MTOK


def month_output_mtok(t_eff: Decimal, utilization: Decimal) -> Decimal:
    """实际月产出（Mtok/月）：`Q_cap_M · U`。"""
    return month_capacity_mtok(t_eff) * D(utilization)


def analyze(params: ScenarioParams, derived: DerivedParams) -> ThroughputInfo:
    """产出吞吐信息 + 一致性告警（纯函数）。"""
    warnings: List[str] = []
    q_out = derived.Q_cap_M * derived.U
    headroom = derived.Q_cap_M - derived.Q_eq

    if derived.Q_cap_M <= ZERO:
        warnings.append("满负荷产能为 0：请检查有效吞吐 T_eff 是否录入。")
    if derived.k_source == "default":
        warnings.append(
            "等效折算系数 k 使用默认经验值 0.1（估算），建议提供实测吞吐或 T_pf/T_dc。"
        )
    if headroom < ZERO:
        warnings.append(
            "月需求量已超过满负荷月产能（超出容量墙），自建/租用方案需扩容才可承接。"
        )
    if derived.U > ZERO:
        deviation = abs(derived.U_implied - derived.U) / derived.U
        if deviation > D("0.05"):
            warnings.append(
                "利用率 U 与「月需求量/满负荷产能」隐含利用率偏差超过 5%"
                f"（U={derived.U}，隐含={safe_div(derived.Q_eq, derived.Q_cap_M)}），"
                "请确认口径一致性。"
            )

    return ThroughputInfo(
        T_eff=params.perf.T_eff,
        Q_cap_M=derived.Q_cap_M,
        Q_out_M=q_out,
        k=derived.k,
        k_source=derived.k_source,
        k_source_label=K_SOURCE_LABELS.get(derived.k_source, derived.k_source),
        capacity_headroom=headroom,
        over_capacity=headroom < ZERO,
        warnings=warnings,
    )


TTFT_REF_MS: Decimal = Decimal("1000")
TPOT_REF_MS: Decimal = Decimal("100")

REF_T_PF: Decimal = Decimal("20000")
REF_T_DC: Decimal = Decimal("2000")

THROUGHPUT_BAND: Decimal = Decimal("0.15")

QUANT_THROUGHPUT_MULT: Dict[str, Decimal] = {
    "FP4": Decimal("2.0"),
    "FP8": Decimal("1.0"),
    "FP16": Decimal("0.6"),
    "BF16": Decimal("0.6"),
    "INT8": Decimal("1.3"),
    "INT4": Decimal("1.8"),
    "MXFP4": Decimal("2.2"),
    "NVFP4": Decimal("2.2"),
}

SPEC_DECODE_ACCEPT_LENGTH_MULT: Dict[str, Decimal] = {
    "none": Decimal("1.0"),
    "MTP": Decimal("1.3"),
    "STP": Decimal("1.5"),
    "EAGLE": Decimal("1.8"),
}


@dataclass(frozen=True)
class ThroughputCalcResult:
    """吞吐计算器输出（P2-1）。"""

    B_max: Decimal
    B_limit: Decimal
    sla_constrained: bool
    T_pf_low: Decimal
    T_pf_mid: Decimal
    T_pf_high: Decimal
    T_dc_low: Decimal
    T_dc_mid: Decimal
    T_dc_high: Decimal
    k: Decimal
    k_low: Decimal
    k_high: Decimal
    k_source: str
    k_source_label: str
    T_eff_suggestion: Decimal
    warnings: List[str]


def model_efficiency(
    m_param: Decimal,
    quant: str,
    spec_method: str = "none",
) -> Decimal:
    """模型规模 / 量化 / 投机解码带来的吞吐效率因子（单调：模型越大越低；低精度越高）。

    - `m_param`：应为**激活参数规模**（MoE 用 `active_params_b`，稠密回退 `M_param`）；
      由调用方经 `effective_active_params_b` 传入，本函数不感知 MoE 语义。
    - `spec_method`：投机解码方法（MTP/STP/EAGLE）→ 乘接受长度倍率（见 C-3）。
    纯启发式，量级合理、可复现，不进入 golden 主链。
    """
    base = Decimal("1") - (D(m_param) - Decimal("70")) / Decimal("400")
    if base < Decimal("0.3"):
        base = Decimal("0.3")
    if base > Decimal("1.5"):
        base = Decimal("1.5")
    mult = QUANT_THROUGHPUT_MULT.get(str(quant).upper(), Decimal("1.0"))
    spec_mult = SPEC_DECODE_ACCEPT_LENGTH_MULT.get(str(spec_method).upper(), Decimal("1.0"))
    return base * mult * spec_mult


def kv_cache_batch_limit(perf: PerfParams) -> Optional[Decimal]:
    """E-5：由 KV cache 显存容量推导 batch 上限（可选启用）。

    仅当 `vram_total_gb` 与 `kv_cache_per_token_gb` 均 > 0 时生效：
    ``floor((vram_total − Mem_w) / (kv_cache_per_token × Ctx))``。
    否则返回 ``None``（不约束，回退硬件 B_max）。默认场景两字段为 0 ⇒ 不约束。
    """
    if perf.vram_total_gb <= ZERO or perf.kv_cache_per_token_gb <= ZERO:
        return None
    kv_budget = perf.vram_total_gb - perf.Mem_w
    if kv_budget <= ZERO:
        return Decimal("1")
    per_seq = perf.kv_cache_per_token_gb * perf.Ctx
    if per_seq <= ZERO:
        return None
    return (kv_budget / per_seq).to_integral_value(rounding="ROUND_FLOOR")


def effective_b_max(perf: PerfParams) -> Decimal:
    """E-5：有效 batch 上限 = min(硬件 B_max, KV cache 容量约束)；未启用时回退 B_max。

    退化性：默认 `kv_cache_per_token_gb=0 / vram_total_gb=0` ⇒ 返回 `perf.B_max`，黄金向量零回归。
    """
    kv = kv_cache_batch_limit(perf)
    if kv is None:
        return perf.B_max
    return min(perf.B_max, kv)


def available_batch_limit(
    b_max: Decimal,
    sla_ttft_ms: Decimal,
    sla_tpot_ms: Decimal,
    spec_method: str = SPEC_METHOD_NONE,
) -> Decimal:
    """由 SLA 阈值推导可用 batch 上限（架构 §266 硬耦合）。

    - TTFT 越严（越小）→ 单次 prefill 可用时间越少 → batch 越小；
    - TPOT 越严（越小）→ 单 token 解码时间越紧 → batch 越小；
    - **E-6 投机解码**：`spec_method` 降低等效 TPOT 延迟要求（接受长度倍率）→ 放松 batch 约束；
    取三者较小值，并夹在 [1, B_max]。放松（大于参考）SLA 不放大超过 B_max。
    """
    ttft_rel = D(sla_ttft_ms) / TTFT_REF_MS if TTFT_REF_MS > ZERO else ONE
    spec_mult = SPEC_DECODE_ACCEPT_LENGTH_MULT.get(str(spec_method).upper(), ONE)
    tpot_eff = D(sla_tpot_ms) * spec_mult if spec_mult > ZERO else D(sla_tpot_ms)
    tpot_rel = tpot_eff / TPOT_REF_MS if TPOT_REF_MS > ZERO else ONE
    relax = min(ttft_rel, tpot_rel)
    raw = D(b_max) * relax
    limit = raw.to_integral_value(rounding="ROUND_FLOOR")
    if limit < Decimal("1"):
        limit = Decimal("1")
    if limit > D(b_max):
        limit = D(b_max)
    return limit


def derive_throughput_calc(
    params: ScenarioParams, derived: DerivedParams
) -> ThroughputCalcResult:
    """吞吐计算器主入口：输入模型规模/量化/batch + SLA，输出吞吐区间与 k。"""
    warnings: List[str] = []
    b_max = effective_b_max(params.perf)
    b_limit = available_batch_limit(
        b_max, params.perf.SLA_ttft, params.perf.SLA_tpot, params.perf.spec_method
    )
    sla_constrained = b_limit < D(b_max)

    eff = model_efficiency(
        effective_active_params_b(params.perf),
        params.perf.quant,
        params.perf.spec_method,
    )
    scale = D(b_limit) / D(b_max) if D(b_max) > ZERO else ZERO
    t_pf_mid = REF_T_PF * eff * scale
    t_dc_mid = REF_T_DC * eff * scale

    if sla_constrained:
        warnings.append(
            f"SLA（TTFT={params.perf.SLA_ttft}ms / TPOT={params.perf.SLA_tpot}ms）"
            f"将可用 batch 上限由 {b_max} 收紧至 {b_limit}，有效吞吐随之下降。"
        )
    if t_pf_mid <= ZERO or t_dc_mid <= ZERO:
        warnings.append("推导吞吐为 0：请检查模型规模 / batch / SLA 参数是否合理。")

    t_pf_low = t_pf_mid * (ONE - THROUGHPUT_BAND)
    t_pf_high = t_pf_mid * (ONE + THROUGHPUT_BAND)
    t_dc_low = t_dc_mid * (ONE - THROUGHPUT_BAND)
    t_dc_high = t_dc_mid * (ONE + THROUGHPUT_BAND)

    if params.perf.k_override is not None and params.perf.k_override > ZERO:
        k_source = "measured"
        k_mid = params.perf.k_override
        k_low = k_mid
        k_high = k_mid
    else:
        k_source = "throughput_ratio"
        k_mid = safe_div(t_dc_mid, t_pf_mid, D("0.1"))
        k_low = safe_div(t_dc_low, t_pf_high, D("0.1"))
        k_high = safe_div(t_dc_high, t_pf_low, D("0.1"))

    return ThroughputCalcResult(
        B_max=D(b_max),
        B_limit=b_limit,
        sla_constrained=sla_constrained,
        T_pf_low=t_pf_low,
        T_pf_mid=t_pf_mid,
        T_pf_high=t_pf_high,
        T_dc_low=t_dc_low,
        T_dc_mid=t_dc_mid,
        T_dc_high=t_dc_high,
        k=k_mid,
        k_low=k_low,
        k_high=k_high,
        k_source=k_source,
        k_source_label=K_SOURCE_LABELS.get(k_source, k_source),
        T_eff_suggestion=t_dc_mid,
        warnings=warnings,
    )
