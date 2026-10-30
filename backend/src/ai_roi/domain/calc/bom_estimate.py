"""智算组网配置清单自动解析 + 方案估算（用户需求 2026-08-19）。

背景：运维侧以「智算组网配置清单」（Excel，如 5090方案-100GE组网）作为方案交付物，
含 GPU 服务器 / 推理·存储·管理交换机 / AOC·MPO·光模块·线缆 / 分布式存储节点 /
系统集成·维保的逐项数量与单价。本模块把这类清单解析为结构化 BOM，并映射到
`ScenarioParams` 走既有计算引擎做 ROI 估算——即「上传方案 → 自动测算」。

清单列约定（第一个 sheet）：
`序号 | 类型 | 设备名称 | 参数描述 | 数量 | 单价（含税） | 总价 | 备注`

映射策略（估算假设显式标注，不静默）：
- GPU：从设备名称/类型识别型号关键词（5090/H20/910B 等）→ `GPU_CATALOG` 匹配；
  `N_gpu = 服务器台数 × 单机卡数`（catalog.max_cards_per_node；5090=5）；
  服务器单价清单缺失 → 用 catalog 参考价 `P_gpu×卡数`，并写入假设；
- 配套 CAPEX：推理/存储/管理组网 + 存储节点 + 系统集成 按清单**实际数量×单价**，
  总额注入 `hw.P_aux`（整机配套价，单次投入，与硬件反选口径一致）；
- 维保（/年）→ 叠加 `power.Co_ops`（年费分摊 /12）；
- 其余业务参数（电价/售价/需求/利用率）沿用默认，由用户在向导确认调整。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D, ZERO, dec_str, dsum, safe_div, to_jsonable
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.hardware_recommend import GPU_CATALOG
from ai_roi.domain.calc.parameters import ScenarioParams, default_params
from ai_roi.domain.calc.codec import params_to_dict
from ai_roi.domain.validation.params import build_report

CATEGORY_MAP = {
    "5090服务器": "gpu_server",
    "推理网络": "compute_net",
    "存储网络": "storage_net",
    "存储": "storage",
    "带内管理": "mgmt_net",
    "带外管理": "oob_net",
    "服务": "service",
}

GPU_KEYWORDS = {
    "5090": "rtx5090",
    "h100": "h100_sxm",
    "h800": "h800_sxm",
    "h20": "h20",
    "a100": "a100_80g",
    "l40s": "l40s",
    "910b": "ascend_910b",
    "910c": "ascend_910c",
    "思元": "cambricon_590",
    "海光": "hygon_k100",
    "沐曦": "muxi_c500",
    "mi300": "mi300x",
}


@dataclasses.dataclass(frozen=True)
class BomLine:
    """清单行。"""

    type: str
    name: str
    spec: str
    qty: Decimal
    unit_price: Decimal
    total: Decimal
    note: str = ""


class BomSpec:
    """解析后的结构化清单。"""

    def __init__(self, lines: List[BomLine]) -> None:
        self.lines = lines
        self.by_category: Dict[str, List[BomLine]] = {}
        for line in lines:
            cat = CATEGORY_MAP.get(line.type, "other")
            self.by_category.setdefault(cat, []).append(line)

    @property
    def gpu_servers(self) -> List[BomLine]:
        return self.by_category.get("gpu_server", [])

    def category_total(self, category: str) -> Decimal:
        return dsum(line.total for line in self.by_category.get(category, []))

    def all_capex(self) -> Decimal:
        """全部硬件/服务投入（不含维保年费口径，维保按 1 年计入一次）。"""
        return dsum(line.total for line in self.lines)


def parse_network_bom_rows(rows: List[List[str]]) -> BomSpec:
    """解析智算组网配置清单行矩阵（xlsx 首 sheet，单元格已字符串化）。

    openpyxl 的字节 → 行矩阵读取在基础设施层
    （`ai_roi.infrastructure.files.bom_xlsx.read_bom_rows`），本函数保持纯 Python。

    兼容合并单元格：`类型` 列为空时前向填充（沿用上一行类型，如存储网络下的
    AOC/光模块/MPO 多行共享同一类型）。
    """
    lines: List[BomLine] = []
    last_type = ""
    for row in rows:
        cells = list(row)
        if len(cells) < 5:
            continue
        type_name = cells[1]
        name = cells[2]
        if not name:
            continue
        if type_name:
            last_type = type_name
        type_name = last_type
        if type_name == "类型" or name in ("设备名称", "合计"):
            continue
        qty = _to_dec(cells[4])
        unit_price = _to_dec(cells[5]) if len(cells) > 5 else ZERO
        total = _to_dec(cells[6]) if len(cells) > 6 and cells[6] else qty * unit_price
        note = cells[7] if len(cells) > 7 else ""
        lines.append(
            BomLine(
                type=type_name,
                name=name,
                spec=cells[3] if len(cells) > 3 else "",
                qty=qty,
                unit_price=unit_price,
                total=total,
                note=note,
            )
        )
    if not lines:
        raise ValueError("清单为空或格式不符：需包含「类型/设备名称/数量/单价」列")
    return BomSpec(lines)


def _to_dec(value: Any) -> Decimal:
    if value is None or str(value).strip() == "":
        return ZERO
    try:
        return D(str(value).replace(",", "").strip())
    except Exception:
        return ZERO


def estimate_from_bom(
    bom: BomSpec,
    base: Optional[ScenarioParams] = None,
) -> Dict[str, Any]:
    """清单 → ScenarioParams + 计算引擎估算。

    返回：{assumptions, params, params_dict, kpis, supporting_capex, bom_summary}
    """
    base = base or default_params()
    assumptions: List[str] = []

    gpu = None
    server_count = ZERO
    gpu_server_body_total = ZERO
    gpu_server_extra = ZERO
    for line in bom.gpu_servers:
        if "服务器" in line.name or "server" in line.name.lower():
            server_count += line.qty
            gpu_server_body_total += line.total
        else:
            gpu_server_extra += line.total
        for keyword, gpu_id in GPU_KEYWORDS.items():
            if keyword in line.name.lower() or keyword in line.type.lower():
                gpu = next((g for g in GPU_CATALOG if g.id == gpu_id), None)
                break
    if gpu is None:
        raise ValueError(
            "无法识别 GPU 型号（支持关键词：5090/H100/H800/H20/A100/L40S/910B/910C/思元/海光/沐曦/MI300）"
        )
    n_gpu = server_count * gpu.max_cards_per_node
    assumptions.append(
        f"GPU：{server_count} 台「{gpu.name}」服务器 × 每台 {gpu.max_cards_per_node} 卡 ⇒ "
        f"N_gpu={n_gpu}（卡数按目录 {gpu.id} 单机插槽推算，清单未直接给卡数）。"
    )
    if server_count > ZERO and gpu_server_body_total > ZERO:
        price_per_card = safe_div(gpu_server_body_total, n_gpu)
        assumptions.append(
            f"GPU 服务器清单单价 {gpu_server_body_total} 元（{server_count} 台）÷ {gpu.max_cards_per_node} 卡/台"
            f" ⇒ 单卡参考价 {price_per_card} 元/卡（用于 N_gpu×P_gpu 还原服务器本体投资）。"
        )
    else:
        price_per_card = gpu.price_per_card
        assumptions.append(f"GPU 服务器单价清单缺失，按目录参考价 {gpu.price_per_card} 元/卡估算。")

    port_speed = 0
    for line in bom.lines:
        m = __import__("re").search(r"(\d+)\s*GE", line.spec)
        if m and ("交换机" in line.name or "交换" in line.name):
            port_speed = max(port_speed, int(m.group(1)))
    if port_speed:
        assumptions.append(f"组网端口速率识别为 {port_speed}GE（从交换机规格解析）；已标注至参数 supporting_port_speed。")
    else:
        assumptions.append("未从清单识别到明确端口速率（交换机规格未含 GE 字样），按默认速率估算。")

    compute_net = bom.category_total("compute_net")
    storage_net = bom.category_total("storage_net")
    storage_capex = bom.category_total("storage")
    mgmt_capex = bom.category_total("mgmt_net") + bom.category_total("oob_net")
    service_capex = bom.category_total("service")
    supporting_capex = (
        compute_net + storage_net + storage_capex + mgmt_capex + service_capex + gpu_server_extra
    )
    assumptions.append(
        f"配套投入（清单实际）：推理网络 {compute_net} + 存储网络 {storage_net} + "
        f"存储节点 {storage_capex} + 管理/带外 {mgmt_capex} + 集成/服务 {service_capex}"
        + (f" + 服务器配套 {gpu_server_extra}" if gpu_server_extra > ZERO else "")
        + f" = {supporting_capex} 元，并入「整机配套价」P_aux。"
    )

    warranty = ZERO
    for line in bom.by_category.get("service", []):
        if "维保" in line.name:
            warranty += line.total
    co_ops = base.power.Co_ops + safe_div(warranty, D(12))
    if warranty > ZERO:
        assumptions.append(f"维保 {warranty} 元/年已分摊进 Co_ops（+{safe_div(warranty, D(12))} 元/月）。")

    params = (
        base
        .with_override("hw.N_gpu", n_gpu)
        .with_override("hw.P_gpu", price_per_card)
        .with_override("hw.P_aux", supporting_capex)
        .with_override("hw.supporting_fabric", gpu.fabric_recommended)
        .with_override("hw.supporting_cards_per_node", gpu.max_cards_per_node)
        .with_override("hw.supporting_port_speed", port_speed)
        .with_override("power.Co_ops", co_ops)
        .with_override("power.P_sys_override", base.power.P_sys_override)
    )
    pre_launch = ZERO
    for line in bom.by_category.get("service", []):
        if "维保" not in line.name:
            pre_launch += line.total
    params = params.with_override("hw.pre_launch_cost", pre_launch)
    if pre_launch > ZERO:
        assumptions.append(f"系统集成等一次性服务 {pre_launch} 元计入上线前投入（pre_launch_cost）。")

    report = build_report(params)
    if not report.ok:
        assumptions.extend(f"参数校验未通过：{item.message}" for item in report.errors)

    payload = compute_all(
        params,
        EngineOptions(include_sensitivity=False, include_scenarios=False, include_crossover=True),
    )
    kpis = {k["key"]: k["value"] for k in payload["kpis"]}
    kpi_meta = {k["key"]: {"label": k.get("label", k["key"]), "unit": k.get("unit", "")} for k in payload["kpis"]}

    bom_summary = {
        "gpu": {"id": gpu.id, "name": gpu.name, "price_per_card": dec_str(gpu.price_per_card)},
        "server_count": dec_str(server_count),
        "cards_per_node": dec_str(gpu.max_cards_per_node),
        "n_gpu": dec_str(n_gpu),
        "compute_net": dec_str(compute_net),
        "storage_net": dec_str(storage_net),
        "storage": dec_str(storage_capex),
        "mgmt_net": dec_str(mgmt_capex),
        "oob_net": dec_str(bom.category_total("oob_net")),
        "gpu_server_body": dec_str(gpu_server_body_total),
        "service": dec_str(service_capex),
        "supporting_capex": dec_str(supporting_capex),
        "total_estimate": dec_str(gpu_server_body_total + supporting_capex),
        "lines": [
            {
                "type": line.type,
                "name": line.name,
                "qty": dec_str(line.qty),
                "unit_price": dec_str(line.unit_price),
                "total": dec_str(line.total),
                "note": line.note,
            }
            for line in bom.lines
        ],
    }

    return {
        "assumptions": assumptions,
        "params": to_jsonable(params_to_dict(params)),
        "kpis": kpis,
        "kpi_meta": kpi_meta,
        "bom_summary": bom_summary,
        "financials": {
            "npv": payload["financials"]["npv"],
            "tco": payload["financials"]["tco"],
            "payback_static": payload["financials"]["payback_static"],
            "irr_annual": payload["financials"].get("irr", {}).get("irr_annual"),
        },
    }
