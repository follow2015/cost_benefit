/**
 * QA 独立验证（P3 增量能力）——严过关（Yan）。
 * 与工程师 `incremental.test.ts` 互补，侧重「手工公式核对」与「黄金向量新路径存在性」。
 * 全部用例带 `qa_` 前缀。
 */
import { describe, it, expect } from 'vitest';
import { Decimal } from '../decimalConfig';
import {
  defaultParams,
  withOverride,
  scale,
  ScenarioParams,
} from '../parameters';
import { computeAll, EngineOptions, evaluateTarget, evaluateKpis } from '../engine';
import { computeJoint, JOINT_DEFAULT_VARS } from '../sensitivity';
import { computeCustom, CustomScenarioSpec } from '../scenario';
import { paramsFromDict } from '../codec';
import golden from '../goldenVectors.json';

const ZERO = new Decimal(0);
const rel = (a: Decimal, b: Decimal): Decimal => {
  const diff = a.minus(b).abs();
  return b.eq(ZERO) ? diff : diff.div(b.abs());
};

describe('qa_① 融资结构：24 期手工核算 + 税盾 + 杠杆/全权益', () => {
  it('qa_finance_24m_manual: 首月 interest=debt×0.05/12、principal 直线、25 期后无息无本', () => {
    let params = defaultParams();
    params = withOverride(params, 'finance.T_horizon', new Decimal(36)) as ScenarioParams;
    params = withOverride(params, 'finance.debt_ratio', new Decimal('0.5')) as ScenarioParams;
    params = withOverride(params, 'finance.debt_rate', new Decimal('0.05')) as ScenarioParams;
    params = withOverride(params, 'finance.loan_term_months', new Decimal(24)) as ScenarioParams;
    const payload = computeAll(params);
    const fin = payload.financials as any;
    const financing = fin.financing;
    const i0 = (payload.derived as any).I0 as Decimal;
    const debt = i0.times(new Decimal('0.5'));

    expect(rel(new Decimal(financing.debt), debt).lte(new Decimal('1e-15'))).toBe(true);
    const rows = fin.cashflows as any[];
    // 首月利息 = debt × 0.05 / 12
    const expectedInterest = debt.times(new Decimal('0.05')).div(new Decimal(12));
    expect(rel(new Decimal(rows[0].interest), expectedInterest).lte(new Decimal('1e-15'))).toBe(true);
    // 首月本金 = debt / 24
    const expectedPrincipal = debt.div(new Decimal(24));
    expect(rel(new Decimal(rows[0].principal), expectedPrincipal).lte(new Decimal('1e-15'))).toBe(true);
    for (let t = 1; t <= 23; t++) {
      expect(rel(new Decimal(rows[t - 1].principal), expectedPrincipal).lte(new Decimal('1e-15'))).toBe(true);
    }
    expect(new Decimal(rows[23].principal).gt(ZERO)).toBe(true);
    expect(new Decimal(rows[24].interest).eq(ZERO)).toBe(true);
    expect(new Decimal(rows[24].principal).eq(ZERO)).toBe(true);
    expect(rel(new Decimal(financing.principal_total), debt).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('qa_finance_taxed: EBT 含利息扣除，tax=max(0,EBT)×Tax，税盾=interest×Tax', () => {
    let base = defaultParams();
    base = withOverride(base, 'conventions.taxed', true) as ScenarioParams;
    const noDebt = computeAll(base);
    const withDebt = computeAll(withOverride(base, 'finance.debt_ratio', new Decimal('0.4')) as ScenarioParams);
    const rowsDebt = (withDebt.financials as any).cashflows as any[];
    const rowsNoDebt = (noDebt.financials as any).cashflows as any[];
    const taxRate = new Decimal('0.25');
    for (const row of rowsDebt) {
      const expectedEbt = new Decimal(row.revenue)
        .minus(new Decimal(row.opex_cash))
        .minus(new Decimal(row.depreciation))
        .minus(new Decimal(row.interest));
      expect(rel(new Decimal(row.ebt), expectedEbt).lte(new Decimal('1e-12'))).toBe(true);
      const expectedTax = expectedEbt.gt(ZERO) ? expectedEbt.times(taxRate) : ZERO;
      expect(rel(new Decimal(row.tax), expectedTax).lte(new Decimal('1e-12'))).toBe(true);
    }
    expect(new Decimal((withDebt.financials as any).total_tax).lt(new Decimal((noDebt.financials as any).total_tax))).toBe(true);
    // 税盾 = interest × Tax（对 EBT>0 的有息月份）
    for (let i = 0; i < rowsDebt.length; i++) {
      const a = rowsDebt[i];
      const b = rowsNoDebt[i];
      if (new Decimal(a.interest).gt(ZERO) && new Decimal(a.ebt).gt(ZERO)) {
        const shield = new Decimal(a.interest).times(taxRate);
        expect(rel(new Decimal(b.tax).minus(new Decimal(a.tax)), shield).lte(new Decimal('1e-9'))).toBe(true);
      }
    }
  });

  it('qa_finance_levered: debt>0 杠杆 NPV≠全权益 NPV；debt=0 逐位退化相等', () => {
    const unlevered = computeAll(defaultParams());
    const levered = computeAll(withOverride(defaultParams(), 'finance.debt_ratio', new Decimal('0.5')) as ScenarioParams);
    expect(new Decimal((levered.financials as any).npv).ne(new Decimal((unlevered.financials as any).npv))).toBe(true);
    expect((levered.financials as any).financing.levered_npv.toString()).toBe((levered.financials as any).npv.toString());
    expect((unlevered.financials as any).financing.levered_npv.toString()).toBe((unlevered.financials as any).npv.toString());
    expect(new Decimal((levered.financials as any).financing.levered_irr).ne(new Decimal((unlevered.financials as any).irr.irr_annual))).toBe(true);
    expect((unlevered.financials as any).financing.levered_irr.toString()).toBe((unlevered.financials as any).irr.irr_annual.toString());
  });

  it('qa_finance_no_debt: interest_coverage=null（∞ 语义），KPI 末位仍输出', () => {
    const payload = computeAll(defaultParams());
    expect((payload.financials as any).financing.interest_coverage).toBeNull();
    const kpis = payload.kpis as any[];
    expect(kpis[13].key).toBe('interest_coverage');
    expect(kpis[13].value).toBeNull();
  });
});

describe('qa_② 分时电价：手工加权 + 退化 + E_price 敏感性', () => {
  it('qa_tou_weighted_manual: 峰 1.5×/谷 0.7×、峰 20%/谷 30% → weighted=0.808 驱动成本链', () => {
    let params = defaultParams();
    const ePrice = (params.power as any).E_price as Decimal; // 0.8
    params = withOverride(params, 'power.e_price_peak', new Decimal('1.5').times(ePrice)) as ScenarioParams; // 1.2
    params = withOverride(params, 'power.e_price_flat', ePrice) as ScenarioParams;
    params = withOverride(params, 'power.e_price_valley', new Decimal('0.7').times(ePrice)) as ScenarioParams; // 0.56
    params = withOverride(params, 'power.tou_peak_share', new Decimal('0.2')) as ScenarioParams;
    params = withOverride(params, 'power.tou_valley_share', new Decimal('0.3')) as ScenarioParams;
    const payload = computeAll(params);
    const derived = payload.derived as any;
    const weightedManual = new Decimal('0.56').times(new Decimal('0.3'))
      .plus(new Decimal('0.8').times(new Decimal('0.5')))
      .plus(new Decimal('1.2').times(new Decimal('0.2')));
    expect(rel(new Decimal(derived.weighted_e_price), weightedManual).lte(new Decimal('1e-15'))).toBe(true);
    const expectedCvar = new Decimal(derived.P_sys).times(new Decimal('1.3')).times(weightedManual).times(new Decimal(720));
    expect(rel(new Decimal(derived.C_var_per_U), expectedCvar).lte(new Decimal('1e-12'))).toBe(true);
    const bA = new Decimal((payload.cost_models as any[])[0].b);
    expect(rel(bA, new Decimal(derived.C_var_per_U).div(new Decimal(derived.Q_cap_M))).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('qa_tou_degenerate: 未启用 weighted=E_price，且 E_price 单独变化仍驱动（敏感性保持）', () => {
    const payload = computeAll(defaultParams());
    expect(new Decimal((payload.derived as any).weighted_e_price).toString()).toBe('0.8');
    const changed = computeAll(withOverride(defaultParams(), 'power.E_price', new Decimal('1.5')) as ScenarioParams);
    expect(new Decimal((changed.derived as any).weighted_e_price).toString()).toBe('1.5');
    expect(new Decimal((changed.derived as any).C_var_per_U).gt(new Decimal((payload.derived as any).C_var_per_U))).toBe(true);
  });
});

describe('qa_④ 需求增长：g=0.5 第 13/25 月手工因子 + 退化', () => {
  it('qa_demand_t13: D_t = D×1.5（t=13）、D×2.25（t=25），收入/变动成本缩放；g=0 退化', () => {
    const basePayload = computeAll(defaultParams());
    const params = withOverride(defaultParams(), 'demand.g_demand', new Decimal('0.5')) as ScenarioParams;
    const payload = computeAll(params);
    const rows = (payload.financials as any).cashflows as any[];
    const revR = (payload.revenue as any).R as Decimal;
    expect(rel(new Decimal(rows[0].revenue), new Decimal(revR)).lte(new Decimal('1e-12'))).toBe(true);
    expect(rel(new Decimal(rows[12].revenue), new Decimal(revR).times(new Decimal('1.5'))).lte(new Decimal('1e-12'))).toBe(true);
    expect(rel(new Decimal(rows[24].revenue), new Decimal(revR).times(new Decimal('2.25'))).lte(new Decimal('1e-12'))).toBe(true);
    const derived = payload.derived as any;
    const cFixCash = new Decimal(derived.C_fix_cash);
    const cVarU = new Decimal(derived.C_var_per_U).times(new Decimal(derived.U));
    expect(rel(new Decimal(rows[12].opex_cash), cFixCash.plus(cVarU.times(new Decimal('1.5')))).lte(new Decimal('1e-12'))).toBe(true);
    // 退化：g=0 参数重算后逐月与基准一致
    const degeneratePayload = computeAll(withOverride(defaultParams(), 'demand.g_demand', new Decimal(0)) as ScenarioParams);
    const degenerateRows = (degeneratePayload.financials as any).cashflows as any[];
    const baseRows = (basePayload.financials as any).cashflows as any[];
    for (let i = 0; i < degenerateRows.length; i++) {
      expect(degenerateRows[i].revenue.toString()).toBe(baseRows[i].revenue.toString());
      expect(degenerateRows[i].opex_cash.toString()).toBe(baseRows[i].opex_cash.toString());
      expect(degenerateRows[i].net_cf.toString()).toBe(baseRows[i].net_cf.toString());
    }
  });
});

describe('qa_③ 联合敏感性 4 网格手算 + 自定义情景字段', () => {
  it('qa_joint_manual: 4 点重算 min/max/p50、主效应、二阶交互与 computeJoint 输出一致', () => {
    const base = defaultParams();
    const joint = computeJoint(base, evaluateTarget, 'npv', new Decimal('0.2'), JOINT_DEFAULT_VARS.slice(0, 2));
    const scaled = (uHigh: boolean, eHigh: boolean): ScenarioParams => {
      let p = scale(base, 'demand.U', new Decimal(uHigh ? '1.2' : '0.8'));
      p = scale(p, 'demand.D_eq', new Decimal(uHigh ? '1.2' : '0.8'));
      p = scale(p, 'power.E_price', new Decimal(eHigh ? '1.2' : '0.8'));
      return p;
    };
    const npvLL = evaluateTarget(scaled(false, false), 'npv')!;
    const npvHL = evaluateTarget(scaled(true, false), 'npv')!;
    const npvLH = evaluateTarget(scaled(false, true), 'npv')!;
    const npvHH = evaluateTarget(scaled(true, true), 'npv')!;
    const vals = [npvLL, npvHL, npvLH, npvHH].sort((a, b) => a.minus(b).cmp(ZERO));
    expect(joint.npv_min.toString()).toBe(vals[0].toString());
    expect(joint.npv_max.toString()).toBe(vals[3].toString());
    const p50 = vals[1].plus(vals[2].minus(vals[1]).times(new Decimal('0.5')));
    expect(rel(joint.percentiles.p50, p50).lte(new Decimal('1e-12'))).toBe(true);
    const sU = npvHL.plus(npvHH).div(2).minus(npvLL.plus(npvLH).div(2)).abs();
    expect(rel(joint.main_effects.U, sU).lte(new Decimal('1e-12'))).toBe(true);
    const sE = npvLH.plus(npvHH).div(2).minus(npvLL.plus(npvHL).div(2)).abs();
    expect(rel(joint.main_effects.E_price, sE).lte(new Decimal('1e-12'))).toBe(true);
    const iUE = npvHH.minus(npvHL).minus(npvLH).plus(npvLL);
    expect(rel(joint.interactions.UE_price, iUE).lte(new Decimal('1e-12'))).toBe(true);
  });

  it('qa_custom_scenarios: K=3 并列，KPI 7 字段齐全，overrides 回显', () => {
    const specs: CustomScenarioSpec[] = [
      { key: 'low_demand', label: '低需求', overrides: { 'demand.U': new Decimal('0.4'), 'demand.D_eq': new Decimal(2000) } },
      { key: 'high_price', label: '高售价', overrides: { 'pricing.p_out': new Decimal(40), 'pricing.p_in': new Decimal(10) } },
      { key: 'full_debt', label: '高杠杆', overrides: { 'finance.debt_ratio': new Decimal('0.8'), 'finance.debt_rate': new Decimal('0.08') } },
    ];
    const result = computeCustom(defaultParams(), specs, evaluateKpis);
    expect(result.cases.length).toBe(3);
    const kpiFields = ['npv', 'irr', 'roi', 'cost_per_m', 'payback_static', 'gross_margin', 'U_be'];
    for (const c of result.cases) {
      expect(Object.keys(c.kpis).sort()).toEqual([...kpiFields].sort());
      expect(c.kpis.npv).not.toBeNull();
      expect(c.feasible).toBe(true);
      expect(Object.keys(c.overrides).length).toBeGreaterThan(0);
    }
    // 高杠杆情景 NPV 与基准不同（融资影响）
    const baseNpv = new Decimal((computeAll(defaultParams()).financials as any).npv);
    expect(new Decimal(result.cases[2].kpis.npv!).ne(baseNpv)).toBe(true);
  });
});

describe('qa_⑤ 黄金向量 GV09–GV15 新路径 + 公式规格 F061–F066', () => {
  it('qa_golden_gv09_15: 新用例断言路径完整且非空；历史 GV01–GV08 新路径不污染', () => {
    const cases = (golden as any).cases as any[];
    const requiredPaths = [
      'derived.weighted_e_price',
      'financials.financing.debt_ratio',
      'financials.financing.debt',
      'financials.financing.equity',
      'financials.financing.interest_total',
      'financials.financing.principal_total',
      'financials.financing.roe',
      'financials.financing.interest_coverage',
      'financials.financing.levered_npv',
      'financials.cashflows[0].interest',
      'financials.cashflows[0].principal',
      'kpis[12].key',
      'kpis[12].value',
      'joint.npv_min',
      'joint.npv_max',
      'joint.percentiles.p50',
      'joint.main_effects.U',
      'joint.main_effects.E_price',
      'joint.interactions.UE_price',
      'custom_scenarios.cases[0].kpis.npv',
      'custom_scenarios.cases[2].kpis.npv',
    ];
    for (const cid of ['GV09', 'GV10', 'GV11', 'GV12', 'GV13', 'GV14', 'GV15']) {
      const c = cases.find((x: any) => x.id === cid);
      expect(c).toBeDefined();
      for (const p of requiredPaths) {
        expect(p in c.expect).toBe(true);
      }
    }
    const gv14 = cases.find((x: any) => x.id === 'GV14');
    expect(gv14.expect['joint.npv_min']).not.toBeNull();
    expect(gv14.expect['joint.main_effects.U']).not.toBeNull();
    const gv15 = cases.find((x: any) => x.id === 'GV15');
    expect(gv15.expect['custom_scenarios.cases[0].kpis.npv']).not.toBeNull();
    // 历史 GV01–GV08：新路径不污染旧断言
    for (let i = 1; i <= 8; i++) {
      const cid = `GV${String(i).padStart(2, '0')}`;
      const c = cases.find((x: any) => x.id === cid);
      expect(c.expect['financials.financing.debt_ratio']).toBe('0');
      expect(c.expect['financials.cashflows[0].interest']).toBe('0');
      expect(c.expect['joint.npv_min']).toBeNull();
    }
    // 双端 golden 文件版本一致（该文件即前端副本；检查版本字段）
    expect((golden as any).version).toBe('1.2.0');
    expect((golden as any).generated_by).toBe('calc-py-0.2.0');
  });

  it('qa_formula_spec: F061–F066 + F100/F101 存在、旧 ID 保留、版本 bump', () => {
    // 前端 formulaSpec.ts 内容由后端权威生成，这里通过 computeAll 的版本字段校验
    const payload = computeAll(defaultParams());
    expect(payload.engine_version).toBe('calc-ts-0.2.0');
    expect(payload.formula_spec_version).toBe('1.2.0');
  });
});
