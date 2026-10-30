"""报告数据组装（P1 REQ-12）。

把「方案 meta + 口径(conventions) + 入参(params) + 计算结果(payload)」整理成
一份结构化的报告上下文 `ReportData`，供 `pdf.py` / `excel.py` 消费。

设计要点：
- 不引入任何前端无法复现的口径；数值一律沿用后端权威结果（payload）的字符串；
- 必须包含口径摘要与免责声明（合规要求）；
- 纯函数、零 IO，便于单测。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

PARAM_GROUP_LABELS: Dict[str, str] = {
    "hw": "硬件配置",
    "power": "功耗",
    "perf": "性能",
    "demand": "需求",
    "pricing": "定价",
    "finance": "财务",
    "bench": "基准引用",
    "conventions": "口径",
}

PARAM_KEY_LABELS: Dict[str, str] = {
    "gpu_code": "GPU 型号",
    "gpu_count": "GPU 数量",
    "node_count": "节点数",
    "mem_gb": "显存(GB)",
    "power_w": "单卡功耗(W)",
    "pue": "PUE",
    "k": "等效折算系数 k",
    "k_source": "k 来源",
    "model_code": "模型代号",
    "throughput_prefill": "Prefill 吞吐",
    "throughput_decode": "Decode 吞吐",
    "throughput_effective": "等效有效吞吐",
    "Q_eq": "等效均衡需求( Mtok/月)",
    "Q_demand": "需求规模",
    "price_in": "输入单价",
    "price_out": "输出单价",
    "price_cache": "缓存单价",
    "rent_inc": "租金计入项",
    "rent_cny_per_hour": "租用单价(元/小时)",
    "T_horizon": "测算期(月)",
    "r_w": "加权资本成本 WACC",
    "tax_rate": "税率",
    "depreciation_years": "折旧年限",
    "currency": "币种",
    "taxed": "是否税前",
    "utilization_def": "利用率口径",
}

CONVENTION_LABELS: Dict[str, str] = {
    "currency": "本位币",
    "taxed": "口径",
    "utilization_def": "利用率定义",
    "T_horizon": "测算期(月)",
    "r_w": "加权资本成本 WACC",
    "generated_at": "基准/报告生成日期",
    "formula_spec_version": "公式规范版本",
    "engine_version": "引擎版本",
}

_UTIL_LABELS: Dict[str, str] = {
    "effective_load_over_capacity": "有效负载 / 满负荷算力",
}


def _humanize_key(key: str) -> str:
    """下划线命名 → 可读中文/英文标签。"""
    return PARAM_KEY_LABELS.get(key, key.replace("_", " ").title())


def _to_decimal(raw: Any) -> Optional[Decimal]:
    """字符串/数字 → Decimal，非法返回 None。"""
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _fmt_number(raw: Any) -> str:
    """通用数值格式化（千分位、最多 4 位小数）。"""
    dec = _to_decimal(raw)
    if dec is None:
        return "—" if raw is None else str(raw)
    if dec == dec.to_integral_value():
        return f"{dec:,.0f}"
    return f"{dec:,.4f}".rstrip("0").rstrip(".")


def _fmt_kpi(value: Any, kind: str) -> str:
    """KPI 值格式化（比率/月份 → 百分比）。"""
    if value is None:
        return "—"
    dec = _to_decimal(value)
    if dec is None:
        return str(value)
    if kind in ("ratio", "months"):
        return f"{dec * 100:.2f}%"
    if kind == "money":
        return f"{dec:,.2f}"
    if kind == "cost":
        return f"{dec:,.4f}"
    return f"{dec:,.4f}".rstrip("0").rstrip(".")


def _convention_rows(conventions: Dict[str, Any], payload: Dict[str, Any], generated_at: str = "") -> List[Dict[str, str]]:
    """口径摘要行（币种 / 税前 / 利用率口径 / 版本 / 测算期 / WACC / 基准日期）。"""
    merged = dict(payload.get("conventions") or {})
    merged.update(conventions or {})
    if generated_at:
        merged.setdefault("generated_at", generated_at)
    rows: List[Dict[str, str]] = []
    ordered = ["currency", "taxed", "utilization_def", "T_horizon", "r_w", "generated_at", "formula_spec_version", "engine_version"]
    for key in ordered:
        value: Any = merged.get(key)
        if value is None:
            continue
        label = CONVENTION_LABELS.get(key, key)
        if key == "taxed":
            text = "税前" if value in (False, "False", 0, "0") else "税后"
        elif key == "generated_at":
            text = str(value) if value else ""
        elif key == "utilization_def":
            text = _UTIL_LABELS.get(str(value), str(value))
        elif key in ("T_horizon", "r_w"):
            text = _fmt_number(value)
        else:
            text = str(value)
        rows.append({"label": label, "value": text})
    return rows


def _param_sections(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """参数分组 → 报告段落。"""
    sections: List[Dict[str, Any]] = []
    order = ["hw", "power", "perf", "demand", "pricing", "finance", "bench", "conventions"]
    keys = list(order)
    keys.extend(k for k in params.keys() if k not in order)
    for group in keys:
        group_data = params.get(group)
        if not isinstance(group_data, dict):
            continue
        rows = [
            {"key": _humanize_key(k), "value": _fmt_number(v)}
            for k, v in group_data.items()
            if k not in ("conventions",)
        ]
        if not rows:
            continue
        sections.append(
            {"group": group, "label": PARAM_GROUP_LABELS.get(group, group), "rows": rows}
        )
    return sections


def _kpis(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """KPI 卡片 → 报告行。"""
    out: List[Dict[str, str]] = []
    recommended: Optional[str] = None
    for item in payload.get("kpis", []) or []:
        if item.get("kind") == "text":
            if item.get("key") == "recommended_plan" and item.get("value"):
                recommended = str(item.get("value"))
            continue
        out.append(
            {
                "label": str(item.get("label", "")),
                "value": _fmt_kpi(item.get("value"), str(item.get("kind", ""))),
                "unit": str(item.get("unit", "")),
            }
        )
    return out, recommended  # type: ignore[return-value]


def _financials(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """核心财务指标行。"""
    fin = payload.get("financials", {}) or {}
    irr = fin.get("irr", {}) or {}
    rows = [
        ("NPV（净现值）", fin.get("npv"), "money"),
        ("TCO（全周期总拥有成本）", fin.get("tco"), "money"),
        ("ROI（投资回报率）", fin.get("roi"), "ratio"),
        ("IRR（年化内部收益率）", irr.get("irr_annual"), "ratio"),
        ("静态回本（月）", fin.get("payback_static"), "months"),
        ("折现回本（月）", fin.get("payback_discounted"), "months"),
        ("全周期总收入", fin.get("total_revenue"), "money"),
        ("全周期总经营现金流出", fin.get("total_opex_cash"), "money"),
        ("全周期总税", fin.get("total_tax"), "money"),
    ]
    return [{"label": label, "value": _fmt_kpi(value, kind)} for label, value, kind in rows]


def _cost_breakdown(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """单位成本结构（按占比）。"""
    items = (payload.get("unit_cost", {}) or {}).get("breakdown", []) or []
    return [
        {
            "label": str(item.get("label", "")),
            "amount": _fmt_number(item.get("amount")),
            "share": _fmt_kpi(item.get("share"), "ratio"),
        }
        for item in items
    ]


def _cashflows_yearly(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """逐年现金流（供表格渲染）。"""
    rows = (payload.get("financials", {}) or {}).get("cashflows_yearly", []) or []
    keys = [
        ("period", "期"),
        ("period_type", "类型"),
        ("revenue", "收入"),
        ("opex_cash", "经营现金"),
        ("depreciation", "折旧"),
        ("ebt", "税前利润"),
        ("tax", "税"),
        ("net_cf", "净现金流"),
        ("cum_cf", "累计净现金流"),
        ("discounted_cf", "折现现金流"),
        ("cum_discounted_cf", "累计折现现金流"),
    ]
    return [
        {label: _fmt_number(row.get(key)) for key, label in keys}
        for row in rows
    ]


def _sensitivity(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """敏感性分析摘要。"""
    sens = payload.get("sensitivity")
    if not sens:
        return None
    items = [
        {
            "label": str(item.get("label", "")),
            "base": _fmt_number(item.get("base")),
            "low": _fmt_number(item.get("low")),
            "high": _fmt_number(item.get("high")),
            "swing_pct": _fmt_kpi(item.get("swing_pct"), "ratio"),
        }
        for item in (sens.get("items", []) or [])
    ]
    return {"target_label": str(sens.get("target_label", "")), "items": items}


CN_CFG_LABELS: Dict[str, str] = {
    "none": "无国产化要求（沿用国际主流卡）",
    "partial": "部分国产化（混合部署，国产卡承担部分负载）",
    "full": "全栈国产化（关键算力全部采用国产卡，如昇腾 910B）",
}


def _localization(scenario: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """P2-5 信创合规报表：国产化专项段落。

    额外显式呈现：国产卡占比、CN_cfg 取值与含义、国产化专项结论与合规提示。
    """
    params = scenario.get("params", {}) or {}
    hw = params.get("hw", {}) or {}
    domestic_share = hw.get("domestic_gpu_share")
    cn_cfg = str(hw.get("CN_cfg", "none") or "none")
    share_dec = _to_decimal(domestic_share)
    share_pct = f"{(share_dec * 100):.2f}%" if share_dec is not None else "未填写"
    cn_label = CN_CFG_LABELS.get(cn_cfg, cn_cfg)

    conclusion = (
        f"关键算力国产化率 {share_pct}，国产化口径：{cn_label}。"
    )
    prompts: List[str] = []
    if cn_cfg == "none":
        prompts.append("当前未设置国产化口径（CN_cfg=none）：若面向政务/金融等信创场景，建议明确国产卡占比与供应链来源。")
    else:
        if share_dec is None or share_dec <= Decimal("0"):
            prompts.append("已声明国产化口径但未填写国产卡占比（domestic_gpu_share），请补充以评估关键算力国产化率。")
        elif share_dec < Decimal("0.5"):
            prompts.append(f"关键算力国产化率 {share_pct} 低于 50%：信创达标存在缺口，建议提升国产卡（如昇腾 910B）承载比例。")
        else:
            prompts.append(f"关键算力国产化率 {share_pct} ≥ 50%：基本满足信创要求，仍建议留存供应链来源证明以备审计。")
    prompts.append("供应链风险提示：国产卡供给与生态适配（算子/框架兼容）可能影响上线节奏，建议在敏感性中单独评估。")

    return {
        "domestic_gpu_share": share_pct,
        "cn_cfg": cn_cfg,
        "cn_cfg_label": cn_label,
        "conclusion": conclusion,
        "prompts": prompts,
    }


def assemble_report(
    scenario: Dict[str, Any],
    payload: Dict[str, Any],
    compliance: Optional[str] = None,
) -> Dict[str, Any]:
    """组装报告数据（字典），供 PDF / Excel 渲染。

    Args:
        scenario: 方案详情（含 name/version/conventions/params），来自 `ScenarioDetailOut.dict()`
        payload: 权威计算结果载荷（`compute_all` 经 `to_jsonable` 后的字典）
        compliance: 报表变体，`localization` 时追加「信创合规」专项段落。
    """
    kpis, recommended = _kpis(payload)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    localization = _localization(scenario) if compliance == "localization" else None
    report: Dict[str, Any] = {
        "title": "AI 算力投资 ROI 测算报告",
        "scenario_name": str(scenario.get("name", "")),
        "version": scenario.get("version", 1),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "engine_version": str(payload.get("engine_version", "")),
        "formula_spec_version": str(payload.get("formula_spec_version", "")),
        "conventions": _convention_rows(scenario.get("conventions", {}) or {}, payload, generated_at=generated_at),
        "param_sections": _param_sections(scenario.get("params", {}) or {}),
        "kpis": kpis,
        "recommended_plan": recommended,
        "financials": _financials(payload),
        "cost_breakdown": _cost_breakdown(payload),
        "cashflows_yearly": _cashflows_yearly(payload),
        "sensitivity": _sensitivity(payload),
        "localization": localization,
        "warnings": [str(w) for w in (payload.get("warnings", []) or [])],
        "disclaimer": str(
            payload.get(
                "disclaimer",
                "本平台测算结果完全基于用户输入假设与行业基准，不构成任何投资承诺或建议；"
                "实际决策须结合尽调与专业意见。",
            )
        ),
    }
    if localization is not None:
        report["title"] = "AI 算力投资 ROI 测算报告（信创合规版）"
    return report
