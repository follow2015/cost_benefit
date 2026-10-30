"""双端一致性（后端侧）：`compute_all` 复现 goldenVectors.json 全部断言，偏差 ≤0.1%。

该黄金向量由 `scripts/gen_golden.py` 权威生成，前端 decimal.js 引擎镜像实现须对齐同一份。
运行：`pytest backend/app/calc/__tests__/test_consistency.py -q`（需先 `pip install -r requirements.txt`）。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ai_roi.domain.calc.decimal_config import D, dec_str
from ai_roi.domain.calc.engine import compute_all, EngineOptions
from ai_roi.domain.calc.path_resolve import resolve
from ai_roi.domain.calc.codec import params_from_dict
from ai_roi.domain.calc.scenario import CustomScenarioSpec

def resolve_str(payload: dict, path: str) -> str:
    val = resolve(payload, path)
    if isinstance(val, Decimal):
        return dec_str(val)
    return str(val)

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "goldenVectors.json"

with GOLDEN_PATH.open(encoding="utf-8") as fh:
    GOLDEN = json.load(fh)

TOLERANCE = Decimal(str(GOLDEN.get("tolerance", "0.001")))
CASES = GOLDEN["cases"]


def _options(opts: dict) -> EngineOptions:
    raw_specs = opts.get("custom_scenario_specs")
    custom_specs = None
    if raw_specs:
        custom_specs = [
            CustomScenarioSpec(
                key=s["key"],
                label=s["label"],
                overrides={path: D(val) for path, val in s["overrides"].items()},
            )
            for s in raw_specs
        ]
    return EngineOptions(
        include_sensitivity=opts.get("include_sensitivity", True),
        include_scenarios=opts.get("include_scenarios", True),
        include_crossover=opts.get("include_crossover", True),
        sensitivity_target=opts.get("sensitivity_target", "npv"),
        sensitivity_delta=Decimal(str(opts.get("sensitivity_delta", "0.2"))),
        include_joint=opts.get("include_joint", False),
        joint_target=opts.get("joint_target", "npv"),
        joint_delta=Decimal(str(opts.get("joint_delta", "0.2"))),
        joint_vars=opts.get("joint_vars"),
        include_custom_scenarios=opts.get("include_custom_scenarios", False),
        custom_scenario_specs=custom_specs,
    )


def _relative(server: Decimal, client: Decimal) -> Decimal:
    diff = abs(server - client)
    return diff if server == 0 else diff / abs(server)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_consistency(case: dict) -> None:
    params = params_from_dict(case["params"])
    payload = compute_all(params, _options(case["options"]))

    for path, expected in case["expect"].items():
        if expected is None:
            actual = resolve(payload, path)
            assert actual is None or (isinstance(actual, Decimal) and actual.is_nan()), path
            continue
        if isinstance(expected, bool):
            assert resolve(payload, path) == expected, path
            continue
        if isinstance(expected, str):
            assert resolve_str(payload, path) == expected, path
            continue
        actual = resolve(payload, path)
        assert isinstance(actual, Decimal), f"{path} 期望 Decimal，实得 {type(actual)}"
        dev = _relative(Decimal(str(expected)), actual)
        assert dev <= TOLERANCE, f"{path}: 偏差 {dev} 超过 {TOLERANCE}"


def test_kpi_formula_ids_all_resolvable() -> None:
    """compute_all 产出的每个 KPI formula_id 必须存在于公式规格。

    历史缺陷：F071/F072/F073/F081/F082/F091/F092 曾被 KPI 引用但 spec 未定义，
    前端 ⓘ 抽屉展开时 GET /formulas/{id} 返回 404（dangling）。本测试守住契约。
    """
    from ai_roi.domain.calc.engine import compute_all
    from ai_roi.domain.calc.formula_spec import FORMULA_INDEX

    for case in CASES:
        params = params_from_dict(case["params"])
        payload = compute_all(params, _options(case["options"]))
        for kpi in payload["kpis"]:
            fid = kpi.get("formula_id")
            assert fid in FORMULA_INDEX, f"{case['id']}: KPI {kpi['key']} 引用未定义公式 {fid}"


def test_calc_context_installed() -> None:
    """领域包 import 后，进程级 decimal 上下文必须是 34 位 ROUND_HALF_UP。

    精度策略由包边界显式安装（install_calc_context），叶子模块不得 import 期
    篡改全局状态（purity 约定）。本测试守住安装点不被意外移除。
    """
    import decimal

    import ai_roi.domain.calc  # noqa: F401 - 触发包边界安装

    assert decimal.getcontext().prec == 34
    assert decimal.getcontext().rounding == "ROUND_HALF_UP"
    assert decimal.DefaultContext.prec == 34
