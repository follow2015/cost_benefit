/**
 * P2 物理/时间建模增强前端镜像逻辑回归测试：
 * - P2-A 负载率功耗曲线：P_eff(U) = P_sys·(P_idle_ratio + U·(1−P_idle_ratio))，
 *   待机功耗计入固定成本；默认 P_idle_ratio=0 ⇒ 逐位退化为线性从零模型（黄金向量零回归）。
 * - P2-B 单位成本学习曲线：财务逐期可变 opex × (1−rate)^(t/12)；默认 rate=0 ⇒ 不变。
 * 仅验证前端引擎镜像，不触碰既有 golden 断言路径。
 */

import { describe, it, expect } from 'vitest';
import { Decimal, ZERO } from '../decimalConfig';
import { defaultParams, withOverride, derive, ScenarioParams, DerivedParams } from '../parameters';
import { computeAll } from '../engine';
import { paramsToDict, paramsFromDict } from '../codec';

const rel = (a: Decimal, b: Decimal): Decimal => {
  const diff = a.minus(b).abs();
  return b.eq(ZERO) ? diff : diff.div(b.abs());
};

// 默认硬件：P_sys = 8×700/1000 + 4.9 = 10.5 kW；PUE=1.3；E_price=0.8；H=720
// 满负荷月电费系数 = 10.5 × 1.3 × 0.8 × 720 = 7862.4 元/月（U=1）
const FULL_COEF = new Decimal('7862.4');

describe('P2-A 负载率功耗曲线', () => {
  it('默认退化：P_idle_ratio=0 ⇒ 待机成本 0、可变系数 = 满负荷系数（与历史一致）', () => {
    const d = derive(defaultParams()) as DerivedParams;
    expect(d.C_power_idle_m.toString()).toBe('0');
    expect(rel(d.C_var_per_U, FULL_COEF).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('P_idle_ratio=0.4：待机成本=满负荷×0.4、可变系数=满负荷×0.6', () => {
    const p = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.4')) as ScenarioParams;
    const d = derive(p) as DerivedParams;
    expect(rel(d.C_power_idle_m, FULL_COEF.times(new Decimal('0.4'))).lte(new Decimal('1e-12'))).toBe(true);
    expect(rel(d.C_var_per_U, FULL_COEF.times(new Decimal('0.6'))).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('低利用率下：待机功耗抬高单位成本（idle floor 修正），高利用率趋近一致', () => {
    let withIdle = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.4')) as ScenarioParams;
    withIdle = withOverride(withIdle, 'demand.U', new Decimal('0.20')) as ScenarioParams;
    const base = computeAll(defaultParams()); // U=0.6 无待机
    const loaded = computeAll(withIdle);
    const baseCost = new Decimal((base.unit_cost as any).cost_per_m_capacity);
    const idleCost = new Decimal((loaded.unit_cost as any).cost_per_m_capacity);
    // 默认场景 U=0.6：base 电费=7862.4×0.6=4717；idle 场景电费=3144.96+4717.44×0.2=4088
    // 固定部分相当、但 idle 场景 U 更低 ⇒ 摊薄成本更高
    expect(idleCost.gt(baseCost)).toBe(true);
  });

  it('C_power_idle_m 计入固定成本：C_fix_cash 随 idle_ratio 增加', () => {
    const base = derive(defaultParams()) as DerivedParams;
    const p = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.3')) as ScenarioParams;
    const d = derive(p) as DerivedParams;
    expect(d.C_fix_cash.gt(base.C_fix_cash)).toBe(true);
    expect(rel(d.C_fix_cash.minus(base.C_fix_cash), FULL_COEF.times(new Decimal('0.3'))).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('token_per_kwh 使用有效功耗（随 idle_ratio 上升而下降）', () => {
    const base = computeAll(defaultParams());
    const p = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.4')) as ScenarioParams;
    const loaded = computeAll(p);
    const baseKwh = new Decimal((base.kpis as any[]).find((k: any) => k.key === 'token_per_kwh')!.value);
    const loadedKwh = new Decimal((loaded.kpis as any[]).find((k: any) => k.key === 'token_per_kwh')!.value);
    expect(loadedKwh.lt(baseKwh)).toBe(true); // 有效功耗更大 ⇒ 每度电 Token 更少
  });

  it('idle_power_cost KPI = 待机功耗固定成本', () => {
    const p = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.5')) as ScenarioParams;
    const payload = computeAll(p);
    const idleKpi = (payload.kpis as any[]).find((k: any) => k.key === 'idle_power_cost')!;
    const d = derive(p) as DerivedParams;
    expect(rel(new Decimal(idleKpi.value), d.C_power_idle_m).lte(new Decimal('1e-12'))).toBe(true);
  });
});

describe('P2-B 单位成本学习曲线', () => {
  it('默认退化：cost_learning_rate=0 ⇒ 现金流与基准逐位一致', () => {
    const base = computeAll(defaultParams());
    const p = withOverride(defaultParams(), 'finance.cost_learning_rate', new Decimal(0)) as ScenarioParams;
    const payload = computeAll(p);
    const baseRows = (base.financials as any).cashflows as any[];
    const rows = (payload.financials as any).cashflows as any[];
    expect(rows.length).toBe(baseRows.length);
    for (let i = 0; i < rows.length; i++) {
      expect(rows[i].opex_cash.toString()).toBe(baseRows[i].opex_cash.toString());
      expect(rows[i].net_cf.toString()).toBe(baseRows[i].net_cf.toString());
    }
  });

  it('cost_learning_rate=0.25：后期可变 opex 低于前期，NPV 高于基准', () => {
    const base = computeAll(defaultParams());
    const p = withOverride(defaultParams(), 'finance.cost_learning_rate', new Decimal('0.25')) as ScenarioParams;
    const payload = computeAll(p);
    const rows = (payload.financials as any).cashflows as any[];
    const baseRows = (base.financials as any).cashflows as any[];
    // 首期 exponent=0 ⇒ factor=1：opex 与基准一致
    expect(rows[0].opex_cash.toString()).toBe(baseRows[0].opex_cash.toString());
    // 第 13 期 exponent=1 ⇒ factor=0.75：可变部分下降（固定不变）⇒ opex 低于基准
    expect(new Decimal(rows[12].opex_cash).lt(new Decimal(baseRows[12].opex_cash))).toBe(true);
    // NPV 改善（成本下降）
    expect(new Decimal((payload.financials as any).npv).gt(new Decimal((base.financials as any).npv))).toBe(true);
  });

  it('learning_terminal_factor = (1−rate)^(T_horizon/12)：0.75³ = 0.421875', () => {
    const p = withOverride(defaultParams(), 'finance.cost_learning_rate', new Decimal('0.25')) as ScenarioParams;
    const payload = computeAll(p);
    const kpi = (payload.kpis as any[]).find((k: any) => k.key === 'learning_terminal_factor')!;
    expect(new Decimal(kpi.value).toString()).toBe('0.421875');
  });

  it('学习曲线仅作用于可变部分：固定成本不受影响', () => {
    const p = withOverride(defaultParams(), 'finance.cost_learning_rate', new Decimal('0.3')) as ScenarioParams;
    const payload = computeAll(p);
    const rows = (payload.financials as any).cashflows as any[];
    const base = computeAll(defaultParams());
    const baseRows = (base.financials as any).cashflows as any[];
    const d = derive(defaultParams()) as DerivedParams;
    // 第 25 期（exponent=2，factor=0.49）：opex = C_fix_cash + 可变×0.49
    const expectedOpex = d.C_fix_cash
      .plus(d.C_var_per_U.times(d.U).times(new Decimal('0.49')))
      .toString();
    expect(rows[24].opex_cash.toString()).toBe(expectedOpex);
    // 固定成本占比不变
    expect(new Decimal(rows[24].opex_cash).gt(new Decimal(baseRows[24].opex_cash))).toBe(false);
  });
});

describe('P2 codec 往返', () => {
  it('paramsToDict → paramsFromDict 保留 P_idle_ratio 与 cost_learning_rate', () => {
    let p = withOverride(defaultParams(), 'power.P_idle_ratio', new Decimal('0.35')) as ScenarioParams;
    p = withOverride(p, 'finance.cost_learning_rate', new Decimal('0.2')) as ScenarioParams;
    const dict = paramsToDict(p);
    expect(dict.power).toHaveProperty('P_idle_ratio', '0.35');
    expect(dict.finance).toHaveProperty('cost_learning_rate', '0.2');
    const round = paramsFromDict(dict);
    expect(new Decimal(round.power.P_idle_ratio).toString()).toBe('0.35');
    expect(new Decimal(round.finance.cost_learning_rate).toString()).toBe('0.2');
  });
});
