"""S-3 汇率层：seed 换算 + 成本标杆解析纯逻辑（不触库）。"""
from __future__ import annotations

import pytest

from ai_roi.domain.calc.decimal_config import D
from ai_roi.application.use_cases.benchmark_service import resolve_cost_benchmark_from_meta
from scripts.seed_inferencex import build_model_rows, cny_cost_benchmark


def test_cny_cost_benchmark_basic() -> None:
    """USD × 汇率 → CNY，精确 6 位。"""
    assert cny_cost_benchmark(0.011, 7.2) == pytest.approx(0.0792)
    assert cny_cost_benchmark(0.007, 7.2) == pytest.approx(0.0504)


def test_seed_model_meta_has_cny_and_usd() -> None:
    """seed 同时写入 CNY 换算值与 USD 源（便于核对口径）。"""
    rows = build_model_rows()
    qwen = next(r for r in rows if r.code == "qwen-3.5-397b-a17b")
    cny = qwen.meta["cost_benchmark_cny_per_mtok"]
    assert cny["GB300_NVL72"]["AgentX"] == pytest.approx(0.007 * 7.2)
    assert qwen.meta["inferencex_cost_usd_per_mtok"]["GB300_NVL72"]["AgentX"] == 0.007
    assert qwen.meta["fx_usd_cny"] == 7.2


def test_resolve_cost_benchmark_from_meta() -> None:
    """S-3 三维查表 + 汇率换算；任一维度缺失返回 None。"""
    qwen = next(r for r in build_model_rows() if r.code == "qwen-3.5-397b-a17b")
    val = resolve_cost_benchmark_from_meta(qwen.meta, "GB300_NVL72", "AgentX", D("7.2"))
    assert val == D("0.0504")
    assert resolve_cost_benchmark_from_meta(qwen.meta, "NO_SUCH_HW", "AgentX", D("7.2")) is None
    assert resolve_cost_benchmark_from_meta(qwen.meta, "GB300_NVL72", "8K/1K", D("7.2")) == D("0.9576")
    assert resolve_cost_benchmark_from_meta(None, "GB300_NVL72", "AgentX", D("7.2")) is None
