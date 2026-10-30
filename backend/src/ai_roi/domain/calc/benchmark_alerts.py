"""标杆对标告警（市场公允成本标杆 ↔ 自建口径）。

从 `engine.compute_core` 抽出的独立领域模块（redesign 解耦）：核心推导链不再
内联任何「与基准库对标」的告警逻辑，本模块是 C-1 / E-10 两条告警的唯一来源。

两条告警的区分（不可混淆）：
- **C-1 售价 vs 标杆**：对外售价等效单价低于市场公允成本标杆 ⇒ 单 token 亏损；
- **E-10 成本 vs 标杆**：自建单位成本偏离行业实测标杆 > ±50% ⇒ 吞吐假设可能失真。
"""

from __future__ import annotations

from typing import List

from ai_roi.domain.calc.decimal_config import D, HUNDRED, ZERO, dec_str
from ai_roi.domain.calc.parameters import ScenarioParams
from ai_roi.domain.calc.revenue import RevenueResult
from ai_roi.domain.calc.unit_cost import UnitCostResult

DEVIATION_THRESHOLD = D("0.5")


def benchmark_alerts(
    params: ScenarioParams,
    revenue_result: RevenueResult,
    unit_cost_result: UnitCostResult,
) -> List[str]:
    """生成标杆对标告警列表（无标杆录入时返回空列表）。"""
    alerts: List[str] = []
    cb = params.pricing.cost_benchmark
    if cb is None:
        return alerts

    if revenue_result.loss_vs_benchmark:
        alerts.append(
            f"口径告警：对外售价等效单价 {dec_str(revenue_result.p_eq)} 元/Mtok 低于市场公允成本标杆 "
            f"{dec_str(cb)} 元/Mtok，按此定价单 token 亏损"
            "（对标市场成本的毛利为负），建议重新议价或改用第三方 API/云方案。"
        )

    if cb > ZERO and unit_cost_result.cost_per_m_capacity > ZERO:
        deviation = abs(unit_cost_result.cost_per_m_capacity - cb) / cb
        if deviation > DEVIATION_THRESHOLD:
            direction = "高于" if unit_cost_result.cost_per_m_capacity > cb else "低于"
            alerts.append(
                f"标杆告警：每百万 token 自建设本 {dec_str(unit_cost_result.cost_per_m_capacity)} 元/Mtok "
                f"{direction}行业基准 {dec_str(cb)} 元/Mtok 约 {dec_str(deviation * HUNDRED)}%（>±50%），"
                "T_eff 等吞吐假设可能偏离行业实测，建议用基准库校准。"
            )
    return alerts
