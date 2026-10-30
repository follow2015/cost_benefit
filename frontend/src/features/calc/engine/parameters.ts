/**
 * 参数模型与派生量。与后端 `app/calc/parameters.py` 逐字段对齐。
 * 约定：所有百分比一律以比率（0–1）存储；Decimal 由 decimalConfig 提供。
 */

import { D, Decimal, ZERO, ONE, H, SEC, MTOK, MONTHS_PER_YEAR, safeDiv, type Numeric } from './decimalConfig';
import { Conventions, defaultConventions } from './context';

// 利用率耦合口径
export const UTIL_MODE_EXPLICIT = 'explicit';
export const UTIL_MODE_DEMAND_FROM_U = 'demand_from_u';
export const UTIL_MODE_U_FROM_DEMAND = 'u_from_demand';

// 租赁包含项
export const RENT_INC_POWER = 'power';
export const RENT_INC_POWER_HOSTING = 'power_hosting';
export const RENT_INC_NONE = 'none';

// 电力运维口径（PowerParams.power_mode）
export const POWER_MODE_SEPARATE = 'separate'; // 柜电分离（默认）：机柜费 Co_loc + 电费按功耗核算
export const POWER_MODE_BUNDLE = 'bundle'; // 包柜包电：机柜+电费一口价（元/柜/月），不再按功耗核算电费
// 机柜数自动推导参考：每机柜可承载卡数（8 卡机 × 4 台/柜 = 32 卡/柜）
export const RACK_CARDS_PER_NODE = 32;

// 来源标记
export const SOURCE_MEASURED = 'measured';
export const SOURCE_BENCHMARK = 'benchmark';
export const SOURCE_ESTIMATED = 'estimated';

// 量化/精度枚举（对齐后端 VALID_QUANTS，C-3 订正）
export const QUANT_FP4 = 'FP4';
export const QUANT_FP8 = 'FP8';
export const QUANT_FP16 = 'FP16';
export const QUANT_BF16 = 'BF16';
export const QUANT_INT4 = 'INT4';
export const QUANT_INT8 = 'INT8';
export const QUANT_MXFP4 = 'MXFP4';
export const QUANT_NVFP4 = 'NVFP4';
export const QUANT_OPTIONS = [
  QUANT_FP4, QUANT_FP8, QUANT_FP16, QUANT_BF16, QUANT_INT4, QUANT_INT8, QUANT_MXFP4, QUANT_NVFP4,
];

// 投机解码方法枚举（对齐后端 VALID_SPEC_METHODS，C-3 订正）
export const SPEC_METHOD_NONE = 'none';
export const SPEC_METHOD_MTP = 'MTP';
export const SPEC_METHOD_STP = 'STP';
export const SPEC_METHOD_EAGLE = 'EAGLE';
export const SPEC_METHOD_OPTIONS = [SPEC_METHOD_NONE, SPEC_METHOD_MTP, SPEC_METHOD_STP, SPEC_METHOD_EAGLE];

export interface HardwareParams {
  N_gpu: Decimal;
  P_gpu: Decimal;
  P_aux: Decimal;
  T_deploy: Decimal;
  availability: Decimal;
  Y_dep: Decimal;
  S_pct: Decimal;
  L_sw: Decimal;
  pre_launch_cost: Decimal;
  // P2-5 信创合规：国产卡（昇腾 910B 等）占比（比率 0–1）
  domestic_gpu_share: Decimal;
  // P2-5 信创合规口径枚举（PRD §⑦）：none / partial / full
  CN_cfg: string;
  // 硬件反选装配标记：跨机组网形态（none/rdma/ethernet），非反选来源为空串。
  // 配合 supporting_mem_gb，前端可在改卡数后按同一口径联动重算配套 CAPEX。
  supporting_fabric: string;
  // 硬件反选装配快照：权重显存需求（GB，即反选时 mem_required_gb），供前端
  // 联动重算存储容量使用；非反选来源为 0。
  supporting_mem_gb: Decimal;
  // 硬件反选装配快照：单机可插卡数（如 5090=5），供前端 BOM/联动推导节点数。
  supporting_cards_per_node: Decimal;
  // 通用/CPU 计算节点数（无 GPU，但需上联到算力/通用网络）；默认 0。
  extra_nodes: number;
  // 硬件反选装配快照：跨机组网端口速率（Gbps，如 100/200/400/800）；0 = 默认 400G。
  supporting_port_speed: number;
  // 硬件反选装配快照：Spine 端口速率（Gbps），供联动重算同源；0 = 与 Leaf 同速率。
  supporting_spine_port_speed: number;
}

export interface PowerParams {
  TDP: Decimal;
  P_aux_power: Decimal;
  P_sys_override: Decimal | null;
  PUE: Decimal;
  E_price: Decimal;
  Co_loc: Decimal;
  Co_net: Decimal;
  Co_stor: Decimal;
  Co_ops: Decimal;
  // P0 覆盖度补齐（对照《大模型 Token 工厂运营策略方案》）：三项原缺失的固定成本科目。
  // 与 Co_ops（运维人力）互不重叠：Co_ops=运维，Co_eng=研发/平台，Co_sales_admin=销管，Co_other=其他。
  // 单位均为「元/年」，按月计入固定成本时除以 12。默认 0 ⇒ 用户按需录入，不改变默认场景口径与历史黄金向量。
  Co_eng: Decimal; // 研发与平台人力成本（元/年）
  Co_sales_admin: Decimal; // 销售与管理费用（元/年）
  Co_other: Decimal; // 其他运营费用（元/年）
  // 分时电价（TOU，峰/平/谷）；默认各档 = E_price、峰谷占比 = 0 ⇒ 退化为现状
  e_price_peak: Decimal;
  e_price_flat: Decimal;
  e_price_valley: Decimal;
  tou_peak_share: Decimal;
  tou_valley_share: Decimal;
  // P2 负载率功耗曲线：待机功耗占额定峰值功耗比例（0–1）；默认 0 ⇒ 退化为线性从零模型。
  // 有效功耗 P_eff(U)=P_sys·(P_idle_ratio + U·(1−P_idle_ratio))：待机为固定成本、可变随 U 增长。
  P_idle_ratio: Decimal;
  // 电力运维口径：柜电分离（separate，默认，Co_loc+电费按功耗）/ 包柜包电（bundle，一口价）
  power_mode: string;
  bundle_monthly_per_rack: Decimal; // 包柜包电单价（元/柜/月，含机柜+电费）
  racks: Decimal; // 机柜数；0 ⇒ 自动推导（ceil(N_gpu / RACK_CARDS_PER_NODE)）
  nodes_per_rack: Decimal; // 每机柜可放节点数（参考）
}

export interface PerfParams {
  M_param: Decimal;
  // C-2 订正：MoE 激活参数（稠密模型缺省 null 回退 M_param）
  active_params_b: Decimal | null;
  quant: string;
  // C-3 订正：投机解码方法
  spec_method: string;
  Mem_w: Decimal;
  Ctx: Decimal;
  B_max: Decimal;
  // E-5 KV cache 显存建模 + B_max 容量约束：kv_cache_per_token_gb 与 vram_total_gb 均 > 0 时，
  // 有效 batch 上限 = min(B_max, floor((vram_total − Mem_w) / (kv_cache_per_token × Ctx)))；
  // 否则回退 B_max（默认，黄金向量零回归）。vram_total_gb 可来自 BenchmarkGpu.vram_gb。
  kv_cache_per_token_gb: Decimal;
  vram_total_gb: Decimal;
  T_eff: Decimal;
  T_pf: Decimal;
  T_dc: Decimal;
  SLA_ttft: Decimal;
  SLA_tpot: Decimal;
  // P1 SLA 赔偿计提：月度 SLA 赔偿拨备占月收入比率（0–1）；默认 0 ⇒ 不计拨备。
  // 直接并入现金流 opex_cash（真金白银的月度风险成本），影响 EBIT/税/NPV/IRR/回本。
  SLA_penalty_rate: Decimal;
  k_override: Decimal | null;
  k_benchmark: Decimal | null;
}

export interface DemandParams {
  rho: Decimal;
  D_eq: Decimal;
  h: Decimal;
  U: Decimal;
  K_peak: Decimal;
  util_mode: string;
  g_demand: Decimal;
  // E-9 AgentX 场景：可选 subagent 拓扑标注（仅用于画像记录，不参与数值推导）。
  subagent_topology: string | null; // "tree" / "linear" / null；AgentX 44% 会话含 subagent
}

export interface PricingParams {
  p_in: Decimal;
  p_out: Decimal;
  p_cache: Decimal | null;
  g_price: Decimal;
  Rent_gpu: Decimal;
  rent_inc: string;
  rent_fixed_monthly: Decimal;
  API_in: Decimal;
  API_out: Decimal;
  API_cache: Decimal | null;
  // C-1 订正：成本侧 vs 收入侧口径分离。市场公允「单位成本标杆」（元/Mtok，对标 InferenceX y_costh）。
  // 与 p_in/p_out（对外售价，收入侧）严格区分；缺省 null ⇒ 不展示市场对标、不触发亏损告警。
  cost_benchmark: Decimal | null;
  // S-3 汇率层：InferenceX 成本侧为 USD/Mtok，本项目本位币 CNY，接入时经此汇率折算（默认 7.2 占位）。
  // 仅用于「市场成本标杆」换算（cost_benchmark），不影响售价与自建设本。
  fx_usd_cny: Decimal;
  // P1 资源包 / 递延收入（合同负债）：预收费→消耗→确认链路。默认关闭/0 ⇒ 退化为按量计费。
  // 报告型字段：不改写核心现金流，仅量化「合同负债初始/每月确认/预收现金/期末未确认/未确认占比/预付费现金跑道」。
  pkg_enabled: boolean; // 是否启用资源包（递延收入）口径
  pkg_prepaid: Decimal; // 预付费总额 / 合同负债初始（元）
  pkg_tokens: Decimal; // 包内含 Token（Mtok）
  pkg_consume_months: Decimal; // 消耗（摊销）周期（月）
}

export interface FinanceParams {
  T_horizon: Decimal;
  r_w: Decimal;
  Tax: Decimal;
  infl: Decimal;
  revenue_ramp: boolean;
  // 融资结构（债务杠杆）；默认 debt_ratio=0 ⇒ 无融资，退化为现状
  debt_ratio: Decimal;
  debt_rate: Decimal;
  loan_term_months: Decimal;
  // P2 单位成本学习曲线：单位可变成本年降幅（比率/年，默认 0 ⇒ 不变）。
  // 财务逐期 opex 可变部分乘 (1−rate)^(t/12)，与 g_demand/g_price 同处 period-loop。
  cost_learning_rate: Decimal;
}

export interface BenchRefs {
  gpu_id: number | null;
  model_id: number | null;
  cloud_id: number | null;
  api_id: number | null;
  bench_version: string | null;
  sources: Record<string, string>;
}

// P2-3 混合部署：权重 w_A(自建)/w_B(租用)/w_C(API)，和=1；enabled 决定是否纳入第四方案。
export interface HybridParams {
  enabled: boolean;
  w_A: Decimal;
  w_B: Decimal;
  w_C: Decimal;
}

export interface DerivedParams {
  CAPEX: Decimal;
  P_sys: Decimal;
  Dep_m: Decimal;
  C_fix_cash: Decimal;
  C_fix_acct: Decimal;
  C_var_per_U: Decimal;
  C_power_idle_m: Decimal; // 月待机功耗固定成本（元/月，P2 负载曲线）
  bundle_rack_cost_m: Decimal; // 包柜包电月成本（元/月；柜电分离=0）
  racks: Decimal; // 机柜数（包柜包电按此计；柜电分离=自动推导参考值）
  power_mode: string; // 电力运维口径（separate/bundle）
  weighted_e_price: Decimal;
  Q_cap_M: Decimal;
  k: Decimal;
  k_source: string;
  factor: Decimal;
  D_out: Decimal;
  D_in: Decimal;
  Q_eq: Decimal;
  U: Decimal;
  U_implied: Decimal;
  I0: Decimal;
  SV: Decimal;
  r_m: Decimal;
  dep_months: Decimal;
}

export interface ScenarioParams {
  hw: HardwareParams;
  power: PowerParams;
  perf: PerfParams;
  demand: DemandParams;
  pricing: PricingParams;
  finance: FinanceParams;
  bench: BenchRefs;
  hybrid: HybridParams;
  conventions: Conventions;
}

export function defaultHardware(): HardwareParams {
  return {
    N_gpu: D(8),
    P_gpu: D(250000),
    P_aux: D(150000),
    T_deploy: D(3),
    availability: D('0.995'),
    Y_dep: D(4),
    S_pct: D('0.10'),
    L_sw: ZERO,
    pre_launch_cost: ZERO,
    domestic_gpu_share: ZERO,
    CN_cfg: 'none',
    supporting_fabric: '',
    supporting_mem_gb: ZERO,
    supporting_cards_per_node: ZERO,
    extra_nodes: 0,
    supporting_port_speed: 0,
    supporting_spine_port_speed: 0,
  };
}

export function defaultPower(): PowerParams {
  return {
    TDP: D(700),
    P_aux_power: D('4.9'),
    P_sys_override: null,
    PUE: D('1.3'),
    E_price: D('0.8'),
    Co_loc: D(5000),
    Co_net: D(2000),
    Co_stor: D(1000),
    Co_ops: D(120000),
    Co_eng: ZERO,
    Co_sales_admin: ZERO,
    Co_other: ZERO,
    e_price_peak: D('0.8'),
    e_price_flat: D('0.8'),
    e_price_valley: D('0.8'),
    tou_peak_share: ZERO,
    tou_valley_share: ZERO,
    P_idle_ratio: ZERO,
    power_mode: POWER_MODE_SEPARATE,
    bundle_monthly_per_rack: ZERO,
    racks: ZERO,
    nodes_per_rack: D(4),
  };
}

export function defaultPerf(): PerfParams {
  return {
    M_param: D(70),
    active_params_b: null,
    quant: 'FP8',
    spec_method: SPEC_METHOD_NONE,
    Mem_w: D(140),
    Ctx: D(8192),
    B_max: D(64),
    kv_cache_per_token_gb: ZERO, // E-5：默认未启用 ⇒ 回退 B_max（黄金向量零回归）
    vram_total_gb: ZERO, // E-5：默认未启用 ⇒ 回退 B_max
    T_eff: D(2500),
    T_pf: D(20000),
    T_dc: D(2000),
    SLA_ttft: D(500),
    SLA_tpot: D(50),
    SLA_penalty_rate: ZERO,
    k_override: null,
    k_benchmark: null,
  };
}

export function defaultDemand(): DemandParams {
  return {
    rho: D(1).div(D(3)),
    D_eq: D(3888),
    h: D('0.20'),
    U: D('0.60'),
    K_peak: ONE,
    util_mode: UTIL_MODE_EXPLICIT,
    g_demand: ZERO,
    subagent_topology: null, // E-9：默认无 subagent 拓扑
  };
}

export function defaultPricing(): PricingParams {
  const p = {
    p_in: D('7.5'),
    p_out: D(30),
    p_cache: null,
    g_price: ZERO,
    Rent_gpu: D(18),
    rent_inc: RENT_INC_POWER,
    rent_fixed_monthly: ZERO,
    API_in: D(18),
    API_out: D(70),
    API_cache: null,
    cost_benchmark: null, // C-1：市场公允成本标杆，缺省不启用
    fx_usd_cny: D('7.2'), // S-3：CNY/USD 汇率占位（运行期可按实时汇率覆盖）
    pkg_enabled: false,
    pkg_prepaid: ZERO,
    pkg_tokens: ZERO,
    pkg_consume_months: ZERO,
  };
  return p;
}

export function defaultFinance(): FinanceParams {
  return {
    T_horizon: D(36),
    r_w: D('0.08'),
    Tax: D('0.25'),
    infl: ZERO,
    revenue_ramp: false,
    debt_ratio: ZERO,
    debt_rate: D('0.05'),
    loan_term_months: D(48),
    cost_learning_rate: ZERO,
  };
}

export function defaultBench(): BenchRefs {
  return {
    gpu_id: null,
    model_id: null,
    cloud_id: null,
    api_id: null,
    bench_version: null,
    sources: {},
  };
}

export function defaultHybrid(): HybridParams {
  return {
    enabled: false,
    w_A: D('0.5'),
    w_B: D('0.3'),
    w_C: D('0.2'),
  };
}

/** 输入侧混合单价（含缓存折扣）。 */
export function pricingCacheEffective(p: PricingParams): Decimal {
  return p.p_cache !== null ? p.p_cache : p.p_in.div(D(10));
}

export function apiCacheEffective(p: PricingParams): Decimal {
  return p.API_cache !== null ? p.API_cache : p.API_in.div(D(10));
}

export function defaultParams(): ScenarioParams {
  return {
    hw: defaultHardware(),
    power: defaultPower(),
    perf: defaultPerf(),
    demand: defaultDemand(),
    pricing: defaultPricing(),
    finance: defaultFinance(),
    bench: defaultBench(),
    hybrid: defaultHybrid(),
    conventions: defaultConventions(),
  };
}

/** k 优先解析：实测/录入 → 吞吐比 T_dc/T_pf → 基准库 → 默认 0.1。 */
export function resolveK(perf: PerfParams): [Decimal, string] {
  if (perf.k_override !== null && perf.k_override.gt(ZERO)) {
    return [perf.k_override, 'measured'];
  }
  if (perf.T_pf && perf.T_pf.gt(ZERO) && perf.T_dc && perf.T_dc.gt(ZERO)) {
    return [perf.T_dc.div(perf.T_pf), 'throughput_ratio'];
  }
  if (perf.k_benchmark !== null && perf.k_benchmark.gt(ZERO)) {
    return [perf.k_benchmark, 'benchmark'];
  }
  return [D('0.1'), 'default'];
}

export function derive(params: ScenarioParams): DerivedParams {
  const { hw, power, perf, demand, finance } = params;

  const capex = hw.N_gpu.times(hw.P_gpu).plus(hw.P_aux);
  const pSys =
    power.P_sys_override !== null
      ? power.P_sys_override
      : hw.N_gpu.times(power.TDP).div(D(1000)).plus(power.P_aux_power);

  const depMonths = hw.Y_dep.times(MONTHS_PER_YEAR);
  const depM = safeDiv(capex.times(ONE.minus(hw.S_pct)), depMonths);
  // 固定现金成本基础项（不含机柜/电力口径项——两模式差异在下方分支处理）
  const cFixCashBase = power.Co_net.plus(power.Co_stor).plus(power.Co_ops.div(MONTHS_PER_YEAR)).plus(hw.L_sw.div(MONTHS_PER_YEAR))
    .plus(power.Co_eng.div(MONTHS_PER_YEAR)).plus(power.Co_sales_admin.div(MONTHS_PER_YEAR)).plus(power.Co_other.div(MONTHS_PER_YEAR));
  let cFixAcct: Decimal;

  // ---- 分时电价（TOU）加权月电价 ----
  // 未启用 TOU（峰谷占比均=0）⇒ 加权价 = 统一电价 E_price（保持现状语义，E_price 敏感性/情景有效）；
  // 启用 TOU（任一段占比>0）⇒ 用峰/平/谷三档按占比加权：w_flat = 1 − w_peak − w_valley。
  const wPeak = power.tou_peak_share;
  const wValley = power.tou_valley_share;
  let weightedEPrice: Decimal;
  if (wPeak.eq(ZERO) && wValley.eq(ZERO)) {
    weightedEPrice = power.E_price;
  } else {
    const wFlat = ONE.minus(wPeak).minus(wValley);
    weightedEPrice = power.e_price_valley
      .times(wValley)
      .plus(power.e_price_flat.times(wFlat))
      .plus(power.e_price_peak.times(wPeak));
  }

  // ---- P2 负载率功耗曲线：P_eff(U) = P_sys·(P_idle_ratio + U·(1−P_idle_ratio)) ----
  // 待机功耗（idle floor）计入固定成本；可变系数退化为「纯可变部分」。
  // 默认 P_idle_ratio=0 ⇒ P_eff(U)=P_sys·U、待机成本=0，与历史线性从零模型逐位一致（黄金向量零回归）。
  const cPowerIdleM = pSys.times(power.PUE).times(weightedEPrice).times(H).times(power.P_idle_ratio);
  let cVarPerU = pSys.times(power.PUE).times(weightedEPrice).times(H).times(ONE.minus(power.P_idle_ratio));

  // ---- 电力运维口径：柜电分离（默认）/ 包柜包电 ----
  // 默认 separate ⇒ 与历史逐位一致（零回归）；bundle 时电费不再按功耗核算：
  // 固定成本 = 基础项 + 包柜包电一口价（机柜+电费），Co_loc 与 idle 电费剔除、可变电费归零。
  const racksN = power.racks.gt(ZERO) ? power.racks : hw.N_gpu.div(RACK_CARDS_PER_NODE).ceil();
  let bundleRackCostM = ZERO;
  let cFixCash: Decimal;
  if (power.power_mode === POWER_MODE_BUNDLE) {
    bundleRackCostM = power.bundle_monthly_per_rack.times(racksN);
    cFixCash = cFixCashBase.plus(bundleRackCostM);
    cVarPerU = ZERO;
  } else {
    cFixCash = cFixCashBase.plus(power.Co_loc).plus(cPowerIdleM);
  }
  cFixAcct = depM.plus(cFixCash);

  const qCapM = perf.T_eff.times(SEC).div(MTOK);
  const [k, kSource] = resolveK(perf);
  const factor = ONE.plus(k.times(demand.rho).times(ONE.minus(demand.h)));

  let utilization = demand.U;
  let dEq = demand.D_eq;
  if (demand.util_mode === UTIL_MODE_DEMAND_FROM_U) {
    dEq = qCapM.times(demand.U);
  } else if (demand.util_mode === UTIL_MODE_U_FROM_DEMAND) {
    let implied = safeDiv(demand.D_eq, qCapM);
    if (implied.gt(ONE)) implied = ONE;
    utilization = implied;
  }

  const dOut = safeDiv(dEq, factor);
  const dIn = demand.rho.times(dOut);
  const uImplied = safeDiv(dEq, qCapM);

  const i0 = capex.plus(hw.pre_launch_cost);
  const sv = capex.times(hw.S_pct);
  const rM = ONE.plus(finance.r_w).ln().div(MONTHS_PER_YEAR).exp().minus(ONE);

  return {
    CAPEX: capex,
    P_sys: pSys,
    Dep_m: depM,
    C_fix_cash: cFixCash,
    C_fix_acct: cFixAcct,
    C_var_per_U: cVarPerU,
    C_power_idle_m: cPowerIdleM,
    bundle_rack_cost_m: bundleRackCostM,
    racks: racksN,
    power_mode: power.power_mode,
    weighted_e_price: weightedEPrice,
    Q_cap_M: qCapM,
    k,
    k_source: kSource,
    factor,
    D_out: dOut,
    D_in: dIn,
    Q_eq: dEq,
    U: utilization,
    U_implied: uImplied,
    I0: i0,
    SV: sv,
    r_m: rM,
    dep_months: depMonths,
  };
}

/** 按 `group.field` 路径覆盖某参数（返回新对象，不可变语义）。 */
export function withOverride(params: ScenarioParams, path: string, value: Numeric): ScenarioParams {
  const [groupName, fieldName] = path.split('.');
  if (!fieldName || !(groupName in params)) {
    throw new Error(`非法参数路径：${path}`);
  }
  const group = (params as unknown as Record<string, unknown>)[groupName] as Record<string, unknown>;
  if (!(fieldName in group)) {
    throw new Error(`参数组 ${groupName} 中不存在字段 ${fieldName}`);
  }
  const current = group[fieldName];
  const newGroup = { ...group };
  // P1-4 加固：显式支持把 Optional 字段清回 null（如清除 k_override 回退自动推导），
  // 避免 current 为 Decimal 时走 D(null) 抛 DecimalError。
  if (value === null) {
    newGroup[fieldName] = null;
  } else if (current instanceof Decimal) {
    newGroup[fieldName] = D(value);
  } else if (typeof current === 'boolean') {
    newGroup[fieldName] = Boolean(value);
  } else if (typeof current === 'number') {
    newGroup[fieldName] = Number(value);
  } else if (typeof current === 'string') {
    newGroup[fieldName] = String(value);
  } else if (current === null) {
    newGroup[fieldName] = value === null ? null : D(value);
  }
  return { ...params, [groupName]: newGroup } as unknown as ScenarioParams;
}

export function getValue(params: ScenarioParams, path: string): Numeric {
  const [groupName, fieldName] = path.split('.');
  const group = (params as unknown as Record<string, unknown>)[groupName] as Record<string, unknown>;
  return group[fieldName] as Numeric;
}

/** 按比例缩放某参数（敏感性 ±Δ% 用）。 */
export function scale(params: ScenarioParams, path: string, factor: Decimal): ScenarioParams {
  const current = getValue(params, path);
  if (current === null) return params;
  return withOverride(params, path, D(current as Numeric).times(factor));
}

// ===========================================================================
// E-9 AgentX 长上下文真实负载画像预设（对齐后端 parameters.py AGENTX_PRESET_*）
// 来源：InferenceX v1.0 数据集（393 会话）：输入中位 142k、输出中位 444、
// 缓存命中 95–98%、输入:输出 ≈ 200:1、44% 会话含 subagent。
// 供前端「场景预设」一键填入，也供 agentxParams() 复用。
// ===========================================================================
export const AGENTX_PRESET_RHO = D(200); // 输入:输出比（rho = D_in/D_out）
export const AGENTX_PRESET_H = D('0.96'); // 缓存命中率（高命中摊薄 prefill 成本）
export const AGENTX_PRESET_CTX = D(128000); // 上下文长度（token，中位 142k 量级）
export const SHORT_CTX_PRESET_CTX = D(8192); // 短链（8K/1K）场景参考

/** E-9：返回 AgentX 长上下文场景预设（在默认模板基础上覆盖需求/性能画像）。
 *  纯函数、零 IO；与 defaultParams() 互不污染（不可变语义）。 */
export function agentxParams(): ScenarioParams {
  const base = defaultParams();
  return {
    ...base,
    demand: { ...base.demand, rho: AGENTX_PRESET_RHO, h: AGENTX_PRESET_H },
    perf: { ...base.perf, Ctx: AGENTX_PRESET_CTX },
  };
}
