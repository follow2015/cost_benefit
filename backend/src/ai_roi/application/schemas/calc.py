"""计算相关 DTO。

约定：**所有 Decimal 在 JSON 中一律为字符串**（架构 §3.4），因此结果 `payload` 用
`Dict[str, Any]`，由 `ai_roi.domain.calc.decimal_config.to_jsonable` 统一转换后直出，
避免 Pydantic 的 float 序列化破坏 34 位精度。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CalcOptionsIn(BaseModel):
    """计算选项（与 `ai_roi.domain.calc.engine.EngineOptions` 对齐）。"""

    include_sensitivity: bool = True
    include_scenarios: bool = True
    include_crossover: bool = True
    sensitivity_target: str = "npv"
    sensitivity_delta: str = "0.2"
    include_joint: bool = False
    joint_target: str = "npv"
    joint_delta: str = "0.2"
    joint_vars: Optional[List[str]] = None
    include_custom_scenarios: bool = False
    custom_scenario_specs: Optional[List[Dict[str, Any]]] = None


class CalcRequest(BaseModel):
    """计算请求。

    - 传 `scenario_id`：读库参数计算并落库结果（权威重算）；
    - 传 `params`：无状态试算（不落库），用于向导实时预览的后端校验；
    - 两者都传：以 `params` 为准，但结果关联到该 scenario。
    """

    scenario_id: Optional[int] = None
    params: Optional[Dict[str, Any]] = None
    options: CalcOptionsIn = Field(default_factory=CalcOptionsIn)
    persist: bool = True
    client_kpis: Optional[Dict[str, str]] = None


class CalcResultOut(BaseModel):
    """计算结果。"""

    id: Optional[int] = None
    scenario_id: Optional[int] = None
    scenario_version: int = 1
    engine_version: str = ""
    formula_spec_version: str = ""
    params_hash: str = ""
    duration_ms: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    client_deviation: Optional[str] = None
    created_at: Optional[datetime] = None


class CalcSummaryOut(BaseModel):
    """结果摘要（列表/对比页用）。"""

    id: int
    scenario_id: Optional[int] = None
    scenario_name: str = ""
    kpi_summary: Dict[str, Any] = Field(default_factory=dict)
    engine_version: str = ""
    created_at: datetime


class CompareRequest(BaseModel):
    """多方案对比请求（P0：同一 KPI 集横向对比）。"""

    scenario_ids: List[int] = Field(min_length=1, max_length=8)
    options: CalcOptionsIn = Field(default_factory=CalcOptionsIn)


class CompareItem(BaseModel):
    """对比项。"""

    scenario_id: int
    scenario_name: str
    kpis: List[Dict[str, Any]] = Field(default_factory=list)
    kpi_map: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class CompareResponse(BaseModel):
    """对比响应。"""

    items: List[CompareItem] = Field(default_factory=list)
    kpi_meta: List[Dict[str, Any]] = Field(default_factory=list)


class MonteCarloRequest(BaseModel):
    """蒙特卡洛模拟请求（P2-4 / REQ-18）。

    - 传 `scenario_id`：读库参数模拟（不落库）；
    - 传 `params`：无状态模拟；两者都缺则报错。
    """

    scenario_id: Optional[int] = None
    params: Optional[Dict[str, Any]] = None
    n: int = Field(default=2000, ge=1, le=50000)
    seed: Optional[int] = None


class HardwareRecommendIn(BaseModel):
    """硬件反选推荐请求（架构 §3.13）；Decimal 一律字符串（全站口径）。

    需求来源：`T_eff_target` 或 `D_eq_target` 二选一（都提供时取更严格者）；
    其余字段可选，缺省回落设计默认。`base_params` 为方案参数基线（可带完整 7 组）。
    """

    T_eff_target: Optional[str] = None
    D_eq_target: Optional[str] = None
    U_target: str = "0.7"
    growth_headroom: str = "0.2"
    M_param: str = "70"
    quant: str = "FP8"
    Ctx: Optional[str] = None
    Mem_w_override: Optional[str] = None
    SLA_ttft: Optional[str] = None
    SLA_tpot: Optional[str] = None
    CN_cfg: str = "none"
    capex_budget: Optional[str] = None
    power_budget_kw: Optional[str] = None
    objective: str = "balanced"
    fabric: str = ""
    extra_nodes: int = Field(default=0, ge=0)
    port_speed: Optional[int] = Field(default=None, ge=200, le=800)
    spine_port_speed: Optional[int] = Field(default=None, ge=200, le=800)
    model_code: Optional[str] = None
    base_params: Optional[Dict[str, Any]] = None
    top_n: int = Field(default=3, ge=1, le=6)


class FormulaOut(BaseModel):
    """公式条目（ⓘ 追溯抽屉）。"""

    id: str
    name: str
    expression: str
    inputs: List[str] = Field(default_factory=list)
    unit: str = ""
    note: str = ""
    group: str = ""
