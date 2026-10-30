/** 三方案统一线性成本模型 `C(Q) = a + b·Q`。对齐后端 `app/calc/cost_model.py`。 */

import { D, H, MONTHS_PER_YEAR, ONE, ZERO, Decimal, safeDiv } from './decimalConfig';
import {
  DerivedParams,
  PricingParams,
  RENT_INC_NONE,
  RENT_INC_POWER,
  RENT_INC_POWER_HOSTING,
  ScenarioParams,
  apiCacheEffective,
} from './parameters';

export const PLAN_SELF_BUILD = 'self_build';
export const PLAN_RENT = 'rent';
export const PLAN_API = 'api';
export const PLAN_HYBRID = 'hybrid';

export const PLAN_LABELS: Record<string, string> = {
  [PLAN_SELF_BUILD]: '方案A 自建',
  [PLAN_RENT]: '方案B 租用',
  [PLAN_API]: '方案C 第三方 API',
  [PLAN_HYBRID]: '方案D 混合部署',
};

export interface CostCurvePoint {
  Q: Decimal;
  total_cost: Decimal;
  unit_cost: Decimal;
}

export interface CostModelLike {
  plan: string;
  a: Decimal;
  b: Decimal;
  cost(q: Decimal): Decimal;
  unitCost(q: Decimal): Decimal;
  name(): string;
  toDict(): { plan: string; label: string; a: Decimal; b: Decimal };
}

export abstract class CostModel implements CostModelLike {
  plan = '';
  abstract get a(): Decimal;
  abstract get b(): Decimal;
  cost(q: Decimal): Decimal {
    return this.a.plus(this.b.times(D(q)));
  }
  unitCost(q: Decimal): Decimal {
    return safeDiv(this.cost(q), D(q));
  }
  name(): string {
    return PLAN_LABELS[this.plan] ?? this.plan;
  }
  toDict(): { plan: string; label: string; a: Decimal; b: Decimal } {
    return { plan: this.plan, label: this.name(), a: this.a, b: this.b };
  }
}

export class SelfBuildCost extends CostModel {
  plan = PLAN_SELF_BUILD;
  constructor(
    public C_fix_acct: Decimal,
    public C_var_per_U: Decimal,
    public Q_cap_M: Decimal,
  ) {
    super();
  }
  get a(): Decimal {
    return this.C_fix_acct;
  }
  get b(): Decimal {
    return safeDiv(this.C_var_per_U, this.Q_cap_M);
  }
}

export class RentCost extends CostModel {
  plan = PLAN_RENT;
  constructor(
    public fixed: Decimal,
    public Rent_gpu: Decimal,
    public N_gpu: Decimal,
    public Q_cap_M: Decimal,
    public power_per_mtok: Decimal = ZERO,
  ) {
    super();
  }
  get a(): Decimal {
    return this.fixed;
  }
  get b(): Decimal {
    const rentPerMonth = this.Rent_gpu.times(this.N_gpu).times(H);
    return safeDiv(rentPerMonth, this.Q_cap_M).plus(this.power_per_mtok);
  }
}

export class ApiCost extends CostModel {
  plan = PLAN_API;
  constructor(
    public API_in: Decimal,
    public API_out: Decimal,
    public API_cache: Decimal,
    public rho: Decimal,
    public h: Decimal,
    public factor: Decimal,
  ) {
    super();
  }
  get a(): Decimal {
    return ZERO;
  }
  get b(): Decimal {
    const blendedIn = ONE.minus(this.h).times(this.API_in).plus(this.h.times(this.API_cache));
    return safeDiv(this.rho.times(blendedIn).plus(this.API_out), this.factor);
  }
}

export function buildSelfBuild(derived: DerivedParams): SelfBuildCost {
  return new SelfBuildCost(derived.C_fix_acct, derived.C_var_per_U, derived.Q_cap_M);
}

export function buildRent(params: ScenarioParams, derived: DerivedParams): RentCost {
  const power = params.power;
  const rentInc = params.pricing.rent_inc;
  const selfPaidHosting = rentInc === RENT_INC_POWER_HOSTING ? ZERO : power.Co_loc;
  const powerPerMtok =
    rentInc === RENT_INC_NONE ? safeDiv(derived.C_var_per_U, derived.Q_cap_M) : ZERO;
  // P2 负载曲线：仅自付电（rent_inc=none）时，待机功耗作为固定成本计入；含电方案由云厂承担。
  const idleForRent = rentInc === RENT_INC_NONE ? derived.C_power_idle_m : ZERO;
  const fixed = params.pricing.rent_fixed_monthly
    .plus(selfPaidHosting)
    .plus(power.Co_net)
    .plus(power.Co_stor)
    .plus(power.Co_ops.div(MONTHS_PER_YEAR))
    .plus(power.Co_eng.div(MONTHS_PER_YEAR))
    .plus(power.Co_sales_admin.div(MONTHS_PER_YEAR))
    .plus(power.Co_other.div(MONTHS_PER_YEAR))
    .plus(idleForRent);
  return new RentCost(fixed, params.pricing.Rent_gpu, params.hw.N_gpu, derived.Q_cap_M, powerPerMtok);
}

export function buildApi(params: ScenarioParams, derived: DerivedParams): ApiCost {
  return new ApiCost(
    params.pricing.API_in,
    params.pricing.API_out,
    apiCacheEffective(params.pricing),
    params.demand.rho,
    params.demand.h,
    derived.factor,
  );
}

export function buildAll(params: ScenarioParams, derived: DerivedParams): CostModel[] {
  return [buildSelfBuild(derived), buildRent(params, derived), buildApi(params, derived)];
}

// ===========================================================================
// P2-3 混合部署第四方案（前端镜像，对齐后端 `cost_model.py` 扩展段）。
// 按权重 w_A/w_B/w_C（和=1）线性加权 A/B/C；C_hybrid(Q)=a_h+b_h·Q 复用统一线性化。
// ===========================================================================
export class HybridCost extends CostModel {
  plan = PLAN_HYBRID;
  constructor(
    public w_A: Decimal,
    public w_B: Decimal,
    public w_C: Decimal,
    public a_A: Decimal,
    public b_A: Decimal,
    public a_B: Decimal,
    public b_B: Decimal,
    public a_C: Decimal,
    public b_C: Decimal,
  ) {
    super();
  }
  get a(): Decimal {
    return this.w_A.times(this.a_A).plus(this.w_B.times(this.a_B)).plus(this.w_C.times(this.a_C));
  }
  get b(): Decimal {
    return this.w_A.times(this.b_A).plus(this.w_B.times(this.b_B)).plus(this.w_C.times(this.b_C));
  }
}

/** 归一化权重使其和为 1（全 0 时退化为三等分）。 */
export function normalizeWeights(wA: Decimal, wB: Decimal, wC: Decimal): [Decimal, Decimal, Decimal] {
  const total = wA.plus(wB).plus(wC);
  if (total.lte(ZERO)) {
    return [new Decimal(1).div(3), new Decimal(1).div(3), new Decimal(1).div(3)];
  }
  return [wA.div(total), wB.div(total), wC.div(total)];
}

/** 由三方案成本模型 + 权重构造混合部署模型（顺序须为 A→B→C）。 */
export function buildHybrid(weights: [Decimal, Decimal, Decimal], models: CostModelLike[]): HybridCost {
  if (models.length < 3) throw new Error('混合部署需要 A/B/C 三方案成本模型');
  const [a, b, c] = models;
  const [wA, wB, wC] = normalizeWeights(weights[0], weights[1], weights[2]);
  return new HybridCost(
    wA, wB, wC,
    a.a, a.b,
    b.a, b.b,
    c.a, c.b,
  );
}
