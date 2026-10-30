"""三方案临界规模与下包络（架构 §3.10）。

- 两两交点：`Q_XY = (a_X − a_Y)/(b_Y − b_X)`；
- 无解处理：平行线（`b` 相同）、交点 `Q<0`、交点超出容量墙 `Q_cap_M`；
- **下包络线**：仅保留活跃转折点（最低成本段真实切换处），非活跃交点只做信息展示，
  避免把「已被第三方案支配」的交点误标为推荐分界。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from ai_roi.domain.calc.cost_model import CostModel
from ai_roi.domain.calc.decimal_config import D, ZERO, safe_div

CURVE_SAMPLES = 41


@dataclass(frozen=True)
class CostCurve:
    """一条方案成本线及采样点。"""

    plan: str
    label: str
    a: Decimal
    b: Decimal
    points: List[Dict[str, Decimal]] = field(default_factory=list)


@dataclass(frozen=True)
class Crossover:
    """两方案交点。"""

    plans: List[str]
    Q: Optional[Decimal]
    active: bool
    status: str
    note: str


@dataclass(frozen=True)
class Segment:
    """推荐区间（下包络的一段）。"""

    from_Q: Decimal
    to_Q: Optional[Decimal]
    best_plan: str
    best_label: str


@dataclass(frozen=True)
class CrossoverResult:
    """临界规模求解结果（对应类图 CrossoverResult）。"""

    curves: List[CostCurve]
    crossovers: List[Crossover]
    recommended: List[Segment]
    q_max: Decimal
    capacity_wall: Decimal
    notes: List[str] = field(default_factory=list)


def pair_crossover(left: CostModel, right: CostModel) -> tuple[Optional[Decimal], str, str]:
    """求两方案交点，并给出状态与说明。"""
    denominator = right.b - left.b
    if denominator == ZERO:
        cheaper = left if left.a <= right.a else right
        return (
            None,
            "parallel",
            f"两方案单位变动成本相同（平行线），全程 {cheaper.name()} 恒不劣，无临界点。",
        )
    q = (left.a - right.a) / denominator
    if q < ZERO:
        cheaper = left if left.cost(D(1)) <= right.cost(D(1)) else right
        return q, "negative", f"交点位于负需求区间，在任何正需求下 {cheaper.name()} 恒优。"
    return q, "ok", "存在有效交点。"


def _lower_envelope(
    models: Sequence[CostModel], q_max: Decimal
) -> tuple[List[Segment], List[Decimal]]:
    """在 `Q∈[0, q_max]` 上求下包络分段与活跃转折点。"""
    if not models:
        return [], []
    current = min(models, key=lambda m: (m.a, m.b))
    segments: List[Segment] = []
    switch_points: List[Decimal] = []
    start = ZERO
    guard = 0

    while guard <= len(models) + 2:
        guard += 1
        next_q: Optional[Decimal] = None
        next_model: Optional[CostModel] = None
        for candidate in models:
            if candidate.plan == current.plan:
                continue
            q, status, _ = pair_crossover(current, candidate)
            if status != "ok" or q is None:
                continue
            if q <= start or q > q_max:
                continue
            if candidate.b < current.b and (next_q is None or q < next_q):
                next_q, next_model = q, candidate
        if next_q is None or next_model is None:
            segments.append(
                Segment(
                    from_Q=start,
                    to_Q=None,
                    best_plan=current.plan,
                    best_label=current.name(),
                )
            )
            break
        segments.append(
            Segment(
                from_Q=start,
                to_Q=next_q,
                best_plan=current.plan,
                best_label=current.name(),
            )
        )
        switch_points.append(next_q)
        start, current = next_q, next_model
    return segments, switch_points


def _compute_crossover(
    models: Sequence[CostModel],
    demand_q: Decimal,
    capacity_wall: Decimal,
    dominated_note: str,
    no_active_note: str,
) -> CrossoverResult:
    """三/四方案成本曲线、两两交点与推荐区间（共享内核，P1-1 去重）。

    Args:
        models: 方案成本模型（三方案 A/B/C 或叠加混合方案的四个）。
        demand_q: 当前月需求量（Mtok/月），用于确定采样上限。
        capacity_wall: 自建/租用满负荷产能（Mtok/月）。
        dominated_note: 被支配交点的说明文案（三方案与四方案措辞不同，参数化注入）。
        no_active_note: 无活跃交点时的说明文案（同上）。
    """
    notes: List[str] = []
    candidates = [demand_q * D(2), capacity_wall * D("1.2")]
    q_max = max([value for value in candidates if value > ZERO] or [D(1_000)])

    curves: List[CostCurve] = []
    for model in models:
        points: List[Dict[str, Decimal]] = []
        for index in range(CURVE_SAMPLES):
            q = q_max * D(index) / D(CURVE_SAMPLES - 1)
            points.append(
                {
                    "Q": q,
                    "total_cost": model.cost(q),
                    "unit_cost": safe_div(model.cost(q), q),
                }
            )
        curves.append(
            CostCurve(plan=model.plan, label=model.name(), a=model.a, b=model.b, points=points)
        )

    segments, switch_points = _lower_envelope(models, q_max)

    crossovers: List[Crossover] = []
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            q, status, note = pair_crossover(left, right)
            active = q is not None and any(
                abs(q - switch) <= D("1e-12") for switch in switch_points
            )
            if status == "ok" and q is not None and q > capacity_wall > ZERO:
                status = "beyond_capacity"
                note = "交点超出当前满负荷产能（容量墙），需扩容才会发生成本反转。"
            elif status == "ok" and not active:
                status = "dominated"
                note = dominated_note
            crossovers.append(
                Crossover(
                    plans=[left.plan, right.plan],
                    Q=q,
                    active=active,
                    status=status,
                    note=note,
                )
            )

    if not switch_points:
        notes.append(no_active_note)
    if capacity_wall > ZERO and demand_q > capacity_wall:
        notes.append("当前需求已超自建/租用容量墙，A/B 方案需扩容，成本线仅供参考。")

    return CrossoverResult(
        curves=curves,
        crossovers=crossovers,
        recommended=segments,
        q_max=q_max,
        capacity_wall=capacity_wall,
        notes=notes,
    )


def compute(
    models: Sequence[CostModel],
    demand_q: Decimal,
    capacity_wall: Decimal,
) -> CrossoverResult:
    """求三方案成本曲线、两两交点与推荐区间。

    Args:
        models: 三方案成本模型（A/B/C）。
        demand_q: 当前月需求量（Mtok/月），用于确定采样上限。
        capacity_wall: 自建/租用满负荷产能（Mtok/月）。
    """
    return _compute_crossover(
        models,
        demand_q,
        capacity_wall,
        dominated_note="交点存在但被第三方案支配（非活跃转折点），仅作信息展示，不作为推荐分界。",
        no_active_note="三方案成本线在可行域内无活跃交点：推荐方案在全区间不变。",
    )


def compute_hybrid(
    three_models: Sequence[CostModel],
    hybrid_model: CostModel,
    demand_q: Decimal,
    capacity_wall: Decimal,
) -> CrossoverResult:
    """混合部署下包络：在 A/B/C 三方案基础上叠加混合方案 H，求四方案成本线与临界规模。

    - 复用共享内核 `_compute_crossover`，交点求解对 H 同样处理
      「交点<0 / 超容量墙 / 平行线 → 无有效临界点」标注；
    - 活跃转折点仍为下包络真实切换处，被支配方案交点仅作信息展示。
    """
    return _compute_crossover(
        list(three_models) + [hybrid_model],
        demand_q,
        capacity_wall,
        dominated_note="交点存在但被其他方案支配（非活跃转折点），仅作信息展示，不作为推荐分界。",
        no_active_note="混合部署四方案成本线在可行域内无活跃交点：推荐方案在全区间不变。",
    )
