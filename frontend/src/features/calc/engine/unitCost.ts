/** 单位 token 成本推导链。对齐后端 `app/calc/unit_cost.py`。 */

import { D, MONTHS_PER_YEAR, MTOK, ONE, ZERO, Decimal, safeDiv } from './decimalConfig';
import { DerivedParams, POWER_MODE_BUNDLE, ScenarioParams } from './parameters';

export interface CostBreakdownItem {
  key: string;
  label: string;
  amount: Decimal;
  share: Decimal;
}

export interface UnitCostResult {
  C_fix_acct: Decimal;
  C_fix_cash: Decimal;
  C_var: Decimal;
  C_total: Decimal;
  C_total_cash: Decimal;
  Q_out_M: Decimal;
  cost_per_m_capacity: Decimal;
  cost_per_m_demand: Decimal;
  c_unit: Decimal;
  context_uplift: Decimal; // C-4 长上下文成本上浮因子（≥1；短链=1，黄金向量零回归）
  breakdown: CostBreakdownItem[];
}

// C-4 长上下文成本曲线（InferenceX AgentX 方法论）：长上下文使 prefill 需重算未命中部分，
// 成本随 Ctx 线性上浮；但缓存命中 h 摊薄（h 越高，需重算比例越低）。
// 公式：uplift = 1 + CTX_UPLIFT_K · max(Ctx/8192 − 1, 0) · (1 − h)
const CTX_UPLIFT_K = new Decimal('1.0');
const SHORT_CTX = new Decimal('8192');

/** C-4：长上下文成本上浮因子（≥1）。纯函数。 */
export function contextUpliftFactor(params: ScenarioParams): Decimal {
  const perf = params.perf;
  if (perf.Ctx.lte(SHORT_CTX)) return ONE;
  const longRatio = perf.Ctx.div(SHORT_CTX).minus(ONE);
  const miss = ONE.minus(params.demand.h); // 未命中比例（需重算 prefill 的部分）
  return ONE.plus(CTX_UPLIFT_K.times(longRatio).times(miss));
}

export function compute(params: ScenarioParams, derived: DerivedParams): UnitCostResult {
  const cVar = derived.C_var_per_U.times(derived.U);
  const cTotal = derived.C_fix_acct.plus(cVar);
  const cTotalCash = derived.C_fix_cash.plus(cVar);
  const qOut = derived.Q_cap_M.times(derived.U);

  // ---- C-4 长上下文成本曲线：长上下文 prefill 重算成本随 Ctx 上浮（h 摊薄） ----
  const uplift = contextUpliftFactor(params);
  const costPerMCapacity = safeDiv(cTotal, qOut).times(uplift);
  const costPerMDemand = safeDiv(cTotal, derived.Q_eq).times(uplift);

  // ---- 电力运维口径：柜电分离（机柜托管 Co_loc + 电费） / 包柜包电（一口价入固定） ----
  const bundle = params.power.power_mode === POWER_MODE_BUNDLE;
  const raw: Array<[string, string, Decimal]> = [
    ['depreciation', '折旧摊销', derived.Dep_m],
    ['power', '电费', cVar],
    ['power_idle', '待机功耗', derived.C_power_idle_m],
    ['colocation', bundle ? '包柜包电' : '机柜托管', bundle ? derived.bundle_rack_cost_m : params.power.Co_loc],
    ['network', '网络带宽', params.power.Co_net],
    ['storage', '存储', params.power.Co_stor],
    ['ops', '运维人力', params.power.Co_ops.div(MONTHS_PER_YEAR)],
    ['eng', '研发与平台人力', params.power.Co_eng.div(MONTHS_PER_YEAR)],
    ['sales_admin', '销售与管理费用', params.power.Co_sales_admin.div(MONTHS_PER_YEAR)],
    ['other', '其他运营费用', params.power.Co_other.div(MONTHS_PER_YEAR)],
    ['software', '软件许可', params.hw.L_sw.div(MONTHS_PER_YEAR)],
  ];
  const breakdown = raw
    .filter(([, , amount]) => D(amount).ne(ZERO))
    .map(([key, label, amount]) => {
      const dec = D(amount);
      return { key, label, amount: dec, share: safeDiv(dec, cTotal) };
    });

  return {
    C_fix_acct: derived.C_fix_acct,
    C_fix_cash: derived.C_fix_cash,
    C_var: cVar,
    C_total: cTotal,
    C_total_cash: cTotalCash,
    Q_out_M: qOut,
    cost_per_m_capacity: costPerMCapacity,
    cost_per_m_demand: costPerMDemand,
    c_unit: costPerMCapacity.div(MTOK),
    context_uplift: uplift,
    breakdown,
  };
}
