"""参数编解码：JSON（字符串 Decimal）⇄ `ScenarioParams` 数据类。

前后端 JSON 字段名完全一致（snake_case + 保留 PRD 符号名），本模块是唯一的转换入口，
对应前端 `calc-engine/parameters.ts` 的 `paramsFromJSON / paramsToJSON`。
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Union, get_args, get_origin, get_type_hints

from ai_roi.domain.calc.context import Conventions
from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.calc.parameters import (
    BenchRefs,
    DemandParams,
    FinanceParams,
    HardwareParams,
    HybridParams,
    PerfParams,
    PowerParams,
    PricingParams,
    ScenarioParams,
)

_GROUPS = {
    "hw": HardwareParams,
    "power": PowerParams,
    "perf": PerfParams,
    "demand": DemandParams,
    "pricing": PricingParams,
    "finance": FinanceParams,
    "bench": BenchRefs,
    "hybrid": HybridParams,
}


def _is_decimal_annotation(annotation: Any) -> bool:
    """判断注解是否为 Decimal / Optional[Decimal]。"""
    if annotation is Decimal:
        return True
    if get_origin(annotation) is Union:
        return Decimal in get_args(annotation)
    return False


def _is_int_annotation(annotation: Any) -> bool:
    """判断注解是否为 int / Optional[int]。"""
    if annotation is int:
        return True
    if get_origin(annotation) is Union:
        return int in get_args(annotation) and Decimal not in get_args(annotation)
    return False


def _build_group(cls: type, data: Optional[Dict[str, Any]]) -> Any:
    """按注解类型把 dict 转成对应参数组数据类。"""
    payload = data or {}
    hints = get_type_hints(cls)
    kwargs: Dict[str, Any] = {}
    for field_info in fields(cls):
        if field_info.name not in payload:
            continue
        raw = payload[field_info.name]
        annotation = hints.get(field_info.name)
        if raw is None:
            kwargs[field_info.name] = None
        elif _is_decimal_annotation(annotation):
            kwargs[field_info.name] = D(raw)
        elif _is_int_annotation(annotation):
            kwargs[field_info.name] = int(raw)
        elif annotation is bool:
            kwargs[field_info.name] = bool(raw)
        elif annotation is str:
            kwargs[field_info.name] = str(raw)
        else:
            kwargs[field_info.name] = raw
    return cls(**kwargs)


def params_from_dict(data: Optional[Dict[str, Any]]) -> ScenarioParams:
    """从 JSON dict 构造参数对象；缺省字段回落到默认模板值。"""
    payload = data or {}
    groups = {name: _build_group(cls, payload.get(name)) for name, cls in _GROUPS.items()}
    return ScenarioParams(
        conventions=Conventions.from_dict(payload.get("conventions")),
        **groups,
    )


def _dump(value: Any) -> Any:
    """递归导出数据类为 dict（Decimal 原样保留，由 to_jsonable 统一转字符串）。"""
    if is_dataclass(value) and not isinstance(value, type):
        return {field_info.name: _dump(getattr(value, field_info.name)) for field_info in fields(value)}
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


def params_to_dict(params: ScenarioParams) -> Dict[str, Any]:
    """导出参数对象为 dict（用于快照冻结与前端回填）。"""
    result: Dict[str, Any] = {name: _dump(getattr(params, name)) for name in _GROUPS}
    result["conventions"] = params.conventions.to_dict()
    return result
