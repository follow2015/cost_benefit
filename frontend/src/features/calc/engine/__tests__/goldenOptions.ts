/**
 * 黄金向量选项组装（前后端双端一致性的单一事实来源，前端侧）。
 *
 * 与后端 `src/ai_roi/domain/calc/__tests__/test_consistency.py` 的 `_options()`
 * 逐字段对齐。历史上 verify-consistency.mjs 内联生成过一份只传 5 个选项的
 * 残缺 harness，导致 GV14（联合敏感性）/GV15（自定义情景）恒为 null 的误报；
 * 现由本模块统一供给 consistency.test.ts 与 harness.ts，杜绝双份漂移。
 */

import { Decimal } from '../decimalConfig';
import { EngineOptions } from '../engine';
import golden from '../goldenVectors.json';

export interface GoldenCase {
  id: string;
  name: string;
  params: Record<string, unknown>;
  options: {
    include_sensitivity: boolean;
    include_scenarios: boolean;
    include_crossover: boolean;
    sensitivity_target: string;
    sensitivity_delta: string;
    include_joint?: boolean;
    joint_target?: string;
    joint_delta?: string;
    joint_vars?: string[] | null;
    include_custom_scenarios?: boolean;
    custom_scenario_specs?: Array<{ key: string; label: string; overrides: Record<string, string> }> | null;
  };
  expect: Record<string, unknown>;
}

export const GOLDEN_CASES = golden.cases as GoldenCase[];
export const GOLDEN_TOLERANCE = new Decimal((golden as { tolerance?: string }).tolerance || '0.001');

/** 把黄金向量 JSON 中的 options 组装为 EngineOptions（缺失字段回落默认，与后端同口径）。 */
export function optionsFromCase(opts: GoldenCase['options']): EngineOptions {
  return {
    include_sensitivity: opts.include_sensitivity,
    include_scenarios: opts.include_scenarios,
    include_crossover: opts.include_crossover,
    sensitivity_target: opts.sensitivity_target,
    sensitivity_delta: new Decimal(opts.sensitivity_delta || '0.2'),
    include_joint: opts.include_joint ?? false,
    joint_target: opts.joint_target ?? 'npv',
    joint_delta: new Decimal(opts.joint_delta || '0.2'),
    joint_vars: opts.joint_vars ?? null,
    include_custom_scenarios: opts.include_custom_scenarios ?? false,
    custom_scenario_specs: opts.custom_scenario_specs
      ? opts.custom_scenario_specs.map((s) => ({
          key: s.key,
          label: s.label,
          overrides: Object.fromEntries(Object.entries(s.overrides).map(([k, v]) => [k, new Decimal(v)])),
        }))
      : null,
  };
}
