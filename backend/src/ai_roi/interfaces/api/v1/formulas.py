"""公式规格路由（支撑 PRD REQ-08「100% 指标可追溯」的 ⓘ 抽屉）。

前端本地也内置一份 `formulaSpec.ts`；本接口用于版本核对与降级兜底
（当前端与后端 spec 版本不一致时提示用户刷新，避免解释口径漂移）。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from ai_roi.domain.calc.formula_spec import get_formula, spec_as_dict
from ai_roi.interfaces.api.errors import NotFoundError
from ai_roi.application.schemas.common import ApiResponse

router = APIRouter(prefix="/formulas", tags=["formulas"])


@router.get("", response_model=ApiResponse[Dict[str, Any]])
async def list_formulas(
    group: str = Query(default="", description="按分组过滤：cost_chain/revenue/breakeven/finance/compare"),
) -> ApiResponse[Dict[str, Any]]:
    """返回公式规格全量（可按分组过滤）。

    注：本接口刻意免鉴权——仅暴露公式解释口径的只读参考元数据，不含任何租户/
    业务数据；前端 ⓘ 抽屉与版本核对在匿名态也需可访问。如未来需要按租户隔离，
    应改为带 `require_permission` 的依赖，而非默认开放。
    """
    spec = spec_as_dict()
    if group:
        spec = {
            "version": spec["version"],
            "formulas": [item for item in spec["formulas"] if item["group"] == group],
        }
    return ApiResponse.ok(spec)


@router.get("/{formula_id}", response_model=ApiResponse[Dict[str, Any]])
async def get_one(formula_id: str) -> ApiResponse[Dict[str, Any]]:
    """按 id 取单条公式（如 F009）。"""
    try:
        formula = get_formula(formula_id.upper())
    except KeyError as exc:
        raise NotFoundError(f"公式不存在：{formula_id}") from exc
    return ApiResponse.ok(
        {
            "id": formula.id,
            "name": formula.name,
            "expr": formula.expr,
            "inputs": list(formula.inputs),
            "output": formula.output,
            "unit": formula.unit,
            "group": formula.group,
            "note": formula.note,
        }
    )
