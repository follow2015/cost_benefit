"""硬件反选推荐（架构 §3.13，新增）。

由业务侧目标吞吐/需求量 + 模型规模/SLA/合规约束，反推候选 GPU 型号与所需卡数，
装配为可直接复用 `engine.compute_all()` 的完整测算方案，并按目标函数打分排序。

设计原则（与既有工程风格对齐）：
- 与 `throughput.py` 的正向吞吐公式（`REF_T_DC` / `QUANT_THROUGHPUT_MULT` /
  `available_batch_limit`）严格同源，不引入第二套吞吐口径；
- 纯函数、零 IO；`GPU_CATALOG` 是可替换的数据表（后续可换成 `bench` 基准库查询）；
- 「装不下 / 需多机 / 不合规」的候选明确标 `infeasible` 并说明原因，不静默降级为错误推荐；
- 每条推荐携带 `assumptions`（推导假设）与 `warnings`（不确定性提示），不做静默猜测。

评审修正（2026-08-19，对齐《硬件反选推荐功能设计.md》评审 6 点）：
- FIX-1 整机功耗含配套：`P_sys = N_gpu×TDP/1000 + P_aux_power`，避免电费系统性低估；
- FIX-2 装配参数同步 `demand.U / D_eq`：需求驱动时 `util_mode=u_from_demand` 诚实反映增长裕量；
- FIX-3 SLA 收紧比例真正复用 `available_batch_limit`（参考 batch=64 的收缩比例），非另造线性口径；
- FIX-4 `assumptions` 作为构造参数传入候选，不用 `object.__setattr__` 破坏不可变语义；
- FIX-5 `balanced` 打分先按「可行集中相对最优」归一化（÷ min cost_per_m / min capex），
  消除「元/Mtok vs 元」单位混加与魔法除数；NPV<0 按亏损倍数追加惩罚；
- FIX-6 打分权重/惩罚系数抽为具名常量（`SCORE_W_*` / `NPV_PENALTY_MULT` / `OVER_BUDGET_PENALTY`）。
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D, MTOK, ONE, SEC, ZERO, safe_div
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import (
    UTIL_MODE_U_FROM_DEMAND,
    ScenarioParams,
    default_params,
)
from ai_roi.domain.calc.throughput import (
    QUANT_THROUGHPUT_MULT,
    REF_T_DC,
    available_batch_limit,
)
from ai_roi.domain.validation.params import build_report
from ai_roi.domain.calc.supporting_cost import (
    NetworkCatalogPrices,
    NetworkEstimate,
    STORAGE_MONTHLY_PER_GB,
    STORAGE_PRICE_PER_GB,
    StorageEstimate,
    estimate_network,
    estimate_storage,
    interconnect_loss_for,
)

BYTES_PER_PARAM: Dict[str, Decimal] = {
    "FP16": D("2"), "BF16": D("2"),
    "FP8": D("1"), "INT8": D("1"), "INT4": D("0.5"),
}
MEM_OVERHEAD_MULT = D("1.15")
REF_B_MAX = D("64")
SCORE_W_COST = D("0.7")
SCORE_W_CAPEX = D("0.3")
NPV_PENALTY_MULT = D("0.1")
OVER_BUDGET_PENALTY = D("1.5")
OBJECTIVES = {"balanced", "min_capex", "min_tco", "min_cost_per_m"}


@dataclass(frozen=True)
class GpuSpec:
    """单一 GPU 型号规格（硬件候选库条目）。"""

    id: str
    name: str
    vendor: str
    mem_gb: Decimal
    tdp_w: Decimal
    price_per_card: Decimal
    perf_index: Decimal
    max_cards_per_node: Decimal = D(8)
    domestic: bool = False
    supported_quant: Tuple[str, ...] = ("FP8", "FP16", "BF16", "INT8", "INT4")
    fabric_recommended: str = "roce"
    fabric_speed_gbps: int = 400
    notes: str = ""


GPU_CATALOG: List[GpuSpec] = [
    GpuSpec(
        "h100_sxm", "NVIDIA H100 SXM", "NVIDIA", D(80), D(700), D(250_000),
        perf_index=D("1.30"), fabric_recommended="ib", notes="旗舰卡，出口管制地区采购周期长；2026 国内参考 19-29 万",
    ),
    GpuSpec(
        "h800_sxm", "NVIDIA H800 SXM", "NVIDIA", D(80), D(700), D(250_000),
        perf_index=D("1.00"), fabric_recommended="ib", notes="与 throughput.py 参考基准卡口径一致（perf_index=1.0）",
    ),
    GpuSpec(
        "h20", "NVIDIA H20", "NVIDIA", D(96), D(400), D(110_000),
        perf_index=D("0.70"), fabric_recommended="ib",
        notes="国内唯一合规数据中心级 NVIDIA 卡（96GB），推理性价比主力；参考 9-12 万",
    ),
    GpuSpec(
        "a100_80g", "NVIDIA A100 80GB", "NVIDIA", D(80), D(400), D(120_000),
        perf_index=D("0.75"), fabric_recommended="ib", notes="性价比稳健，供货成熟；2026 参考约 15 万",
    ),
    GpuSpec(
        "l40s", "NVIDIA L40S", "NVIDIA", D(48), D(350), D(65_000),
        perf_index=D("0.45"), supported_quant=("FP8", "FP16", "INT8", "INT4"),
        fabric_recommended="roce", notes="推理性价比型，显存较小，大模型需更高并行度",
    ),
    GpuSpec(
        "rtx5090", "NVIDIA RTX 5090", "NVIDIA", D(32), D(575), D(25_000),
        perf_index=D("0.30"), max_cards_per_node=D(5), supported_quant=("FP8", "FP16", "INT8", "INT4"),
        fabric_recommended="roce", notes="消费级旗舰（32GB GDDR7），无 NVLink，多卡走 PCIe/RoCE；参考 1.5-3.1 万",
    ),
    GpuSpec(
        "ascend_910b", "华为昇腾 910B", "Huawei", D(64), D(310), D(100_000),
        perf_index=D("0.55"), domestic=True, supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="roce", notes="信创合规首选（FP16 256-320 TFLOPS）；集采 7.8 万、零售 10-12 万",
    ),
    GpuSpec(
        "ascend_910c", "华为昇腾 910C", "Huawei", D(64), D(310), D(80_000),
        perf_index=D("0.75"), domestic=True, supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="roce", notes="910B 升级款，市场相对紧缺；参考 6-9 万",
    ),
    GpuSpec(
        "cambricon_590", "寒武纪思元 590", "Cambricon", D(64), D(300), D(55_000),
        perf_index=D("0.45"), domestic=True, supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="roce", notes="高并发推理（FP16 256 TFLOPS，HBM3e）；参考 4.8-6 万",
    ),
    GpuSpec(
        "hygon_k100", "海光 K100", "Hygon", D(64), D(300), D(52_000),
        perf_index=D("0.30"), domestic=True, supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="roce", notes="传统企业 AI 改造（FP16 150 TFLOPS）；参考 5.2 万",
    ),
    GpuSpec(
        "muxi_c500", "沐曦 C500", "Muxi", D(128), D(350), D(58_000),
        perf_index=D("0.45"), domestic=True, supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="roce", notes="AI+渲染混合（128GB HBM3e，FP16 256 TFLOPS）；参考 5.8 万",
    ),
    GpuSpec(
        "mi300x", "AMD MI300X", "AMD", D(192), D(750), D(210_000),
        perf_index=D("1.05"), supported_quant=("FP16", "BF16", "INT8"),
        fabric_recommended="ib", notes="大显存单卡，可降低并行度/整机数量",
    ),
    GpuSpec(
        "b300_sxm", "NVIDIA B300 SXM", "NVIDIA", D(288), D(1400), D(900_000),
        perf_index=D("1.80"), fabric_recommended="ib", fabric_speed_gbps=800,
        notes="Blackwell Ultra 旗舰（288GB HBM3e/8TB/s/液冷）；对华禁售，2026-08 国内渠道 8 卡整机 700-1450 万（单卡≈90 万，灰色市场价，可改）",
    ),
]


@dataclass(frozen=True)
class HardwareRequirement:
    """硬件反选输入（七组参数之外的新增第八组：需求反推组）。"""

    T_eff_target: Optional[Decimal] = None
    D_eq_target: Optional[Decimal] = None
    U_target: Decimal = D("0.7")
    growth_headroom: Decimal = D("0.2")

    M_param: Decimal = D(70)
    quant: str = "FP8"
    Ctx: Decimal = D(8_192)
    Mem_w_override: Optional[Decimal] = None

    SLA_ttft: Optional[Decimal] = None
    SLA_tpot: Optional[Decimal] = None

    CN_cfg: str = "none"

    port_speed: Optional[int] = None

    capex_budget: Optional[Decimal] = None
    power_budget_kw: Optional[Decimal] = None

    objective: str = "balanced"

    fabric: str = ""

    extra_nodes: int = 0

    spine_port_speed: Optional[int] = None

    base_params: Optional[ScenarioParams] = None


@dataclass(frozen=True)
class HardwareCandidate:
    """单个硬件候选的完整评估结果。"""

    gpu: GpuSpec
    N_gpu: Decimal
    feasible: bool
    T_eff_achieved: Decimal
    mem_required_gb: Decimal
    capex: Decimal
    power_kw: Decimal
    over_budget: bool
    score: Decimal
    params: Optional[ScenarioParams]
    kpis: Dict[str, Any]
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    node_count: int = 1
    supporting_capex: Decimal = ZERO
    supporting_power_kw: Decimal = ZERO
    storage: Optional[StorageEstimate] = None
    network: Optional[NetworkEstimate] = None
    hardware_bom: Optional[Dict[str, Any]] = None

    @property
    def total_capex(self) -> Decimal:
        """含配套的总 CAPEX（GPU + 存储 + 组网，打分/预算口径）。"""
        return self.capex + self.supporting_capex

    @property
    def total_power_kw(self) -> Decimal:
        """含配套的总功耗（预算口径）。"""
        return self.power_kw + self.supporting_power_kw


@dataclass(frozen=True)
class HardwareRecommendationResult:
    """硬件反选推荐结果。"""

    target_tok_s: Decimal
    mem_required_gb: Decimal
    candidates: List[HardwareCandidate]
    recommended: List[HardwareCandidate]
    notes: List[str] = field(default_factory=list)


def _target_tok_s(req: HardwareRequirement) -> Tuple[Decimal, List[str]]:
    """换算目标有效吞吐（tok/s），并记录推导假设。"""
    assumptions: List[str] = []
    if req.T_eff_target is not None and req.T_eff_target > ZERO:
        assumptions.append(f"直接采用指定目标吞吐 T_eff_target={req.T_eff_target} tok/s。")
        return req.T_eff_target, assumptions
    if req.D_eq_target is not None and req.D_eq_target > ZERO:
        q_cap_target = safe_div(req.D_eq_target, req.U_target) * (ONE + req.growth_headroom)
        tok_s = q_cap_target * MTOK / SEC
        assumptions.append(
            f"由月需求量 D_eq_target={req.D_eq_target} Mtok/月、目标利用率 U_target="
            f"{req.U_target}、增长裕量 {req.growth_headroom} 反推目标满负荷产能 "
            f"{q_cap_target} Mtok/月 ⇒ 目标吞吐 {tok_s} tok/s。"
        )
        return tok_s, assumptions
    raise ValueError("必须提供 T_eff_target 或 D_eq_target 之一。")


def _mem_required_gb(req: HardwareRequirement) -> Tuple[Decimal, List[str]]:
    """估算权重显存需求（GB）。"""
    if req.Mem_w_override is not None and req.Mem_w_override > ZERO:
        return req.Mem_w_override, [f"采用人工录入权重显存 {req.Mem_w_override} GB。"]
    bytes_per_param = BYTES_PER_PARAM.get(req.quant.upper(), D("2"))
    mem = req.M_param * bytes_per_param * MEM_OVERHEAD_MULT
    note = (
        f"按模型规模 {req.M_param}B × {bytes_per_param} 字节/参数（{req.quant}）× "
        f"开销系数 {MEM_OVERHEAD_MULT}（KV cache/框架/激活值）估算权重显存 ≈ {mem} GB。"
    )
    return mem, [note]


def apply_model_preset(
    req: HardwareRequirement,
    params_b: Decimal,
    vram_gb: Optional[Decimal] = None,
) -> Tuple[HardwareRequirement, List[str]]:
    """把基准库模型规格应用到反选需求（方案构建向导「选模型」入口）。

    - 「选了模型」即以模型规格为权威：无条件覆盖 M_param（模型规模 B）；
    - `vram_gb`（模型表 vram_required_gb）→ Mem_w_override（更准的显存快照）；
    - 量化档位（quant）由调用方显式传入（全尺寸=BF16 / FP8 / INT8 / INT4 对比）。
    """
    notes: List[str] = []
    if params_b > ZERO:
        req = dataclasses.replace(req, M_param=params_b)
        notes.append(f"按基准库模型规格设置 M_param={params_b}B（全尺寸）。")
    if vram_gb is not None and vram_gb > ZERO:
        req = dataclasses.replace(req, Mem_w_override=vram_gb)
        notes.append(f"按模型表推荐显存设置 Mem_w_override={vram_gb}GB。")
    return req, notes


def _sla_scale(req: HardwareRequirement) -> Tuple[Decimal, List[str]]:
    """SLA 对单卡有效吞吐的收紧比例（FIX-3：真正复用 `available_batch_limit`）。

    以参考 batch = 64 求 SLA 约束下的可用 batch 上限，收缩比例 = B_limit / B_ref，
    与正向吞吐计算（throughput.available_batch_limit）完全同源，而非另造线性口径。
    只收紧、不放大：放松（大于参考）SLA 时比例被 available_batch_limit 夹回 1。
    """
    if req.SLA_ttft is None or req.SLA_tpot is None:
        return ONE, []
    b_limit = available_batch_limit(REF_B_MAX, req.SLA_ttft, req.SLA_tpot)
    scale = safe_div(b_limit, REF_B_MAX, ONE)
    note: List[str] = []
    if scale < ONE:
        note.append(
            f"SLA（TTFT={req.SLA_ttft}ms / TPOT={req.SLA_tpot}ms）严于参考基准，"
            f"单卡有效吞吐按 ×{scale} 收紧（复用 available_batch_limit 收缩比例）。"
        )
    return scale, note


def _assemble_params(
    gpu: GpuSpec,
    req: HardwareRequirement,
    base: ScenarioParams,
    n_gpu: Decimal,
    t_eff_achieved: Decimal,
    power_kw: Decimal,
    storage: StorageEstimate,
    network: NetworkEstimate,
    mem_required_gb: Decimal,
) -> Tuple[ScenarioParams, List[str]]:
    """把 (候选卡, 卡数) 装配为完整 `ScenarioParams` 覆盖（FIX-2：需求侧口径同步）。

    覆盖字段：hw.N_gpu / hw.P_gpu / hw.P_aux(=存储+组网配套 CAPEX，与推荐 total_capex
    同口径，非 0 丢弃) / hw.supporting_fabric / hw.supporting_mem_gb（反选推导输入快照，
    供前端改卡数后按同一口径联动重算配套 CAPEX）/ power.TDP / power.P_sys_override
    （FIX-1 含配套功耗：GPU + 主机配套 + 存储/组网）/ power.Co_stor / power.Co_net
    （配套推导月费与基线叠加，不丢弃用户录入）/ perf.T_eff / perf.M_param / perf.quant /
    hw.domestic_gpu_share / hw.CN_cfg / demand.U / demand.D_eq(+util_mode)。
    """
    assumptions: List[str] = []
    supporting_capex = storage.capex + network.capex
    total_power_kw = power_kw + storage.power_kw + network.power_kw
    params = (
        base
        .with_override("hw.N_gpu", n_gpu)
        .with_override("hw.P_gpu", gpu.price_per_card)
        .with_override("hw.P_aux", supporting_capex)
        .with_override("hw.supporting_fabric", network.fabric)
        .with_override("hw.supporting_mem_gb", mem_required_gb)
        .with_override("hw.supporting_cards_per_node", gpu.max_cards_per_node)
        .with_override("hw.extra_nodes", req.extra_nodes)
        .with_override("hw.supporting_spine_port_speed", req.spine_port_speed)
        .with_override("power.TDP", gpu.tdp_w)
        .with_override("power.P_sys_override", total_power_kw)
        .with_override("power.Co_stor", base.power.Co_stor + storage.monthly)
        .with_override("power.Co_net", base.power.Co_net + network.monthly)
        .with_override("perf.T_eff", t_eff_achieved)
        .with_override("perf.M_param", req.M_param)
        .with_override("perf.quant", req.quant)
        .with_override("hw.domestic_gpu_share", ONE if gpu.domestic else ZERO)
        .with_override("hw.CN_cfg", req.CN_cfg)
        .with_override("demand.U", req.U_target)
    )
    assumptions.append(
        f"配套成本口径：存储+组网 CAPEX {supporting_capex} 元已并入方案「整机配套价」"
        f"（财务 CAPEX = 卡价 + 配套，与推荐总 CAPEX 一致；改卡数后前端将按 fabric="
        f"{network.fabric}、权重显存 {mem_required_gb}GB 快照联动重算）；配套功耗 "
        f"{storage.power_kw + network.power_kw} kW 已并入整机功耗（电费口径一致）；"
        f"配套月费 Co_stor={base.power.Co_stor + storage.monthly} 元/月、"
        f"Co_net={base.power.Co_net + network.monthly} 元/月（基线 + 推导，可手动调整）。"
    )
    if req.D_eq_target is not None and req.D_eq_target > ZERO:
        params = params.with_override("demand.D_eq", req.D_eq_target)
        params = params.with_override("demand.util_mode", UTIL_MODE_U_FROM_DEMAND)
        assumptions.append(
            f"需求口径：D_eq={req.D_eq_target} Mtok/月，利用率按需求量/实际产能推导"
            "（含增长裕量，实际利用率 = D_eq / 满负荷产能）。"
        )
    else:
        q_cap_achieved = t_eff_achieved * SEC / MTOK
        d_eq_implied = q_cap_achieved * req.U_target
        params = params.with_override("demand.D_eq", d_eq_implied)
        assumptions.append(
            f"需求口径：仅给吞吐目标，按设计利用率 {req.U_target} 反推 D_eq="
            f"{d_eq_implied} Mtok/月（方案利用率 = U_target）。"
        )
    return params, assumptions


def _evaluate_candidate(
    gpu: GpuSpec,
    req: HardwareRequirement,
    base: ScenarioParams,
    target_tok_s: Decimal,
    mem_required_gb: Decimal,
    sla_scale: Decimal,
    assumptions: List[str],
    catalog: Optional[NetworkCatalogPrices] = None,
) -> HardwareCandidate:
    """评估单个候选卡（吞吐/显存双约束取 max；多机放行 + 配套存储/组网 + 折损；合规硬性剔除）。

    - 多机（N_gpu > 单机插槽）不再判 infeasible：按 `node_count=ceil(N/插槽)` 放行，
      跨机互联吞吐按 fabric 折损，组网/存储成本计入配套 CAPEX 与月费（§3.13 完整建模）；
    - 合规（CN_cfg=full 且非国产）仍为硬性 infeasible；
    - `catalog`：配件库价格覆盖（None = 内置经验常量；有 DB 数据时由路由层注入）。
    """
    warnings: List[str] = []
    quant_mult = QUANT_THROUGHPUT_MULT.get(req.quant.upper(), ONE)
    if req.quant.upper() not in gpu.supported_quant:
        warnings.append(
            f"{gpu.name} 对 {req.quant} 精度支持有限，吞吐按最接近档位估算，建议实测校准。"
        )

    cards_per_node = gpu.max_cards_per_node
    fabric = req.fabric if req.fabric else gpu.fabric_recommended
    per_card_tok_s = REF_T_DC * gpu.perf_index * quant_mult * sla_scale
    n0 = D(math.ceil(safe_div(target_tok_s, per_card_tok_s, D("1e9"))))
    if n0 > cards_per_node:
        loss_guess = interconnect_loss_for(fabric)
        per_card_eff = per_card_tok_s * (D(1) - loss_guess)
        n_throughput = D(math.ceil(safe_div(target_tok_s, per_card_eff, D("1e9"))))
    else:
        n_throughput = n0
    n_memory = D(math.ceil(safe_div(mem_required_gb, gpu.mem_gb, D("1e9"))))
    n_gpu = n_throughput if n_throughput >= n_memory else n_memory
    if n_memory > n_throughput:
        warnings.append("该型号显存偏小，实际卡数由「装下模型」而非「吞吐达标」决定。")

    storage = estimate_storage(
        mem_required_gb, req.M_param, req.Ctx, base.perf.B_max, n_gpu, catalog
    )
    network = estimate_network(
        n_gpu, cards_per_node, fabric=fabric, catalog=catalog,
        storage_capacity_gb=storage.capacity_gb,
        port_speed=req.port_speed or gpu.fabric_speed_gbps,
        extra_nodes=req.extra_nodes,
        spine_port_speed=req.spine_port_speed,
    )
    node_count = network.node_count
    if node_count > 1:
        warnings.append(
            f"需 {node_count} 台机（每台 ≤{cards_per_node} 卡），跨机互联吞吐按 "
            f"×{D(1) - network.interconnect_loss} 折损，存储/组网成本已计入配套 CAPEX 与月费。"
        )

    feasible = True
    if req.CN_cfg == "full" and not gpu.domestic:
        feasible = False
        warnings.append("信创合规要求全栈国产化（CN_cfg=full），该型号非国产卡，不予推荐。")
    elif req.CN_cfg == "partial" and not gpu.domestic:
        warnings.append("信创合规要求部分国产化，该型号非国产卡，建议与国产卡混合部署。")

    capex = n_gpu * gpu.price_per_card
    power_kw = n_gpu * gpu.tdp_w / D(1_000) + base.power.P_aux_power
    supporting_capex = storage.capex + network.capex
    supporting_power_kw = storage.power_kw + network.power_kw
    over_budget = (
        (req.capex_budget is not None and capex + supporting_capex > req.capex_budget)
        or (
            req.power_budget_kw is not None
            and power_kw + supporting_power_kw > req.power_budget_kw
        )
    )
    if over_budget:
        warnings.append("超出预算/功耗约束（含配套存储/组网），已降权保留在候选列表中供参考。")

    t_eff_achieved = per_card_tok_s * n_gpu * (D(1) - network.interconnect_loss)

    params: Optional[ScenarioParams] = None
    kpis: Dict[str, Any] = {}
    hardware_bom: Optional[Dict[str, Any]] = None
    if feasible:
        params, asm_assumptions = _assemble_params(
            gpu, req, base, n_gpu, t_eff_achieved, power_kw, storage, network, mem_required_gb
        )
        assumptions = assumptions + asm_assumptions + storage.assumptions + network.assumptions
        warnings.append(
            "Co_stor/Co_net 为「基线 + 存储/组网推导」叠加口径（非覆盖），"
            "一键应用后可在向导中继续手动调整。"
        )
        report = build_report(params)
        if not report.ok:
            feasible = False
            warnings.extend(item.message for item in report.errors)
        else:
            payload = compute_all(
                params,
                EngineOptions(include_sensitivity=False, include_scenarios=False,
                              include_crossover=True),
            )
            kpis = {
                "npv": payload["financials"]["npv"],
                "tco": payload["financials"]["tco"],
                "cost_per_m": payload["unit_cost"]["cost_per_m_capacity"],
                "payback_static": payload["financials"]["payback_static"],
                "recommended_plan_at_capacity": next(
                    (k["value"] for k in payload["kpis"] if k["key"] == "recommended_plan"), None
                ),
            }
            hardware_bom = _build_bom(
                gpu, n_gpu, node_count, storage, network, catalog
            )

    return HardwareCandidate(
        gpu=gpu,
        N_gpu=n_gpu,
        feasible=feasible,
        T_eff_achieved=t_eff_achieved,
        mem_required_gb=mem_required_gb,
        capex=capex,
        power_kw=power_kw,
        over_budget=over_budget,
        score=ZERO,
        params=params,
        kpis=kpis,
        assumptions=assumptions,
        warnings=warnings,
        node_count=node_count,
        supporting_capex=supporting_capex,
        supporting_power_kw=supporting_power_kw,
        storage=storage,
        network=network,
        hardware_bom=hardware_bom,
    )


def _build_bom(
    gpu: GpuSpec,
    n_gpu: Decimal,
    node_count: int,
    storage: StorageEstimate,
    network: NetworkEstimate,
    catalog: Optional[NetworkCatalogPrices],
) -> Dict[str, Any]:
    """生成硬件 BOM 清单（服务器/算力·存储·管理交换机/线缆/存储，逐项单价×数量=小计）。

    纯函数：数量来自 `estimate_network/estimate_storage` 推导，单价来自目录覆盖或内置常量。
    """
    prices = network.prices
    storage_price_gb = (
        catalog.storage_per_gb
        if catalog is not None and catalog.storage_per_gb is not None
        else STORAGE_PRICE_PER_GB
    )
    storage_monthly_gb = (
        catalog.storage_monthly_per_gb
        if catalog is not None and catalog.storage_monthly_per_gb is not None
        else STORAGE_MONTHLY_PER_GB
    )
    return {
        "gpu": {"id": gpu.id, "name": gpu.name, "vendor": gpu.vendor},
        "servers": {
            "name": f"{gpu.name} 服务器",
            "cards_per_node": int(gpu.max_cards_per_node),
            "node_count": node_count,
            "unit_price": gpu.price_per_card,
            "qty": int(n_gpu),
            "subtotal": gpu.price_per_card * n_gpu,
        },
        "compute_switch": prices.get("compute_switch", {"unit_price": ZERO, "unit": "台", "qty": 0}),
        "storage_switch": prices.get("storage_switch", {"unit_price": ZERO, "unit": "台", "qty": 0}),
        "mgmt_switch": prices.get("mgmt_switch", {"unit_price": ZERO, "unit": "台", "qty": 0}),
        "nic": prices.get("nic", {"unit_price": ZERO, "unit": "卡", "qty": 0}),
        "optics_400g": prices.get("optics_400g", {"unit_price": ZERO, "unit": "个", "qty": 0}),
        "optics_100g": prices.get("optics_100g", {"unit_price": ZERO, "unit": "个", "qty": 0}),
        "aoc": prices.get("aoc", {"unit_price": ZERO, "unit": "根", "qty": 0}),
        "mpo": prices.get("mpo", {"unit_price": ZERO, "unit": "根", "qty": 0}),
        "storage": {
            "capacity_gb": storage.capacity_gb,
            "unit_price_gb": storage_price_gb,
            "capex": storage.capex,
            "monthly_per_gb": storage_monthly_gb,
            "monthly": storage.monthly,
        },
        "total_supporting_capex": storage.capex + network.capex,
    }


def _score_candidate(
    candidate: HardwareCandidate,
    objective: str,
    min_cost_per_m: Decimal,
    min_capex: Decimal,
    min_tco: Decimal,
) -> Decimal:
    """打分（FIX-5：相对最优归一化，消除单位混加；FIX-6：权重为具名常量）。

    分越低越优先（供 sorted() 升序排列）；infeasible 给 1e18 排到最后。
    """
    if not candidate.feasible:
        return D("1e18")
    cost_per_m = D(candidate.kpis.get("cost_per_m") or 0)
    tco = D(candidate.kpis.get("tco") or 0)
    npv = D(candidate.kpis.get("npv") or 0)
    capex = candidate.total_capex

    if objective == "min_capex":
        base = safe_div(capex, min_capex, D("1e9"))
    elif objective == "min_tco":
        base = safe_div(tco, min_tco, D("1e9"))
    elif objective == "min_cost_per_m":
        base = safe_div(cost_per_m, min_cost_per_m, D("1e9"))
    else:
        rel_cost = safe_div(cost_per_m, min_cost_per_m, D("1e9"))
        rel_capex = safe_div(capex, min_capex, D("1e9"))
        base = rel_cost * SCORE_W_COST + rel_capex * SCORE_W_CAPEX
        if npv < ZERO:
            base += safe_div(abs(npv), capex, D("1e9")) * NPV_PENALTY_MULT
    if candidate.over_budget:
        base *= OVER_BUDGET_PENALTY
    return base


def recommend_hardware(
    req: HardwareRequirement,
    top_n: int = 3,
    catalog: Optional[NetworkCatalogPrices] = None,
) -> HardwareRecommendationResult:
    """硬件反选推荐主入口（纯函数、零 IO；`catalog` 由路由层从配件库注入）。"""
    notes: List[str] = []
    target_tok_s, assumptions_target = _target_tok_s(req)
    mem_required_gb, assumptions_mem = _mem_required_gb(req)
    sla_scale, assumptions_sla = _sla_scale(req)
    assumptions = assumptions_target + assumptions_mem + assumptions_sla
    base = req.base_params or default_params()

    candidates = [
        _evaluate_candidate(
            gpu, req, base, target_tok_s, mem_required_gb, sla_scale, assumptions, catalog
        )
        for gpu in GPU_CATALOG
    ]

    feasible_candidates = [c for c in candidates if c.feasible]
    if not feasible_candidates:
        notes.append(
            "所有候选型号均不满足约束（显存/合规），建议放宽约束（如 CN_cfg=full 时补充国产卡）。"
        )
        min_cost_per_m = min_capex = min_tco = ONE
    else:
        min_cost_per_m = min(D(c.kpis.get("cost_per_m") or 0) for c in feasible_candidates)
        min_capex = min(c.total_capex for c in feasible_candidates)
        min_tco = min(D(c.kpis.get("tco") or 0) for c in feasible_candidates)

    objective = req.objective if req.objective in OBJECTIVES else "balanced"
    scored = [
        dataclasses.replace(
            c,
            score=_score_candidate(c, objective, min_cost_per_m, min_capex, min_tco),
        )
        for c in candidates
    ]
    recommended = sorted((c for c in scored if c.feasible), key=lambda c: c.score)[:top_n]

    return HardwareRecommendationResult(
        target_tok_s=target_tok_s,
        mem_required_gb=mem_required_gb,
        candidates=scored,
        recommended=recommended,
        notes=notes,
    )
