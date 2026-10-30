"""参数校验（唯一事实来源，前端 `src/utils/validation.ts` 与之镜像）。

分两级：
- **error**：不可计算或必然产出误导结论 → 抛 `ValidationFailedError`（HTTP 422）；
- **warning**：可计算但需提示（口径不一致、超容量墙、k 非实测）→ 随结果返回。

不在此处做单位换算：所有百分比进入引擎前已是比率（0–1），换算由前端表单层负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ai_roi.domain.calc.decimal_config import ONE, ZERO, dec_str, safe_div
from ai_roi.domain.calc.parameters import (
    RENT_INC_NONE,
    RENT_INC_POWER,
    RENT_INC_POWER_HOSTING,
    UTIL_MODE_DEMAND_FROM_U,
    UTIL_MODE_EXPLICIT,
    UTIL_MODE_U_FROM_DEMAND,
    ScenarioParams,
    derive,
)
from ai_roi.domain.errors import ValidationFailedError


@dataclass
class FieldIssue:
    """单条校验问题。"""

    path: str
    level: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        """转字典。"""
        return {"path": self.path, "level": self.level, "message": self.message}


@dataclass
class ValidationReport:
    """校验报告。"""

    errors: List[FieldIssue] = field(default_factory=list)
    warnings: List[FieldIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否无 error。"""
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        """转字典（用于错误响应 detail）。"""
        return {
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
        }


_POSITIVE_FIELDS: List[tuple[str, str]] = [
    ("hw.N_gpu", "GPU 卡数"),
    ("hw.P_gpu", "单卡采购价"),
    ("hw.Y_dep", "折旧年限"),
    ("power.PUE", "PUE"),
    ("power.E_price", "电价"),
    ("perf.T_eff", "综合有效吞吐 T_eff"),
    ("finance.T_horizon", "分析周期"),
]

_NON_NEGATIVE_FIELDS: List[tuple[str, str]] = [
    ("hw.P_aux", "整机配套价"),
    ("hw.T_deploy", "部署上线周期"),
    ("hw.L_sw", "软件许可年费"),
    ("hw.pre_launch_cost", "上线前一次性费用"),
    ("power.TDP", "单卡 TDP"),
    ("power.P_aux_power", "配套设备功耗"),
    ("power.Co_loc", "机柜托管费"),
    ("power.Co_net", "网络带宽费"),
    ("power.Co_stor", "存储费"),
    ("power.Co_ops", "运维人力分摊"),
    ("perf.T_pf", "prefill 吞吐"),
    ("perf.T_dc", "decode 吞吐"),
    ("demand.rho", "输入输出比 rho"),
    ("demand.D_eq", "月等效输出量 D_eq"),
    ("pricing.p_in", "输入单价"),
    ("pricing.p_out", "输出单价"),
    ("pricing.Rent_gpu", "云租赁单价"),
    ("pricing.rent_fixed_monthly", "包月固定费"),
    ("pricing.API_in", "API 输入价"),
    ("pricing.API_out", "API 输出价"),
]

_RATIO_FIELDS: List[tuple[str, str]] = [
    ("hw.availability", "可用性"),
    ("hw.S_pct", "残值率"),
    ("demand.h", "缓存命中率"),
    ("demand.U", "利用率 U"),
    ("finance.Tax", "税率"),
    ("power.P_idle_ratio", "待机功耗比例 P_idle_ratio"),
    ("perf.SLA_penalty_rate", "SLA 赔偿计提率"),
    ("finance.debt_ratio", "债务占比"),
    ("finance.cost_learning_rate", "学习曲线年降幅"),
]

_GROWTH_RATE_FIELDS: List[tuple[str, str]] = [
    ("pricing.g_price", "年价格变动率 g_price"),
    ("finance.infl", "通胀率 infl"),
    ("demand.g_demand", "需求年增长率 g_demand"),
]

_VALID_UTIL_MODES = {
    UTIL_MODE_EXPLICIT,
    UTIL_MODE_DEMAND_FROM_U,
    UTIL_MODE_U_FROM_DEMAND,
}
_VALID_RENT_INC = {RENT_INC_POWER, RENT_INC_POWER_HOSTING, RENT_INC_NONE}
_VALID_CN_CFG = {"none", "partial", "full"}
_VALID_POWER_MODES = {"separate", "bundle"}

_UTIL_MISMATCH_TOLERANCE = Decimal("0.2")


def _as_decimal(value: Any) -> Optional[Decimal]:
    """安全取 Decimal。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - 任何转换失败都视为非数值
        return None


def build_report(params: ScenarioParams) -> ValidationReport:
    """执行全部校验并返回报告（不抛异常）。"""
    report = ValidationReport()

    for path, label in _POSITIVE_FIELDS:
        value = _as_decimal(params.get_value(path))
        if value is None or value <= ZERO:
            report.errors.append(FieldIssue(path, "error", f"{label} 必须大于 0"))

    for path, label in _NON_NEGATIVE_FIELDS:
        value = _as_decimal(params.get_value(path))
        if value is None or value < ZERO:
            report.errors.append(FieldIssue(path, "error", f"{label} 不能为负数"))

    for path, label in _RATIO_FIELDS:
        value = _as_decimal(params.get_value(path))
        if value is None or value < ZERO or value > ONE:
            report.errors.append(
                FieldIssue(path, "error", f"{label} 必须是 0–1 之间的比率（如 60% 请填 0.6）")
            )

    for path, label in _GROWTH_RATE_FIELDS:
        value = _as_decimal(params.get_value(path))
        if value is not None and value < Decimal("-0.99"):
            report.errors.append(
                FieldIssue(path, "error", f"{label} 低于 −99%，缩放因子底数将非正，无法计算")
            )
    if _as_decimal(params.finance.cost_learning_rate) is not None and (
        params.finance.cost_learning_rate >= ONE
    ):
        report.errors.append(
            FieldIssue(
                "finance.cost_learning_rate",
                "error",
                "学习曲线年降幅必须小于 100%（否则缩放因子底数非正）",
            )
        )

    if params.demand.util_mode not in _VALID_UTIL_MODES:
        report.errors.append(
            FieldIssue(
                "demand.util_mode",
                "error",
                f"利用率耦合口径非法，应为 {sorted(_VALID_UTIL_MODES)} 之一",
            )
        )
    if params.pricing.rent_inc not in _VALID_RENT_INC:
        report.errors.append(
            FieldIssue(
                "pricing.rent_inc",
                "error",
                f"租赁包含项非法，应为 {sorted(_VALID_RENT_INC)} 之一",
            )
        )
    if params.hw.CN_cfg not in _VALID_CN_CFG:
        report.errors.append(
            FieldIssue(
                "hw.CN_cfg",
                "error",
                f"信创合规口径非法，应为 {sorted(_VALID_CN_CFG)} 之一",
            )
        )
    if params.power.power_mode not in _VALID_POWER_MODES:
        report.errors.append(
            FieldIssue(
                "power.power_mode",
                "error",
                f"电力运维口径非法，应为 {sorted(_VALID_POWER_MODES)} 之一（separate=柜电分离 / bundle=包柜包电）",
            )
        )
    if params.power.power_mode == "bundle" and params.power.bundle_monthly_per_rack <= ZERO:
        report.warnings.append(
            FieldIssue(
                "power.bundle_monthly_per_rack",
                "warning",
                "包柜包电模式下未填写包柜包电单价（元/柜/月），按 0 计可能导致电力成本失真",
            )
        )

    if params.power.tou_peak_share + params.power.tou_valley_share > ONE:
        report.warnings.append(
            FieldIssue(
                "power.tou_*_share",
                "warning",
                "峰谷时段占比之和超过 100%，平段占比将为负，加权电价口径失真，请修正",
            )
        )

    if params.hybrid.enabled:
        weights = (params.hybrid.w_A, params.hybrid.w_B, params.hybrid.w_C)
        negative = [w for w in weights if w is not None and w < ZERO]
        total = ZERO
        for w in weights:
            if w is not None:
                total += w
        if negative or abs(total - ONE) > Decimal("1e-9"):
            report.warnings.append(
                FieldIssue(
                    "hybrid.w_*",
                    "warning",
                    f"混合部署已启用，但权重不合法（当前和 = {dec_str(total)}，要求非负且和≈1），"
                    "已回退为 A/B/C 三方案，第四方案不生效",
                )
            )

    if params.conventions.currency != "CNY":
        report.errors.append(
            FieldIssue(
                "conventions.currency",
                "error",
                "P0 仅支持 CNY 本位币，其他币种请等待 P1 多币种能力",
            )
        )

    r_w = _as_decimal(params.finance.r_w)
    if r_w is None or r_w <= Decimal("-1"):
        report.errors.append(FieldIssue("finance.r_w", "error", "WACC 必须大于 −100%"))
    elif r_w > ONE:
        report.warnings.append(
            FieldIssue("finance.r_w", "warning", f"WACC {dec_str(r_w)} 高于 100%，请确认口径是否为年化比率")
        )

    horizon = _as_decimal(params.finance.T_horizon)
    if horizon is not None and horizon > Decimal("240"):
        report.warnings.append(
            FieldIssue("finance.T_horizon", "warning", "分析周期超过 20 年，长周期假设的可信度显著下降")
        )
    if horizon is not None and params.hw.T_deploy >= horizon:
        report.errors.append(
            FieldIssue("hw.T_deploy", "error", "部署上线周期必须小于分析周期，否则周期内无运营期")
        )

    if report.errors:
        return report

    derived = derive(params)

    if derived.Q_cap_M <= ZERO:
        report.errors.append(
            FieldIssue("perf.T_eff", "error", "满负荷月产能为 0，请检查有效吞吐 T_eff")
        )
        return report

    if derived.Q_eq > derived.Q_cap_M:
        report.warnings.append(
            FieldIssue(
                "demand.D_eq",
                "warning",
                f"月需求量 {dec_str(derived.Q_eq)} Mtok 超过满负荷产能 "
                f"{dec_str(derived.Q_cap_M)} Mtok（容量墙），需扩容或下调需求假设",
            )
        )

    if params.demand.util_mode == UTIL_MODE_EXPLICIT and derived.U > ZERO:
        relative_gap = abs(safe_div(derived.U_implied - derived.U, derived.U))
        if relative_gap > _UTIL_MISMATCH_TOLERANCE:
            report.warnings.append(
                FieldIssue(
                    "demand.U",
                    "warning",
                    f"录入利用率 {dec_str(derived.U)} 与需求量隐含利用率 "
                    f"{dec_str(derived.U_implied)} 偏差 {dec_str(relative_gap)}，"
                    "建议改用「由 U 推算需求量」或「由需求量推算 U」以统一口径",
                )
            )

    if derived.k_source == "default":
        report.warnings.append(
            FieldIssue(
                "perf.k_override",
                "warning",
                "等效折算系数 k 使用了兜底默认值 0.1，建议补充实测吞吐或选择基准模型",
            )
        )

    if params.pricing.p_out <= ZERO and params.pricing.p_in <= ZERO:
        report.errors.append(
            FieldIssue("pricing.p_out", "error", "输入价与输出价不能同时为 0，否则收入恒为 0")
        )
    if params.pricing.p_cache_effective > params.pricing.p_in:
        report.warnings.append(
            FieldIssue("pricing.p_cache", "warning", "缓存命中价高于输入价，与常见定价策略相反，请确认")
        )
    if params.pricing.p_out < params.pricing.p_in:
        report.warnings.append(
            FieldIssue("pricing.p_out", "warning", "输出价低于输入价，与主流 API 定价结构相反，请确认")
        )

    return report


def validate_params(params: ScenarioParams) -> List[Dict[str, str]]:
    """校验参数；存在 error 时抛异常，否则返回 warning 列表。

    Raises:
        ValidationFailedError: 存在阻塞性错误。
    """
    report = build_report(params)
    if not report.ok:
        raise ValidationFailedError("参数校验未通过，请修正标红项后重试", report.to_dict())
    return [item.to_dict() for item in report.warnings]
