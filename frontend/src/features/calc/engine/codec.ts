/**
 * 参数编解码：ScenarioParams 对象 ⇄ JSON dict（Decimal 转字符串）。
 * 对齐后端 `app/calc/codec.py`，是前后端字段单一事实来源。
 */

import { D, Decimal, decStr } from './decimalConfig';
import { Conventions, defaultConventions } from './context';
import {
  BenchRefs,
  DerivedParams,
  FinanceParams,
  HardwareParams,
  HybridParams,
  PerfParams,
  PowerParams,
  PricingParams,
  DemandParams,
  ScenarioParams,
  defaultBench,
  defaultDemand,
  defaultFinance,
  defaultHardware,
  defaultHybrid,
  defaultPerf,
  defaultPower,
  defaultPricing,
} from './parameters';

const GROUPS = ['hw', 'power', 'perf', 'demand', 'pricing', 'finance', 'bench', 'hybrid'] as const;
type GroupName = (typeof GROUPS)[number];

const DECIMAL_GROUPS: Record<GroupName, string[]> = {
  hw: ['N_gpu', 'P_gpu', 'P_aux', 'T_deploy', 'availability', 'Y_dep', 'S_pct', 'L_sw', 'pre_launch_cost', 'domestic_gpu_share', 'supporting_mem_gb', 'supporting_cards_per_node', 'extra_nodes', 'supporting_port_speed', 'supporting_spine_port_speed'],
  power: ['TDP', 'P_aux_power', 'PUE', 'E_price', 'Co_loc', 'Co_net', 'Co_stor', 'Co_ops', 'Co_eng', 'Co_sales_admin', 'Co_other', 'e_price_peak', 'e_price_flat', 'e_price_valley', 'tou_peak_share', 'tou_valley_share', 'P_idle_ratio', 'bundle_monthly_per_rack', 'racks', 'nodes_per_rack'],
  perf: ['M_param', 'Mem_w', 'Ctx', 'B_max', 'T_eff', 'T_pf', 'T_dc', 'SLA_ttft', 'SLA_tpot', 'SLA_penalty_rate', 'kv_cache_per_token_gb', 'vram_total_gb'],
  demand: ['rho', 'D_eq', 'h', 'U', 'K_peak', 'g_demand'],
  pricing: ['p_in', 'p_out', 'g_price', 'Rent_gpu', 'rent_fixed_monthly', 'API_in', 'API_out', 'pkg_prepaid', 'pkg_tokens', 'pkg_consume_months', 'fx_usd_cny'],
  finance: ['T_horizon', 'r_w', 'Tax', 'infl', 'debt_ratio', 'debt_rate', 'loan_term_months', 'cost_learning_rate'],
  bench: [],
  hybrid: ['w_A', 'w_B', 'w_C'],
};

const STRING_GROUPS: Record<GroupName, string[]> = {
  hw: ['CN_cfg', 'supporting_fabric'],
  power: ['power_mode'],
  perf: ['quant', 'spec_method'],
  demand: ['util_mode', 'subagent_topology'],
  pricing: ['rent_inc', 'pkg_enabled'],
  finance: [],
  bench: ['bench_version'],
  hybrid: [],
};

const NULLABLE_DECIMAL: Record<GroupName, string[]> = {
  hw: [],
  power: ['P_sys_override'],
  perf: ['k_override', 'k_benchmark', 'active_params_b'],
  demand: [],
  pricing: ['p_cache', 'API_cache', 'cost_benchmark'],
  finance: [],
  bench: [],
  hybrid: [],
};

const BOOL_GROUPS: Record<GroupName, string[]> = {
  hw: [],
  power: [],
  perf: [],
  demand: [],
  pricing: [],
  finance: ['revenue_ramp'],
  bench: [],
  hybrid: ['enabled'],
};

const INT_GROUPS: Record<GroupName, string[]> = {
  hw: [],
  power: [],
  perf: [],
  demand: [],
  pricing: [],
  finance: [],
  bench: ['gpu_id', 'model_id', 'cloud_id', 'api_id'],
  hybrid: [],
};

/** 字符串字典字段（Record<string, string>）：bench.sources 参数来源标记。 */
const DICT_GROUPS: Record<GroupName, string[]> = {
  hw: [],
  power: [],
  perf: [],
  demand: [],
  pricing: [],
  finance: [],
  bench: ['sources'],
  hybrid: [],
};

/** 每组默认模板值（对齐后端 dataclass 默认，缺省字段回落）。 */
const DEFAULT_GROUP: Record<GroupName, () => Record<string, unknown>> = {
  hw: () => defaultHardware() as unknown as Record<string, unknown>,
  power: () => defaultPower() as unknown as Record<string, unknown>,
  perf: () => defaultPerf() as unknown as Record<string, unknown>,
  demand: () => defaultDemand() as unknown as Record<string, unknown>,
  pricing: () => defaultPricing() as unknown as Record<string, unknown>,
  finance: () => defaultFinance() as unknown as Record<string, unknown>,
  bench: () => defaultBench() as unknown as Record<string, unknown>,
  hybrid: () => defaultHybrid() as unknown as Record<string, unknown>,
};

function buildGroup(groupName: GroupName, data: Record<string, unknown> | null): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const defaults = DEFAULT_GROUP[groupName]();
  const decs = DECIMAL_GROUPS[groupName];
  for (const field of decs) {
    const raw = data?.[field];
    out[field] = raw === undefined || raw === null ? defaults[field] : D(raw as string);
  }
  const strs = STRING_GROUPS[groupName];
  for (const field of strs) {
    out[field] = data?.[field] ?? defaults[field];
  }
  const bools = BOOL_GROUPS[groupName];
  for (const field of bools) {
    out[field] = data?.[field] !== undefined ? Boolean(data?.[field]) : defaults[field];
  }
  const ints = INT_GROUPS[groupName];
  for (const field of ints) {
    const raw = data?.[field];
    out[field] = raw === undefined || raw === null ? defaults[field] : Number(raw);
  }
  const nulls = NULLABLE_DECIMAL[groupName];
  for (const field of nulls) {
    const raw = data?.[field];
    out[field] = raw === undefined || raw === null || raw === '' ? null : D(raw as string);
  }
  const dicts = DICT_GROUPS[groupName];
  for (const field of dicts) {
    const raw = data?.[field];
    out[field] =
      raw !== undefined && raw !== null && typeof raw === 'object' && !Array.isArray(raw)
        ? { ...(raw as Record<string, string>) }
        : { ...((defaults[field] as Record<string, string>) ?? {}) };
  }
  return out;
}

/** 从 JSON dict 构造参数对象（缺省字段回落到默认值）。 */
export function paramsFromDict(data: Record<string, unknown> | null | undefined): ScenarioParams {
  const payload = data ?? {};
  return {
    hw: buildGroup('hw', payload.hw as Record<string, unknown>) as unknown as HardwareParams,
    power: buildGroup('power', payload.power as Record<string, unknown>) as unknown as PowerParams,
    perf: buildGroup('perf', payload.perf as Record<string, unknown>) as unknown as PerfParams,
    demand: buildGroup('demand', payload.demand as Record<string, unknown>) as unknown as DemandParams,
    pricing: buildGroup('pricing', payload.pricing as Record<string, unknown>) as unknown as PricingParams,
    finance: buildGroup('finance', payload.finance as Record<string, unknown>) as unknown as FinanceParams,
    bench: buildGroup('bench', payload.bench as Record<string, unknown>) as unknown as BenchRefs,
    hybrid: buildGroup('hybrid', payload.hybrid as Record<string, unknown>) as unknown as HybridParams,
    conventions: conventionsFromDict((payload.conventions as Record<string, unknown>) ?? null),
  };
}

export function conventionsFromDict(data: Record<string, unknown> | null): Conventions {
  if (!data) return defaultConventions();
  return {
    currency: String(data.currency ?? 'CNY'),
    taxed: Boolean(data.taxed ?? false),
    utilization_def: String(data.utilization_def ?? 'effective_load_over_capacity'),
    fx: data.fx === undefined || data.fx === null ? D(1) : D(data.fx as string),
  };
}

/** 参数对象导出为 dict（Decimal 转字符串，供 worker postMessage / 快照冻结）。
 *  注意：必须是深一层的值转换（Decimal→字符串），不能只做浅拷贝——
 *  浅拷贝会让 Decimal 实例原样进入 dict，而 postMessage 用结构化克隆算法，
 *  class 实例不可克隆，会抛 DataCloneError 导致 worker 调用 Promise reject、UI 永久转圈。 */
export function paramsToDict(params: ScenarioParams): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const group of GROUPS) {
    const src = (params as unknown as Record<string, Record<string, unknown>>)[group];
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(src)) {
      const v = src[key];
      out[key] = v instanceof Decimal ? decStr(v) : v;
    }
    result[group] = out;
  }
  const convSrc = params.conventions as unknown as Record<string, unknown>;
  const conv: Record<string, unknown> = {};
  for (const key of Object.keys(convSrc)) {
    const v = convSrc[key];
    conv[key] = v instanceof Decimal ? decStr(v) : v;
  }
  result.conventions = conv;
  return result;
}
