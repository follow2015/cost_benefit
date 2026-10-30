"""硬件反选推荐（§3.13）回归测试。

覆盖：吞吐/需求双路径换算、显存/吞吐双约束取 max、多机 infeasible、合规过滤/降权、
预算降权、打分排序、以及评审 6 点修正（P_sys 含配套功耗、U/D_eq 装配、SLA 复用、
assumptions 构造参数、balanced 归一化打分、无魔法数）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai_roi.domain.calc.decimal_config import D, SEC, MTOK, ONE, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.hardware_recommend import (
    GPU_CATALOG,
    HardwareRequirement,
    apply_model_preset,
    recommend_hardware,
)
from ai_roi.domain.calc.codec import params_from_dict, params_to_dict

BASE_OPTS = EngineOptions(include_sensitivity=False, include_scenarios=False, include_crossover=False)


def _by_id(result, gpu_id: str):
    return next(c for c in result.candidates if c.gpu.id == gpu_id)


class TestTargetConversion:
    def test_teff_target_direct(self) -> None:
        req = HardwareRequirement(T_eff_target=D(6000))
        result = recommend_hardware(req)
        assert result.target_tok_s == D(6000)
        assert any("直接采用指定目标吞吐" in a for a in result.candidates[0].assumptions)

    def test_deq_target_implied(self) -> None:
        req = HardwareRequirement(D_eq_target=D(300), U_target=D("0.7"), growth_headroom=D("0.2"))
        result = recommend_hardware(req)
        expected = D(300) / D("0.7") * D("1.2") * MTOK / SEC
        assert abs(result.target_tok_s - expected) < D("1e-6")

    def test_missing_targets_raises(self) -> None:
        with pytest.raises(ValueError):
            recommend_hardware(HardwareRequirement())


class TestConstraints:
    def test_memory_bound_warns(self) -> None:
        """700B 模型 FP8 ⇒ 显存 805GB；MI300X(192GB) 卡数由显存决定。"""
        req = HardwareRequirement(T_eff_target=D(4000), M_param=D(700), quant="FP8")
        result = recommend_hardware(req)
        cand = _by_id(result, "mi300x")
        assert cand.N_gpu == D(5)
        assert any("显存偏小" in w for w in cand.warnings)
        assert abs(cand.mem_required_gb - D(805)) < D("1e-6")

    def test_multinode_released_with_network(self) -> None:
        """20000 tok/s：H100 单机 8 卡；H800 多机放行（node_count=2）+ 互联折损 + 组网成本。"""
        req = HardwareRequirement(T_eff_target=D(20000))
        result = recommend_hardware(req)
        h100 = _by_id(result, "h100_sxm")
        assert h100.feasible and h100.N_gpu == D(8) and h100.node_count == 1
        h800 = _by_id(result, "h800_sxm")
        assert h800.feasible
        assert h800.node_count == 2
        assert h800.N_gpu == D(11)
        assert any("折损" in w for w in h800.warnings)
        assert h800.supporting_capex > ZERO
        assert h800.T_eff_achieved >= D(20000)
        assert h800.network is not None and h800.network.interconnect_loss > ZERO

    def test_sla_tightens_cards(self) -> None:
        """SLA 250/25 ⇒ 收缩比例 0.25（复用 available_batch_limit）：H800 卡数 3 → 13（多机重算）。"""
        base = recommend_hardware(HardwareRequirement(T_eff_target=D(6000)))
        strict = recommend_hardware(
            HardwareRequirement(T_eff_target=D(6000), SLA_ttft=D(250), SLA_tpot=D(25))
        )
        assert _by_id(base, "h800_sxm").N_gpu == D(3)
        strict_h800 = _by_id(strict, "h800_sxm")
        assert strict_h800.N_gpu == D(13)
        assert strict_h800.node_count == 2
        assert strict_h800.feasible
        assert strict_h800.T_eff_achieved >= D(6000)


class TestComplianceAndBudget:
    def test_cn_full_excludes_non_domestic(self) -> None:
        req = HardwareRequirement(T_eff_target=D(3000), CN_cfg="full")
        result = recommend_hardware(req)
        assert not _by_id(result, "h800_sxm").feasible
        assert any("非国产卡" in w for w in _by_id(result, "h800_sxm").warnings)
        assert _by_id(result, "ascend_910b").feasible
        assert all(c.gpu.domestic for c in result.recommended)

    def test_cn_partial_warns_but_keeps(self) -> None:
        req = HardwareRequirement(T_eff_target=D(3000), CN_cfg="partial")
        result = recommend_hardware(req)
        cand = _by_id(result, "h800_sxm")
        assert cand.feasible
        assert any("部分国产化" in w for w in cand.warnings)

    def test_budget_over_penalized_not_removed(self) -> None:
        req = HardwareRequirement(T_eff_target=D(6000), capex_budget=D(500_000))
        result = recommend_hardware(req)
        h100 = _by_id(result, "h100_sxm")
        assert h100.over_budget
        assert h100.feasible
        assert any("降权" in w for w in h100.warnings)
        relaxed = recommend_hardware(HardwareRequirement(T_eff_target=D(6000)))
        assert h100.score >= _by_id(relaxed, "h100_sxm").score


class TestScoring:
    def test_balanced_returns_feasible_sorted(self) -> None:
        req = HardwareRequirement(T_eff_target=D(6000))
        result = recommend_hardware(req)
        scores = [c.score for c in result.recommended]
        assert scores == sorted(scores)
        assert all(c.feasible for c in result.recommended)
        assert len(result.recommended) <= 3
        assert all(c.score < D("1e18") for c in result.recommended)

    def test_objective_changes_order(self) -> None:
        """目标函数正确性：min_capex 榜首 = 可行集 CAPEX 最小；min_cost_per_m 榜首 = 单位成本最小。

        注：目录扩至 12 款后 910C 可能在多个目标下同时夺冠（真实性价比），故断言
        各目标榜首取到该目标的最优值（而非「榜首必不同」）。
        """
        req_capex = HardwareRequirement(T_eff_target=D(6000), objective="min_capex")
        req_cost = HardwareRequirement(T_eff_target=D(6000), objective="min_cost_per_m")
        r1, r2 = recommend_hardware(req_capex), recommend_hardware(req_cost)
        feasible1 = [c for c in r1.candidates if c.feasible]
        feasible2 = [c for c in r2.candidates if c.feasible]
        assert r1.recommended[0].total_capex == min(c.total_capex for c in feasible1)
        top_cost = min(D(c.kpis["cost_per_m"]) for c in feasible2)
        assert D(r2.recommended[0].kpis["cost_per_m"]) == top_cost

    def test_infeasible_candidates_scored_last(self) -> None:
        """CN_cfg=full 时非国产卡 infeasible（score=1e18 排最后），推荐全为国产。"""
        req = HardwareRequirement(T_eff_target=D(20000), CN_cfg="full")
        result = recommend_hardware(req)
        infeasible = [c for c in result.candidates if not c.feasible]
        assert infeasible
        assert all(c.score == D("1e18") for c in infeasible)
        assert all(c.gpu.domestic for c in result.recommended)


class TestReviewFixes:
    def test_fix1_power_includes_aux(self) -> None:
        """整机功耗 = GPU + 主机配套 + 存储/组网配套（电费口径一致）；配套 CAPEX 并入整机配套价。"""
        req = HardwareRequirement(T_eff_target=D(6000))
        result = recommend_hardware(req)
        cand = _by_id(result, "h100_sxm")
        expected_kw = D(3) * D(700) / D(1000) + D("4.9")
        assert cand.power_kw == expected_kw
        assert cand.params.power.P_sys_override == cand.total_power_kw
        assert cand.params.power.P_sys_override == expected_kw + cand.storage.power_kw + cand.network.power_kw
        assert cand.params.hw.P_aux == cand.supporting_capex
        from ai_roi.domain.calc.parameters import derive

        derived = derive(cand.params)
        assert derived.CAPEX == cand.total_capex
        budget_req = HardwareRequirement(
            T_eff_target=D(6000), power_budget_kw=D("5.0")
        )
        assert _by_id(recommend_hardware(budget_req), "h100_sxm").over_budget

    def test_fix2_demand_assembly_teff_path(self) -> None:
        """仅吞吐目标：D_eq = Q_cap_achieved × U_target，利用率恰为 U_target。"""
        req = HardwareRequirement(T_eff_target=D(6000), U_target=D("0.7"))
        cand = recommend_hardware(req).recommended[0]
        q_cap = cand.T_eff_achieved * SEC / MTOK
        assert cand.params.demand.U == D("0.7")
        assert abs(cand.params.demand.D_eq - q_cap * D("0.7")) < D("1e-6")

    def test_multinode_supporting_capex_enters_params(self) -> None:
        """多机场景：组网 CAPEX 同样并入 hw.P_aux，财务 CAPEX 与推荐 total_capex 一致。"""
        req = HardwareRequirement(T_eff_target=D(20000))
        cand = next(c for c in recommend_hardware(req).candidates if c.node_count > 1)
        assert cand.network is not None and cand.network.capex > ZERO
        assert cand.params.hw.P_aux == cand.supporting_capex
        from ai_roi.domain.calc.parameters import derive

        assert derive(cand.params).CAPEX == cand.total_capex
        assert cand.params.power.P_sys_override == cand.total_power_kw

    def test_hardware_bom_generated(self) -> None:
        """BOM 清单生成：服务器/三层交换机/线缆/存储明细，配套 CAPEX 合计 = storage+network。

        服务器行按实际插卡数计价（§2.3 修正）：unit_price=单卡价、qty=实际卡数，
        保证 unit_price × qty == subtotal（与 capex = n_gpu × price_per_card 同口径）。
        """
        cand = recommend_hardware(HardwareRequirement(T_eff_target=D(20000))).recommended[0]
        bom = cand.hardware_bom
        assert bom is not None
        assert bom["servers"]["unit_price"] == cand.gpu.price_per_card
        assert bom["servers"]["qty"] == int(cand.N_gpu)
        assert bom["servers"]["subtotal"] == bom["servers"]["unit_price"] * bom["servers"]["qty"]
        assert bom["compute_switch"]["qty"] == cand.network.switches
        assert bom["storage"]["capacity_gb"] == cand.storage.capacity_gb
        assert bom["total_supporting_capex"] == cand.supporting_capex
        assert cand.params.hw.supporting_cards_per_node == cand.gpu.max_cards_per_node

    def test_supporting_inputs_persisted_for_frontend_relink(self) -> None:
        """反选推导输入持久化：fabric + mem_required_gb 快照（前端改卡数联动重算的输入）。"""
        req = HardwareRequirement(T_eff_target=D(20000), fabric="rdma")
        cand = _by_id(recommend_hardware(req), "h800_sxm")
        assert cand.node_count > 1
        assert cand.params.hw.supporting_fabric == "rdma"
        assert cand.params.hw.supporting_mem_gb > ZERO
        from ai_roi.domain.calc.parameters import default_params

        d = default_params()
        assert d.hw.supporting_fabric == ""
        assert d.hw.supporting_mem_gb == ZERO

    def test_fabric_auto_adaptation_by_card(self) -> None:
        """组网最优适配：fabric 未指定时 H 系→ib（多机），消费级/国产→roce。"""
        h100 = _by_id(recommend_hardware(HardwareRequirement(T_eff_target=D(20000))), "h100_sxm")
        if h100.node_count > 1:
            assert h100.network.fabric == "ib"
        asc = _by_id(
            recommend_hardware(HardwareRequirement(T_eff_target=D(20000), CN_cfg="full")),
            "ascend_910b",
        )
        if asc.node_count > 1:
            assert asc.network.fabric == "roce"
        explicit = _by_id(
            recommend_hardware(HardwareRequirement(T_eff_target=D(20000), fabric="ethernet")),
            "h100_sxm",
        )
        if explicit.node_count > 1:
            assert explicit.network.fabric == "ethernet"

    def test_fix2_demand_assembly_deq_path(self) -> None:
        """需求驱动：D_eq 保留目标值、util_mode=u_from_demand（诚实反映增长裕量）。"""
        req = HardwareRequirement(D_eq_target=D(300), U_target=D("0.7"))
        cand = recommend_hardware(req).recommended[0]
        assert cand.params.demand.D_eq == D(300)
        assert cand.params.demand.util_mode == "u_from_demand"

    def test_fix3_sla_reuses_available_batch_limit(self) -> None:
        """收缩比例 = available_batch_limit(64, ttft, tpot)/64：500/50 ⇒ 0.5，250/25 ⇒ 0.25。"""
        from ai_roi.domain.calc.throughput import available_batch_limit

        assert available_batch_limit(D(64), D(500), D(50)) == D(32)
        assert available_batch_limit(D(64), D(250), D(25)) == D(16)
        relaxed = recommend_hardware(
            HardwareRequirement(T_eff_target=D(3000), SLA_ttft=D(500), SLA_tpot=D(50))
        )
        strict = recommend_hardware(
            HardwareRequirement(T_eff_target=D(3000), SLA_ttft=D(250), SLA_tpot=D(25))
        )
        assert _by_id(relaxed, "h800_sxm").N_gpu == D(3)
        assert _by_id(strict, "h800_sxm").N_gpu == D(6)

    def test_fix4_assumptions_passed_by_constructor(self) -> None:
        """候选 assumptions 非空且与推导链一致（不经 __setattr__ 强改）。"""
        cand = recommend_hardware(HardwareRequirement(T_eff_target=D(6000))).recommended[0]
        assert cand.assumptions
        assert any("直接采用指定目标吞吐" in a for a in cand.assumptions)

    def test_fix5_balanced_score_normalized(self) -> None:
        """balanced 打分 = 相对最优归一化加权：榜首 cost_per_m 相对最优、CAPEX 相对最优。"""
        result = recommend_hardware(HardwareRequirement(T_eff_target=D(6000)))
        top = result.recommended[0]
        feasible = [c for c in result.candidates if c.feasible]
        min_cost = min(D(c.kpis["cost_per_m"]) for c in feasible)
        min_capex = min(c.capex for c in feasible)
        assert D(top.kpis["cost_per_m"]) == min_cost or top.capex == min_capex

    def test_fix_roce_loss_consistency_multinode(self) -> None:
        """§2.1 回归：RoCE 国产卡多机场景，预估卡数与最终折损必须同源，保证折损后 t_eff 仍 ≥ 目标。

        910B 默认 fabric=roce（高折损档 0.08）。旧实现预估用 RDMA(0.05)、最终用 RoCE(0.08) 不一致，
        会导致 n_gpu 偏小、t_eff_achieved < 目标。修复后二者统一走 interconnect_loss_for。
        """
        from ai_roi.domain.calc.supporting_cost import ETH_INTERCONNECT_LOSS, interconnect_loss_for

        req = HardwareRequirement(T_eff_target=D(20000), CN_cfg="full")
        cand = _by_id(recommend_hardware(req), "ascend_910b")
        assert cand.node_count > 1
        assert cand.network.fabric == "roce"
        assert cand.network.interconnect_loss == interconnect_loss_for("roce") == ETH_INTERCONNECT_LOSS
        assert cand.T_eff_achieved >= D(20000)


class TestSerializationContract:
    def test_params_roundtrip_same_result(self) -> None:
        """recommended[i].params 经 params_to_dict/params_from_dict 回填后，compute_all 结果逐位一致。"""
        cand = recommend_hardware(HardwareRequirement(T_eff_target=D(6000))).recommended[0]
        restored = params_from_dict(params_to_dict(cand.params))
        payload = compute_all(restored, BASE_OPTS)
        assert payload["financials"]["npv"] == cand.kpis["npv"]

    def test_catalog_has_reference_card(self) -> None:
        """目录必须含 perf_index=1.0 的基准卡（H800），保证吞吐口径可追溯。"""
        assert any(s.id == "h800_sxm" and s.perf_index == ONE for s in GPU_CATALOG)


class TestBuilderSupport:
    def test_b300_in_catalog(self) -> None:
        """B300（Blackwell Ultra）入目录：288GB / 1400W / ib / 800G 推荐。"""
        b300 = next((g for g in GPU_CATALOG if g.id == "b300_sxm"), None)
        assert b300 is not None
        assert b300.mem_gb == D(288)
        assert b300.tdp_w == D(1400)
        assert b300.fabric_recommended == "ib"
        assert b300.fabric_speed_gbps == 800

    def test_b300_multinode_auto_800g_ib(self) -> None:
        """B300 多机：fabric 自动 ib、端口自动 800G。"""
        cand = _by_id(
            recommend_hardware(HardwareRequirement(T_eff_target=D(50000))), "b300_sxm"
        )
        assert cand.node_count > 1
        assert cand.network.fabric == "ib"
        assert cand.network.port_speed_gbps == D(800)

    def test_explicit_port_speed_overrides_auto(self) -> None:
        """显式 port_speed=400 覆盖卡型推荐 800G；800G 组网 CAPEX ≈ 400G ×1.8（单价倍率）。"""
        r_auto = recommend_hardware(HardwareRequirement(T_eff_target=D(50000)))
        r_400 = recommend_hardware(HardwareRequirement(T_eff_target=D(50000), port_speed=400))
        c800 = _by_id(r_auto, "b300_sxm")
        c400 = _by_id(r_400, "b300_sxm")
        assert c400.network.port_speed_gbps == D(400)
        assert c800.network.capex > c400.network.capex

    def test_apply_model_preset(self) -> None:
        """模型预设：无条件覆盖 M_param（全尺寸）+ 显存快照。"""
        req, notes = apply_model_preset(HardwareRequirement(), D(2800), D(640))
        assert req.M_param == D(2800)
        assert req.Mem_w_override == D(640)
        assert any("M_param=2800B" in n for n in notes)
        assert any("640GB" in n for n in notes)

    def test_model_preset_quant_unchanged(self) -> None:
        """模型预设不改量化档（量化由调用方显式传）。"""
        req, _ = apply_model_preset(HardwareRequirement(quant="BF16"), D(2800), D(640))
        assert req.quant == "BF16"

    def test_k3_full_size_b300_feasible(self) -> None:
        """Kimi K3 全尺寸（BF16）+ B300：50k tok/s 多机可行，显存 640GB 主导卡数下限。"""
        r = recommend_hardware(
            HardwareRequirement(T_eff_target=D(50000), quant="BF16", M_param=D(2800), Mem_w_override=D(640))
        )
        b300 = _by_id(r, "b300_sxm")
        assert b300.feasible
        assert b300.mem_required_gb == D(640)
        assert b300.N_gpu >= D(3)
