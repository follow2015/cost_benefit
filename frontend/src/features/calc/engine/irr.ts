/** IRR 数值求解（月 IRR + 年化 + MIRR）。对齐后端 `app/calc/irr.py`。 */

import { D, MONTHS_PER_YEAR, ONE, ZERO, Decimal, dpow, safeDiv } from './decimalConfig';

const NPV_TOLERANCE = new Decimal('0.01');
const MAX_ITERATIONS = 100;
const SCAN_LOW = new Decimal('-0.99');
const SCAN_HIGH = new Decimal('1.0');
const SCAN_STEPS = 80;

export interface IrrResult {
  solution: boolean;
  irr_monthly: Decimal | null;
  irr_annual: Decimal | null;
  roots_monthly: Decimal[];
  mirr_monthly: Decimal | null;
  mirr_annual: Decimal | null;
  method: string;
  note: string;
  iterations: number;
}

type Cashflows = Decimal[];

export function npvAt(rateMonthly: Decimal, cashflows: Cashflows): Decimal {
  let total = ZERO;
  const onePlus = ONE.plus(rateMonthly);
  for (let period = 0; period < cashflows.length; period++) {
    const amount = cashflows[period];
    if (period === 0) {
      total = total.plus(amount);
      continue;
    }
    total = total.plus(safeDiv(amount, dpow(onePlus, new Decimal(period))));
  }
  return total;
}

export function dnpvAt(rateMonthly: Decimal, cashflows: Cashflows): Decimal {
  let total = ZERO;
  const onePlus = ONE.plus(rateMonthly);
  for (let period = 0; period < cashflows.length; period++) {
    const amount = cashflows[period];
    if (period === 0) continue;
    total = total.plus(new Decimal(period).times(amount).div(dpow(onePlus, new Decimal(period + 1))).negated());
  }
  return total;
}

export function annualize(rateMonthly: Decimal): Decimal {
  return dpow(ONE.plus(rateMonthly), MONTHS_PER_YEAR).minus(ONE);
}

function hasSignChange(cashflows: Cashflows): boolean {
  const signs = cashflows.filter((cf) => cf.ne(ZERO)).map((cf) => (cf.gt(ZERO) ? 1 : -1));
  for (let i = 0; i < signs.length - 1; i++) {
    if (signs[i] !== signs[i + 1]) return true;
  }
  return false;
}

function bracketRoots(cashflows: Cashflows): Array<[Decimal, Decimal]> {
  const brackets: Array<[Decimal, Decimal]> = [];
  const step = SCAN_HIGH.minus(SCAN_LOW).div(new Decimal(SCAN_STEPS));
  let prevRate = SCAN_LOW;
  let prevNpv = npvAt(prevRate, cashflows);
  for (let i = 1; i <= SCAN_STEPS; i++) {
    const rate = SCAN_LOW.plus(step.times(new Decimal(i)));
    const value = npvAt(rate, cashflows);
    if (prevNpv.eq(ZERO)) {
      brackets.push([prevRate, prevRate]);
    } else if (prevNpv.gt(ZERO) !== value.gt(ZERO)) {
      brackets.push([prevRate, rate]);
    }
    prevRate = rate;
    prevNpv = value;
  }
  return brackets;
}

function solveBracket(
  low: Decimal,
  high: Decimal,
  cashflows: Cashflows,
): [Decimal | null, number] {
  if (low.eq(high)) return [low, 0];
  let lo = low;
  let hi = high;
  let npvLo = npvAt(lo, cashflows);
  let guess = lo.plus(hi).div(new Decimal(2));
  for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
    const value = npvAt(guess, cashflows);
    if (value.abs().lt(NPV_TOLERANCE)) return [guess, iteration];
    const derivative = dnpvAt(guess, cashflows);
    let newtonOk = false;
    if (derivative.ne(ZERO)) {
      const candidate = guess.minus(value.div(derivative));
      if (candidate.gt(lo) && candidate.lt(hi)) {
        guess = candidate;
        newtonOk = true;
      }
    }
    if (!newtonOk) {
      if (value.gt(ZERO) === npvLo.gt(ZERO)) {
        lo = guess;
        npvLo = value;
      } else {
        hi = guess;
      }
      guess = lo.plus(hi).div(new Decimal(2));
    }
  }
  return npvAt(guess, cashflows).abs().lt(ONE) ? [guess, MAX_ITERATIONS] : [null, MAX_ITERATIONS];
}

export function computeMirr(
  cashflows: Cashflows,
  financeRate: Decimal,
  reinvestRate: Decimal,
): Decimal | null {
  const periods = cashflows.length - 1;
  if (periods <= 0) return null;
  let fvPositive = ZERO;
  let pvNegative = ZERO;
  for (let period = 0; period < cashflows.length; period++) {
    const amount = cashflows[period];
    if (amount.gt(ZERO)) {
      fvPositive = fvPositive.plus(amount.times(dpow(ONE.plus(reinvestRate), new Decimal(periods - period))));
    } else if (amount.lt(ZERO)) {
      pvNegative = pvNegative.plus(amount.div(dpow(ONE.plus(financeRate), new Decimal(period))));
    }
  }
  if (fvPositive.lte(ZERO) || pvNegative.gte(ZERO)) return null;
  const ratio = fvPositive.div(pvNegative.negated());
  return dpow(ratio, ONE.div(new Decimal(periods))).minus(ONE);
}

export function compute(
  cashflows: Cashflows,
  financeRate: Decimal = ZERO,
  reinvestRate: Decimal = ZERO,
): IrrResult {
  if (cashflows.length < 2) {
    return { solution: false, irr_monthly: null, irr_annual: null, roots_monthly: [], mirr_monthly: null, mirr_annual: null, method: 'none', note: '现金流期数不足，无法求解 IRR。', iterations: 0 };
  }
  if (!hasSignChange(cashflows)) {
    return { solution: false, irr_monthly: null, irr_annual: null, roots_monthly: [], mirr_monthly: null, mirr_annual: null, method: 'none', note: '现金流无正负变号（全为流入或全为流出），IRR 无解。', iterations: 0 };
  }

  const mirr = computeMirr(cashflows, financeRate, reinvestRate);
  const mirrAnnual = mirr !== null ? annualize(mirr) : null;

  const brackets = bracketRoots(cashflows);
  const roots: Decimal[] = [];
  let iterationsUsed = 0;
  for (const [low, high] of brackets) {
    const [root, iterations] = solveBracket(low, high, cashflows);
    iterationsUsed += iterations;
    if (root !== null && roots.every((existing) => root.minus(existing).abs().gt(new Decimal('1e-9')))) {
      roots.push(root);
    }
  }

  if (roots.length === 0) {
    return {
      solution: false,
      irr_monthly: null,
      irr_annual: null,
      roots_monthly: [],
      mirr_monthly: mirr,
      mirr_annual: mirrAnnual,
      method: mirr !== null ? 'mirr' : 'none',
      note: `NPV 在 [${SCAN_LOW}, ${SCAN_HIGH}] 月利率区间内未变号或未收敛；已返回 MIRR 作为参考指标。`,
      iterations: iterationsUsed,
    };
  }

  if (roots.length > 1) {
    const adopted = mirr !== null ? mirr : roots[0];
    return {
      solution: true,
      irr_monthly: adopted,
      irr_annual: annualize(adopted),
      roots_monthly: roots,
      mirr_monthly: mirr,
      mirr_annual: mirrAnnual,
      method: 'mirr',
      note: `检测到 ${roots.length} 个实根（非常规现金流），已采纳 MIRR 作为稳健指标并标注。`,
      iterations: iterationsUsed,
    };
  }

  const root = roots[0];
  return {
    solution: true,
    irr_monthly: root,
    irr_annual: annualize(root),
    roots_monthly: roots,
    mirr_monthly: mirr,
    mirr_annual: mirrAnnual,
    method: 'bisection_newton',
    note: '唯一实根，二分 + 牛顿收敛。',
    iterations: iterationsUsed,
  };
}
