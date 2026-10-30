"""方案 DTO。

`params` 使用 `Dict[str, Any]` 而非逐字段 Pydantic 模型，原因：
1. 参数字典有 60+ 字段且 Decimal 需以字符串交换，逐字段建模会引入 float 转换风险；
2. 真正的校验由 `ai_roi.domain.calc.codec.params_from_dict` + `ai_roi.domain.validation.params` 完成（单一事实来源）；
3. 前端 `ScenarioParamsDTO` 与 `ai_roi.domain.calc.codec.params_to_dict` 同构，契约由黄金向量保障。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScenarioCreate(BaseModel):
    """创建方案。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    is_template: bool = False


class ScenarioUpdate(BaseModel):
    """更新方案（部分字段）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    note: str = ""


class ScenarioListItemOut(BaseModel):
    """列表项（含最近一次计算的 KPI 摘要，供工作台卡片直读）。"""

    id: int
    name: str
    description: str = ""
    status: str
    version: int
    tags: List[str] = Field(default_factory=list)
    is_template: bool = False
    conventions: Dict[str, Any] = Field(default_factory=dict)
    latest_kpi: Optional[Dict[str, Any]] = None
    latest_result_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ScenarioDetailOut(BaseModel):
    """方案详情。"""

    id: int
    name: str
    description: str = ""
    status: str
    version: int
    tags: List[str] = Field(default_factory=list)
    is_template: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)
    conventions: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class SnapshotOut(BaseModel):
    """快照条目。"""

    id: int
    version: int
    note: str = ""
    diff: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[int] = None
    created_at: datetime
