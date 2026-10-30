/**
 * C-3/C-2 镜像单测：量化枚举（FP4/MXFP4/NVFP4）+ 投机解码倍率 + MoE 激活参数。
 * 与后端 `app/calc/__tests__/test_throughput.py` 口径一致，保证双端吞吐推导零漂移。
 */

import { describe, it, expect } from 'vitest';
import { D, Decimal } from '../decimalConfig';
import { defaultParams } from '../parameters';
import { modelEfficiency, deriveThroughputCalc } from '../throughput';

function withPerf(overrides: Record<string, unknown>) {
  const params = defaultParams();
  const perf = { ...params.perf, ...overrides };
  return { ...params, perf };
}

describe('C-3 量化枚举 + 投机解码倍率', () => {
  it('FP4/MXFP4 高于 FP8', () => {
    const fp8 = modelEfficiency(D(70), 'FP8');
    const fp4 = modelEfficiency(D(70), 'FP4');
    const mxfp4 = modelEfficiency(D(70), 'MXFP4');
    const nvfp4 = modelEfficiency(D(70), 'NVFP4');
    expect(fp4.gt(fp8)).toBe(true);
    expect(mxfp4.gt(fp4)).toBe(true);
    expect(nvfp4.toString()).toBe(mxfp4.toString());
    // 未知量化回退 FP8
    expect(modelEfficiency(D(70), 'UNKNOWN').toString()).toBe(fp8.toString());
  });

  it('投机解码按接受长度倍率提升', () => {
    const none = modelEfficiency(D(70), 'FP8', 'none');
    const mtp = modelEfficiency(D(70), 'FP8', 'MTP');
    const stp = modelEfficiency(D(70), 'FP8', 'STP');
    const eagle = modelEfficiency(D(70), 'FP8', 'EAGLE');
    expect(mtp.toString()).toBe(none.times(D('1.3')).toString());
    expect(stp.toString()).toBe(none.times(D('1.5')).toString());
    expect(eagle.toString()).toBe(none.times(D('1.8')).toString());
    expect(modelEfficiency(D(70), 'FP4', 'EAGLE').toString()).toBe(
      modelEfficiency(D(70), 'FP4').times(D('1.8')).toString(),
    );
  });
});

describe('C-2 MoE 激活参数', () => {
  it('active_params_b 缺失回退 M_param（稠密语义）', () => {
    const dense = defaultParams().perf;
    expect(dense.active_params_b).toBeNull();
  });

  it('MoE 激活参数（49B）< 总参数（1.6T）→ 有效吞吐高于稠密 70B', () => {
    const dense = withPerf({ M_param: D(70), active_params_b: null, SLA_ttft: D(1000), SLA_tpot: D(100) });
    const moe = withPerf({ M_param: D(1600), active_params_b: D(49), SLA_ttft: D(1000), SLA_tpot: D(100) });
    const rDense = deriveThroughputCalc(dense as any);
    const rMoe = deriveThroughputCalc(moe as any);
    expect(rMoe.T_eff_suggestion.gt(rDense.T_eff_suggestion)).toBe(true);
  });
});
