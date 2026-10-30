"""蒙特卡洛模拟（P2-4 / REQ-18）。

对 ≥8 个关键变量（U、E_price、Rent_gpu、API_out、CAPEX、T_eff、r_w、p_out、
p_in、D_eq 等）设定分布（三角分布，参数取基准 ± 偏差），用简单随机抽样 N 次
（默认 N=2000，可配），每次经 `engine.evaluate_npv_irr` 精简求值（NPV / IRR）跑一遍，
收集 NPV / IRR 分布。

输出：
- 均值、标准差、分位数（P5/P10/P25/P50/P75/P90/P95）；
- P(NPV>0)、P(IRR>r_w)；
- 直方图分箱。

精度策略：抽样可用 float（分布估计，精度要求低，不进 Decimal 主链）；但每次 NPV
计算复用 `financials` 的口径逻辑（`evaluate_npv_irr`，与 `compute_all` 同源，但不构建
KPI/成本模型/现金流序列等整份载荷），保证与确定性结果一致。无 numpy 时
仅用标准库 `random`，不强制加重依赖。

注意：本模块为新增文件，不修改既有 `financials.py` / `engine.py` 口径。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D, ZERO
from ai_roi.domain.calc.engine import evaluate_npv_irr
from ai_roi.domain.calc.parameters import ScenarioParams

_SAMPLING_VARS: List[Tuple[str, float, bool]] = [
    ("demand.U", 0.20, True),
    ("power.E_price", 0.20, True),
    ("pricing.Rent_gpu", 0.25, True),
    ("pricing.API_out", 0.25, True),
    ("hw.P_gpu", 0.20, True),
    ("perf.T_eff", 0.15, True),
    ("finance.r_w", 0.30, True),
    ("pricing.p_out", 0.20, True),
    ("pricing.p_in", 0.20, True),
    ("demand.D_eq", 0.20, True),
    ("power.Co_eng", 0.20, True),
    ("power.Co_sales_admin", 0.20, True),
    ("power.Co_other", 0.20, True),
    ("perf.SLA_penalty_rate", 0.20, True),
    ("finance.cost_learning_rate", 0.20, True),
]


@dataclass(frozen=True)
class MonteCarloResult:
    """蒙特卡洛模拟结果。"""

    n: int
    seed: Optional[int]
    mean_npv: float
    std_npv: float
    percentiles_npv: Dict[str, float]
    p_npv_positive: float
    p_irr_gt_rw: float
    histogram: List[Dict[str, float]]
    deterministic_npv: float
    deterministic_irr: float
    notes: List[str] = field(default_factory=list)


def _sample_relative(rng: random.Random, spread: float) -> float:
    """相对偏差（三角分布，对称中心 0，范围 [-spread, +spread]）。"""
    return rng.triangular(-spread, spread, 0.0)


def _percentile(sorted_vals: List[float], p: float) -> float:
    """线性插值分位数（p 为 0–100）。"""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    rank = (n - 1) * p / 100.0
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return float(sorted_vals[low])
    frac = rank - low
    return float(sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac)


def _histogram(values: List[float], nbins: int = 20) -> List[Dict[str, float]]:
    """等宽直方图分箱。"""
    if not values:
        return []
    mn = min(values)
    mx = max(values)
    if mx <= mn:
        return [{"bin_start": float(mn), "bin_end": float(mn + 1.0), "count": float(len(values))}]
    width = (mx - mn) / nbins
    bins = [
        {"bin_start": float(mn + i * width), "bin_end": float(mn + (i + 1) * width), "count": 0.0}
        for i in range(nbins)
    ]
    for v in values:
        idx = int((v - mn) / width)
        if idx >= nbins:
            idx = nbins - 1
        if idx < 0:
            idx = 0
        bins[idx]["count"] += 1.0
    return bins


def montecarlo_compute(
    params: ScenarioParams,
    n: int = 2000,
    seed: Optional[int] = None,
    spreads: Optional[Dict[str, float]] = None,
) -> MonteCarloResult:
    """执行蒙特卡洛模拟，返回 NPV / IRR 分布统计。

    Args:
        params: 基准方案参数。
        n: 抽样次数（默认 2000）。
        seed: 随机种子（可复现；默认 None 不固定）。
        spreads: 各变量相对波动幅度的覆盖字典（path → spread）；
            缺省使用 `_SAMPLING_VARS` 的默认幅度；传全 0 即确定性回归。
    """
    rng = random.Random(seed)
    n = max(1, int(n))

    vars_table: List[Tuple[str, float, bool]] = [
        (path, float(spreads.get(path, spread)) if spreads else spread, non_neg)
        for path, spread, non_neg in _SAMPLING_VARS
    ]

    deterministic_npv, deterministic_irr = evaluate_npv_irr(params)
    deterministic_npv = float(deterministic_npv) if deterministic_npv is not None else 0.0
    deterministic_irr = float(deterministic_irr) if deterministic_irr is not None else 0.0
    r_w = float(params.finance.r_w)

    npv_list: List[float] = []
    irr_list: List[float] = []
    notes: List[str] = []

    for _ in range(n):
        perturbed = params
        for path, spread, non_neg in vars_table:
            base_val = perturbed.get_value(path)
            if base_val is None:
                continue
            base_f = float(base_val)
            rel = _sample_relative(rng, spread)
            new_val = base_f * (1.0 + rel)
            if non_neg and new_val <= 0:
                new_val = base_f * 1e-3 if base_f > 0 else 1e-3
            perturbed = perturbed.with_override(path, new_val)

        npv, irr = evaluate_npv_irr(perturbed)
        npv_list.append(float(npv) if npv is not None else 0.0)
        irr_list.append(float(irr) if irr is not None else 0.0)

    mean_npv = sum(npv_list) / n
    variance = sum((x - mean_npv) ** 2 for x in npv_list) / n
    std_npv = math.sqrt(variance)

    sorted_npv = sorted(npv_list)
    percentiles_npv = {
        "p5": _percentile(sorted_npv, 5),
        "p10": _percentile(sorted_npv, 10),
        "p25": _percentile(sorted_npv, 25),
        "p50": _percentile(sorted_npv, 50),
        "p75": _percentile(sorted_npv, 75),
        "p90": _percentile(sorted_npv, 90),
        "p95": _percentile(sorted_npv, 95),
    }

    p_npv_positive = sum(1 for x in npv_list if x > 0) / n
    p_irr_gt_rw = sum(1 for x in irr_list if x > r_w) / n

    notes.append(
        f"对 {len(_SAMPLING_VARS)} 个变量做三角分布随机抽样（N={n}），"
        f"每次复用 financials 口径计算 NPV/IRR。"
    )

    return MonteCarloResult(
        n=n,
        seed=seed,
        mean_npv=mean_npv,
        std_npv=std_npv,
        percentiles_npv=percentiles_npv,
        p_npv_positive=p_npv_positive,
        p_irr_gt_rw=p_irr_gt_rw,
        histogram=_histogram(npv_list),
        deterministic_npv=deterministic_npv,
        deterministic_irr=deterministic_irr,
        notes=notes,
    )
