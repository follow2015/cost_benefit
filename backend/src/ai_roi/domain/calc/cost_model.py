"""三方案统一成本模型（架构 §3.10）。

统一线性化：`C(Q) = a + b·Q`
- `Q`  = 月等效输出量（Mtok/月）
- `a`  = 月固定成本（元/月）
- `b`  = 单位变动成本（元/Mtok）

- **A 自建**：`a = C_fix_acct`（含折旧的会计口径固定成本）；`b = C_var_per_U / Q_cap_M`
- **B 租用**：`a = 包月固定 + 自付托管/网络/存储/运维`；`b = Rent_gpu·N_gpu·H / Q_cap_M`（+ 不含电时叠加电费）
- **C API**：`a = 0`；`b = (rho·((1−h)·API_in + h·API_cache) + API_out) / factor`
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Sequence

from ai_roi.domain.calc.decimal_config import D, H, MONTHS_PER_YEAR, ONE, ZERO, safe_div
from ai_roi.domain.calc.parameters import (
    POWER_MODE_BUNDLE,
    RENT_INC_NONE,
    RENT_INC_POWER,
    RENT_INC_POWER_HOSTING,
    DerivedParams,
    ScenarioParams,
)

PLAN_SELF_BUILD = "self_build"
PLAN_RENT = "rent"
PLAN_API = "api"
PLAN_HYBRID = "hybrid"

PLAN_LABELS: Dict[str, str] = {
    PLAN_SELF_BUILD: "方案A 自建",
    PLAN_RENT: "方案B 租用",
    PLAN_API: "方案C 第三方 API",
    PLAN_HYBRID: "方案D 混合部署",
}


class CostModel(ABC):
    """线性成本模型抽象：`C(Q) = a + b·Q`。"""

    plan: str = ""

    @property
    @abstractmethod
    def a(self) -> Decimal:
        """月固定成本（元/月）。"""

    @property
    @abstractmethod
    def b(self) -> Decimal:
        """单位变动成本（元/Mtok）。"""

    def cost(self, q_mtok: Decimal) -> Decimal:
        """给定月需求量 Q（Mtok）的月总成本（元/月）。"""
        return self.a + self.b * D(q_mtok)

    def unit_cost(self, q_mtok: Decimal) -> Decimal:
        """给定月需求量 Q 的每百万 token 成本（元/Mtok）。"""
        return safe_div(self.cost(q_mtok), D(q_mtok))

    def name(self) -> str:
        """人类可读方案名。"""
        return PLAN_LABELS.get(self.plan, self.plan)

    def to_dict(self) -> Dict[str, object]:
        """序列化为曲线定义（前端画三方案成本线用）。"""
        return {"plan": self.plan, "label": self.name(), "a": self.a, "b": self.b}


@dataclass(frozen=True)
class SelfBuildCost(CostModel):
    """方案 A 自建（CAPEX 路径）。"""

    C_fix_acct: Decimal
    C_var_per_U: Decimal
    Q_cap_M: Decimal
    plan: str = PLAN_SELF_BUILD

    @property
    def a(self) -> Decimal:
        return self.C_fix_acct

    @property
    def b(self) -> Decimal:
        return safe_div(self.C_var_per_U, self.Q_cap_M)


@dataclass(frozen=True)
class RentCost(CostModel):
    """方案 B 租用（GPU 云/裸金属，OPEX 路径）。"""

    fixed: Decimal
    Rent_gpu: Decimal
    N_gpu: Decimal
    Q_cap_M: Decimal
    power_per_mtok: Decimal = ZERO
    plan: str = PLAN_RENT

    @property
    def a(self) -> Decimal:
        return self.fixed

    @property
    def b(self) -> Decimal:
        rent_per_month = self.Rent_gpu * self.N_gpu * H
        return safe_div(rent_per_month, self.Q_cap_M) + self.power_per_mtok


@dataclass(frozen=True)
class ApiCost(CostModel):
    """方案 C 直接调第三方 API（纯线性，无固定成本）。"""

    API_in: Decimal
    API_out: Decimal
    API_cache: Decimal
    rho: Decimal
    h: Decimal
    factor: Decimal
    plan: str = PLAN_API

    @property
    def a(self) -> Decimal:
        return ZERO

    @property
    def b(self) -> Decimal:
        blended_in = (ONE - self.h) * self.API_in + self.h * self.API_cache
        return safe_div(self.rho * blended_in + self.API_out, self.factor)


def build_self_build(derived: DerivedParams) -> SelfBuildCost:
    """构建方案 A 成本模型。"""
    return SelfBuildCost(
        C_fix_acct=derived.C_fix_acct,
        C_var_per_U=derived.C_var_per_U,
        Q_cap_M=derived.Q_cap_M,
    )


def build_rent(params: ScenarioParams, derived: DerivedParams) -> RentCost:
    """构建方案 B 成本模型。

    托管/电费是否自付取决于 `pricing.rent_inc`：
    - `power`（PRD 默认，含电不含托管）→ 自付托管 Co_loc；电费不重复计。
    - `power_hosting` → 托管与电费均由云厂承担。
    - `none` → 托管与电费均自付。
    """
    power = params.power
    rent_inc = params.pricing.rent_inc
    if power.power_mode == POWER_MODE_BUNDLE:
        self_paid_hosting = ZERO if rent_inc == RENT_INC_POWER_HOSTING else derived.bundle_rack_cost_m
    else:
        self_paid_hosting = ZERO if rent_inc == RENT_INC_POWER_HOSTING else power.Co_loc
    power_per_mtok = (
        safe_div(derived.C_var_per_U, derived.Q_cap_M) if rent_inc == RENT_INC_NONE else ZERO
    )
    idle_for_rent = derived.C_power_idle_m if rent_inc == RENT_INC_NONE else ZERO
    fixed = (
        params.pricing.rent_fixed_monthly
        + self_paid_hosting
        + power.Co_net
        + power.Co_stor
        + power.Co_ops / MONTHS_PER_YEAR
        + power.Co_eng / MONTHS_PER_YEAR
        + power.Co_sales_admin / MONTHS_PER_YEAR
        + power.Co_other / MONTHS_PER_YEAR
        + idle_for_rent
    )
    return RentCost(
        fixed=fixed,
        Rent_gpu=params.pricing.Rent_gpu,
        N_gpu=params.hw.N_gpu,
        Q_cap_M=derived.Q_cap_M,
        power_per_mtok=power_per_mtok,
    )


def build_api(params: ScenarioParams, derived: DerivedParams) -> ApiCost:
    """构建方案 C 成本模型。"""
    return ApiCost(
        API_in=params.pricing.API_in,
        API_out=params.pricing.API_out,
        API_cache=params.pricing.api_cache_effective,
        rho=params.demand.rho,
        h=params.demand.h,
        factor=derived.factor,
    )


def build_all(params: ScenarioParams, derived: DerivedParams) -> List[CostModel]:
    """构建三方案成本模型（顺序固定：A→B→C，前后端一致）。"""
    return [
        build_self_build(derived),
        build_rent(params, derived),
        build_api(params, derived),
    ]


@dataclass(frozen=True)
class HybridCost(CostModel):
    """方案 D 混合部署：A/B/C 线性加权（权重和=1）。"""

    w_A: Decimal
    w_B: Decimal
    w_C: Decimal
    a_A: Decimal
    b_A: Decimal
    a_B: Decimal
    b_B: Decimal
    a_C: Decimal
    b_C: Decimal
    plan: str = PLAN_HYBRID

    @property
    def a(self) -> Decimal:
        return self.w_A * self.a_A + self.w_B * self.a_B + self.w_C * self.a_C

    @property
    def b(self) -> Decimal:
        return self.w_A * self.b_A + self.w_B * self.b_B + self.w_C * self.b_C


def normalize_weights(
    w_A: Decimal, w_B: Decimal, w_C: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """归一化权重使其和为 1（全 0 时退化为三等分）。"""
    total = w_A + w_B + w_C
    if total <= ZERO:
        return ONE / D(3), ONE / D(3), ONE / D(3)
    return w_A / total, w_B / total, w_C / total


def build_hybrid(
    weights: tuple[Decimal, Decimal, Decimal],
    models: Sequence[CostModel],
) -> HybridCost:
    """由三方案成本模型 + 权重构造混合部署模型（顺序须为 A→B→C）。

    `C_hybrid(Q) = Σ w_i·(a_i + b_i·Q) = a_h + b_h·Q`，复用统一线性化。
    """
    if len(models) < 3:
        raise ValueError("混合部署需要 A/B/C 三方案成本模型")
    a, b = models[0], models[1]
    c = models[2]
    w_A, w_B, w_C = normalize_weights(*weights)
    return HybridCost(
        w_A=w_A,
        w_B=w_B,
        w_C=w_C,
        a_A=a.a,
        b_A=a.b,
        a_B=b.a,
        b_B=b.b,
        a_C=c.a,
        b_C=c.b,
    )
