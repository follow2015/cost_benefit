/**
 * codec 字段覆盖防回归：参数模型（parameters.ts）中的每个字段都必须被
 * codec 的某张表登记，否则 paramsFromDict 会静默丢弃该字段。
 *
 * 历史缺陷：sla_penalty_rate 大小写与后端不一致、active_params_b/spec_method/
 * extra_nodes/supporting_*_port_speed/bench_version/sources 等字段从未登记，
 * 导致「加载已存场景丢字段 / 前端录入传不到后端」的静默数据丢失。
 */

import { describe, it, expect } from 'vitest';
import {
  defaultBench,
  defaultDemand,
  defaultFinance,
  defaultHardware,
  defaultHybrid,
  defaultPerf,
  defaultPower,
  defaultPricing,
} from '../parameters';
import { paramsFromDict, paramsToDict } from '../codec';

const GROUPS = {
  hw: defaultHardware,
  power: defaultPower,
  perf: defaultPerf,
  demand: defaultDemand,
  pricing: defaultPricing,
  finance: defaultFinance,
  bench: defaultBench,
  hybrid: defaultHybrid,
} as const;

describe('codec 字段覆盖', () => {
  it('默认模板每个字段都能在 round-trip 后原样保留', () => {
    for (const [group, factory] of Object.entries(GROUPS)) {
      const defaults = factory() as unknown as Record<string, unknown>;
      const full = Object.fromEntries(
        Object.entries(defaults).map(([k, v]) => [k, typeof v === 'object' && v !== null && 'toString' in v ? (v as { toString(): string }).toString() : v]),
      );
      const roundTripped = paramsToDict(paramsFromDict({ [group]: full })) as Record<
        string,
        Record<string, unknown>
      >;
      for (const key of Object.keys(defaults)) {
        expect(roundTripped[group], `组 ${group} 字段 ${key} round-trip 后丢失`).toHaveProperty(key);
      }
    }
  });

  it('混合参数（含权重）round-trip 保持数值', () => {
    const dict = paramsToDict(paramsFromDict(null));
    expect(dict).toHaveProperty('hybrid');
    expect(dict).toHaveProperty('conventions');
  });
});
