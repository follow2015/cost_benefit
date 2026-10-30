"""盈亏平衡（架构 §3.6，重写 PRD 附录 D 的量纲/符号）。

- 单位贡献边际：`M_U = p_eq·Q_cap_M − C_var_per_U`（元/月，每单位利用率）
- 盈亏平衡利用率：`U_be = C_fix_acct / M_U`，**分母 ≤ 0 时无解**
- 盈亏平衡产量：`Q_be = Q_cap_M · U_be`
- 盈亏平衡售价：`p_be = (C_fix_acct + C_var_per_U·U) / (Q_cap_M·U)`

> 与架构 §3.6 的一处口径澄清：文档写作 `Q_eq·U`，但 `Q_eq` 已是月需求量（不随 U 二次放大），
> 按量纲自洽应为满负荷产能 `Q_cap_M·U`（= 该利用率下的实际产出）。此处按量纲正确式实现，
> 并在交付说明中列为「遗留待确认口径」。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from ai_roi.domain.calc.decimal_config import ZERO, safe_div
from ai_roi.domain.calc.parameters import DerivedParams
from ai_roi.domain.calc.revenue import RevenueResult


@dataclass(frozen=True)
class BreakevenPoint:
    """盈亏平衡图上的一个采样点。"""

    U: Decimal
    revenue: Decimal
    cost: Decimal


@dataclass(frozen=True)
class BreakevenResult:
    """盈亏平衡结果。"""

    feasible: bool
    M_U: Decimal
    U_be: Optional[Decimal]
    Q_be: Optional[Decimal]
    p_be: Decimal
    note: str
    curve: List[BreakevenPoint]


def _sample_curve(
    derived: DerivedParams, p_eq: Decimal, steps: int = 21
) -> List[BreakevenPoint]:
    """在 U∈[0,1] 采样收入线与成本线（盈亏平衡图数据源）。"""
    points: List[BreakevenPoint] = []
    for index in range(steps):
        u = Decimal(index) / Decimal(steps - 1)
        points.append(
            BreakevenPoint(
                U=u,
                revenue=p_eq * derived.Q_cap_M * u,
                cost=derived.C_fix_acct + derived.C_var_per_U * u,
            )
        )
    return points


def compute(derived: DerivedParams, rev: RevenueResult) -> BreakevenResult:
    """计算盈亏平衡（纯函数）。"""
    m_u = rev.p_eq * derived.Q_cap_M - derived.C_var_per_U
    curve = _sample_curve(derived, rev.p_eq)
    p_be = safe_div(
        derived.C_fix_acct + derived.C_var_per_U * derived.U,
        derived.Q_cap_M * derived.U,
    )

    if m_u <= ZERO:
        return BreakevenResult(
            feasible=False,
            M_U=m_u,
            U_be=None,
            Q_be=None,
            p_be=p_be,
            note="无盈亏平衡点：等效售价覆盖不了单位可变成本（贡献边际 ≤ 0），请上调售价或降低电价/功耗。",
            curve=curve,
        )

    u_be = derived.C_fix_acct / m_u
    q_be = derived.Q_cap_M * u_be
    if u_be > Decimal(1):
        note = (
            f"盈亏平衡利用率 {u_be} > 100%：即使满负荷运行仍无法覆盖固定成本，方案在当前定价下不可行。"
        )
    else:
        note = "存在盈亏平衡点；当前利用率高于该点即为盈利。"
    return BreakevenResult(
        feasible=True,
        M_U=m_u,
        U_be=u_be,
        Q_be=q_be,
        p_be=p_be,
        note=note,
        curve=curve,
    )
