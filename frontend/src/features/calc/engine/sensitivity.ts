/** 单因素敏感性分析 · 龙卷风图。对齐后端 `app/calc/sensitivity.py`。 */

import { D, ONE, ZERO, Decimal, dsum, safeDiv } from './decimalConfig';
import { ScenarioParams, scale } from './parameters';

export const TARGET_NPV = 'npv';
export const TARGET_COST_PER_M = 'cost_per_m';
export const TARGET_COST_ADVANTAGE = 'cost_advantage';

export const TARGET_LABELS: Record<string, string> = {
  [TARGET_NPV]: 'NPV（元）',
  [TARGET_COST_PER_M]: '每百万 token 成本（元/Mtok）',
  [TARGET_COST_ADVANTAGE]: '自建相对最优替代方案的月成本优势（元/月）',
};

export interface SensitivityVar {
  key: string;
  label: string;
  paths: string[];
  note?: string;
}

export const DEFAULT_VARS: SensitivityVar[] = [
  { key: 'U', label: '有效利用率 U', paths: ['demand.U', 'demand.D_eq'], note: '利用率与月需求量同比例变动，保持「负载—收入」口径一致。' },
  { key: 'E_price', label: '电价 E_price', paths: ['power.E_price'] },
  { key: 'Rent_gpu', label: '云租赁单价 Rent_gpu', paths: ['pricing.Rent_gpu'] },
  { key: 'API_out', label: '第三方 API 输出价', paths: ['pricing.API_out'] },
  { key: 'CAPEX', label: '整机 CAPEX', paths: ['hw.P_gpu', 'hw.P_aux'], note: 'GPU 采购价与配套价同比例变动。' },
  { key: 'T_eff', label: '有效吞吐 T_eff', paths: ['perf.T_eff'] },
  { key: 'r_w', label: '折现率 WACC', paths: ['finance.r_w'] },
  { key: 'p_out', label: '输出 token 单价 p_out', paths: ['pricing.p_out'] },
  // ---- §4.1 补全：P0/P1/P2 新增成本科目纳入可观测性（追加至末尾，不挪动既有 0–7 序）----
  { key: 'Co_eng', label: '研发人力 Co_eng', paths: ['power.Co_eng'] },
  { key: 'Co_sales_admin', label: '销管费用 Co_sales_admin', paths: ['power.Co_sales_admin'] },
  { key: 'Co_other', label: '其他费用 Co_other', paths: ['power.Co_other'] },
  { key: 'SLA_penalty_rate', label: 'SLA 计提率', paths: ['perf.SLA_penalty_rate'] },
  { key: 'cost_learning_rate', label: '学习曲线年降幅', paths: ['finance.cost_learning_rate'] },
];

export interface SensitivityItem {
  param: string;
  label: string;
  base: Decimal;
  low: Decimal | null;
  high: Decimal | null;
  delta_low: Decimal | null;
  delta_high: Decimal | null;
  swing: Decimal;
  swing_pct: Decimal;
  low_feasible: boolean;
  high_feasible: boolean;
  note: string;
}

export interface SensitivityResult {
  target: string;
  target_label: string;
  delta: Decimal;
  base: Decimal;
  items: SensitivityItem[];
  notes: string[];
}

export type Evaluator = (params: ScenarioParams, target: string) => Decimal | null;

function scaled(params: ScenarioParams, variable: SensitivityVar, factor: Decimal): ScenarioParams {
  let result = params;
  for (const path of variable.paths) {
    result = scale(result, path, factor);
  }
  return result;
}

export function compute(
  params: ScenarioParams,
  evaluator: Evaluator,
  target: string = TARGET_NPV,
  delta: Decimal = D('0.2'),
  variables: SensitivityVar[] = DEFAULT_VARS,
): SensitivityResult {
  const baseValue = evaluator(params, target);
  if (baseValue === null) {
    return {
      target,
      target_label: TARGET_LABELS[target] ?? target,
      delta,
      base: ZERO,
      items: [],
      notes: ['基准情形不可行，无法开展敏感性分析。'],
    };
  }

  const items: SensitivityItem[] = [];
  for (const variable of variables) {
    const lowValue = evaluator(scaled(params, variable, ONE.minus(delta)), target);
    const highValue = evaluator(scaled(params, variable, ONE.plus(delta)), target);

    let swing: Decimal;
    if (lowValue === null && highValue === null) swing = ZERO;
    else if (lowValue === null) swing = highValue!.minus(baseValue).abs();
    else if (highValue === null) swing = lowValue.minus(baseValue).abs();
    else swing = highValue.minus(lowValue).abs();

    const notes: string[] = [];
    if (variable.note) notes.push(variable.note);
    if (lowValue === null) notes.push(`${variable.label} −${delta.times(D(100)).toString()}% 时方案不可行，已截断。`);
    if (highValue === null) notes.push(`${variable.label} +${delta.times(D(100)).toString()}% 时方案不可行，已截断。`);

    items.push({
      param: variable.key,
      label: variable.label,
      base: baseValue,
      low: lowValue,
      high: highValue,
      delta_low: lowValue === null ? null : lowValue.minus(baseValue),
      delta_high: highValue === null ? null : highValue.minus(baseValue),
      swing,
      swing_pct: safeDiv(swing, baseValue.abs()),
      low_feasible: lowValue !== null,
      high_feasible: highValue !== null,
      note: notes.join('；'),
    });
  }

  items.sort((a, b) => b.swing.minus(a.swing).cmp(ZERO));
  return {
    target,
    target_label: TARGET_LABELS[target] ?? target,
    delta,
    base: baseValue,
    items,
    notes: [],
  };
}

export function varRegistry(): Record<string, SensitivityVar> {
  const map: Record<string, SensitivityVar> = {};
  for (const v of DEFAULT_VARS) map[v.key] = v;
  return map;
}

// ===========================================================================
// 多因素联合敏感性（确定性，非随机）—— 与蒙特卡洛严格区分（设计 §2.3 §3）。
// 全因子网格 2^N → NPV 联合 min/max/分位数 + 一阶主效应 S_i + 二阶交互 I_ij。
// ===========================================================================
//: 联合敏感性默认变量集（顺序固定，后端一致）：U + E_price（GV14 用两变量）。
export const JOINT_DEFAULT_VARS: SensitivityVar[] = [
  { key: 'U', label: '有效利用率 U', paths: ['demand.U', 'demand.D_eq'], note: '利用率与月需求量同比例变动，保持「负载—收入」口径一致。' },
  { key: 'E_price', label: '电价 E_price', paths: ['power.E_price'] },
  { key: 'Rent_gpu', label: '云租赁单价 Rent_gpu', paths: ['pricing.Rent_gpu'] },
  { key: 'API_out', label: '第三方 API 输出价', paths: ['pricing.API_out'] },
  { key: 'CAPEX', label: '整机 CAPEX', paths: ['hw.P_gpu', 'hw.P_aux'], note: 'GPU 采购价与配套价同比例变动。' },
  { key: 'T_eff', label: '有效吞吐 T_eff', paths: ['perf.T_eff'] },
  { key: 'r_w', label: '折现率 WACC', paths: ['finance.r_w'] },
  { key: 'p_out', label: '输出 token 单价 p_out', paths: ['pricing.p_out'] },
];

export interface JointSensitivityResult {
  npv_min: Decimal;
  npv_max: Decimal;
  percentiles: Record<string, Decimal>;
  main_effects: Record<string, Decimal>;
  interactions: Record<string, Decimal>;
  notes: string[];
}

function percentile(sortedVals: Decimal[], q: Decimal): Decimal {
  const n = sortedVals.length;
  if (n === 0) return ZERO;
  if (n === 1) return sortedVals[0];
  const rank = q.times(new Decimal(n - 1));
  const lo = rank.floor().toNumber();
  const hi = Math.min(lo + 1, n - 1);
  if (lo === hi) return sortedVals[lo];
  const frac = rank.minus(new Decimal(lo));
  return sortedVals[lo].plus(sortedVals[hi].minus(sortedVals[lo]).times(frac));
}

export function computeJoint(
  params: ScenarioParams,
  evaluator: Evaluator,
  target: string = TARGET_NPV,
  delta: Decimal = D('0.2'),
  variables: SensitivityVar[] = JOINT_DEFAULT_VARS.slice(0, 2),
): JointSensitivityResult {
  const varList = variables.length ? variables : JOINT_DEFAULT_VARS.slice(0, 2);
  const n = varList.length;

  // 全因子网格 2^N：每位 0=low(−Δ)、1=high(+Δ)
  const npvGrid: Decimal[] = [];
  const gridParams: ScenarioParams[] = [];
  for (let mask = 0; mask < 1 << n; mask++) {
    let scaledParams = params;
    for (let i = 0; i < n; i++) {
      const factor = (mask >> i) & 1 ? ONE.plus(delta) : ONE.minus(delta);
      scaledParams = scaled(scaledParams, varList[i], factor);
    }
    gridParams.push(scaledParams);
    const value = evaluator(scaledParams, target);
    if (value !== null) npvGrid.push(value);
  }

  const notes: string[] = [];
  if (npvGrid.length === 0) {
    notes.push('联合敏感性所有网格点均不可行，无法给出边界。');
    const emptyEffects: Record<string, Decimal> = {};
    for (const v of varList) emptyEffects[v.key] = ZERO;
    return {
      npv_min: ZERO,
      npv_max: ZERO,
      percentiles: { p5: ZERO, p50: ZERO, p95: ZERO },
      main_effects: emptyEffects,
      interactions: {},
      notes,
    };
  }

  const npvSorted = [...npvGrid].sort((a, b) => a.minus(b).cmp(ZERO));
  const npvMin = npvSorted[0];
  const npvMax = npvSorted[npvSorted.length - 1];
  const percentiles = {
    p5: percentile(npvSorted, D('0.05')),
    p50: percentile(npvSorted, D('0.5')),
    p95: percentile(npvSorted, D('0.95')),
  };

  // 主效应 S_i = |E[NPV | x_i=high] − E[NPV | x_i=low]|（对其余 N−1 变量全网格平均）
  const mainEffects: Record<string, Decimal> = {};
  for (let i = 0; i < n; i++) {
    const highVals: Decimal[] = [];
    const lowVals: Decimal[] = [];
    for (let mask = 0; mask < 1 << n; mask++) {
      const v = evaluator(gridParams[mask], target);
      if (v === null) continue;
      if ((mask >> i) & 1) highVals.push(v);
      else lowVals.push(v);
    }
    if (highVals.length > 0 && lowVals.length > 0) {
      const meanHigh = dsum(highVals).div(new Decimal(highVals.length));
      const meanLow = dsum(lowVals).div(new Decimal(lowVals.length));
      mainEffects[varList[i].key] = meanHigh.minus(meanLow).abs();
    } else {
      mainEffects[varList[i].key] = ZERO;
    }
  }

  // 交互效应 I_ij = NPV(hi,hi) − NPV(hi,lo) − NPV(lo,hi) + NPV(lo,lo)（二阶混合差分）
  const interactions: Record<string, Decimal> = {};
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const key = `${varList[i].key}${varList[j].key}`;
      const corner = (aHigh: boolean, bHigh: boolean): Decimal | null => {
        let mask = 0;
        if (aHigh) mask |= 1 << i;
        if (bHigh) mask |= 1 << j;
        return evaluator(gridParams[mask], target);
      };
      const hiHi = corner(true, true);
      const hiLo = corner(true, false);
      const loHi = corner(false, true);
      const loLo = corner(false, false);
      if (hiHi !== null && hiLo !== null && loHi !== null && loLo !== null) {
        interactions[key] = hiHi.minus(hiLo).minus(loHi).plus(loLo);
      } else {
        interactions[key] = ZERO;
      }
    }
  }

  return {
    npv_min: npvMin,
    npv_max: npvMax,
    percentiles,
    main_effects: mainEffects,
    interactions,
    notes,
  };
}
