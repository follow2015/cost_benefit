/** 情景分析：保守 / 基准 / 乐观。对齐后端 `app/calc/scenario.py`。 */

import { D, Decimal } from './decimalConfig';
import { ScenarioParams, scale, withOverride } from './parameters';

export const SCENARIO_CONSERVATIVE = 'conservative';
export const SCENARIO_BASE = 'base';
export const SCENARIO_OPTIMISTIC = 'optimistic';

export const SCENARIO_LABELS: Record<string, string> = {
  [SCENARIO_CONSERVATIVE]: '保守',
  [SCENARIO_BASE]: '基准',
  [SCENARIO_OPTIMISTIC]: '乐观',
};

export const SCENARIO_MULTIPLIERS: Record<string, Record<string, Decimal>> = {
  [SCENARIO_CONSERVATIVE]: {
    'demand.U': D('0.8'),
    'demand.D_eq': D('0.8'),
    'power.E_price': D('1.15'),
    'hw.P_gpu': D('1.1'),
    'hw.P_aux': D('1.1'),
    'perf.T_eff': D('0.85'),
    'pricing.p_out': D('0.9'),
    'pricing.p_in': D('0.9'),
    'pricing.Rent_gpu': D('1.1'),
    'finance.r_w': D('1.25'),
  },
  [SCENARIO_BASE]: {},
  [SCENARIO_OPTIMISTIC]: {
    'demand.U': D('1.15'),
    'demand.D_eq': D('1.15'),
    'power.E_price': D('0.9'),
    'hw.P_gpu': D('0.92'),
    'hw.P_aux': D('0.92'),
    'perf.T_eff': D('1.15'),
    'pricing.p_out': D('1.1'),
    'pricing.p_in': D('1.1'),
    'pricing.Rent_gpu': D('0.92'),
    'finance.r_w': D('0.85'),
  },
};

export interface ScenarioCase {
  key: string;
  label: string;
  multipliers: Record<string, Decimal>;
  kpis: Record<string, Decimal | null>;
  feasible: boolean;
  note: string;
}

export interface ScenarioSetResult {
  cases: ScenarioCase[];
  notes: string[];
}

export type KpiEvaluator = (params: ScenarioParams) => Record<string, Decimal | null>;

function applyMultipliers(params: ScenarioParams, multipliers: Record<string, Decimal>): ScenarioParams {
  let result = params;
  for (const [path, factor] of Object.entries(multipliers)) {
    result = scale(result, path, factor);
  }
  return result;
}

export function compute(params: ScenarioParams, evaluator: KpiEvaluator): ScenarioSetResult {
  const cases: ScenarioCase[] = [];
  for (const key of [SCENARIO_CONSERVATIVE, SCENARIO_BASE, SCENARIO_OPTIMISTIC]) {
    const multipliers = SCENARIO_MULTIPLIERS[key];
    const caseParams = applyMultipliers(params, multipliers);
    const kpis = evaluator(caseParams);
    const feasible = kpis.npv !== null && kpis.npv !== undefined;
    cases.push({
      key,
      label: SCENARIO_LABELS[key],
      multipliers,
      kpis,
      feasible,
      note: feasible ? '' : '该情景下方案不可行（无盈亏平衡点或产能不足）。',
    });
  }
  return { cases, notes: [] };
}

// ===========================================================================
// 自定义情景（突破保守/基准/乐观三档）—— 复用 `evaluateKpis` 并列任意 K 组。
// 设计 §2.3 §3：每组 = 一组参数覆盖（overrides），结果与现有 `scenarios` 同结构但 K 任意。
// ===========================================================================
export interface CustomScenarioSpec {
  key: string;
  label: string;
  overrides: Record<string, Decimal>; // 参数路径 → 覆盖值
}

export interface CustomScenario {
  key: string;
  label: string;
  overrides: Record<string, Decimal>;
  kpis: Record<string, Decimal | null>;
  feasible: boolean;
  note: string;
}

export interface CustomScenarioSet {
  cases: CustomScenario[];
  notes: string[];
}

function applyOverrides(params: ScenarioParams, overrides: Record<string, Decimal>): ScenarioParams {
  let result = params;
  for (const [path, value] of Object.entries(overrides)) {
    result = withOverride(result, path, value);
  }
  return result;
}

export function computeCustom(
  params: ScenarioParams,
  specs: CustomScenarioSpec[],
  evaluator: KpiEvaluator,
): CustomScenarioSet {
  const cases: CustomScenario[] = specs.map((spec) => {
    const caseParams = applyOverrides(params, spec.overrides);
    const kpis = evaluator(caseParams);
    const feasible = kpis.npv !== null && kpis.npv !== undefined;
    return {
      key: spec.key,
      label: spec.label,
      overrides: { ...spec.overrides },
      kpis,
      feasible,
      note: feasible ? '' : '该情景下方案不可行（无盈亏平衡点或产能不足）。',
    };
  });
  return { cases, notes: [] };
}
