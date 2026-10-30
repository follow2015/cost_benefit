/**
 * P2 前端镜像逻辑回归测试：
 * - P2-1 吞吐：SLA 严格 → batch 上限 / T_eff 建议值下降（方向正确）。
 * - P2-4 蒙特卡洛：分布方差=0 → 均值≈确定性 NPV（容差 1%）；明显盈利 P(NPV>0)=1、明显亏损=0。
 * 仅验证前端引擎镜像，不触碰主成本链口径。
 */

import { describe, it, expect } from 'vitest';
import { Decimal } from '../decimalConfig';
import { defaultParams, withOverride, ScenarioParams } from '../parameters';
import { availableBatchLimit, deriveThroughputCalc } from '../throughput';
import { montecarloCompute } from '../montecarlo';

const ZERO = new Decimal(0);

describe('P2-1 吞吐：SLA 越严格 batch/T_eff 越小', () => {
  it('宽松 SLA(1000/100) 不收紧，batch=B_max', () => {
    expect(availableBatchLimit(new Decimal(64), new Decimal(1000), new Decimal(100)).toString()).toBe('64');
  });

  it('严格 SLA(500/50) 收紧到 B_max/2', () => {
    expect(availableBatchLimit(new Decimal(64), new Decimal(500), new Decimal(50)).toString()).toBe('32');
  });

  it('derive: 严格 SLA 得到更小 batch 与更小 T_eff 建议', () => {
    const base = defaultParams();
    const relaxed = withOverride(withOverride(base, 'perf.SLA_ttft', new Decimal(1000)), 'perf.SLA_tpot', new Decimal(100)) as ScenarioParams;
    const strict = withOverride(withOverride(base, 'perf.SLA_ttft', new Decimal(250)), 'perf.SLA_tpot', new Decimal(25)) as ScenarioParams;
    const rR = deriveThroughputCalc(relaxed);
    const rS = deriveThroughputCalc(strict);
    expect(rS.B_limit.lessThan(rR.B_limit)).toBe(true);
    expect(rS.T_eff_suggestion.lessThan(rR.T_eff_suggestion)).toBe(true);
  });
});

describe('P2-4 蒙特卡洛确定性回归', () => {
  const ZERO_SPREADS: Record<string, number> = {
    'demand.U': 0, 'power.E_price': 0, 'pricing.Rent_gpu': 0, 'pricing.API_out': 0,
    'hw.P_gpu': 0, 'perf.T_eff': 0, 'finance.r_w': 0, 'pricing.p_out': 0,
    'pricing.p_in': 0, 'demand.D_eq': 0,
    // §4.1 补全：新增抽样变量同样置 0 以构造确定性回归
    'power.Co_eng': 0, 'power.Co_sales_admin': 0, 'power.Co_other': 0,
    'perf.SLA_penalty_rate': 0, 'finance.cost_learning_rate': 0,
  };

  it('方差=0 → 均值≈确定性 NPV（容差 1%）', () => {
    const params = defaultParams();
    const r = montecarloCompute(params, 300, 42, ZERO_SPREADS);
    const tol = Math.abs(r.deterministic_npv) * 0.01 + 1e-6;
    expect(Math.abs(r.mean_npv - r.deterministic_npv)).toBeLessThanOrEqual(tol);
  });

  it('明显盈利 → P(NPV>0)=1', () => {
    let params = defaultParams();
    params = withOverride(params, 'pricing.p_out', new Decimal(500)) as ScenarioParams;
    params = withOverride(params, 'pricing.p_in', new Decimal(1)) as ScenarioParams;
    params = withOverride(params, 'pricing.Rent_gpu', new Decimal(1)) as ScenarioParams;
    params = withOverride(params, 'pricing.API_out', new Decimal(1)) as ScenarioParams;
    const r = montecarloCompute(params, 500, 7);
    expect(r.deterministic_npv).toBeGreaterThan(0);
    expect(r.p_npv_positive).toBe(1);
  });

  it('明显亏损（输出单价=0）→ P(NPV>0)=0', () => {
    const params = withOverride(defaultParams(), 'pricing.p_out', new Decimal(0)) as ScenarioParams;
    const r = montecarloCompute(params, 500, 7);
    expect(r.deterministic_npv).toBeLessThan(0);
    expect(r.p_npv_positive).toBe(0);
  });
});
