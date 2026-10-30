/** 投资财务指标：现金流 / NPV / TCO / ROI / 回本。对齐后端 `app/calc/financials.py`。
 *
 * 增量能力（见 docs/03-Incremental-Design.md）：
 * ① 融资结构（债务杠杆）：债务余额递推 → 利息/本金/税盾/权益 CF；`npv`/`irr` 自然延伸为杠杆后口径；
 * ④ 需求逐年增长（g_demand）：月序列 `D_t = D·(1+g_demand)^floor((t−1)/12)` 缩放收入与变动成本。
 * 默认参数下完全退化为现状（debt_ratio=0、g_demand=0）。
 */

import { D, MONTHS_PER_YEAR, ONE, ZERO, Decimal, dpow, dmax, dsum, safeDiv } from './decimalConfig';
import { DerivedParams, ScenarioParams } from './parameters';
import { RevenueResult } from './revenue';
import { IrrResult, compute as computeIrr } from './irr';

export const PERIOD_MONTH = 'month';
export const PERIOD_YEAR = 'year';

export interface CashflowRow {
  period: number;
  period_type: string;
  revenue: Decimal;
  opex_cash: Decimal;
  depreciation: Decimal;
  ebt: Decimal;
  interest: Decimal;
  principal: Decimal;
  tax: Decimal;
  net_cf: Decimal;
  cum_cf: Decimal;
  discount_factor: Decimal;
  discount_ratio: Decimal;
  discounted_cf: Decimal;
  cum_discounted_cf: Decimal;
}

export interface FinancingResult {
  debt_ratio: Decimal;
  debt: Decimal;
  equity: Decimal;
  interest_total: Decimal;
  principal_total: Decimal;
  interest_coverage: Decimal | null;
  roe: Decimal;
  levered_npv: Decimal;
  levered_irr: Decimal | null;
}

export interface FinancialResult {
  I0: Decimal;
  SV: Decimal;
  r_m: Decimal;
  npv: Decimal;
  roi: Decimal;
  tco: Decimal;
  total_revenue: Decimal;
  total_opex_cash: Decimal;
  total_tax: Decimal;
  total_net_cf: Decimal;
  sla_provision_total: Decimal; // SLA 赔偿计提合计（元，= Σ R_t × SLA_penalty_rate）
  payback_static: Decimal | null;
  payback_discounted: Decimal | null;
  irr: IrrResult;
  financing: FinancingResult;
  cashflows: CashflowRow[];
  cashflows_yearly: CashflowRow[];
  notes: string[];
}

function rampFactor(period: number, params: ScenarioParams): Decimal {
  if (!params.finance.revenue_ramp) return ONE;
  const tDeploy = params.hw.T_deploy;
  if (tDeploy.lte(ZERO) || new Decimal(period).gt(tDeploy)) return ONE;
  return new Decimal(period).div(tDeploy);
}

function yearBucket(rows: CashflowRow[], rM: Decimal): CashflowRow[] {
  const yearly: CashflowRow[] = [];
  let cumCf = ZERO;
  let cumDisc = ZERO;
  let bucket: CashflowRow[] = [];
  for (const row of rows) {
    bucket.push(row);
    if (bucket.length === Number(MONTHS_PER_YEAR) || row === rows[rows.length - 1]) {
      const yearIndex = yearly.length + 1;
      const revenue = dsum(bucket.map((r) => r.revenue));
      const opex = dsum(bucket.map((r) => r.opex_cash));
      const dep = dsum(bucket.map((r) => r.depreciation));
      const ebt = dsum(bucket.map((r) => r.ebt));
      const interest = dsum(bucket.map((r) => r.interest));
      const principal = dsum(bucket.map((r) => r.principal));
      const tax = dsum(bucket.map((r) => r.tax));
      const netCf = dsum(bucket.map((r) => r.net_cf));
      const disc = dsum(bucket.map((r) => r.discounted_cf));
      cumCf = cumCf.plus(netCf);
      cumDisc = cumDisc.plus(disc);
      yearly.push({
        period: yearIndex,
        period_type: PERIOD_YEAR,
        revenue,
        opex_cash: opex,
        depreciation: dep,
        ebt,
        interest,
        principal,
        tax,
        net_cf: netCf,
        cum_cf: cumCf,
        discount_factor: ONE.div(dpow(ONE.plus(rM), MONTHS_PER_YEAR.times(yearIndex))),
        discount_ratio: safeDiv(disc, netCf, ONE),
        discounted_cf: disc,
        cum_discounted_cf: cumDisc,
      });
      bucket = [];
    }
  }
  return yearly;
}

function interpolatePayback(
  threshold: Decimal,
  cumulative: Array<[number, Decimal, Decimal]>,
): Decimal | null {
  let previous = ZERO;
  for (const [period, cumValue, flow] of cumulative) {
    if (cumValue.gte(threshold)) {
      if (flow.eq(ZERO)) return new Decimal(period);
      let fraction = threshold.minus(previous).div(flow);
      if (fraction.lt(ZERO)) fraction = ZERO;
      if (fraction.gt(ONE)) fraction = ONE;
      return new Decimal(period - 1).plus(fraction);
    }
    previous = cumValue;
  }
  return null;
}

export function compute(
  params: ScenarioParams,
  derived: DerivedParams,
  rev: RevenueResult,
): FinancialResult {
  const finance = params.finance;
  const horizon = Number(finance.T_horizon);
  const notes: string[] = [];

  // ----------------------------------------------------------------- 融资派生
  const debtRatio = finance.debt_ratio;
  const debt = derived.I0.times(debtRatio);
  const equity = derived.I0.times(ONE.minus(debtRatio));
  const debtRateMonth = finance.debt_rate.div(MONTHS_PER_YEAR);
  const loanTerm = Number(finance.loan_term_months);
  let bal = debt; // 上期末债务余额（bal_0 = debt）

  const rows: CashflowRow[] = [];
  let cumCf = ZERO;
  let cumDisc = ZERO;
  const onePlusRm = ONE.plus(derived.r_m);

  let interestTotal = ZERO;
  let principalTotal = ZERO;
  const coverageCandidates: Decimal[] = []; // 仅利息 > 0 的月份

  // P0-1 加固：年化缩放底数夹紧（增长率/通胀率/学习率越界时降级而非产生 NaN/中断）
  // decimal.js 对非整数幂的负底数返回 NaN；把非法底数夹到 1e-6 并记录告警（与后端逐位一致）。
  const priceBase = ONE.plus(params.pricing.g_price);
  const inflBase = ONE.plus(finance.infl);
  const learnBase = ONE.minus(params.finance.cost_learning_rate);
  const scaleClamped = priceBase.lte(ZERO) || inflBase.lte(ZERO) || learnBase.lte(ZERO);
  const safePriceBase = priceBase.gt(ZERO) ? priceBase : new Decimal('1e-6');
  const safeInflBase = inflBase.gt(ZERO) ? inflBase : new Decimal('1e-6');
  const safeLearnBase = learnBase.gt(ZERO) ? learnBase : new Decimal('1e-6');

  for (let period = 1; period <= horizon; period++) {
    const ramp = rampFactor(period, params);
    const exponent = new Decimal(period - 1).div(MONTHS_PER_YEAR);
    const gPrice = params.pricing.g_price;
    const priceScale = gPrice.ne(ZERO) ? dpow(safePriceBase, exponent) : ONE;
    const inflScale = finance.infl.ne(ZERO) ? dpow(safeInflBase, exponent) : ONE;

    // ---- ④ 需求逐年增长：D_t = D·(1+g_demand)^floor((t-1)/12) ----
    const yearIndex = new Decimal(period - 1).divToInt(MONTHS_PER_YEAR); // 整数幂，走精确 pow
    const demandGrowth = dpow(ONE.plus(params.demand.g_demand), yearIndex);
    // 退化：g_demand=0 ⇒ demandGrowth=1

    // ---- P2 单位成本学习曲线：可变 opex 随周期递减 learningFactor=(1−rate)^(t/12) ----
    // 默认 cost_learning_rate=0 ⇒ learningFactor=1（不变，黄金向量零回归）。
    const learningRate = params.finance.cost_learning_rate;
    const learningFactor = learningRate.ne(ZERO) ? dpow(safeLearnBase, exponent) : ONE;

    const revenue = rev.R.times(demandGrowth).times(priceScale).times(ramp);
    const opexCash = derived.C_fix_cash
      .plus(derived.C_var_per_U.times(derived.U).times(demandGrowth).times(learningFactor))
      .times(inflScale)
      .plus(revenue.times(params.perf.SLA_penalty_rate)); // P1 SLA 赔偿拨备（占月收入比率）

    // ---- ① 融资：债务余额递推 → 利息/本金 ----
    const interest = bal.gt(ZERO) ? bal.times(debtRateMonth) : ZERO;
    let principal: Decimal;
    if (period <= loanTerm && loanTerm > 0 && debt.gt(ZERO)) {
      principal = period === loanTerm ? bal : debt.div(new Decimal(loanTerm)); // 末月结清余数（直线摊销）
    } else {
      principal = ZERO;
    }

    const depreciation = new Decimal(period).lte(derived.dep_months) ? derived.Dep_m : ZERO;
    const ebt = revenue.minus(opexCash).minus(depreciation).minus(interest);
    const tax = params.conventions.taxed ? dmax(ZERO, ebt).times(finance.Tax) : ZERO;
    let netCf = revenue.minus(opexCash).minus(interest).minus(principal).minus(tax);
    if (period === horizon) netCf = netCf.plus(derived.SV); // 期末残值计入最后一期现金流

    // 余额递推（精确减法）
    bal = bal.gt(ZERO) ? bal.minus(principal) : ZERO;

    // 利息覆盖倍数候选（仅利息 > 0 月份，EBIT = EBT + interest）
    if (interest.gt(ZERO)) {
      const ebit = ebt.plus(interest);
      coverageCandidates.push(safeDiv(ebit, interest));
    }

    interestTotal = interestTotal.plus(interest);
    principalTotal = principalTotal.plus(principal);

    cumCf = cumCf.plus(netCf);
    const discountFactor = ONE.div(dpow(onePlusRm, new Decimal(period)));
    const discounted = netCf.times(discountFactor);
    cumDisc = cumDisc.plus(discounted);

    rows.push({
      period,
      period_type: PERIOD_MONTH,
      revenue,
      opex_cash: opexCash,
      depreciation,
      ebt,
      interest,
      principal,
      tax,
      net_cf: netCf,
      cum_cf: cumCf,
      discount_factor: discountFactor,
      discount_ratio: safeDiv(discounted, netCf, ONE),
      discounted_cf: discounted,
      cum_discounted_cf: cumDisc,
    });
  }

  const totalRevenue = dsum(rows.map((r) => r.revenue));
  const totalOpex = dsum(rows.map((r) => r.opex_cash));
  const totalTax = dsum(rows.map((r) => r.tax));
  const totalCf = dsum(rows.map((r) => r.net_cf));
  if (scaleClamped) {
    notes.push(
      '年化缩放因子底数出现非正（年价格变动/通胀率 ≤ −100%，或学习曲线年降幅 ≥ 100%），已夹紧至 1e-6 计算，结果仅作下限参考，请修正参数后重算。',
    );
  }
  const slaProvisionTotal = totalRevenue.times(params.perf.SLA_penalty_rate); // P1 SLA 赔偿计提合计

  // `npv` 键随债务比自然延伸为「杠杆后（权益口径）」：`−equity + Σ 折现 net_cf`；
  // debt_ratio=0 时 equity=I0 ⇒ 与现状 `−I0 + Σ 折现 net_cf` 逐位一致（退化不变）。
  const npv = equity.negated().plus(cumDisc);
  const tco = derived.CAPEX.plus(totalOpex);
  const roi = safeDiv(totalCf.minus(derived.I0), derived.I0);

  const paybackStatic = interpolatePayback(
    derived.I0,
    rows.map((r) => [r.period, r.cum_cf, r.net_cf] as [number, Decimal, Decimal]),
  );
  const paybackDiscounted = interpolatePayback(
    derived.I0,
    rows.map((r) => [r.period, r.cum_discounted_cf, r.discounted_cf] as [number, Decimal, Decimal]),
  );
  if (paybackStatic === null) notes.push(`分析周期 ${horizon} 个月内未收回期初投资（静态回本 > 周期）。`);
  if (paybackDiscounted === null) notes.push(`分析周期 ${horizon} 个月内折现累计现金流未转正（折现回本 > 周期）。`);
  if (!params.conventions.taxed) notes.push('当前为税前口径（Taxed=false）：现金流未扣税，亦未计折旧税盾。');

  // ---- ① 融资：权益现金流与杠杆指标 ----
  // equity_cf_0 = −equity；权益 CF = 现状 CF（debt_ratio=0 时 equity=I0）
  const equityCashflows: Decimal[] = [equity.negated(), ...rows.map((r) => r.net_cf)];
  const irrResult = computeIrr(equityCashflows, derived.r_m, derived.r_m);
  const roe = safeDiv(totalCf, equity); // Σ_{t≥1} equity_cf_t / equity（现金流回馈倍数）
  const interestCoverage = coverageCandidates.length
    ? Decimal.min(...coverageCandidates)
    : null;

  const financing: FinancingResult = {
    debt_ratio: debtRatio,
    debt,
    equity,
    interest_total: interestTotal,
    principal_total: principalTotal,
    interest_coverage: interestCoverage,
    roe,
    levered_npv: npv,
    levered_irr: irrResult.irr_annual,
  };

  return {
    I0: derived.I0,
    SV: derived.SV,
    r_m: derived.r_m,
    npv,
    roi,
    tco,
    total_revenue: totalRevenue,
    total_opex_cash: totalOpex,
    total_tax: totalTax,
    total_net_cf: totalCf,
    sla_provision_total: slaProvisionTotal,
    payback_static: paybackStatic,
    payback_discounted: paybackDiscounted,
    irr: irrResult,
    financing,
    cashflows: rows,
    cashflows_yearly: yearBucket(rows, derived.r_m),
    notes,
  };
}
