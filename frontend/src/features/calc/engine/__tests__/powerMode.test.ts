/** 电力运维口径：柜电分离（默认）/ 包柜包电（bundle）——前后端镜像一致性 + 数值方向。 */
import { describe, it, expect } from 'vitest';
import { Decimal } from '../decimalConfig';
import { defaultParams, withOverride, POWER_MODE_BUNDLE, POWER_MODE_SEPARATE } from '../parameters';
import { paramsToDict, paramsFromDict } from '../codec';
import { compute } from '../unitCost';
import { computeAll } from '../engine';

const OPTS = {
  include_sensitivity: false, include_scenarios: false, include_crossover: false,
  sensitivity_target: 'npv', sensitivity_delta: new Decimal('0.2'),
};

describe('电力运维口径：柜电分离 vs 包柜包电', () => {
  it('默认柜电分离：C_var_per_U>0、bundle 成本 0，与既有口径一致', () => {
    const d = defaultParams();
    const payload = computeAll(d, OPTS);
    const derived = payload.derived as any;
    expect(derived.C_var_per_U.gt(0)).toBe(true);
    expect(derived.bundle_rack_cost_m.eq(0)).toBe(true);
    expect(derived.racks.eq(new Decimal(8).div(32).ceil())).toBe(true); // 8 卡 → 1 柜
    const kpis = payload.kpis as any[];
    expect(kpis.find((k: any) => k.key === 'bundle_rack_cost_m').value.toString()).toBe('0');
  });

  it('包柜包电：C_var_per_U=0、idle=0、rack 成本入固定、可变电费从单位成本消失', () => {
    const params = withOverride(
      withOverride(
        withOverride(defaultParams(), 'power.power_mode', POWER_MODE_BUNDLE),
        'power.bundle_monthly_per_rack', new Decimal(8000),
      ),
      'hw.N_gpu', new Decimal(8),
    );
    const payload = computeAll(params, OPTS);
    const derived = payload.derived as any;
    expect(derived.power_mode).toBe(POWER_MODE_BUNDLE);
    expect(derived.C_var_per_U.eq(0)).toBe(true);
    expect(derived.C_power_idle_m.eq(0)).toBe(true);
    expect(derived.racks.eq(1)).toBe(true); // ceil(8/32)
    expect(derived.bundle_rack_cost_m.eq(8000)).toBe(true);
    // 固定成本 = 基础项(2000+1000+120000/12=13000) + 8000 = 21000（不含 Co_loc 5000、不含 idle）
    expect(derived.C_fix_cash.eq(21000)).toBe(true);
    // 单位成本结构：无「电费」行（amount=0 被剔除）、colocation 行标签=包柜包电
    const uc = compute(params, derived);
    const powerRow = uc.breakdown.find((b: any) => b.key === 'power');
    const colocRow = uc.breakdown.find((b: any) => b.key === 'colocation');
    expect(powerRow).toBeUndefined();
    expect(colocRow!.label).toBe('包柜包电');
    expect(colocRow!.amount.eq(8000)).toBe(true);
  });

  it('柜电分离（默认）：单位成本保留「电费」与「机柜托管」两行（>0）', () => {
    const params = defaultParams();
    const payload = computeAll(params, OPTS);
    const derived = payload.derived as any;
    const uc = compute(params, derived);
    const powerRow = uc.breakdown.find((b: any) => b.key === 'power');
    const colocRow = uc.breakdown.find((b: any) => b.key === 'colocation');
    expect(powerRow).toBeDefined();
    expect(powerRow!.amount.gt(0)).toBe(true);
    expect(colocRow!.label).toBe('机柜托管');
    expect(colocRow!.amount.gt(0)).toBe(true);
    const kpis = payload.kpis as any[];
    expect(new Decimal(kpis.find((k: any) => k.key === 'bundle_rack_cost_m').value).eq(0)).toBe(true);
  });

  it('机柜数自动推导：N_gpu=70 → ceil(70/32)=3 柜；显式 racks 优先', () => {
    const auto = withOverride(
      withOverride(
        withOverride(defaultParams(), 'power.power_mode', POWER_MODE_BUNDLE),
        'power.bundle_monthly_per_rack', new Decimal(8000),
      ),
      'hw.N_gpu', new Decimal(70),
    );
    const d1 = (computeAll(auto, OPTS).derived as any);
    expect(d1.racks.eq(3)).toBe(true);
    expect(d1.bundle_rack_cost_m.eq(8000 * 3)).toBe(true);
    const explicit = withOverride(auto, 'power.racks', new Decimal(5));
    const d2 = (computeAll(explicit, OPTS).derived as any);
    expect(d2.racks.eq(5)).toBe(true);
    expect(d2.bundle_rack_cost_m.eq(8000 * 5)).toBe(true);
  });

  it('codec 往返：power_mode/bundle_monthly_per_rack/racks 全保留', () => {
    const p = withOverride(
      withOverride(defaultParams(), 'power.power_mode', POWER_MODE_BUNDLE),
      'power.bundle_monthly_per_rack', new Decimal(8000),
    );
    const round = paramsFromDict(paramsToDict(p));
    expect(round.power.power_mode).toBe(POWER_MODE_BUNDLE);
    expect(round.power.bundle_monthly_per_rack.eq(8000)).toBe(true);
    expect(round.power.racks.eq(0)).toBe(true);
  });
});
