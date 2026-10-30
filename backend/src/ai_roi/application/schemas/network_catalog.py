"""组网配套目录（配件库）Schema。"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ai_roi.infrastructure.db.models.network_catalog import CATEGORIES


class NetworkCatalogItemIn(BaseModel):
    """新增配件条目。"""

    category: str = Field(..., description=f"类别，可选 {CATEGORIES}")
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    price_cny: str = Field(..., description="单价（CNY，字符串 Decimal）")
    unit: str = "台"
    spec: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    is_builtin: bool = False
    is_active: bool = True


class NetworkCatalogItemUpdate(BaseModel):
    """更新配件条目（仅提交字段生效）。"""

    name: Optional[str] = None
    price_cny: Optional[str] = None
    unit: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    is_active: Optional[bool] = None


class NetworkCatalogItemOut(BaseModel):
    """配件条目（出参）。"""

    id: int
    category: str
    code: str
    name: str
    price_cny: str
    unit: str
    spec: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    as_of: Optional[date] = None
    version: int = 1
    is_active: bool = True
    is_builtin: bool = False
