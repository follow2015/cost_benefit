"""电力运维口径：柜电分离（默认）/ 包柜包电（bundle）——零回归 + 双模式数值方向。"""
import pytest
from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import (
    POWER_MODE_BUNDLE,
    POWER_MODE_SEPARATE,
    default_params,
    derive,
)
from ai_roi.domain.validation.params import build_report

BASE_OPTS = EngineOptions(include_sensitivity=False, include_scenarios=False, include_crossover=False)


def _bundle(n_gpu=D(8), price=D(8000), racks=None, extra=None):
    p = (
        default_params()
        .with_override("power.power_mode", POWER_MODE_BUNDLE)
        .with_override("power.bundle_monthly_per_rack", price)
        .with_override("hw.N_gpu", n_gpu)
    )
    if racks is not None:
        p = p.with_override("power.racks", racks)
    if extra:
        for path, val in extra.items():
            p = p.with_override(path, val)
    return p


class TestPowerModeSeparate:
    def test_default_mode_is_separate_zero_regression(self) -> None:
        """默认柜电分离：C_var_per_U 与历史一致、bundle 成本 0、机柜数为参考值。"""
        d = derive(default_params())
        assert d.power_mode == POWER_MODE_SEPARATE
        assert d.C_var_per_U > ZERO
        assert d.bundle_rack_cost_m == ZERO
        assert d.racks == D(1)
        assert d.C_fix_cash == D(18_000)

    def test_breakdown_labels_separate(self) -> None:
        """柜电分离：breakdown 保留「电费」「机柜托管」两行。"""
        payload = compute_all(default_params(), BASE_OPTS)
        keys = {item["key"]: item for item in payload["unit_cost"]["breakdown"]}
        assert "power" in keys and keys["power"]["amount"] > 0
        assert keys["colocation"]["label"] == "机柜托管"


class TestPowerModeBundle:
    def test_bundle_zeroes_var_power(self) -> None:
        """包柜包电：C_var_per_U=0、idle=0、rack 成本入固定。"""
        d = derive(_bundle(n_gpu=D(8)))
        assert d.power_mode == POWER_MODE_BUNDLE
        assert d.C_var_per_U == ZERO
        assert d.C_power_idle_m == ZERO
        assert d.racks == D(1)
        assert d.bundle_rack_cost_m == D(8000)
        assert d.C_fix_cash == D(21_000)

    def test_auto_racks_and_explicit(self) -> None:
        """机柜数：70 卡自动 ceil(70/32)=3；显式 racks 优先。"""
        auto = derive(_bundle(n_gpu=D(70)))
        assert auto.racks == D(3)
        assert auto.bundle_rack_cost_m == D(24_000)
        explicit = derive(_bundle(n_gpu=D(70), racks=D(5)))
        assert explicit.racks == D(5)
        assert explicit.bundle_rack_cost_m == D(40_000)

    def test_breakdown_bundle(self) -> None:
        """包柜包电：breakdown 无「电费」行（0 剔除）、colocation 行=包柜包电。"""
        payload = compute_all(_bundle(n_gpu=D(8)), BASE_OPTS)
        keys = {item["key"]: item for item in payload["unit_cost"]["breakdown"]}
        assert "power" not in keys
        assert "power_idle" not in keys
        assert keys["colocation"]["label"] == "包柜包电"
        assert keys["colocation"]["amount"] == D(8000)

    def test_bundle_kpis(self) -> None:
        """KPI：racks_count=1、bundle_rack_cost_m=8000（F093/F094）。"""
        payload = compute_all(_bundle(n_gpu=D(8)), BASE_OPTS)
        kpi = {k["key"]: k["value"] for k in payload["kpis"]}
        assert kpi["racks_count"] == D(1)
        assert kpi["bundle_rack_cost_m"] == D(8000)
        assert payload["derived"]["power_mode"] == POWER_MODE_BUNDLE

    def test_bundle_validation(self) -> None:
        """校验：非法 power_mode → error；bundle 缺单价 → warning。"""
        bad = default_params().with_override("power.power_mode", "weird")
        report = build_report(bad)
        assert any(e.path == "power.power_mode" and e.level == "error" for e in report.errors)
        no_price = _bundle(price=D(0))
        report2 = build_report(no_price)
        assert any(
            w.path == "power.bundle_monthly_per_rack" and w.level == "warning"
            for w in report2.warnings
        )
