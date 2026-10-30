"""参数模型与派生量（对应 PRD §2.5 参数字典七组 + 架构 §3.3）。

约定（必须与前端 `calc-engine/parameters.ts` 完全一致）：
- **所有百分比在引擎内部一律以比率（0–1）存储**（如残值率 10% → 0.10），UI 层负责换算；
- 金额单位 = 元（CNY 本位币）；需求量单位 = 百万 token/月（Mtok）；吞吐 = 等效输出 token/s；
- 字段名沿用 PRD/架构类图的符号名（N_gpu / P_gpu / T_eff ...），前后端 JSON 字段逐一对齐。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal
from typing import Any, Dict, Optional

from ai_roi.domain.calc.context import Conventions
from ai_roi.domain.calc.decimal_config import (
    CALC_CONTEXT,
    D,
    H,
    MONTHS_PER_YEAR,
    MTOK,
    ONE,
    SEC,
    ZERO,
    safe_div,
)

UTIL_MODE_EXPLICIT = "explicit"
UTIL_MODE_DEMAND_FROM_U = "demand_from_u"
UTIL_MODE_U_FROM_DEMAND = "u_from_demand"

RENT_INC_POWER = "power"
RENT_INC_POWER_HOSTING = "power_hosting"
RENT_INC_NONE = "none"

POWER_MODE_SEPARATE = "separate"
POWER_MODE_BUNDLE = "bundle"
VALID_POWER_MODES = {POWER_MODE_SEPARATE, POWER_MODE_BUNDLE}
RACK_CARDS_PER_NODE = 32

SOURCE_MEASURED = "measured"
SOURCE_BENCHMARK = "benchmark"
SOURCE_ESTIMATED = "estimated"

QUANT_FP4 = "FP4"
QUANT_FP8 = "FP8"
QUANT_FP16 = "FP16"
QUANT_BF16 = "BF16"
QUANT_INT4 = "INT4"
QUANT_INT8 = "INT8"
QUANT_MXFP4 = "MXFP4"
QUANT_NVFP4 = "NVFP4"
VALID_QUANTS = frozenset(
    {
        QUANT_FP4,
        QUANT_FP8,
        QUANT_FP16,
        QUANT_BF16,
        QUANT_INT4,
        QUANT_INT8,
        QUANT_MXFP4,
        QUANT_NVFP4,
    }
)

SPEC_METHOD_NONE = "none"
SPEC_METHOD_MTP = "MTP"
SPEC_METHOD_STP = "STP"
SPEC_METHOD_EAGLE = "EAGLE"
VALID_SPEC_METHODS = frozenset(
    {SPEC_METHOD_NONE, SPEC_METHOD_MTP, SPEC_METHOD_STP, SPEC_METHOD_EAGLE}
)


@dataclass(frozen=True)
class HardwareParams:
    """① 服务器与硬件组。"""

    N_gpu: Decimal = D(8)
    P_gpu: Decimal = D(250_000)
    P_aux: Decimal = D(150_000)
    T_deploy: Decimal = D(3)
    availability: Decimal = D("0.995")
    Y_dep: Decimal = D(4)
    S_pct: Decimal = D("0.10")
    L_sw: Decimal = ZERO
    pre_launch_cost: Decimal = ZERO
    domestic_gpu_share: Decimal = ZERO
    CN_cfg: str = "none"
    supporting_fabric: str = ""
    supporting_mem_gb: Decimal = ZERO
    supporting_cards_per_node: Decimal = ZERO
    supporting_port_speed: int = 0
    extra_nodes: int = 0
    supporting_spine_port_speed: int = 0


@dataclass(frozen=True)
class PowerParams:
    """② 部署与电力组。"""

    TDP: Decimal = D(700)
    P_aux_power: Decimal = D("4.9")
    P_sys_override: Optional[Decimal] = None
    PUE: Decimal = D("1.3")
    E_price: Decimal = D("0.8")
    Co_loc: Decimal = D(5_000)
    Co_net: Decimal = D(2_000)
    Co_stor: Decimal = D(1_000)
    Co_ops: Decimal = D(120_000)
    Co_eng: Decimal = ZERO
    Co_sales_admin: Decimal = ZERO
    Co_other: Decimal = ZERO
    e_price_peak: Decimal = D("0.8")
    e_price_flat: Decimal = D("0.8")
    e_price_valley: Decimal = D("0.8")
    tou_peak_share: Decimal = ZERO
    tou_valley_share: Decimal = ZERO
    P_idle_ratio: Decimal = ZERO
    power_mode: str = "separate"
    bundle_monthly_per_rack: Decimal = ZERO
    racks: Decimal = ZERO
    nodes_per_rack: Decimal = D(4)


@dataclass(frozen=True)
class PerfParams:
    """③ 模型与推理性能组。"""

    M_param: Decimal = D(70)
    active_params_b: Optional[Decimal] = None
    quant: str = "FP8"
    spec_method: str = SPEC_METHOD_NONE
    Mem_w: Decimal = D(140)
    Ctx: Decimal = D(8_192)
    B_max: Decimal = D(64)
    kv_cache_per_token_gb: Decimal = ZERO
    vram_total_gb: Decimal = ZERO
    T_eff: Decimal = D(2_500)
    T_pf: Decimal = D(20_000)
    T_dc: Decimal = D(2_000)
    SLA_ttft: Decimal = D(500)
    SLA_tpot: Decimal = D(50)
    SLA_penalty_rate: Decimal = ZERO
    k_override: Optional[Decimal] = None
    k_benchmark: Optional[Decimal] = None


@dataclass(frozen=True)
class DemandParams:
    """④ 业务量与利用率组。"""

    rho: Decimal = CALC_CONTEXT.divide(D(1), D(3))
    D_eq: Decimal = D(3_888)
    h: Decimal = D("0.20")
    U: Decimal = D("0.60")
    K_peak: Decimal = ONE
    util_mode: str = UTIL_MODE_EXPLICIT
    g_demand: Decimal = ZERO
    subagent_topology: Optional[str] = None


@dataclass(frozen=True)
class PricingParams:
    """⑤ 定价与收入组 + ⑦ 对比基准（云租赁/第三方 API）。"""

    p_in: Decimal = D("7.5")
    p_out: Decimal = D(30)
    p_cache: Optional[Decimal] = None
    g_price: Decimal = ZERO
    Rent_gpu: Decimal = D(18)
    rent_inc: str = RENT_INC_POWER
    rent_fixed_monthly: Decimal = ZERO
    API_in: Decimal = D(18)
    API_out: Decimal = D(70)
    API_cache: Optional[Decimal] = None
    cost_benchmark: Optional[Decimal] = None
    fx_usd_cny: Decimal = D("7.2")
    pkg_enabled: bool = False
    pkg_prepaid: Decimal = ZERO
    pkg_tokens: Decimal = ZERO
    pkg_consume_months: Decimal = ZERO

    @property
    def p_cache_effective(self) -> Decimal:
        """缓存命中价（缺省 0.1×p_in，PRD §2.5 ⑤）。"""
        return self.p_cache if self.p_cache is not None else self.p_in / D(10)

    @property
    def api_cache_effective(self) -> Decimal:
        """API 缓存命中价（缺省 0.1×API_in，PRD §2.5 ⑦）。"""
        return self.API_cache if self.API_cache is not None else self.API_in / D(10)


@dataclass(frozen=True)
class FinanceParams:
    """⑥ 财务与折现组。"""

    T_horizon: Decimal = D(36)
    r_w: Decimal = D("0.08")
    Tax: Decimal = D("0.25")
    infl: Decimal = ZERO
    revenue_ramp: bool = False
    debt_ratio: Decimal = ZERO
    debt_rate: Decimal = D("0.05")
    loan_term_months: Decimal = D(48)
    cost_learning_rate: Decimal = ZERO


@dataclass(frozen=True)
class BenchRefs:
    """基准库引用（仅记录来源与版本，数值已冻结进快照）。"""

    gpu_id: Optional[int] = None
    model_id: Optional[int] = None
    cloud_id: Optional[int] = None
    api_id: Optional[int] = None
    bench_version: Optional[str] = None
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridParams:
    """混合部署第四方案权重组（P2-3；对齐前端 `calc-engine/parameters.ts` `HybridParams`）。

    - `enabled`：是否纳入第四方案（**唯一开关**，缺省 False → 保持 A/B/C 三方案）；
    - `w_A / w_B / w_C`：自建 / 租用 / API 三方案权重（前端保证非负、和≈1），缺省各 1/3。
      后端 `engine.compute_all` 仅在 `enabled` 且权重合法（和≈1、非负）时叠加混合方案。
    """

    enabled: bool = False
    w_A: Decimal = CALC_CONTEXT.divide(D(1), D(3))
    w_B: Decimal = CALC_CONTEXT.divide(D(1), D(3))
    w_C: Decimal = CALC_CONTEXT.divide(D(1), D(3))


@dataclass(frozen=True)
class ScenarioParams:
    """完整方案参数（七组 + 口径）。不可变，便于敏感性/情景派生。"""

    hw: HardwareParams = field(default_factory=HardwareParams)
    power: PowerParams = field(default_factory=PowerParams)
    perf: PerfParams = field(default_factory=PerfParams)
    demand: DemandParams = field(default_factory=DemandParams)
    pricing: PricingParams = field(default_factory=PricingParams)
    finance: FinanceParams = field(default_factory=FinanceParams)
    bench: BenchRefs = field(default_factory=BenchRefs)
    hybrid: HybridParams = field(default_factory=HybridParams)
    conventions: Conventions = field(default_factory=Conventions)

    def with_override(self, path: str, value: Any) -> "ScenarioParams":
        """按 `group.field` 路径返回覆盖后的新参数对象（敏感性/情景分析使用）。

        Args:
            path: 形如 ``power.E_price``、``demand.U``。
            value: 新值（数值类型自动转 Decimal）。

        Raises:
            KeyError: 路径不存在。
        """
        group_name, _, field_name = path.partition(".")
        if not field_name or not hasattr(self, group_name):
            raise KeyError(f"非法参数路径：{path}")
        group = getattr(self, group_name)
        if not any(f.name == field_name for f in fields(group)):
            raise KeyError(f"参数组 {group_name} 中不存在字段 {field_name}")
        current = getattr(group, field_name)
        if value is None:
            new_value = None
        elif isinstance(current, Decimal) or current is None:
            new_value = D(value)
        else:
            new_value = value
        new_group = replace(group, **{field_name: new_value})
        return replace(self, **{group_name: new_group})

    def get_value(self, path: str) -> Any:
        """按 `group.field` 路径读取参数值。"""
        group_name, _, field_name = path.partition(".")
        return getattr(getattr(self, group_name), field_name)

    def scale(self, path: str, factor: Decimal) -> "ScenarioParams":
        """按比例缩放某参数（敏感性 ±Δ% 用）。"""
        current = self.get_value(path)
        if current is None:
            return self
        return self.with_override(path, D(current) * D(factor))


@dataclass(frozen=True)
class DerivedParams:
    """派生量（架构 §3.3，全部由输入参数确定，纯函数）。"""

    CAPEX: Decimal
    P_sys: Decimal
    Dep_m: Decimal
    C_fix_cash: Decimal
    C_fix_acct: Decimal
    C_var_per_U: Decimal
    C_power_idle_m: Decimal
    bundle_rack_cost_m: Decimal
    racks: Decimal
    power_mode: str
    weighted_e_price: Decimal
    Q_cap_M: Decimal
    k: Decimal
    k_source: str
    factor: Decimal
    D_out: Decimal
    D_in: Decimal
    Q_eq: Decimal
    U: Decimal
    U_implied: Decimal
    I0: Decimal
    SV: Decimal
    r_m: Decimal
    dep_months: Decimal


def effective_active_params_b(perf: PerfParams) -> Decimal:
    """C-2：返回参与吞吐/显存推导的「有效参数规模（B）」。

    MoE 模型取激活参数 `active_params_b`；稠密模型或未录入时回退 `M_param`。
    退化性：旧调用方（未设 active_params_b）得到与历史完全一致的 `M_param`，黄金向量零回归。
    """
    if perf.active_params_b is not None and perf.active_params_b > ZERO:
        return perf.active_params_b
    return perf.M_param


def resolve_k(perf: PerfParams) -> tuple[Decimal, str]:
    """解析等效折算系数 k（架构 §3.5 优先级）。

    优先级：实测/录入 → 吞吐比 T_dc/T_pf → 基准库 → 默认 0.1。

    Returns:
        (k, 来源标识)
    """
    if perf.k_override is not None and perf.k_override > ZERO:
        return perf.k_override, "measured"
    if perf.T_pf and perf.T_pf > ZERO and perf.T_dc and perf.T_dc > ZERO:
        return perf.T_dc / perf.T_pf, "throughput_ratio"
    if perf.k_benchmark is not None and perf.k_benchmark > ZERO:
        return perf.k_benchmark, "benchmark"
    return D("0.1"), "default"


def derive(params: ScenarioParams) -> DerivedParams:
    """由输入参数计算全部派生量（纯函数、零 IO）。"""
    hw, power, perf, demand, finance = (
        params.hw,
        params.power,
        params.perf,
        params.demand,
        params.finance,
    )

    capex = hw.N_gpu * hw.P_gpu + hw.P_aux
    p_sys = (
        power.P_sys_override
        if power.P_sys_override is not None
        else hw.N_gpu * power.TDP / D(1_000) + power.P_aux_power
    )

    dep_months = hw.Y_dep * MONTHS_PER_YEAR
    dep_m = safe_div(capex * (ONE - hw.S_pct), dep_months)
    c_fix_cash_base = (
        power.Co_net
        + power.Co_stor
        + power.Co_ops / MONTHS_PER_YEAR
        + power.Co_eng / MONTHS_PER_YEAR
        + power.Co_sales_admin / MONTHS_PER_YEAR
        + power.Co_other / MONTHS_PER_YEAR
        + hw.L_sw / MONTHS_PER_YEAR
    )

    w_peak = power.tou_peak_share
    w_valley = power.tou_valley_share
    if w_peak == ZERO and w_valley == ZERO:
        weighted_e_price = power.E_price
    else:
        w_flat = ONE - w_peak - w_valley
        weighted_e_price = (
            power.e_price_valley * w_valley
            + power.e_price_flat * w_flat
            + power.e_price_peak * w_peak
        )

    c_power_idle_m = p_sys * power.PUE * weighted_e_price * H * power.P_idle_ratio
    c_var_per_u = p_sys * power.PUE * weighted_e_price * H * (ONE - power.P_idle_ratio)

    if power.power_mode == POWER_MODE_BUNDLE:
        racks_n = power.racks if power.racks > ZERO else D(math.ceil(float(hw.N_gpu) / RACK_CARDS_PER_NODE))
        bundle_rack_cost_m = power.bundle_monthly_per_rack * racks_n
        c_fix_cash = c_fix_cash_base + bundle_rack_cost_m
        c_power_idle_m = ZERO
        c_var_per_u = ZERO
    else:
        racks_n = power.racks if power.racks > ZERO else D(math.ceil(float(hw.N_gpu) / RACK_CARDS_PER_NODE))
        bundle_rack_cost_m = ZERO
        c_fix_cash = c_fix_cash_base + power.Co_loc + c_power_idle_m
    c_fix_acct = dep_m + c_fix_cash

    q_cap_m = perf.T_eff * SEC / MTOK
    k, k_source = resolve_k(perf)
    factor = ONE + k * demand.rho * (ONE - demand.h)

    utilization = demand.U
    d_eq = demand.D_eq
    if demand.util_mode == UTIL_MODE_DEMAND_FROM_U:
        d_eq = q_cap_m * demand.U
    elif demand.util_mode == UTIL_MODE_U_FROM_DEMAND:
        utilization = safe_div(demand.D_eq, q_cap_m)
        utilization = utilization if utilization <= ONE else ONE

    d_out = safe_div(d_eq, factor)
    d_in = demand.rho * d_out
    u_implied = safe_div(d_eq, q_cap_m)

    i0 = capex + hw.pre_launch_cost
    sv = capex * hw.S_pct
    r_m = ((ONE + finance.r_w).ln() / MONTHS_PER_YEAR).exp() - ONE

    return DerivedParams(
        CAPEX=capex,
        P_sys=p_sys,
        Dep_m=dep_m,
        C_fix_cash=c_fix_cash,
        C_fix_acct=c_fix_acct,
        C_var_per_U=c_var_per_u,
        C_power_idle_m=c_power_idle_m,
        bundle_rack_cost_m=bundle_rack_cost_m,
        racks=racks_n,
        power_mode=power.power_mode,
        weighted_e_price=weighted_e_price,
        Q_cap_M=q_cap_m,
        k=k,
        k_source=k_source,
        factor=factor,
        D_out=d_out,
        D_in=d_in,
        Q_eq=d_eq,
        U=utilization,
        U_implied=u_implied,
        I0=i0,
        SV=sv,
        r_m=r_m,
        dep_months=dep_months,
    )


def default_params() -> ScenarioParams:
    """内置默认模板参数（全部数值为 PRD §2.5 的「待核实默认值」量级）。"""
    return ScenarioParams()


AGENTX_PRESET_RHO = D(200)
AGENTX_PRESET_H = D("0.96")
AGENTX_PRESET_CTX = D(128_000)
SHORT_CTX_PRESET_CTX = D(8_192)


def agentx_params() -> ScenarioParams:
    """E-9：返回 AgentX 长上下文场景预设（在默认模板基础上覆盖需求/性能画像）。

    纯函数、零 IO；与 `default_params()` 互不污染（frozen dataclass replace）。
    """
    base = default_params()
    return replace(
        base,
        demand=replace(base.demand, rho=AGENTX_PRESET_RHO, h=AGENTX_PRESET_H),
        perf=replace(base.perf, Ctx=AGENTX_PRESET_CTX),
    )
