"""API 选项透传回归测试（集成缺口修复）。

背景：`ai_roi.domain.calc.engine.EngineOptions` 已含增量能力字段（include_joint / joint_* /
include_custom_scenarios / custom_scenario_specs），但 `CalcOptionsIn` 此前未定义、
`build_engine_options` 也未透传，导致通过 HTTP 调用 `/api/v1/calc` 无法开启这些能力。

本测试证明：`CalcOptionsIn(include_joint=True, include_custom_scenarios=True, ...)`
经 `build_engine_options` 转换后，增量字段完整到达 `EngineOptions`（进而到达引擎），
并覆盖 delta 边界保护、target 白名单与 custom spec 解析。
"""

from __future__ import annotations

from decimal import Decimal

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import default_params
from ai_roi.domain.calc.scenario import CustomScenarioSpec
from ai_roi.domain.calc.sensitivity import TARGET_COST_PER_M, TARGET_NPV
from ai_roi.application.schemas.calc import CalcOptionsIn
from ai_roi.application.use_cases.calc_service import build_engine_options, params_fingerprint


def test_build_engine_options_passthrough_incremental_fields() -> None:
    """HTTP 层开启增量能力 → EngineOptions 增量字段全部到达引擎。"""
    options = CalcOptionsIn(
        include_joint=True,
        include_custom_scenarios=True,
        joint_delta="0.15",
        joint_vars=["U", "E_price"],
        custom_scenario_specs=[
            {
                "key": "low_demand",
                "label": "低需求",
                "overrides": {"demand.U": "0.4", "demand.D_eq": "2000"},
            },
            {
                "key": "high_price",
                "label": "高售价",
                "overrides": {"pricing.p_out": "40", "pricing.p_in": "10"},
            },
        ],
    )
    engine_opts = build_engine_options(options)

    assert engine_opts.include_joint is True
    assert engine_opts.joint_target == TARGET_NPV
    assert engine_opts.joint_delta == D("0.15")
    assert engine_opts.joint_vars == ["U", "E_price"]
    assert engine_opts.include_custom_scenarios is True
    assert engine_opts.custom_scenario_specs is not None
    assert len(engine_opts.custom_scenario_specs) == 2

    spec = engine_opts.custom_scenario_specs[0]
    assert isinstance(spec, CustomScenarioSpec)
    assert spec.key == "low_demand"
    assert spec.label == "低需求"
    assert spec.overrides == {"demand.U": D("0.4"), "demand.D_eq": D("2000")}

    payload = compute_all(default_params(), engine_opts)
    assert payload["joint"] is not None
    assert payload["custom_scenarios"] is not None
    assert len(payload["custom_scenarios"]["cases"]) == 2


def test_build_engine_options_joint_delta_bounds_fallback() -> None:
    """joint_delta 非法/越界（≤0、≥0.95、非数字）回落 0.2，与 sensitivity_delta 同规则。"""
    for bad in ("0", "-0.1", "0.95", "1.5", "abc"):
        engine_opts = build_engine_options(CalcOptionsIn(joint_delta=bad))
        assert engine_opts.joint_delta == D("0.2"), f"joint_delta={bad!r} 应回落 0.2"
    assert build_engine_options(CalcOptionsIn(joint_delta="0.3")).joint_delta == D("0.3")
    assert build_engine_options(CalcOptionsIn()).joint_delta == D("0.2")


def test_build_engine_options_joint_target_whitelist_fallback() -> None:
    """joint_target 白名单校验：非法值回退 npv，合法值保留。"""
    assert build_engine_options(CalcOptionsIn(joint_target="bogus")).joint_target == TARGET_NPV
    assert (
        build_engine_options(CalcOptionsIn(joint_target=TARGET_COST_PER_M)).joint_target
        == TARGET_COST_PER_M
    )
    assert build_engine_options(CalcOptionsIn()).joint_target == TARGET_NPV


def test_build_engine_options_custom_specs_invalid_fallback_none() -> None:
    """custom_scenario_specs 解析失败（缺 key / overrides 非 dict / 数值非法）整体回退 None。

    注：非 list 输入（如字符串）会被 pydantic 的 `Optional[List[...]]` 在进入服务层前拒绝，
    故此处只覆盖「列表元素不合法」的服务层回退路径。
    """
    bad_specs: list = [
        [{"label": "无 key", "overrides": {"demand.U": "0.5"}}],
        [{"key": "k", "overrides": "not-a-dict"}],
        [{"key": "k", "overrides": {"demand.U": "not-a-number"}}],
    ]
    for specs in bad_specs:
        engine_opts = build_engine_options(CalcOptionsIn(custom_scenario_specs=specs))
        assert engine_opts.custom_scenario_specs is None
    assert build_engine_options(CalcOptionsIn(custom_scenario_specs=[])).custom_scenario_specs is None
    assert build_engine_options(CalcOptionsIn(custom_scenario_specs=None)).custom_scenario_specs is None


def test_custom_specs_invalid_surfaces_warning() -> None:
    """§2.6 回归：自定义情景非法不再静默丢弃——丢弃告警写入 warnings 并随结果返回。"""
    warnings: list = []
    engine_opts = build_engine_options(
        CalcOptionsIn(custom_scenario_specs=[{"label": "无 key", "overrides": {"demand.U": "0.5"}}]),
        warnings,  # type: ignore[arg-type]
    )
    assert engine_opts.custom_scenario_specs is None
    assert len(warnings) == 1
    assert warnings[0]["path"] == "custom_scenario_specs"
    assert warnings[0]["level"] == "warning"
    assert "忽略未生效" in warnings[0]["message"]

    ok_warnings: list = []
    ok_opts = build_engine_options(
        CalcOptionsIn(
            custom_scenario_specs=[{"key": "k", "label": "L", "overrides": {"demand.U": "0.5"}}]
        ),
        ok_warnings,  # type: ignore[arg-type]
    )
    assert ok_opts.custom_scenario_specs is not None
    assert ok_warnings == []


def test_default_options_unchanged_and_defaults() -> None:
    """默认 CalcOptionsIn 的增量能力全关，EngineOptions 与默认一致。"""
    engine_opts = build_engine_options(CalcOptionsIn())
    assert engine_opts.include_joint is False
    assert engine_opts.include_custom_scenarios is False
    assert engine_opts.joint_vars is None
    assert engine_opts.custom_scenario_specs is None
    assert engine_opts == EngineOptions()


def test_fingerprint_distinguishes_incremental_options() -> None:
    """params 相同但增量选项不同 → 指纹不同（避免错误缓存命中）。"""
    base = default_params()
    plain = params_fingerprint(base, build_engine_options(CalcOptionsIn()))
    joint = params_fingerprint(
        base,
        build_engine_options(
            CalcOptionsIn(include_joint=True, joint_delta="0.15", joint_vars=["U", "E_price"])
        ),
    )
    custom = params_fingerprint(
        base,
        build_engine_options(
            CalcOptionsIn(
                include_custom_scenarios=True,
                custom_scenario_specs=[
                    {"key": "low", "label": "低需求", "overrides": {"demand.U": "0.4"}}
                ],
            )
        ),
    )
    assert plain != joint
    assert plain != custom
    assert joint != custom
    again = params_fingerprint(
        base,
        build_engine_options(
            CalcOptionsIn(include_joint=True, joint_delta="0.15", joint_vars=["U", "E_price"])
        ),
    )
    assert again == joint
