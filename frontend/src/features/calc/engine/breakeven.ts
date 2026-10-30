/** 盈亏平衡。对齐后端 `app/calc/breakeven.py`。 */

import { ZERO, Decimal, safeDiv } from './decimalConfig';
import { DerivedParams } from './parameters';
import { RevenueResult } from './revenue';

export interface BreakevenPoint {
  U: Decimal;
  revenue: Decimal;
  cost: Decimal;
}

export interface BreakevenResult {
  feasible: boolean;
  M_U: Decimal;
  U_be: Decimal | null;
  Q_be: Decimal | null;
  p_be: Decimal;
  note: string;
  curve: BreakevenPoint[];
}

function sampleCurve(derived: DerivedParams, pEq: Decimal, steps = 21): BreakevenPoint[] {
  const points: BreakevenPoint[] = [];
  for (let i = 0; i < steps; i++) {
    const u = new Decimal(i).div(new Decimal(steps - 1));
    points.push({
      U: u,
      revenue: pEq.times(derived.Q_cap_M).times(u),
      cost: derived.C_fix_acct.plus(derived.C_var_per_U.times(u)),
    });
  }
  return points;
}

export function compute(derived: DerivedParams, rev: RevenueResult): BreakevenResult {
  const mU = rev.p_eq.times(derived.Q_cap_M).minus(derived.C_var_per_U);
  const curve = sampleCurve(derived, rev.p_eq);
  const pBe = safeDiv(
    derived.C_fix_acct.plus(derived.C_var_per_U.times(derived.U)),
    derived.Q_cap_M.times(derived.U),
  );

  if (mU.lte(ZERO)) {
    return {
      feasible: false,
      M_U: mU,
      U_be: null,
      Q_be: null,
      p_be: pBe,
      note: '无盈亏平衡点：等效售价覆盖不了单位可变成本（贡献边际 ≤ 0），请上调售价或降低电价/功耗。',
      curve,
    };
  }

  const uBe = derived.C_fix_acct.div(mU);
  const qBe = derived.Q_cap_M.times(uBe);
  const note =
    uBe.gt(new Decimal(1))
      ? `盈亏平衡利用率 ${uBe.toString()} > 100%：即使满负荷运行仍无法覆盖固定成本，方案在当前定价下不可行。`
      : '存在盈亏平衡点；当前利用率高于该点即为盈利。';
  return {
    feasible: true,
    M_U: mU,
    U_be: uBe,
    Q_be: qBe,
    p_be: pBe,
    note,
    curve,
  };
}
