"""IRR 数值求解（架构 §3.9）。

- 统一求解**月 IRR** `r_m`，年化 `IRR = (1+r_m)^12 − 1`；
- 步骤：① 符号变化检查（无变号 → 无解）；② 对数网格扫描定区间；③ 二分 + 牛顿；
- 多解：返回所有实根，并计算 **MIRR** 作为采纳值并标注；
- 不收敛：`solution=False` + 说明与扫描边界。

全程 Decimal，导数解析式：`dNPV/dr = Σ −t·CF_t/(1+r)^(t+1)`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Sequence

from ai_roi.domain.calc.decimal_config import D, MONTHS_PER_YEAR, ONE, ZERO, dpow, safe_div

NPV_TOLERANCE = Decimal("0.01")
MAX_ITERATIONS = 100
SCAN_LOW = Decimal("-0.99")
SCAN_HIGH = Decimal("1.0")
SCAN_STEPS = 80


@dataclass(frozen=True)
class IrrResult:
    """IRR 求解结果。"""

    solution: bool
    irr_monthly: Optional[Decimal] = None
    irr_annual: Optional[Decimal] = None
    roots_monthly: List[Decimal] = field(default_factory=list)
    mirr_monthly: Optional[Decimal] = None
    mirr_annual: Optional[Decimal] = None
    method: str = "none"
    note: str = ""
    iterations: int = 0


def npv_at(rate_monthly: Decimal, cashflows: Sequence[Decimal]) -> Decimal:
    """给定月利率求 NPV。`cashflows[0]` 视为 t=0 现金流（通常为 −I0）。"""
    total = ZERO
    one_plus = ONE + rate_monthly
    for period, amount in enumerate(cashflows):
        if period == 0:
            total += amount
            continue
        total += safe_div(amount, dpow(one_plus, D(period)))
    return total


def dnpv_at(rate_monthly: Decimal, cashflows: Sequence[Decimal]) -> Decimal:
    """NPV 对月利率的解析导数。"""
    total = ZERO
    one_plus = ONE + rate_monthly
    for period, amount in enumerate(cashflows):
        if period == 0:
            continue
        total += -D(period) * amount / dpow(one_plus, D(period + 1))
    return total


def annualize(rate_monthly: Decimal) -> Decimal:
    """月利率年化：`(1+r_m)^12 − 1`。"""
    return dpow(ONE + rate_monthly, MONTHS_PER_YEAR) - ONE


def _has_sign_change(cashflows: Sequence[Decimal]) -> bool:
    """现金流是否存在正负变号（IRR 存在的必要条件）。"""
    signs = [1 if cf > ZERO else (-1 if cf < ZERO else 0) for cf in cashflows if cf != ZERO]
    return any(a != b for a, b in zip(signs, signs[1:]))


def _bracket_roots(cashflows: Sequence[Decimal]) -> List[tuple[Decimal, Decimal]]:
    """对数/线性网格扫描，找出所有 NPV 变号区间。"""
    brackets: List[tuple[Decimal, Decimal]] = []
    step = (SCAN_HIGH - SCAN_LOW) / Decimal(SCAN_STEPS)
    prev_rate = SCAN_LOW
    prev_npv = npv_at(prev_rate, cashflows)
    for index in range(1, SCAN_STEPS + 1):
        rate = SCAN_LOW + step * Decimal(index)
        value = npv_at(rate, cashflows)
        if prev_npv == ZERO:
            brackets.append((prev_rate, prev_rate))
        elif (prev_npv > ZERO) != (value > ZERO):
            brackets.append((prev_rate, rate))
        prev_rate, prev_npv = rate, value
    return brackets


def _solve_bracket(
    low: Decimal, high: Decimal, cashflows: Sequence[Decimal]
) -> tuple[Optional[Decimal], int]:
    """在给定区间内用二分 + 牛顿求根。"""
    if low == high:
        return low, 0
    lo, hi = low, high
    npv_lo = npv_at(lo, cashflows)
    guess = (lo + hi) / D(2)
    for iteration in range(1, MAX_ITERATIONS + 1):
        value = npv_at(guess, cashflows)
        if abs(value) < NPV_TOLERANCE:
            return guess, iteration
        derivative = dnpv_at(guess, cashflows)
        newton_ok = False
        if derivative != ZERO:
            candidate = guess - value / derivative
            if lo < candidate < hi:
                guess, newton_ok = candidate, True
        if not newton_ok:
            if (value > ZERO) == (npv_lo > ZERO):
                lo, npv_lo = guess, value
            else:
                hi = guess
            guess = (lo + hi) / D(2)
    return (guess, MAX_ITERATIONS) if abs(npv_at(guess, cashflows)) < ONE else (None, MAX_ITERATIONS)


def compute_mirr(
    cashflows: Sequence[Decimal], finance_rate: Decimal, reinvest_rate: Decimal
) -> Optional[Decimal]:
    """修正内部收益率（月度）。

    `MIRR = (FV(正现金流) / −PV(负现金流))^(1/n) − 1`
    """
    periods = len(cashflows) - 1
    if periods <= 0:
        return None
    fv_positive = ZERO
    pv_negative = ZERO
    for period, amount in enumerate(cashflows):
        if amount > ZERO:
            fv_positive += amount * dpow(ONE + reinvest_rate, D(periods - period))
        elif amount < ZERO:
            pv_negative += amount / dpow(ONE + finance_rate, D(period))
    if fv_positive <= ZERO or pv_negative >= ZERO:
        return None
    ratio = fv_positive / (-pv_negative)
    return dpow(ratio, ONE / D(periods)) - ONE


def compute(
    cashflows: Sequence[Decimal],
    finance_rate: Decimal = ZERO,
    reinvest_rate: Decimal = ZERO,
) -> IrrResult:
    """求解 IRR。

    Args:
        cashflows: `[CF_0(=-I0), CF_1, ..., CF_T]`，月度。
        finance_rate: MIRR 融资利率（月），默认 0。
        reinvest_rate: MIRR 再投资利率（月），默认 0。
    """
    if len(cashflows) < 2:
        return IrrResult(solution=False, note="现金流期数不足，无法求解 IRR。")
    if not _has_sign_change(cashflows):
        return IrrResult(
            solution=False,
            note="现金流无正负变号（全为流入或全为流出），IRR 无解。",
        )

    mirr = compute_mirr(cashflows, finance_rate, reinvest_rate)
    mirr_annual = annualize(mirr) if mirr is not None else None

    brackets = _bracket_roots(cashflows)
    roots: List[Decimal] = []
    iterations_used = 0
    for low, high in brackets:
        root, iterations = _solve_bracket(low, high, cashflows)
        iterations_used += iterations
        if root is not None and all(abs(root - existing) > Decimal("1e-9") for existing in roots):
            roots.append(root)

    if not roots:
        return IrrResult(
            solution=False,
            mirr_monthly=mirr,
            mirr_annual=mirr_annual,
            method="mirr" if mirr is not None else "none",
            note=(
                f"NPV 在 [{SCAN_LOW}, {SCAN_HIGH}] 月利率区间内未变号或未收敛；"
                "已返回 MIRR 作为参考指标。"
            ),
            iterations=iterations_used,
        )

    if len(roots) > 1:
        adopted = mirr if mirr is not None else roots[0]
        return IrrResult(
            solution=True,
            irr_monthly=adopted,
            irr_annual=annualize(adopted),
            roots_monthly=roots,
            mirr_monthly=mirr,
            mirr_annual=mirr_annual,
            method="mirr",
            note=f"检测到 {len(roots)} 个实根（非常规现金流），已采纳 MIRR 作为稳健指标并标注。",
            iterations=iterations_used,
        )

    root = roots[0]
    return IrrResult(
        solution=True,
        irr_monthly=root,
        irr_annual=annualize(root),
        roots_monthly=roots,
        mirr_monthly=mirr,
        mirr_annual=mirr_annual,
        method="bisection_newton",
        note="唯一实根，二分 + 牛顿收敛。",
        iterations=iterations_used,
    )
