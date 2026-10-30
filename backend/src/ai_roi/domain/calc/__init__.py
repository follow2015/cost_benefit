"""计算引擎（纯函数、零 IO、零 DB）。

模块划分对应架构 §3.1：
    context / parameters / throughput / cost_model / unit_cost / revenue /
    breakeven / financials / irr / crossover / sensitivity / scenario

统一入口：`engine.compute_all(params, options)`。
精度与公式的单一事实来源：`decimal_config.py` + `formula_spec.py` + `goldenVectors.json`。

精度策略安装点（redesign 显式化）：本包 import 时安装 34 位 ROUND_HALF_UP
进程级 decimal 上下文。这是全局精度策略的唯一持有处——叶子模块
（decimal_config 等）不再于 import 期篡改全局状态，领域层纯度约定由此成立。
"""

from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION, Conventions
from ai_roi.domain.calc.decimal_config import install_calc_context
from ai_roi.domain.calc.engine import EngineOptions, compute_all, compute_core
from ai_roi.domain.calc.parameters import ScenarioParams, default_params, derive

install_calc_context()

__all__ = [
    "Conventions",
    "EngineOptions",
    "ENGINE_VERSION",
    "FORMULA_SPEC_VERSION",
    "ScenarioParams",
    "compute_all",
    "compute_core",
    "default_params",
    "derive",
    "install_calc_context",
]
