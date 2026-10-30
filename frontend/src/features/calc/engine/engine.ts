/**
 * 计算引擎编排（前端镜像实现，权威=后端 Python）。
 * 对齐后端 `app/calc/engine.py`：纯函数、零 IO，输出结构与后端一致（Decimal 经 toJsonable 转字符串）。
 */

import { Decimal, MTOK, MONTHS_PER_YEAR, ONE, ZERO, decStr, dpow, toJsonable, safeDiv } from './decimalConfig';
import { ENGINE_VERSION, FORMULA_SPEC_VERSION } from './context';
import {
  DerivedParams,
  ScenarioParams,
  derive,
} from './parameters';
import * as throughputModule from './throughput';
import * as costModelModule from './costModel';
import * as unitCostModule from './unitCost';
import * as revenueModule from './revenue';
import * as breakevenModule from './breakeven';
import * as financialsModule from './financials';
import * as sensitivityModule from './sensitivity';
import * as scenarioModule from './scenario';
import * as crossoverModule from './crossover';
import { paramsToDict } from './codec';

export interface EngineOptions {
  include_sensitivity: boolean;
  include_scenarios: boolean;
  include_crossover: boolean;
  sensitivity_target: string;
  sensitivity_delta: Decimal;
  // ---- 增量能力（默认关闭，避免膨胀默认载荷、不影响 720 历史向量） ----
  include_joint?: boolean; // 多因素联合敏感性
  joint_target?: string;
  joint_delta?: Decimal;
  joint_vars?: string[] | null; // null ⇒ 默认 U + E_price
  include_custom_scenarios?: boolean; // 自定义情景（任意 K 组）
  custom_scenario_specs?: scenarioModule.CustomScenarioSpec[] | null;
}

export const DEFAULT_OPTIONS: EngineOptions = {
  include_sensitivity: true,
  include_scenarios: true,
  include_crossover: true,
  sensitivity_target: sensitivityModule.TARGET_NPV,
  sensitivity_delta: new Decimal('0.2'),
  include_joint: false,
  joint_target: sensitivityModule.TARGET_NPV,
  joint_delta: new Decimal('0.2'),
  joint_vars: null,
  include_custom_scenarios: false,
  custom_scenario_specs: null,
};

// ---- 类型（来自各模块，便于导出）----
type ThroughputInfo = throughputModule.ThroughputInfo;
type UnitCostResult = unitCostModule.UnitCostResult;
type RevenueResult = revenueModule.RevenueResult;
type BreakevenResult = breakevenModule.BreakevenResult;
type CostModelLike = costModelModule.CostModelLike;
type FinancialResult = financialsModule.FinancialResult;
type SensitivityResult = sensitivityModule.SensitivityResult;
type ScenarioSetResult = scenarioModule.ScenarioSetResult;
type JointSensitivityResult = sensitivityModule.JointSensitivityResult;
type CustomScenarioSet = scenarioModule.CustomScenarioSet;

export interface CoreResult {
  derived: DerivedParams;
  throughput: ThroughputInfo;
  unit_cost: UnitCostResult;
  revenue: RevenueResult;
  breakeven: BreakevenResult;
  cost_models: CostModelLike[];
  financials: FinancialResult;
  warnings: string[];
}

export function computeCore(params: ScenarioParams): CoreResult {
  const derived = derive(params);
  const throughputInfo = throughputModule.analyze(params, derived);
  const unitCostResult = unitCostModule.compute(params, derived);
  const revenueResult = revenueModule.compute(params, derived, unitCostResult.C_total);
  const breakevenResult = breakevenModule.compute(derived, revenueResult);
  const models = costModelModule.buildAll(params, derived);
  const financialResult = financialsModule.compute(params, derived, revenueResult);

  const warnings: string[] = [...throughputInfo.warnings];
  if (!breakevenResult.feasible) warnings.push(breakevenResult.note);
  warnings.push(...financialResult.notes);
  if (derived.k_source !== 'measured') {
    warnings.push(
      `等效折算系数 k = ${decStr(derived.k)} 来源为「${throughputInfo.k_source_label}」，非实测值，结论请结合敏感性分析解读。`,
    );
  }

  // ---- C-1 口径告警：售价 < 市场公允成本标杆 ⇒ 单 token 亏损 ----
  if (revenueResult.loss_vs_benchmark && params.pricing.cost_benchmark !== null) {
    warnings.push(
      `口径告警：对外售价等效单价 ${decStr(revenueResult.p_eq)} 元/Mtok 低于市场公允成本标杆 ` +
        `${decStr(params.pricing.cost_benchmark)} 元/Mtok，按此定价单 token 亏损` +
        '（对标市场成本的毛利为负），建议重新议价或改用第三方 API/云方案。',
    );
  }

  // ---- E-10 标杆告警环：自建设本偏离行业实测标杆 > ±50% ----
  // 与 C-1「售价 vs 标杆」亏损告警区分：本项对标「自建单位成本 vs 行业实测 y_costh」，
  // 用于校验 T_eff 等假设是否合理（自建比行业贵/便宜一倍即提示口径异常）。
  if (params.pricing.cost_benchmark !== null && unitCostResult.cost_per_m_capacity.gt(ZERO)) {
    const cb = params.pricing.cost_benchmark;
    if (cb.gt(ZERO)) {
      const deviation = unitCostResult.cost_per_m_capacity.minus(cb).abs().div(cb);
      if (deviation.gt(new Decimal('0.5'))) {
        const direction = unitCostResult.cost_per_m_capacity.gt(cb) ? '高于' : '低于';
        warnings.push(
          `标杆告警：每百万 token 自建设本 ${decStr(unitCostResult.cost_per_m_capacity)} 元/Mtok ` +
            `${direction}行业基准 ${decStr(cb)} 元/Mtok 约 ${decStr(deviation.times(new Decimal('100')))}%（>±50%），` +
            'T_eff 等吞吐假设可能偏离行业实测，建议用基准库校准。',
        );
      }
    }
  }

  return {
    derived,
    throughput: throughputInfo,
    unit_cost: unitCostResult,
    revenue: revenueResult,
    breakeven: breakevenResult,
    cost_models: models,
    financials: financialResult,
    warnings,
  };
}

export function isFeasible(derived: DerivedParams): boolean {
  return derived.Q_cap_M.gt(ZERO) && derived.U.gt(ZERO) && derived.Q_eq.gt(ZERO);
}

// ---- 评估器（供敏感性 / 情景）----
export function evaluateTarget(params: ScenarioParams, target: string): Decimal | null {
  const derived = derive(params);
  if (!isFeasible(derived)) return null;
  const unitCostResult = unitCostModule.compute(params, derived);
  if (target === sensitivityModule.TARGET_COST_PER_M) return unitCostResult.cost_per_m_capacity;
  if (target === sensitivityModule.TARGET_COST_ADVANTAGE) {
    const models = costModelModule.buildAll(params, derived);
    const demandQ = derived.Q_eq;
    // P2-1 去位置耦合：按 plan 字段定位自建方案，不再假定 models[0] 一定是 A。
    const selfBuild =
      models.find((m) => m.plan === costModelModule.PLAN_SELF_BUILD) ?? models[0];
    const selfBuildCost = selfBuild.cost(demandQ);
    const alternative = Decimal.min(
      ...models.filter((m) => m.plan !== costModelModule.PLAN_SELF_BUILD).map((m) => m.cost(demandQ)),
    );
    return alternative.minus(selfBuildCost);
  }
  const revenueResult = revenueModule.compute(params, derived, unitCostResult.C_total);
  const financialResult = financialsModule.compute(params, derived, revenueResult);
  if (target === sensitivityModule.TARGET_NPV) return financialResult.npv;
  throw new Error(`未知敏感性目标：${target}`);
}

/** P1-2 蒙特卡洛专用精简求值：只跑到 financials，不构建 KPI/成本模型/序列化载荷。
 *  数值路径（derive → unit_cost → revenue → financials）与 computeAll 完全一致，
 *  只是跳过了即算即弃结构，避免 N×T_horizon 次高精度 Decimal 无效分配（零口径风险）。 */
export function evaluateNpvIrr(params: ScenarioParams): [Decimal | null, Decimal | null] {
  const derived = derive(params);
  if (!isFeasible(derived)) return [null, null];
  const unitCostResult = unitCostModule.compute(params, derived);
  const revenueResult = revenueModule.compute(params, derived, unitCostResult.C_total);
  const financialResult = financialsModule.compute(params, derived, revenueResult);
  return [financialResult.npv, financialResult.irr.irr_annual];
}

export function evaluateKpis(params: ScenarioParams): Record<string, Decimal | null> {
  const derived = derive(params);
  if (!isFeasible(derived)) {
    return {
      npv: null, irr: null, roi: null, cost_per_m: null, payback_static: null, gross_margin: null, U_be: null,
    };
  }
  const unitCostResult = unitCostModule.compute(params, derived);
  const revenueResult = revenueModule.compute(params, derived, unitCostResult.C_total);
  const breakevenResult = breakevenModule.compute(derived, revenueResult);
  const financialResult = financialsModule.compute(params, derived, revenueResult);
  return {
    npv: financialResult.npv,
    irr: financialResult.irr.irr_annual,
    roi: financialResult.roi,
    cost_per_m: unitCostResult.cost_per_m_capacity,
    payback_static: financialResult.payback_static,
    gross_margin: revenueResult.G,
    U_be: breakevenResult.U_be,
  };
}

// ---- KPI ----
interface Kpi {
  key: string;
  label: string;
  value: Decimal | string | null;
  unit: string;
  formula_id: string;
  kind: string;
  /** P3-3 推荐方案可行性分级：viable | loss | no_demand | no_solution（仅 recommended_plan 使用） */
  status?: 'viable' | 'loss' | 'no_demand' | 'no_solution';
  /** P3-3 推荐方案分级说明文案（仅 recommended_plan 使用） */
  note?: string;
}

function kpi(key: string, label: string, value: Decimal | null, unit: string, formulaId: string, kind: string): Kpi {
  return { key, label, value, unit, formula_id: formulaId, kind };
}

function buildKpis(params: ScenarioParams, core: CoreResult, crossoverResult: crossoverModule.CrossoverResult | null): Kpi[] {
  const fin = core.financials;
  const nGpu = params.hw.N_gpu;
  const monthsPerYear = new Decimal('12');
  const daysPerMonth = new Decimal('30');
  const hoursPerMonth = new Decimal('720'); // 24h × 30d
  const revPerGpuDay = safeDiv(core.revenue.R, nGpu.times(daysPerMonth)); // P0-2 加固：N_gpu=0 时回退 0 而非抛异常
  const costPerGpuDay = safeDiv(core.unit_cost.C_total, nGpu.times(daysPerMonth));
  // 每度电产出 Token = 月产出token / 月耗电度数；
  // 月耗电 = 有效功耗 P_eff(U)×PUE×720h，P_eff(U)=P_sys·(P_idle_ratio + U·(1−P_idle_ratio))（P2 负载曲线）
  const monthlyToken = core.unit_cost.Q_out_M.times(MTOK);
  const effectivePower = core.derived.P_sys.times(
    params.power.P_idle_ratio.plus(core.derived.U.times(ONE.minus(params.power.P_idle_ratio))),
  );
  const monthlyKwh = effectivePower.times(params.power.PUE).times(hoursPerMonth);
  const tokenPerKwh = monthlyKwh.gt(ZERO) ? monthlyToken.div(monthlyKwh) : null;
  // P3-3 推荐方案可行性分级（与后端 engine.py _build_kpis 镜像）：
  // no_demand：Q_eq ≤ 0，真正无解（值 null → UI 显示无解）；
  // loss：推荐方案毛利率为负 → 仍给成本最优方案 + 红色亏损告警；
  // viable：毛利非负；no_solution：crossover 缺失兜底。
  let recommended: string | null = null;
  let recommendedStatus: 'viable' | 'loss' | 'no_demand' | 'no_solution' = 'no_solution';
  let recommendedNote = '';
  if (crossoverResult && crossoverResult.recommended.length) {
    const currentQ = core.derived.Q_eq;
    if (currentQ.lte(ZERO)) {
      recommendedStatus = 'no_demand';
      recommendedNote = '当前月需求量 ≤ 0，无法给出推荐方案。';
    } else {
      for (const segment of crossoverResult.recommended) {
        const upper = segment.to_Q;
        if (currentQ.gte(segment.from_Q) && (upper === null || currentQ.lt(upper))) {
          recommended = segment.best_label;
          if (core.revenue.G.lt(ZERO)) {
            recommendedStatus = 'loss';
            recommendedNote = '该方案为当前成本最优，但毛利率为负（等效单价低于单位成本），当前定价下不可行，建议重新议价或调整需求结构。';
          } else {
            recommendedStatus = 'viable';
          }
          break;
        }
      }
    }
  }
  return [
    kpi('cost_per_m', '每百万 token 成本', core.unit_cost.cost_per_m_capacity, '元/Mtok', 'F009', 'cost'),
    kpi('gross_margin', '月毛利', core.revenue.G, '元/月', 'F022', 'money'),
    kpi('gm_pct', '毛利率', core.revenue.GM_pct, '比率', 'F022', 'ratio'),
    kpi('npv', 'NPV', fin.npv, '元', 'F043', 'money'),
    kpi('irr', 'IRR（年化）', fin.irr.irr_annual, '比率/年', 'F046', 'ratio'),
    kpi('roi', 'ROI', fin.roi, '比率', 'F045', 'ratio'),
    kpi('tco', 'TCO（全周期）', fin.tco, '元', 'F044', 'money'),
    kpi('payback_static', '静态回本', fin.payback_static, '月', 'F047', 'months'),
    kpi('payback_discounted', '折现回本', fin.payback_discounted, '月', 'F047', 'months'),
    kpi('U_be', '盈亏平衡利用率', core.breakeven.U_be, '比率', 'F031', 'ratio'),
    kpi('p_eq', '等效单价', core.revenue.p_eq, '元/Mtok', 'F021', 'cost'),
    { key: 'recommended_plan', label: '当前需求下推荐方案', value: recommended, unit: '', formula_id: 'F054', kind: 'text', status: recommendedStatus, note: recommendedNote },
    // ---- 增量 KPI（追加至末尾，不挪动 0–11 序） ----
    kpi('debt_ratio', '资产负债率', core.financials.financing.debt_ratio, '比率', 'F062', 'ratio'),
    kpi('interest_coverage', '利息覆盖倍数', core.financials.financing.interest_coverage, '倍', 'F063', 'number'),
    kpi('roe', '权益回报率 ROE', core.financials.financing.roe, '比率', 'F063', 'ratio'),
    kpi('levered_npv', '杠杆后 NPV', core.financials.financing.levered_npv, '元', 'F063', 'money'),
    kpi('levered_irr', '杠杆后 IRR', core.financials.financing.levered_irr, '比率/年', 'F063', 'ratio'),
    // ---- P0 管理驾驶舱 KPI（追加至末尾，不挪动 0–11 序 / 杠杆后序列） ----
    kpi('rev_per_gpu_day', '每卡每天收入', revPerGpuDay, '元/卡/天', 'F071', 'money'),
    kpi('cost_per_gpu_day', '每卡每天成本(全)', costPerGpuDay, '元/卡/天', 'F072', 'money'),
    kpi('token_per_kwh', '每度电产出 Token', tokenPerKwh, 'Token/度', 'F073', 'count'),
    // ---- P1 SLA 赔偿计提 + 资源包/递延收入（追加至末尾，不挪动 0–11 / 杠杆后序列） ----
    kpi(
      'sla_provision_monthly',
      'SLA 赔偿计提(月)',
      core.revenue.R.times(params.perf.SLA_penalty_rate),
      '元/月',
      'F081',
      'money',
    ),
    kpi(
      'sla_provision_total',
      'SLA 赔偿计提(全周期)',
      fin.total_revenue.times(params.perf.SLA_penalty_rate),
      '元',
      'F081',
      'money',
    ),
    ...deferredRevenueKpis(params, core),
    // ---- P2 负载率功耗曲线 + 单位成本学习曲线（追加至末尾，不挪动既有序列） ----
    kpi('idle_power_cost', '待机功耗固定成本(月)', core.derived.C_power_idle_m, '元/月', 'F091', 'money'),
    kpi(
      'learning_terminal_factor',
      '学习曲线期末系数',
      params.finance.cost_learning_rate.ne(ZERO)
        ? dpow(ONE.minus(params.finance.cost_learning_rate), params.finance.T_horizon.div(MONTHS_PER_YEAR))
        : ONE,
      '比率',
      'F092',
      'ratio',
    ),
    // ---- 电力运维口径：柜电分离 / 包柜包电 ----
    kpi('racks_count', '机柜数', core.derived.racks, '柜', 'F093', 'count'),
    kpi('bundle_rack_cost_m', '包柜包电月成本', core.derived.bundle_rack_cost_m, '元/月', 'F094', 'money'),
  ];
}

/** P1 资源包/递延收入（合同负债）报告型 KPI：预收费→消耗→确认→合同负债余额链路。
 *  仅在 pkg_enabled 且消耗周期>0 时计算；否则返回空数组（UI 显示「—」）。 */
function deferredRevenueKpis(params: ScenarioParams, core: CoreResult): Kpi[] {
  const p = params.pricing;
  if (!p.pkg_enabled || p.pkg_consume_months.lte(ZERO) || p.pkg_prepaid.lte(ZERO)) return [];
  const prepaid = p.pkg_prepaid;
  const consumeMonths = p.pkg_consume_months;
  const recognizedMonthly = prepaid.div(consumeMonths); // 每月确认收入（线性）
  const monthlyConsumption = p.pkg_tokens.div(consumeMonths); // 每月消耗 Token（Mtok/月）
  const t = params.finance.T_horizon.div(consumeMonths);
  let unearnedShare = ONE.minus(t); // 期末未确认占比
  if (unearnedShare.lt(ZERO)) unearnedShare = ZERO;
  const deferredEnd = prepaid.times(unearnedShare); // 期末合同负债余额
  const cashMonths = core.revenue.R.gt(ZERO) ? prepaid.div(core.revenue.R) : null; // 预付费现金跑道（月）
  return [
    kpi('deferred_revenue', '合同负债(初始)', prepaid, '元', 'F082', 'money'),
    kpi('rev_recognized_monthly', '每月确认收入', recognizedMonthly, '元/月', 'F082', 'money'),
    kpi('cash_prepaid', '预收现金(一次性)', prepaid, '元', 'F082', 'money'),
    kpi('deferred_revenue_end', '期末合同负债', deferredEnd, '元', 'F082', 'money'),
    kpi('unearned_share', '未确认占比', unearnedShare, '比率', 'F082', 'ratio'),
    kpi('monthly_consumption', '每月消耗Token', monthlyConsumption, 'Mtok/月', 'F082', 'count'),
    ...(cashMonths !== null
      ? [kpi('prepaid_cash_months', '预付费现金跑道', cashMonths, '月', 'F082', 'months')]
      : []),
  ];
}

// ---- 序列化 ----
function derivedDict(d: DerivedParams): Record<string, unknown> {
  return {
    CAPEX: d.CAPEX, P_sys: d.P_sys, Dep_m: d.Dep_m, C_fix_cash: d.C_fix_cash, C_fix_acct: d.C_fix_acct,
    C_var_per_U: d.C_var_per_U, C_power_idle_m: d.C_power_idle_m, bundle_rack_cost_m: d.bundle_rack_cost_m, racks: d.racks, weighted_e_price: d.weighted_e_price, Q_cap_M: d.Q_cap_M, k: d.k, k_source: d.k_source, power_mode: d.power_mode,
    factor: d.factor, D_out: d.D_out, D_in: d.D_in, Q_eq: d.Q_eq, U: d.U, U_implied: d.U_implied, I0: d.I0, SV: d.SV,
    r_m: d.r_m, dep_months: d.dep_months,
  };
}

function cashflowDict(row: financialsModule.CashflowRow): Record<string, unknown> {
  return {
    period: row.period, period_type: row.period_type, revenue: row.revenue, opex_cash: row.opex_cash,
    depreciation: row.depreciation, ebt: row.ebt, interest: row.interest, principal: row.principal,
    tax: row.tax, net_cf: row.net_cf, cum_cf: row.cum_cf,
    discount_factor: row.discount_factor, discount_ratio: row.discount_ratio, discounted_cf: row.discounted_cf, cum_discounted_cf: row.cum_discounted_cf,
  };
}

function financialsDict(fin: FinancialResult): Record<string, unknown> {
  const finStruct = fin.financing;
  return {
    I0: fin.I0, SV: fin.SV, r_m: fin.r_m, npv: fin.npv, roi: fin.roi, tco: fin.tco,
    total_revenue: fin.total_revenue, total_opex_cash: fin.total_opex_cash, total_tax: fin.total_tax,
    total_net_cf: fin.total_net_cf, payback_static: fin.payback_static, payback_discounted: fin.payback_discounted,
    irr: {
      solution: fin.irr.solution, irr_monthly: fin.irr.irr_monthly, irr_annual: fin.irr.irr_annual,
      roots_monthly: fin.irr.roots_monthly, mirr_monthly: fin.irr.mirr_monthly, mirr_annual: fin.irr.mirr_annual,
      method: fin.irr.method, note: fin.irr.note, iterations: fin.irr.iterations,
    },
    financing: {
      debt_ratio: finStruct.debt_ratio,
      debt: finStruct.debt,
      equity: finStruct.equity,
      interest_total: finStruct.interest_total,
      principal_total: finStruct.principal_total,
      interest_coverage: finStruct.interest_coverage,
      roe: finStruct.roe,
      levered_npv: finStruct.levered_npv,
      levered_irr: finStruct.levered_irr,
    },
    cashflows: fin.cashflows.map(cashflowDict),
    cashflows_yearly: fin.cashflows_yearly.map(cashflowDict),
    notes: fin.notes,
  };
}

function crossoverDict(result: crossoverModule.CrossoverResult): Record<string, unknown> {
  return {
    curves: result.curves.map((curve) => ({
      plan: curve.plan, label: curve.label, a: curve.a, b: curve.b,
      points: curve.points.map((p) => ({ Q: p.Q, total_cost: p.total_cost, unit_cost: p.unit_cost })),
    })),
    crossovers: result.crossovers.map((item) => ({
      plans: item.plans, Q: item.Q, active: item.active, status: item.status, note: item.note,
    })),
    recommended: result.recommended.map((segment) => ({
      from_Q: segment.from_Q, to_Q: segment.to_Q, best_plan: segment.best_plan, best_label: segment.best_label,
    })),
    q_max: result.q_max, capacity_wall: result.capacity_wall, notes: result.notes,
  };
}

function sensitivityDict(result: SensitivityResult): Record<string, unknown> {
  return {
    target: result.target, target_label: result.target_label, delta: result.delta, base: result.base,
    items: result.items.map((item) => ({
      param: item.param, label: item.label, base: item.base, low: item.low, high: item.high,
      delta_low: item.delta_low, delta_high: item.delta_high, swing: item.swing, swing_pct: item.swing_pct,
      low_feasible: item.low_feasible, high_feasible: item.high_feasible, note: item.note,
    })),
    notes: result.notes,
  };
}

function scenariosDict(result: ScenarioSetResult): Record<string, unknown> {
  return {
    cases: result.cases.map((item) => ({
      key: item.key, label: item.label, multipliers: item.multipliers, kpis: item.kpis,
      feasible: item.feasible, note: item.note,
    })),
    notes: result.notes,
  };
}

function jointDict(result: JointSensitivityResult): Record<string, unknown> {
  return {
    npv_min: result.npv_min,
    npv_max: result.npv_max,
    percentiles: result.percentiles,
    main_effects: result.main_effects,
    interactions: result.interactions,
    notes: result.notes,
  };
}

function customScenariosDict(result: CustomScenarioSet): Record<string, unknown> {
  return {
    cases: result.cases.map((item) => ({
      key: item.key, label: item.label, overrides: item.overrides, kpis: item.kpis,
      feasible: item.feasible, note: item.note,
    })),
    notes: result.notes,
  };
}

// ---- 入口 ----
export function computeAll(
  params: ScenarioParams,
  options: EngineOptions = DEFAULT_OPTIONS,
): Record<string, unknown> {
  const core = computeCore(params);

  let crossoverResult: crossoverModule.CrossoverResult | null = null;
  if (options.include_crossover) {
    crossoverResult = crossoverModule.compute(
      core.cost_models as unknown as costModelModule.CostModelLike[],
      core.derived.Q_eq,
      core.derived.Q_cap_M,
    );
  }

  let sensitivityResult: SensitivityResult | null = null;
  if (options.include_sensitivity) {
    sensitivityResult = sensitivityModule.compute(params, evaluateTarget, options.sensitivity_target, options.sensitivity_delta);
  }

  let scenariosResult: ScenarioSetResult | null = null;
  if (options.include_scenarios) {
    scenariosResult = scenarioModule.compute(params, evaluateKpis);
  }

  // ---- 增量：多因素联合敏感性（确定性网格 + 方差分解） ----
  let jointResult: JointSensitivityResult | null = null;
  if (options.include_joint) {
    const registry = sensitivityModule.varRegistry();
    const jointVars = (options.joint_vars ?? ['U', 'E_price'])
      .filter((k) => k in registry)
      .map((k) => registry[k]);
    const effectiveVars = jointVars.length ? jointVars : sensitivityModule.JOINT_DEFAULT_VARS.slice(0, 2);
    jointResult = sensitivityModule.computeJoint(
      params,
      evaluateTarget,
      options.joint_target ?? sensitivityModule.TARGET_NPV,
      options.joint_delta ?? new Decimal('0.2'),
      effectiveVars,
    );
  }

  // ---- 增量：自定义情景（任意 K 组参数覆盖，并列 KPI） ----
  let customScenariosResult: CustomScenarioSet | null = null;
  if (options.include_custom_scenarios && options.custom_scenario_specs && options.custom_scenario_specs.length) {
    customScenariosResult = scenarioModule.computeCustom(params, options.custom_scenario_specs, evaluateKpis);
  }

  const demandQ = core.derived.Q_eq;
  const payload: Record<string, unknown> = {
    engine_version: ENGINE_VERSION,
    formula_spec_version: FORMULA_SPEC_VERSION,
    authoritative: false,
    conventions: core.derived ? params.conventions : params.conventions,
    params: {},
    derived: derivedDict(core.derived),
    throughput: {
      T_eff: core.throughput.T_eff, Q_cap_M: core.throughput.Q_cap_M, Q_out_M: core.throughput.Q_out_M,
      k: core.throughput.k, k_source: core.throughput.k_source, k_source_label: core.throughput.k_source_label,
      capacity_headroom: core.throughput.capacity_headroom, over_capacity: core.throughput.over_capacity,
    },
    unit_cost: {
      C_fix_acct: core.unit_cost.C_fix_acct, C_fix_cash: core.unit_cost.C_fix_cash, C_var: core.unit_cost.C_var,
      C_total: core.unit_cost.C_total, C_total_cash: core.unit_cost.C_total_cash, Q_out_M: core.unit_cost.Q_out_M,
      cost_per_m_capacity: core.unit_cost.cost_per_m_capacity, cost_per_m_demand: core.unit_cost.cost_per_m_demand,
      c_unit: core.unit_cost.c_unit,
      breakdown: core.unit_cost.breakdown.map((item) => ({ key: item.key, label: item.label, amount: item.amount, share: item.share })),
    },
    revenue: {
      R: core.revenue.R, revenue_in: core.revenue.revenue_in, revenue_out: core.revenue.revenue_out,
      p_eq: core.revenue.p_eq, p_in_blended: core.revenue.p_in_blended, G: core.revenue.G, GM_pct: core.revenue.GM_pct,
      g_per_m: core.revenue.g_per_m, g_per_token: core.revenue.g_per_token,
    },
    breakeven: {
      feasible: core.breakeven.feasible, M_U: core.breakeven.M_U, U_be: core.breakeven.U_be, Q_be: core.breakeven.Q_be,
      p_be: core.breakeven.p_be, note: core.breakeven.note,
      curve: core.breakeven.curve.map((point) => ({ U: point.U, revenue: point.revenue, cost: point.cost })),
    },
    cost_models: core.cost_models.map((model) => ({
      plan: model.plan, label: model.name(), a: model.a, b: model.b,
      cost_at_demand: model.cost(demandQ), unit_cost_at_demand: safeDiv(model.cost(demandQ), demandQ),
    })),
    crossover: crossoverResult ? crossoverDict(crossoverResult) : null,
    financials: financialsDict(core.financials),
    sensitivity: sensitivityResult ? sensitivityDict(sensitivityResult) : null,
    scenarios: scenariosResult ? scenariosDict(scenariosResult) : null,
    joint: jointResult ? jointDict(jointResult) : null,
    custom_scenarios: customScenariosResult ? customScenariosDict(customScenariosResult) : null,
    kpis: buildKpis(params, core, crossoverResult),
    warnings: core.warnings,
    disclaimer:
      '本平台测算结果完全基于用户输入假设与行业基准，不构成任何投资承诺或建议；实际决策须结合尽调与专业意见。',
  };
  payload.params = paramsToDict(params);
  return payload;
}

export function unitCostPerToken(payload: Record<string, unknown>): Decimal {
  const costPerM = (payload.unit_cost as Record<string, Decimal>).cost_per_m_capacity;
  return (costPerM instanceof Decimal ? costPerM : new Decimal(String(costPerM))).div(MTOK);
}
