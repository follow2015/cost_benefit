"""calc-engine 优化审查（calc-engine-优化与设计增强报告.md）修复回归测试。

覆盖：
- P0-1 增长率/学习率越界不再让 dpow 抛未捕获异常（降级 + 告警）；
- P0-2 hw.N_gpu=0 不再 DivisionByZero（每卡 KPI 回退 0）；
- P1-4 with_override 支持把 Optional 字段清回 None；
- §3 服务校验层对越界增长率/学习率/新比率字段给出结构化 error；
- §4.1 敏感性/蒙特卡洛变量注册表覆盖 P0/P1/P2 新增科目；
- §4.3 公式表 inputs 在默认快照下全部可解析（防文档-代码漂移）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai_roi.domain.calc import montecarlo as mc
from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all, evaluate_target
from ai_roi.domain.calc.formula_spec import FORMULAS
from ai_roi.domain.calc.parameters import default_params, derive
from ai_roi.domain.calc.sensitivity import DEFAULT_VARS
from ai_roi.domain.errors import ValidationFailedError
from ai_roi.domain.validation.params import validate_params

BASE_OPTS = EngineOptions(include_sensitivity=False, include_scenarios=False, include_crossover=False)


def _with(params, path, value):
    return params.with_override(path, value)


class TestDpowExtremeInputsNoCrash:
    """P0-1：缩放底数 ≤ 0 时夹紧降级，绝不抛异常。"""

    @pytest.mark.parametrize(
        "path,value",
        [
            ("pricing.g_price", D("-1.5")),
            ("finance.infl", D("-2.0")),
            ("finance.cost_learning_rate", D("1.2")),
            ("finance.cost_learning_rate", D("1.0")),
        ],
    )
    def test_no_raise_and_clamped_note(self, path: str, value: Decimal) -> None:
        params = _with(default_params(), path, value)
        payload = compute_all(params, BASE_OPTS)
        assert payload["financials"]["npv"] is not None
        warnings = " ".join(payload["warnings"])
        assert "夹紧" in warnings, f"应产生夹紧告警，实际 warnings={payload['warnings']}"

    def test_sane_values_still_exact(self) -> None:
        """正常参数数值路径与夹紧前逐位一致（golden 已覆盖，此处冒烟）。"""
        params = default_params()
        payload = compute_all(params, BASE_OPTS)
        assert payload["financials"]["npv"] is not None
        assert "夹紧" not in " ".join(payload["warnings"])


class TestZeroNgpuDivision:
    """P0-2：N_gpu=0 时每卡 KPI 回退 0，不中断推导链。"""

    def test_zero_ngpu_no_division_error(self) -> None:
        params = _with(default_params(), "hw.N_gpu", D(0))
        payload = compute_all(params, BASE_OPTS)
        kpis = {item["key"]: item["value"] for item in payload["kpis"]}
        assert kpis["rev_per_gpu_day"] == ZERO
        assert kpis["cost_per_gpu_day"] == ZERO


class TestWithOverrideClearNone:
    """P1-4：with_override 可把 Optional 字段清回 None。"""

    def test_clear_k_override(self) -> None:
        params = _with(default_params(), "perf.k_override", D("0.3"))
        assert params.get_value("perf.k_override") == D("0.3")
        cleared = params.with_override("perf.k_override", None)
        assert cleared.get_value("perf.k_override") is None

    def test_clear_p_cache(self) -> None:
        params = _with(default_params(), "pricing.p_cache", D("1.0"))
        cleared = params.with_override("pricing.p_cache", None)
        assert cleared.get_value("pricing.p_cache") is None
        assert cleared.pricing.p_cache_effective == params.pricing.p_in / D(10)


class TestServiceValidation:
    """§3：服务校验层拦截越界输入为结构化 error（HTTP 422 语义）。"""

    @pytest.mark.parametrize(
        "path,value",
        [
            ("pricing.g_price", D("-0.995")),
            ("finance.infl", D("-1.0")),
            ("demand.g_demand", D("-2.0")),
            ("finance.cost_learning_rate", D("1.1")),
            ("power.P_idle_ratio", D("1.5")),
            ("perf.SLA_penalty_rate", D("-0.1")),
            ("finance.debt_ratio", D("1.2")),
            ("hw.CN_cfg", "weird"),
        ],
    )
    def test_invalid_inputs_rejected(self, path: str, value: Decimal) -> None:
        params = _with(default_params(), path, value)
        with pytest.raises(ValidationFailedError):
            validate_params(params)

    def test_valid_default_passes(self) -> None:
        assert validate_params(default_params()) == []

    def test_tou_share_overflow_warns(self) -> None:
        params = default_params()
        params = _with(params, "power.tou_peak_share", D("0.8"))
        params = _with(params, "power.tou_valley_share", D("0.4"))
        warnings = validate_params(params)
        assert any("峰谷" in item["message"] for item in warnings)


class TestRegistriesCoverage:
    """§4.1：敏感性/蒙特卡洛变量注册表覆盖新增成本科目。"""

    def test_sensitivity_default_vars_include_new_costs(self) -> None:
        keys = {var.key for var in DEFAULT_VARS}
        assert {"Co_eng", "Co_sales_admin", "Co_other", "SLA_penalty_rate", "cost_learning_rate"} <= keys

    def test_montecarlo_sampling_vars_include_new_costs(self) -> None:
        paths = {path for path, _, _ in mc._SAMPLING_VARS}
        assert {
            "power.Co_eng",
            "power.Co_sales_admin",
            "power.Co_other",
            "perf.SLA_penalty_rate",
            "finance.cost_learning_rate",
        } <= paths


class TestFormulaSpecResolvable:
    """§4.3：公式表「参数路径型」inputs 必须能在默认快照中解析。

    公式表 inputs 混有参数路径（`group.field`）、派生量名与公式内部符号（`R`/`CF_t` 等），
    后者是代数记号无法机器解析；本测试只强校验点号路径，防「文档-代码字段名漂移」。
    """

    def _param_resolvable(self, path: str) -> bool:
        params = default_params()
        group_name, _, field_name = path.partition(".")
        group = getattr(params, group_name, None)
        return group is not None and hasattr(group, field_name)

    def test_all_dotted_formula_inputs_resolvable(self) -> None:
        unresolved = [
            (f.id, inp)
            for f in FORMULAS
            for inp in f.inputs
            if "." in inp and not self._param_resolvable(inp)
        ]
        assert not unresolved, f"以下公式的点号 inputs 无法在参数模型解析：{unresolved}"

    def test_f006_includes_idle_ratio(self) -> None:
        """F006 电费公式必须登记 P_idle_ratio（P2 负载曲线接入后的文档-代码同步）。"""
        f006 = next(f for f in FORMULAS if f.id == "F006")
        assert "power.P_idle_ratio" in f006.inputs
        assert "P_idle_ratio" in f006.expr
