/**
 * P3 增量能力前端镜像逻辑回归测试：
 * ① 融资结构（debt_ratio）② 分时电价 TOU ③ 联合敏感性 + 自定义情景 ④ 需求增长。
 * 验证「开启态」正确性与「默认退化态」与现状一致。
 */

import { describe, it, expect } from 'vitest';
import { Decimal, ONE } from '../decimalConfig';
import { defaultParams, withOverride, ScenarioParams } from '../parameters';
import { computeAll, EngineOptions } from '../engine';
import { computeJoint, JOINT_DEFAULT_VARS } from '../sensitivity';
import { computeCustom, CustomScenarioSpec } from '../scenario';
import { evaluateTarget, evaluateKpis } from '../engine';

const ZERO = new Decimal(0);
const rel = (a: Decimal, b: Decimal): Decimal => {
  const diff = a.minus(b).abs();
  return b.eq(ZERO) ? diff : diff.div(b.abs());
};

const BASE = computeAll(defaultParams());

describe('① 融资结构（债务杠杆）', () => {
  it('debt_ratio=0 退化：financing 与现状一致，现金流无利息/本金', () => {
    const financing = (BASE.financials as any).financing;
    expect(financing.debt_ratio.toString()).toBe('0');
    expect(financing.debt.toString()).toBe('0');
    expect(financing.equity.toString()).toBe((BASE.derived as any).I0.toString());
    expect(financing.interest_total.toString()).toBe('0');
    expect(financing.principal_total.toString()).toBe('0');
    expect(financing.levered_npv.toString()).toBe((BASE.financials as any).npv.toString());
    expect(financing.levered_irr.toString()).toBe((BASE.financials as any).irr.irr_annual?.toString());
    for (const row of (BASE.financials as any).cashflows as any[]) {
      expect(row.interest.toString()).toBe('0');
      expect(row.principal.toString()).toBe('0');
    }
  });

  it('debt_ratio=0.5：债务/权益拆分 + 月利息/本金递推 + KPI 末位追加', () => {
    let params = defaultParams();
    params = withOverride(params, 'finance.T_horizon', new Decimal(60)) as ScenarioParams;
    params = withOverride(params, 'finance.debt_ratio', new Decimal('0.5')) as ScenarioParams;
    params = withOverride(params, 'finance.debt_rate', new Decimal('0.05')) as ScenarioParams;
    params = withOverride(params, 'finance.loan_term_months', new Decimal(48)) as ScenarioParams;
    const payload = computeAll(params);
    const fin = payload.financials as any;
    const financing = fin.financing;
    const i0 = (payload.derived as any).I0 as Decimal;
    expect(rel(new Decimal(financing.debt), i0.times(new Decimal('0.5'))).lte(new Decimal('1e-12'))).toBe(true);
    expect(rel(new Decimal(financing.equity), i0.times(new Decimal('0.5'))).lte(new Decimal('1e-12'))).toBe(true);

    const rows = fin.cashflows as any[];
    const firstInterest = new Decimal(rows[0].interest);
    const expectedInterest = new Decimal(financing.debt).times(new Decimal('0.05')).div(new Decimal(12));
    expect(rel(firstInterest, expectedInterest).lte(new Decimal('1e-12'))).toBe(true);
    expect(rows[0].principal).toBeDefined();
    expect(new Decimal(rows[47].principal).gt(ZERO)).toBe(true);
    expect(new Decimal(rows[48].interest).eq(ZERO)).toBe(true);
    expect(new Decimal(rows[48].principal).eq(ZERO)).toBe(true);

    const kpis = payload.kpis as any[];
    expect(kpis[12].key).toBe('debt_ratio');
    expect(kpis[12].value.toString()).toBe('0.5');
    expect(kpis[13].key).toBe('interest_coverage');
    expect(kpis[14].key).toBe('roe');
    // P0 管理驾驶舱 KPI 追加至末尾（每卡每天收入/成本、每度电产出 Token）
    // P1 SLA 计提 2 个 KPI 追加至末尾（默认 pkg 关闭 ⇒ 递延收入 KPI 不出现）
    // P2 负载曲线/学习曲线 2 个 KPI 再追加至末尾
    // 电力运维口径（柜电分离/包柜包电）2 个 KPI 再追加至末尾
    expect(kpis.length).toBe(26);
    expect(kpis[17].key).toBe('rev_per_gpu_day');
    expect(kpis[18].key).toBe('cost_per_gpu_day');
    expect(kpis[19].key).toBe('token_per_kwh');
    expect(kpis[20].key).toBe('sla_provision_monthly');
    expect(kpis[21].key).toBe('sla_provision_total');
    // 默认 SLA_penalty_rate=0 ⇒ 计提为 0
    expect(new Decimal(kpis[20].value).eq(ZERO)).toBe(true);
    expect(new Decimal(kpis[21].value).eq(ZERO)).toBe(true);
    // 默认 P_idle_ratio=0 ⇒ 待机功耗成本 0；cost_learning_rate=0 ⇒ 期末系数 1
    expect(kpis[22].key).toBe('idle_power_cost');
    expect(new Decimal(kpis[22].value).eq(ZERO)).toBe(true);
    expect(kpis[23].key).toBe('learning_terminal_factor');
    expect(new Decimal(kpis[23].value).eq(ONE)).toBe(true);
    // 默认柜电分离 ⇒ 包柜包电月成本 0；机柜数为自动推导参考值
    expect(kpis[24].key).toBe('racks_count');
    expect(kpis[25].key).toBe('bundle_rack_cost_m');
    expect(new Decimal(kpis[25].value).eq(ZERO)).toBe(true);
  });
});

describe('P1 资源包/递延收入 + SLA 赔偿计提', () => {
  it('pkg 关闭：递延收入 KPI 不出现，且 sla 计提随比率线性（默认 0）', () => {
    const payload = computeAll(defaultParams());
    const kpis = payload.kpis as any[];
    const keys = kpis.map((k: any) => k.key);
    expect(keys).not.toContain('deferred_revenue');
    expect(keys).not.toContain('rev_recognized_monthly');
    // 默认 SLA_penalty_rate=0 ⇒ 计提 KPI 存在且为 0
    const sla = kpis.find((k: any) => k.key === 'sla_provision_total');
    expect(sla).toBeDefined();
    expect(new Decimal(sla.value).eq(ZERO)).toBe(true);
  });

  it('pkg 开启：合同负债/每月确认/期末未确认/现金跑道 正确联动', () => {
    let p = withOverride(defaultParams(), 'pricing.pkg_enabled', true) as ScenarioParams;
    p = withOverride(p, 'pricing.pkg_prepaid', new Decimal('1200000')) as ScenarioParams; // 预收费 120 万
    p = withOverride(p, 'pricing.pkg_tokens', new Decimal('2000')) as ScenarioParams; // 2000 Mtok
    p = withOverride(p, 'pricing.pkg_consume_months', new Decimal('24')) as ScenarioParams; // 24 个月消耗
    const payload = computeAll(p);
    const kpis = payload.kpis as any[];
    const get = (k: string) => kpis.find((x: any) => x.key === k);
    expect(get('deferred_revenue')!.value.toString()).toBe('1200000'); // 合同负债初始 = 预收费
    expect(get('rev_recognized_monthly')!.value.toString()).toBe('50000'); // 120万 / 24 月
    expect(get('cash_prepaid')!.value.toString()).toBe('1200000');
    // 未确认占比 = max(0, 1 − 36/24) = 0（36 月周期 > 24 月消耗，全确认）
    expect(new Decimal(get('unearned_share')!.value).eq(ZERO)).toBe(true);
    expect(get('deferred_revenue_end')!.value.toString()).toBe('0');
    // 预付费现金跑道 = 120万 / 月收入 R
    expect(new Decimal(get('prepaid_cash_months')!.value).gt(ZERO)).toBe(true);
  });

  it('SLA 赔偿计提随 SLA_penalty_rate 线性计入 opex_cash（影响 NPV）', () => {
    const base = computeAll(defaultParams());
    let p = withOverride(defaultParams(), 'perf.SLA_penalty_rate', new Decimal('0.02')) as ScenarioParams; // 月收入 2%
    const loaded = computeAll(p);
    const baseNpv = new Decimal((base.financials as any).npv);
    const loadedNpv = new Decimal((loaded.financials as any).npv);
    expect(loadedNpv.lt(baseNpv)).toBe(true); // 计提增加成本 ⇒ NPV 下降
    const slaTotal = (loaded.kpis as any[]).find((k: any) => k.key === 'sla_provision_total');
    const totalRev = new Decimal((loaded.financials as any).total_revenue);
    expect(new Decimal(slaTotal!.value).eq(totalRev.times(new Decimal('0.02')))).toBe(true);
  });
});

describe('② 分时电价 TOU', () => {
  it('未启用 TOU：weighted = E_price，且 E_price 变化仍驱动成本（敏感性有效）', () => {
    const payload = computeAll(defaultParams());
    expect(new Decimal((payload.derived as any).weighted_e_price).toString()).toBe('0.8');
    // E_price 变化 → C_var_per_U 变化（退化不破坏 E_price 敏感性）
    const changed = withOverride(defaultParams(), 'power.E_price', new Decimal('1.5')) as ScenarioParams;
    const changedPayload = computeAll(changed);
    expect(new Decimal((changedPayload.derived as any).C_var_per_U).gt(new Decimal((payload.derived as any).C_var_per_U))).toBe(true);
    expect(rel(new Decimal((changedPayload.derived as any).weighted_e_price), new Decimal('1.5')).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('启用 TOU：加权价 = 谷×谷占比 + 平×平占比 + 峰×峰占比，并驱动 b_A', () => {
    let params = defaultParams();
    params = withOverride(params, 'power.e_price_peak', new Decimal('1.2')) as ScenarioParams;
    params = withOverride(params, 'power.e_price_flat', new Decimal('0.8')) as ScenarioParams;
    params = withOverride(params, 'power.e_price_valley', new Decimal('0.4')) as ScenarioParams;
    params = withOverride(params, 'power.tou_peak_share', new Decimal('0.3')) as ScenarioParams;
    params = withOverride(params, 'power.tou_valley_share', new Decimal('0.2')) as ScenarioParams;
    const payload = computeAll(params);
    const derived = payload.derived as any;
    // w_flat = 0.5 ⇒ weighted = 0.4×0.2 + 0.8×0.5 + 1.2×0.3 = 0.84
    const weighted = new Decimal('0.4').times(new Decimal('0.2'))
      .plus(new Decimal('0.8').times(new Decimal('0.5')))
      .plus(new Decimal('1.2').times(new Decimal('0.3')));
    expect(rel(new Decimal(derived.weighted_e_price), weighted).lte(new Decimal('1e-12'))).toBe(true);
    // b_A = C_var_per_U / Q_cap_M
    const bA = new Decimal((payload.cost_models as any[])[0].b);
    const expectedBA = new Decimal(derived.C_var_per_U).div(new Decimal(derived.Q_cap_M));
    expect(rel(bA, expectedBA).lte(new Decimal('1e-12'))).toBe(true);
    // 单位成本随加权价变化
    expect(new Decimal((payload.unit_cost as any).cost_per_m_capacity).ne(new Decimal((BASE.unit_cost as any).cost_per_m_capacity))).toBe(true);
  });
});

describe('③ 联合敏感性 + 自定义情景', () => {
  it('U + E_price 两变量 ±20%：网格 min/max/P50 + 主效应 + 交互', () => {
    const joint = computeJoint(defaultParams(), evaluateTarget, 'npv', new Decimal('0.2'), JOINT_DEFAULT_VARS.slice(0, 2));
    expect(joint.npv_min.lte(joint.npv_max)).toBe(true);
    expect(joint.percentiles.p50).toBeDefined();
    expect(joint.main_effects.U.gt(ZERO)).toBe(true);
    expect(joint.main_effects.E_price.gt(ZERO)).toBe(true);
    expect('UE_price' in joint.interactions).toBe(true);
  });

  it('自定义情景 K=3：并列 KPI 与可行性', () => {
    const specs: CustomScenarioSpec[] = [
      { key: 'conservative_price', label: '保守价', overrides: { 'pricing.p_out': new Decimal(27), 'pricing.p_in': new Decimal('6.75') } },
      { key: 'high_elec', label: '高电价', overrides: { 'power.E_price': new Decimal('1.5') } },
      { key: 'high_leverage', label: '高杠杆', overrides: { 'finance.debt_ratio': new Decimal('0.6'), 'finance.debt_rate': new Decimal('0.06') } },
    ];
    const result = computeCustom(defaultParams(), specs, evaluateKpis);
    expect(result.cases.length).toBe(3);
    expect(result.cases.map((c) => c.key)).toEqual(['conservative_price', 'high_elec', 'high_leverage']);
    expect(result.cases.every((c) => c.feasible)).toBe(true);
    expect(result.cases.every((c) => c.kpis.npv !== null)).toBe(true);
  });

  it('默认载荷不含 joint / custom_scenarios 块（不膨胀默认输出）', () => {
    expect(BASE.joint).toBeNull();
    expect(BASE.custom_scenarios).toBeNull();
  });
});

describe('④ 需求逐年增长', () => {
  it('g_demand=0 退化：收入/成本/现金流与现状一致', () => {
    const params = withOverride(defaultParams(), 'demand.g_demand', new Decimal(0)) as ScenarioParams;
    const payload = computeAll(params);
    const baseRows = (BASE.financials as any).cashflows as any[];
    const rows = (payload.financials as any).cashflows as any[];
    expect(rows.length).toBe(baseRows.length);
    for (let i = 0; i < rows.length; i++) {
      expect(rows[i].revenue.toString()).toBe(baseRows[i].revenue.toString());
      expect(rows[i].opex_cash.toString()).toBe(baseRows[i].opex_cash.toString());
      expect(rows[i].net_cf.toString()).toBe(baseRows[i].net_cf.toString());
    }
    expect((payload.financials as any).npv.toString()).toBe((BASE.financials as any).npv.toString());
  });

  it('g_demand=0.10：后期收入/变动成本随 D_t 上升，NPV 高于基准', () => {
    const params = withOverride(defaultParams(), 'demand.g_demand', new Decimal('0.10')) as ScenarioParams;
    const payload = computeAll(params);
    const rows = (payload.financials as any).cashflows as any[];
    const baseRows = (BASE.financials as any).cashflows as any[];
    expect(new Decimal(rows[12].revenue).gt(new Decimal(rows[0].revenue))).toBe(true);
    expect(new Decimal(rows[23].revenue).gt(new Decimal(rows[11].revenue))).toBe(true);
    expect(new Decimal(rows[12].opex_cash).gt(new Decimal(baseRows[12].opex_cash))).toBe(true);
    expect(new Decimal((payload.financials as any).npv).gt(new Decimal((BASE.financials as any).npv))).toBe(true);
  });
});
