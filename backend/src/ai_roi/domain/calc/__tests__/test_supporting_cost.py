"""配套存储/组网建模（§3.13 完整建模）回归测试。

覆盖：存储容量推导（权重落盘/KV cache/数据集/日志）、存储 CAPEX/月费、
组网拓扑（单机零成本 / 多机交换机+NIC+光模块 / RDMA 与以太网折损）、
以及硬件反选中配套成本的集成（多机放行、Co_stor/Co_net 叠加覆盖）。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.hardware_recommend import HardwareRequirement, recommend_hardware
from ai_roi.domain.calc.supporting_cost import (
    DATASET_MULT,
    ETH_INTERCONNECT_LOSS,
    KV_BYTES_PER_TOKEN,
    LOG_MULT,
    RDMA_INTERCONNECT_LOSS,
    STORAGE_MONTHLY_PER_GB,
    STORAGE_PRICE_PER_GB,
    WEIGHTS_MULT,
    estimate_network,
    estimate_storage,
)


def _by_id(result, gpu_id: str):
    return next(c for c in result.candidates if c.gpu.id == gpu_id)


class TestEstimateStorage:
    def test_capacity_breakdown(self) -> None:
        """70B FP8（Mem_w=80.5GB）、N=8、Ctx=8192、B_max=64。"""
        mem_w = D("80.5")
        storage = estimate_storage(mem_w, D(70), D(8192), D(64), D(8))
        assert storage.weights_gb == mem_w * WEIGHTS_MULT
        assert storage.kv_cache_gb == D(8192) * D(8) * D(64) * KV_BYTES_PER_TOKEN / D(1e9)
        assert storage.dataset_gb == D(70) * DATASET_MULT
        assert storage.log_snapshot_gb == storage.weights_gb * LOG_MULT
        expected_capacity = (
            storage.weights_gb + storage.kv_cache_gb + storage.dataset_gb + storage.log_snapshot_gb
        )
        assert storage.capacity_gb == expected_capacity
        assert storage.capex == expected_capacity * STORAGE_PRICE_PER_GB
        assert storage.monthly == expected_capacity * STORAGE_MONTHLY_PER_GB
        assert any("存储估算" in a for a in storage.assumptions)

    def test_monotonic_with_cards(self) -> None:
        """卡数越多 ⇒ KV cache 越大 ⇒ 容量/成本越大。"""
        s1 = estimate_storage(D(80.5), D(70), D(8192), D(64), D(4))
        s2 = estimate_storage(D(80.5), D(70), D(8192), D(64), D(16))
        assert s2.capacity_gb > s1.capacity_gb


class TestEstimateNetwork:
    def test_single_node_zero_cost(self) -> None:
        net = estimate_network(D(8), D(8), fabric="rdma")
        assert net.node_count == 1
        assert net.fabric == "none"
        assert net.capex == ZERO and net.monthly == ZERO and net.interconnect_loss == ZERO
        assert set(net.prices.keys()) == {
            "compute_switch",
            "spine_switch",
            "storage_switch",
            "mgmt_switch",
            "nic",
            "optics_400g",
            "optics_100g",
            "aoc",
            "mpo",
        }
        assert net.prices["compute_switch"]["qty"] == 0
        assert net.prices["compute_switch"]["fabric"] == "none"
        assert net.prices["spine_switch"]["qty"] == 0

    def test_multi_node_rdma(self) -> None:
        net = estimate_network(D(20), D(8), fabric="rdma")
        assert net.node_count == 3
        assert net.fabric == "rdma"
        assert net.switches == 1
        assert net.compute_switch_capex == D(250_000)
        assert net.mgmt_switch_qty == 1
        assert net.mgmt_switch_capex == D(8_000)
        assert net.storage_switch_qty == 0
        assert net.nic_qty == 20 and net.nic_capex == D(20) * D(15_000)
        assert net.optics_400g_qty == 6
        assert net.aoc_qty == 20
        assert net.mpo_qty == 0
        expected_capex = (
            D(250_000) + D(8_000) + D(20) * D(15_000) + D(6) * D(5_000) + D(20) * D(3_000)
        )
        assert net.capex == expected_capex
        assert net.monthly == D(5_000) + D(300)
        assert net.interconnect_loss == RDMA_INTERCONNECT_LOSS
        assert any("组网估算" in a for a in net.assumptions)
        assert net.prices["compute_switch"]["qty"] == 1
        assert net.prices["mgmt_switch"]["qty"] == 1
        assert net.prices["nic"]["qty"] == 20

    def test_multi_node_ethernet_loss(self) -> None:
        net = estimate_network(D(20), D(8), fabric="ethernet")
        assert net.interconnect_loss == ETH_INTERCONNECT_LOSS

    def test_extra_nodes_and_spine(self) -> None:
        """通用节点并入上联口、Spine 按 fat-tree 推导（≥2 Leaf 时 = Leaf 且≥2）。"""
        net = estimate_network(D(128), D(8), fabric="ib", storage_capacity_gb=D(300_000), extra_nodes=4)
        assert net.node_count == 16
        assert net.switches == 2
        assert net.spine_switches == 2
        assert net.nic_qty == 128 + 4 * 2
        assert net.mpo_qty == net.switches * net.spine_switches * 2
        assert net.capex > ZERO
        net2 = estimate_network(D(128), D(8), fabric="ib", extra_nodes=4, spine_switches=4)
        assert net2.spine_switches == 4
        assert net2.spine_switch_capex == D(4) * D(250_000)

    def test_200g_speed_multiplier(self) -> None:
        """200G 组网：硬件单价按 ×0.6 估算（相对 400G）。"""
        net400 = estimate_network(D(20), D(8), fabric="rdma", port_speed=400)
        net200 = estimate_network(D(20), D(8), fabric="rdma", port_speed=200)
        assert net200.switches == net400.switches
        assert net200.compute_switch_capex == net400.compute_switch_capex * D("0.6")
        assert net200.nic_capex == net400.nic_capex * D("0.6")
        net_bad = estimate_network(D(20), D(8), fabric="rdma", port_speed=123)
        assert net_bad.port_speed_gbps == D(400)

    def test_leaf_spine_different_speed(self) -> None:
        """Leaf 400G + Spine 800G：Spine 单价/主干按 800G 倍率，Leaf 仍 400G。"""
        net = estimate_network(
            D(128), D(8), fabric="ib", extra_nodes=4, port_speed=400, spine_port_speed=800
        )
        assert net.port_speed_gbps == D(400)
        assert net.spine_port_speed_gbps == D(800)
        assert net.spine_switches == net.switches
        assert net.spine_switch_capex == net.compute_switch_capex * D("1.8")
        assert net.mpo_capex == D(net.mpo_qty) * D(2_000) * D("1.8")
        assert any("Spine 800Gbps" in a for a in net.assumptions)

    def test_catalog_spec_ports_drives_topology(self) -> None:
        """配件库 spec.ports 覆盖硬编码 32 口：MQM9790（64 口）应减半交换机台数。"""
        from ai_roi.domain.calc.supporting_cost import NetworkCatalogPrices

        default = estimate_network(D(128), D(8), fabric="ib")
        assert default.switches == 1
        cat64 = NetworkCatalogPrices(compute_switch_ports=64)
        net64 = estimate_network(D(128), D(8), fabric="ib", catalog=cat64)
        assert net64.switches == 1
        assert net64.prices["compute_switch"]["ports"] == 64
        big = estimate_network(D(1024), D(8), fabric="ib")
        big64 = estimate_network(D(1024), D(8), fabric="ib", catalog=NetworkCatalogPrices(compute_switch_ports=64))
        assert big.switches == 8
        assert big64.switches == 4
        assert any("端口数来自配件库 spec.ports=64" in a for a in big64.assumptions)
        cat_speed = NetworkCatalogPrices(compute_switch_speed=200)
        net_speed = estimate_network(D(20), D(8), fabric="rdma", catalog=cat_speed)
        assert net_speed.port_speed_gbps == D(200)
        assert net_speed.compute_switch_capex == D(250_000) * D("0.6")


class TestRecommendIntegration:
    def test_single_node_supporting_storage_only(self) -> None:
        """单机候选：配套 = 存储成本（组网 0）；Co_stor 叠加推导月费。"""
        req = HardwareRequirement(T_eff_target=D(6000))
        cand = recommend_hardware(req).recommended[0]
        assert cand.node_count == 1
        assert cand.supporting_capex == cand.storage.capex
        assert cand.storage.capacity_gb > ZERO
        assert cand.params.power.Co_stor == D(1_000) + cand.storage.monthly

    def test_multi_node_network_monthly_added(self) -> None:
        """多机候选：Co_net = 基线 2000 + 组网月费。"""
        req = HardwareRequirement(T_eff_target=D(20000))
        cand = _by_id(recommend_hardware(req), "h800_sxm")
        assert cand.node_count == 2
        assert cand.network.monthly > ZERO
        assert cand.params.power.Co_net == D(2_000) + cand.network.monthly
        assert cand.supporting_capex > cand.storage.capex

    def test_total_capex_scoring(self) -> None:
        """min_capex 按含配套总 CAPEX 排序。"""
        req = HardwareRequirement(T_eff_target=D(20000), objective="min_capex")
        result = recommend_hardware(req)
        totals = [c.total_capex for c in result.recommended]
        assert totals == sorted(totals)

    def test_budget_uses_total(self) -> None:
        """预算判定含配套成本：GPU CAPEX 低于预算但含配套后超预算 ⇒ over_budget。"""
        req = HardwareRequirement(
            T_eff_target=D(6000), capex_budget=D("500000")
        )
        h100 = _by_id(recommend_hardware(req), "h100_sxm")
        assert h100.over_budget
