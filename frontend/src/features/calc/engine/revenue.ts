/** 收入与毛利。对齐后端 `app/calc/revenue.py`（已修正 PRD 附录 C 量纲错误）。 */

import { MTOK, ONE, ZERO, Decimal, safeDiv } from './decimalConfig';
import { DerivedParams, ScenarioParams, pricingCacheEffective } from './parameters';

export interface RevenueResult {
  R: Decimal;
  revenue_in: Decimal;
  revenue_out: Decimal;
  p_eq: Decimal;
  p_in_blended: Decimal;
  G: Decimal;
  GM_pct: Decimal;
  g_per_m: Decimal;
  g_per_token: Decimal;
  // C-1 双口径：市场公允成本标杆口径（对标 InferenceX y_costh）
  cost_benchmark_total: Decimal | null;
  G_benchmark: Decimal | null;
  GM_pct_benchmark: Decimal | null;
  loss_vs_benchmark: boolean;
}

export function blendedInputPrice(params: ScenarioParams): Decimal {
  const { pricing } = params;
  const h = params.demand.h;
  return ONE.minus(h).times(pricing.p_in).plus(h.times(pricingCacheEffective(pricing)));
}

export function monthlyRevenue(params: ScenarioParams, derived: DerivedParams): Decimal {
  return derived.D_in.times(blendedInputPrice(params)).plus(derived.D_out.times(params.pricing.p_out));
}

export function compute(
  params: ScenarioParams,
  derived: DerivedParams,
  cTotal: Decimal,
): RevenueResult {
  const pInBlended = blendedInputPrice(params);
  const revenueIn = derived.D_in.times(pInBlended);
  const revenueOut = derived.D_out.times(params.pricing.p_out);
  const total = revenueIn.plus(revenueOut);

  const pEq = safeDiv(total, derived.Q_eq);
  const gross = total.minus(cTotal);
  // C-1 双口径：市场公允成本标杆（对标 InferenceX y_costh）
  const cb = params.pricing.cost_benchmark;
  let costBenchmarkTotal: Decimal | null = null;
  let grossBenchmark: Decimal | null = null;
  let gmBenchmark: Decimal | null = null;
  let lossVsBenchmark = false;
  if (cb != null && cb.gt(ZERO) && derived.Q_eq.gt(ZERO)) {
    costBenchmarkTotal = derived.Q_eq.times(cb);
    grossBenchmark = total.minus(costBenchmarkTotal);
    gmBenchmark = safeDiv(grossBenchmark, total);
    lossVsBenchmark = pEq.lt(cb); // 等效售价 < 成本标杆 ⇒ 单位亏损
  }
  return {
    R: total,
    revenue_in: revenueIn,
    revenue_out: revenueOut,
    p_eq: pEq,
    p_in_blended: pInBlended,
    G: gross,
    GM_pct: safeDiv(gross, total),
    g_per_m: safeDiv(gross, derived.Q_eq),
    g_per_token: safeDiv(gross, derived.Q_eq).div(MTOK),
    cost_benchmark_total: costBenchmarkTotal,
    G_benchmark: grossBenchmark,
    GM_pct_benchmark: gmBenchmark,
    loss_vs_benchmark: lossVsBenchmark,
  };
}
