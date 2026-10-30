"""配套存储与组网拓扑建模（硬件反选 §3.13 完整版）。

背景：GPU 反选若只算卡，会系统性低估真实部署的规模与成本——模型权重要落盘、
KV cache 与数据集需要容量、多机需要跨节点网络（RDMA/以太网），且跨机互联对有效
吞吐存在折损。本模块提供两个纯函数估算：

- `estimate_storage`：由模型规模/量化/上下文/并发推导存储容量需求（权重落盘 + KV
  cache + 数据集 + 日志/快照），折算一次性 CAPEX 与月度运维费；
- `estimate_network`：由卡数与单机插槽上限推导节点数，按互联形态（单机 NVLink /
  跨机 RDMA / 跨机以太网）估算交换机/NIC/光模块/线缆 CAPEX、月度电费与运维，以及
  跨机互联对有效吞吐的折损比例。

设计原则（与既有工程风格对齐）：
- 纯函数、零 IO、Decimal 全程；
- 所有参数集中在 `StorageParams` / `NetworkParams`，默认值为保守经验值；
  明确标注「启发式、量级合理、不进黄金向量主链」（与 `throughput.model_efficiency`
  同一定位）；
- 反选集成时用推导月费覆盖装配参数的 `power.Co_stor / Co_net`，不改 `derive()` 的
  默认路径 ⇒ 手工方案口径零回归。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ai_roi.domain.calc.decimal_config import D, ONE, ZERO

KV_BYTES_PER_TOKEN = D("2")
WEIGHTS_MULT = D("2.0")
DATASET_MULT = D("20")
LOG_MULT = D("0.5")
STORAGE_PRICE_PER_GB = D("1.0")
STORAGE_MONTHLY_PER_GB = D("0.02")

UPLINKS_PER_NODE = 2
PORT_SPEED_GBPS = D("400")
PORT_SPEED_MULT: Dict[int, Decimal] = {100: D("0.45"), 200: D("0.6"), 400: D("1.0"), 800: D("1.8")}
PORT_SPEED_OPTIONS = frozenset(PORT_SPEED_MULT.keys())
SWITCH_PORTS = 32
SWITCH_CAPEX = D(250_000)
NIC_CAPEX = D(15_000)
OPTICS_CAPEX = D(5_000)
SWITCH_MONTHLY = D(5_000)
RDMA_INTERCONNECT_LOSS = D("0.05")
ETH_INTERCONNECT_LOSS = D("0.08")
STORAGE_POWER_KW_PER_TB = D("0.3")
SWITCH_POWER_KW = D("1.5")

FABRIC_NONE = "none"
FABRIC_RDMA = "rdma"
FABRIC_ETHERNET = "ethernet"
FABRIC_IB = "ib"
FABRIC_ROCE = "roce"
FABRICS = {FABRIC_NONE, FABRIC_RDMA, FABRIC_ETHERNET, FABRIC_IB, FABRIC_ROCE}


def interconnect_loss_for(fabric: str) -> Decimal:
    """按 fabric 返回跨机互联折损率（唯一事实来源）。

    estimate_network 与外部预估卡数（hardware_recommend._evaluate_candidate）必须同源，
    避免 RoCE 在"预估"与"最终折损"两处使用不一致的折损率常量。
    """
    fabric = fabric if fabric in FABRICS else FABRIC_RDMA
    return ETH_INTERCONNECT_LOSS if fabric in (FABRIC_ETHERNET, FABRIC_ROCE) else RDMA_INTERCONNECT_LOSS

STORAGE_TB_PER_NODE = D(60)
MGMT_PORTS_PER_NODE = 2


@dataclass(frozen=True)
class NetworkCatalogPrices:
    """组网配套目录价格（可被配件库 DB 覆盖；缺省 = 内置经验常量）。

    - `None`（不传）= 全部使用模块级内置常量（现状口径，零回归）；
    - 传实例 = 仅覆盖显式赋值的字段，其余回落内置常量。
    """

    compute_switch_ib_capex: Decimal = SWITCH_CAPEX
    compute_switch_roce_capex: Decimal = D(200_000)
    compute_switch_ports: Optional[int] = None
    compute_switch_speed: Optional[int] = None
    compute_switch_monthly: Decimal = SWITCH_MONTHLY
    spine_switch_ib_capex: Decimal = SWITCH_CAPEX
    spine_switch_roce_capex: Decimal = D(200_000)
    spine_switch_ports: Optional[int] = None
    spine_switch_speed: Optional[int] = None
    spine_switch_monthly: Decimal = SWITCH_MONTHLY
    storage_switch_capex: Decimal = D(120_000)
    storage_switch_ports: int = 48
    storage_switch_monthly: Decimal = D(3_000)
    mgmt_switch_capex: Decimal = D(8_000)
    mgmt_switch_ports: int = 48
    mgmt_switch_monthly: Decimal = D(300)
    nic_ib_capex: Decimal = NIC_CAPEX
    nic_roce_capex: Decimal = D(8_000)
    optics_400g_capex: Decimal = OPTICS_CAPEX
    optics_100g_capex: Decimal = D(1_500)
    aoc_capex: Decimal = D(3_000)
    mpo_capex: Decimal = D(2_000)
    uplinks_per_node: int = UPLINKS_PER_NODE
    storage_tb_per_node: Decimal = STORAGE_TB_PER_NODE
    mgmt_ports_per_node: int = MGMT_PORTS_PER_NODE
    storage_per_gb: Optional[Decimal] = None
    storage_monthly_per_gb: Optional[Decimal] = None


@dataclass(frozen=True)
class StorageEstimate:
    """配套存储估算结果。"""

    capacity_gb: Decimal
    weights_gb: Decimal
    kv_cache_gb: Decimal
    dataset_gb: Decimal
    log_snapshot_gb: Decimal
    capex: Decimal
    monthly: Decimal
    power_kw: Decimal
    assumptions: List[str] = field(default_factory=list)


def estimate_storage(
    mem_w_gb: Decimal,
    m_param: Decimal,
    ctx: Decimal,
    b_max: Decimal,
    n_gpu: Decimal,
    catalog: Optional[NetworkCatalogPrices] = None,
) -> StorageEstimate:
    """估算存储容量需求与成本（纯函数、启发式）。

    Args:
        mem_w_gb: 权重显存需求（GB，来自 `_mem_required_gb`，可被 Mem_w_override 覆盖）。
        m_param: 模型规模（B）。
        ctx: 上下文长度（token）。
        b_max: 并发/batch 上限（单卡）。
        n_gpu: 卡数。
        catalog: 配件库价格覆盖（None = 内置常量；仅覆盖显式字段）。
    """
    assumptions: List[str] = []
    price_per_gb = catalog.storage_per_gb if catalog else None
    monthly_per_gb = catalog.storage_monthly_per_gb if catalog else None
    price = price_per_gb if price_per_gb is not None else STORAGE_PRICE_PER_GB
    monthly_rate = monthly_per_gb if monthly_per_gb is not None else STORAGE_MONTHLY_PER_GB
    weights = mem_w_gb * WEIGHTS_MULT
    kv = ctx * n_gpu * b_max * KV_BYTES_PER_TOKEN / D(1_000_000_000)
    dataset = m_param * DATASET_MULT
    log_snapshot = weights * LOG_MULT
    capacity = weights + kv + dataset + log_snapshot
    capex = capacity * price
    monthly = capacity * monthly_rate
    power_kw = capacity / D(1_000) * STORAGE_POWER_KW_PER_TB
    assumptions.append(
        f"存储估算：权重落盘 {weights}GB（≈Mem_w×{WEIGHTS_MULT}）+ KV cache {kv}GB"
        f"（Ctx×N×B_max×2B）+ 数据集 {dataset}GB + 日志/快照 {log_snapshot}GB ⇒ "
        f"共 {capacity}GB；CAPEX≈{capex} 元、月费≈{monthly} 元"
        f"（单价 {'配件库' if price_per_gb is not None else '内置经验值'}，可手动调整 Co_stor）。"
    )
    return StorageEstimate(
        capacity_gb=capacity,
        weights_gb=weights,
        kv_cache_gb=kv,
        dataset_gb=dataset,
        log_snapshot_gb=log_snapshot,
        capex=capex,
        monthly=monthly,
        power_kw=power_kw,
        assumptions=assumptions,
    )


@dataclass(frozen=True)
class NetworkEstimate:
    """组网拓扑估算结果（BOM 明细：算力/存储/管理交换机 + NIC/光模块/线缆）。"""

    node_count: int
    fabric: str
    port_speed_gbps: Decimal
    spine_port_speed_gbps: Decimal
    storage_port_speed_gbps: Decimal
    switches: int
    compute_switch_capex: Decimal
    spine_switches: int
    spine_switch_capex: Decimal
    storage_switch_qty: int
    storage_switch_capex: Decimal
    mgmt_switch_qty: int
    mgmt_switch_capex: Decimal
    nic_qty: int
    nic_capex: Decimal
    optics_400g_qty: int
    optics_400g_capex: Decimal
    optics_100g_qty: int
    optics_100g_capex: Decimal
    aoc_qty: int
    aoc_capex: Decimal
    mpo_qty: int
    mpo_capex: Decimal
    capex: Decimal
    monthly: Decimal
    power_kw: Decimal
    interconnect_loss: Decimal
    prices: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)


def estimate_network(
    n_gpu: Decimal,
    cards_per_node: Decimal,
    fabric: str = FABRIC_RDMA,
    catalog: Optional[NetworkCatalogPrices] = None,
    storage_capacity_gb: Decimal = ZERO,
    port_speed: int = 400,
    extra_nodes: int = 0,
    spine_switches: Optional[int] = None,
    spine_port_speed: Optional[int] = None,
    storage_port_speed: Optional[int] = None,
) -> NetworkEstimate:
    """估算组网拓扑与成本（纯函数、启发式、分层 BOM）。

    - 算力交换机（数据面 Leaf）：按（GPU 节点 + 通用节点）× 上联口 / 单台端口数推导；
      端口速率由 `port_speed`（或配件库 `compute_switch_speed`）决定；
    - Spine 交换机（核心层）：默认按 fat-tree 全互联公式推导（≥2 台 Leaf 时开启），
      也可显式传入 `spine_switches` 覆盖；端口速率由 `spine_port_speed`（或配件库
      `spine_switch_speed`）决定，支持 Leaf/Spine 异速率（如 Leaf 400G + Spine 800G）；
    - 存储交换机：按存储容量 → 存储节点数（默认 60TB/节点）→ 100G 上联口推导；
    - 管理交换机：按（GPU 节点 + 通用节点 + 存储节点）× 管理口数 / 48 口推导；
    - 线缆：NIC（跨机每卡 1 张）、Leaf 上联光模块（按 Leaf 速率）、100G 光模块（存储上联）、
      AOC（每跨机卡 1 根短距）、MPO（Leaf↔Spine 主干，按 Spine 速率）。

    Args:
        n_gpu: 卡数。
        cards_per_node: 单机可插卡数上限。
        fabric: 跨机互联形态（单机时忽略）；ib/roce/rdma/ethernet。
        catalog: 配件库价格覆盖（None = 内置经验常量）；可携带 ports/speed 规格驱动拓扑。
        storage_capacity_gb: 存储容量（GB），用于推导存储/管理交换机；默认 0（无存储节点）。
        port_speed: 算力面（Leaf）端口速率（200/400/800 Gbps）；800G 时硬件单价按 ×1.8 估算。
        extra_nodes: 通用/CPU 计算节点数（无 GPU，但需上联到算力/通用网络）；默认 0。
        spine_switches: 显式 Spine 交换机台数（覆盖 fat-tree 推导）；None = 自动推导。
        spine_port_speed: Spine 端口速率（200/400/800 Gbps）；None = 复用 Leaf 速率。
        storage_port_speed: 存储网端口速率（100/200/400 Gbps，默认 100）；独立于算力面，
            用于按真实存储网速率推导存储交换机单价与存储光模块倍率。
    """
    fabric = fabric if fabric in FABRICS else FABRIC_RDMA
    p = catalog if catalog is not None else NetworkCatalogPrices()
    leaf_speed = (
        p.compute_switch_speed
        if p.compute_switch_speed and p.compute_switch_speed in PORT_SPEED_OPTIONS
        else (port_speed if port_speed in PORT_SPEED_OPTIONS else 400)
    )
    spine_speed = (
        p.spine_switch_speed
        if p.spine_switch_speed and p.spine_switch_speed in PORT_SPEED_OPTIONS
        else (spine_port_speed if spine_port_speed in PORT_SPEED_OPTIONS else leaf_speed)
    )
    storage_speed = storage_port_speed if storage_port_speed in PORT_SPEED_OPTIONS else 100
    storage_speed_mult = PORT_SPEED_MULT[storage_speed]
    speed_mult = PORT_SPEED_MULT[leaf_speed]
    spine_speed_mult = PORT_SPEED_MULT[spine_speed]
    compute_ports = p.compute_switch_ports if p.compute_switch_ports else SWITCH_PORTS
    spine_ports = p.spine_switch_ports if p.spine_switch_ports else compute_ports
    extra_nodes = max(0, int(extra_nodes))
    compute_unit = (
        (p.compute_switch_ib_capex if fabric in (FABRIC_IB, FABRIC_RDMA) else p.compute_switch_roce_capex)
        * speed_mult
    )
    spine_unit = (
        (p.spine_switch_ib_capex if fabric in (FABRIC_IB, FABRIC_RDMA) else p.spine_switch_roce_capex)
        * spine_speed_mult
    )
    nic_unit = (p.nic_ib_capex if fabric in (FABRIC_IB, FABRIC_RDMA) else p.nic_roce_capex) * speed_mult
    assumptions: List[str] = []
    node_count = max(1, int(math.ceil(float(n_gpu) / float(cards_per_node))))
    if node_count <= 1 and extra_nodes == 0:
        assumptions.append("单机部署（卡间 NVLink 内置），无需外部 fabric，组网 CAPEX/月费为 0。")
        return NetworkEstimate(
            node_count=1,
            fabric=FABRIC_NONE,
            port_speed_gbps=ZERO,
            spine_port_speed_gbps=ZERO,
            storage_port_speed_gbps=ZERO,
            switches=0,
            compute_switch_capex=ZERO,
            spine_switches=0,
            spine_switch_capex=ZERO,
            storage_switch_qty=0,
            storage_switch_capex=ZERO,
            mgmt_switch_qty=0,
            mgmt_switch_capex=ZERO,
            nic_qty=0,
            nic_capex=ZERO,
            optics_400g_qty=0,
            optics_400g_capex=ZERO,
            optics_100g_qty=0,
            optics_100g_capex=ZERO,
            aoc_qty=0,
            aoc_capex=ZERO,
            mpo_qty=0,
            mpo_capex=ZERO,
            capex=ZERO,
            monthly=ZERO,
            power_kw=ZERO,
            interconnect_loss=ZERO,
            prices={
                "compute_switch": {"unit_price": compute_unit, "unit": "台", "qty": 0, "fabric": FABRIC_NONE},
                "spine_switch": {"unit_price": spine_unit, "unit": "台", "qty": 0},
                "storage_switch": {"unit_price": p.storage_switch_capex, "unit": "台", "qty": 0},
                "mgmt_switch": {"unit_price": p.mgmt_switch_capex, "unit": "台", "qty": 0},
                "nic": {"unit_price": nic_unit, "unit": "卡", "qty": 0},
                "optics_400g": {"unit_price": p.optics_400g_capex, "unit": "个", "qty": 0},
                "optics_100g": {"unit_price": p.optics_100g_capex, "unit": "个", "qty": 0},
                "aoc": {"unit_price": p.aoc_capex, "unit": "根", "qty": 0},
                "mpo": {"unit_price": p.mpo_capex, "unit": "根", "qty": 0},
            },
            assumptions=assumptions,
        )

    required_ports = (node_count + extra_nodes) * p.uplinks_per_node
    switches = int(math.ceil(required_ports / compute_ports))
    compute_switch_capex = D(switches) * compute_unit
    if spine_switches is None:
        spine_switches = max(2, switches) if switches >= 2 else 0
    spine_switch_capex = D(spine_switches) * spine_unit
    storage_nodes = (
        int(math.ceil(float(storage_capacity_gb) / (float(p.storage_tb_per_node) * 1_000)))
        if storage_capacity_gb > ZERO
        else 0
    )
    storage_ports = storage_nodes * p.uplinks_per_node
    storage_switch_qty = int(math.ceil(storage_ports / p.storage_switch_ports)) if storage_ports > 0 else 0
    storage_switch_capex = D(storage_switch_qty) * p.storage_switch_capex * storage_speed_mult
    mgmt_ports = (node_count + extra_nodes + storage_nodes) * p.mgmt_ports_per_node
    mgmt_switch_qty = int(math.ceil(mgmt_ports / p.mgmt_switch_ports)) if mgmt_ports > 0 else 0
    mgmt_switch_capex = D(mgmt_switch_qty) * p.mgmt_switch_capex
    nic_qty = int(n_gpu) + extra_nodes * p.uplinks_per_node
    nic_capex = D(nic_qty) * nic_unit
    optics_400g_qty = required_ports
    optics_400g_capex = D(optics_400g_qty) * p.optics_400g_capex * speed_mult
    optics_100g_qty = storage_ports
    optics_100g_capex = D(optics_100g_qty) * p.optics_100g_capex * storage_speed_mult
    aoc_qty = nic_qty
    aoc_capex = D(aoc_qty) * p.aoc_capex * speed_mult
    mpo_qty = max(0, switches * spine_switches) * 2 if spine_switches > 0 else 0
    mpo_capex = D(mpo_qty) * p.mpo_capex * spine_speed_mult

    capex = (
        compute_switch_capex
        + spine_switch_capex
        + storage_switch_capex
        + mgmt_switch_capex
        + nic_capex
        + optics_400g_capex
        + optics_100g_capex
        + aoc_capex
        + mpo_capex
    )
    monthly = (
        D(switches) * p.compute_switch_monthly
        + D(spine_switches) * p.spine_switch_monthly
        + D(storage_switch_qty) * p.storage_switch_monthly
        + D(mgmt_switch_qty) * p.mgmt_switch_monthly
    )
    power_kw = (
        D(switches) * SWITCH_POWER_KW
        + D(spine_switches) * SWITCH_POWER_KW
        + D(storage_switch_qty) * D("1.2")
        + D(mgmt_switch_qty) * D("0.3")
    )
    loss = interconnect_loss_for(fabric)
    prices = {
        "compute_switch": {
            "unit_price": compute_unit, "unit": "台", "qty": switches, "fabric": fabric,
            "port_speed_gbps": leaf_speed, "ports": compute_ports,
        },
        "spine_switch": {
            "unit_price": spine_unit, "unit": "台", "qty": spine_switches, "fabric": fabric,
            "port_speed_gbps": spine_speed, "ports": spine_ports,
        },
        "storage_switch": {"unit_price": p.storage_switch_capex, "unit": "台", "qty": storage_switch_qty, "port_speed_gbps": storage_speed},
        "mgmt_switch": {"unit_price": p.mgmt_switch_capex, "unit": "台", "qty": mgmt_switch_qty},
        "nic": {"unit_price": nic_unit, "unit": "卡", "qty": nic_qty},
        "optics_400g": {"unit_price": p.optics_400g_capex, "unit": "个", "qty": optics_400g_qty},
        "optics_100g": {"unit_price": p.optics_100g_capex, "unit": "个", "qty": optics_100g_qty},
        "aoc": {"unit_price": p.aoc_capex, "unit": "根", "qty": aoc_qty},
        "mpo": {"unit_price": p.mpo_capex, "unit": "根", "qty": mpo_qty},
    }
    assumptions.append(
        f"组网估算：{n_gpu} 卡 / 每机 ≤{cards_per_node} 卡 ⇒ {node_count} 台 GPU 机"
        + (f" + {extra_nodes} 台通用节点" if extra_nodes else "")
        + f"；fabric={fabric}（Leaf {leaf_speed}Gbps×{p.uplinks_per_node} 上联/机"
        + (f"、Spine {spine_speed}Gbps" if spine_speed != leaf_speed else "")
        + f"，{'800G 硬件单价按 ×1.8 估算' if speed_mult != ONE else '400G'}"
        + (f"、Spine 单价按 ×{spine_speed_mult}" if spine_speed_mult != speed_mult else "")
        + f"），"
        f"Leaf 算力交换机 {switches} 台（{compute_ports} 口/台，{required_ports} 上联口）"
        + f" + Spine {spine_switches} 台（{spine_ports} 口/台）"
        + f" + 存储交换机 {storage_switch_qty} 台（存储 {storage_nodes} 节点，{storage_speed}G）"
        + f" + 管理交换机 {mgmt_switch_qty} 台 + NIC {nic_qty} 卡"
        + f" + {leaf_speed}G 模块 {optics_400g_qty} + {storage_speed}G 模块 {optics_100g_qty}"
        + f" + AOC {aoc_qty} 根 + MPO {mpo_qty} 根 ⇒ 组网 CAPEX≈{capex} 元、月费≈{monthly} 元"
        f"（单价：{'配件库' if catalog is not None else '内置经验值'}；"
        + (f"端口数来自配件库 spec.ports={compute_ports}" if catalog and catalog.compute_switch_ports else "端口数按内置 32 口")
        + f"）；跨机吞吐按 ×{D(1) - loss} 折损。"
    )
    return NetworkEstimate(
        node_count=node_count,
        fabric=fabric,
        port_speed_gbps=D(leaf_speed),
        spine_port_speed_gbps=D(spine_speed),
        storage_port_speed_gbps=D(storage_speed),
        switches=switches,
        compute_switch_capex=compute_switch_capex,
        spine_switches=spine_switches,
        spine_switch_capex=spine_switch_capex,
        storage_switch_qty=storage_switch_qty,
        storage_switch_capex=storage_switch_capex,
        mgmt_switch_qty=mgmt_switch_qty,
        mgmt_switch_capex=mgmt_switch_capex,
        nic_qty=nic_qty,
        nic_capex=nic_capex,
        optics_400g_qty=optics_400g_qty,
        optics_400g_capex=optics_400g_capex,
        optics_100g_qty=optics_100g_qty,
        optics_100g_capex=optics_100g_capex,
        aoc_qty=aoc_qty,
        aoc_capex=aoc_capex,
        mpo_qty=mpo_qty,
        mpo_capex=mpo_capex,
        capex=capex,
        monthly=monthly,
        power_kw=power_kw,
        interconnect_loss=loss,
        prices=prices,
        assumptions=assumptions,
    )


__all__ = [
    "FABRIC_NONE",
    "FABRIC_RDMA",
    "FABRIC_ETHERNET",
    "FABRIC_IB",
    "FABRIC_ROCE",
    "FABRICS",
    "StorageEstimate",
    "NetworkEstimate",
    "estimate_storage",
    "estimate_network",
    "KV_BYTES_PER_TOKEN",
    "WEIGHTS_MULT",
    "DATASET_MULT",
    "LOG_MULT",
    "STORAGE_PRICE_PER_GB",
    "STORAGE_MONTHLY_PER_GB",
    "UPLINKS_PER_NODE",
    "PORT_SPEED_GBPS",
    "SWITCH_PORTS",
    "SWITCH_CAPEX",
    "NIC_CAPEX",
    "OPTICS_CAPEX",
    "SWITCH_MONTHLY",
    "RDMA_INTERCONNECT_LOSS",
    "ETH_INTERCONNECT_LOSS",
    "STORAGE_POWER_KW_PER_TB",
    "SWITCH_POWER_KW",
    "NetworkCatalogPrices",
    "STORAGE_TB_PER_NODE",
    "MGMT_PORTS_PER_NODE",
]
