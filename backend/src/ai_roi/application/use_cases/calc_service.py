"""计算服务：权威重算 + 结果落库 + 双端偏差核对。

流程（架构 §4.4 序列图）：
    参数 dict → codec 解析 → validation 校验 → engine.compute_all（权威）
    → to_jsonable 转字符串 → 落库（calc_result + cashflow_row 分区）
    → 与前端预算 KPI 比对偏差 → 审计

偏差核对：前端 decimal.js 与后端 Python decimal 同口径，容差 0.1%（架构 §3.12）。
超容差不阻断请求（后端结果为准），但写入 `client_deviation` 并落审计，便于回归排查。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from ai_roi.application.ports import (
    RESULT_CACHE_DEFAULT_TTL,
    CashflowRepository,
    ResultCache,
    ResultRepository,
    UnitOfWork,
)
from ai_roi.domain.calc.codec import params_from_dict, params_to_dict
from ai_roi.domain.calc.context import ENGINE_VERSION, FORMULA_SPEC_VERSION
from ai_roi.domain.calc.decimal_config import D, ZERO, dec_str, to_jsonable
from ai_roi.domain.calc.engine import EngineOptions, compute_all
from ai_roi.domain.calc.parameters import ScenarioParams
from ai_roi.domain.calc.scenario import CustomScenarioSpec
from ai_roi.domain.calc.sensitivity import (
    TARGET_COST_ADVANTAGE,
    TARGET_COST_PER_M,
    TARGET_NPV,
)
from ai_roi.application.schemas.calc import CalcOptionsIn

CalcResult = Any
from ai_roi.domain.validation.params import validate_params

logger = logging.getLogger(__name__)

CLIENT_TOLERANCE: Decimal = D("0.001")

_VALID_TARGETS = {TARGET_NPV, TARGET_COST_PER_M, TARGET_COST_ADVANTAGE}

_DELTA_FALLBACK = D("0.2")


def _parse_delta(raw: Optional[str]) -> Decimal:
    """把字符串扰动幅度安全转 Decimal；非法或越界回退默认 0.2。"""
    if raw is None:
        return _DELTA_FALLBACK
    try:
        delta = D(raw)
    except (InvalidOperation, ValueError):
        return _DELTA_FALLBACK
    if delta <= ZERO or delta >= D("0.95"):
        return _DELTA_FALLBACK
    return delta


def _parse_custom_specs(
    specs: Optional[List[Dict[str, Any]]],
    warnings: Optional[List[Dict[str, str]]] = None,
) -> Optional[List[CustomScenarioSpec]]:
    """把请求中的自定义情景 dict 列表转成引擎 `CustomScenarioSpec`。

    - 每项要求 `key` 非空且 `overrides` 为 dict（值可为字符串/数字，统一转 Decimal）；
    - 任一 spec 不合法时整体回退 None（与 delta/白名单的宽容风格一致，不阻断主计算）；
    - 发生丢弃时不再静默：向 `warnings` 追加一条提示并落日志，便于前端告警条与审计发现。
    """
    if not specs:
        return None
    parsed: List[CustomScenarioSpec] = []
    for idx, raw in enumerate(specs):
        try:
            if not isinstance(raw, dict):
                _drop_custom_spec(warnings, idx, "条目不是对象")
                return None
            key = str(raw.get("key") or "").strip()
            label = str(raw.get("label") or key)
            overrides_raw = raw.get("overrides") or {}
            if not key or not isinstance(overrides_raw, dict):
                _drop_custom_spec(warnings, idx, "缺少 key 或 overrides 非对象")
                return None
            overrides = {str(path): D(value) for path, value in overrides_raw.items()}
        except (InvalidOperation, ValueError, TypeError):
            _drop_custom_spec(warnings, idx, "overrides 含非法数值")
            return None
        parsed.append(CustomScenarioSpec(key=key, label=label, overrides=overrides))
    return parsed


def _drop_custom_spec(
    warnings: Optional[List[Dict[str, str]]],
    idx: int,
    reason: str,
) -> None:
    """记录一条自定义情景被丢弃的告警（写入 warnings 并落日志，避免静默丢弃）。"""
    msg = f"自定义情景第 {idx + 1} 项非法（{reason}），整组自定义情景已忽略未生效。"
    logger.warning("custom_scenario_specs: %s", msg)
    if warnings is not None:
        warnings.append({"path": "custom_scenario_specs", "level": "warning", "message": msg})


def build_engine_options(
    options: CalcOptionsIn,
    warnings: Optional[List[Dict[str, str]]] = None,
) -> EngineOptions:
    """把 DTO 选项转成引擎选项（含目标白名单与 delta 边界，透传增量能力）。

    `warnings` 可选：传入时，自定义情景解析丢弃等宽容性降级会追加告警到此列表，
    随计算结果返回前端，避免静默丢弃。
    """
    target = options.sensitivity_target if options.sensitivity_target in _VALID_TARGETS else TARGET_NPV
    delta = _parse_delta(options.sensitivity_delta)

    joint_target = options.joint_target if options.joint_target in _VALID_TARGETS else TARGET_NPV
    joint_delta = _parse_delta(options.joint_delta)
    custom_specs = _parse_custom_specs(options.custom_scenario_specs, warnings)

    return EngineOptions(
        include_sensitivity=options.include_sensitivity,
        include_scenarios=options.include_scenarios,
        include_crossover=options.include_crossover,
        sensitivity_target=target,
        sensitivity_delta=delta,
        include_joint=options.include_joint,
        joint_target=joint_target,
        joint_delta=joint_delta,
        joint_vars=options.joint_vars,
        include_custom_scenarios=options.include_custom_scenarios,
        custom_scenario_specs=custom_specs,
    )


@dataclass(frozen=True)
class CalcOutcome:
    """一次计算的产出。"""

    payload: Dict[str, Any]
    kpi_summary: Dict[str, Any]
    params_hash: str
    duration_ms: int
    warnings: List[Dict[str, str]]
    client_deviation: Optional[str] = None
    deviation_detail: Optional[Dict[str, str]] = None
    record: Optional[CalcResult] = None


def params_fingerprint(params: ScenarioParams, options: EngineOptions) -> str:
    """参数 + 选项指纹（sha256），用于结果缓存命中。"""
    canonical = {
        "params": to_jsonable(params_to_dict(params)),
        "options": {
            "include_sensitivity": options.include_sensitivity,
            "include_scenarios": options.include_scenarios,
            "include_crossover": options.include_crossover,
            "sensitivity_target": options.sensitivity_target,
            "sensitivity_delta": dec_str(options.sensitivity_delta),
            "include_joint": options.include_joint,
            "joint_target": options.joint_target,
            "joint_delta": dec_str(options.joint_delta),
            "joint_vars": options.joint_vars,
            "include_custom_scenarios": options.include_custom_scenarios,
            "custom_scenario_specs": (
                [
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "overrides": {
                            path: dec_str(value) for path, value in spec.overrides.items()
                        },
                    }
                    for spec in options.custom_scenario_specs
                ]
                if options.custom_scenario_specs
                else None
            ),
        },
        "engine": ENGINE_VERSION,
        "spec": FORMULA_SPEC_VERSION,
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compare_with_client(
    server_kpis: Dict[str, Optional[Decimal]], client_kpis: Optional[Dict[str, str]]
) -> Tuple[Optional[str], Dict[str, str]]:
    """比对前端预算与后端权威 KPI，返回 (最大相对偏差, 逐项偏差)。

    比对规则：
    - 双方都为 None → 视为一致（跳过）；
    - 一方为 None → 记为 `n/a`（结构性差异，需人工关注）；
    - 后端基准为 0 → 用绝对差判定；否则用相对差 `|c−s| / |s|`。
    """
    detail: Dict[str, str] = {}
    if not client_kpis:
        return None, detail

    max_deviation = ZERO
    for key, server_value in server_kpis.items():
        if key not in client_kpis:
            continue
        raw_client = client_kpis[key]
        if raw_client is None or raw_client == "":
            if server_value is not None:
                detail[key] = "n/a"
            continue
        if server_value is None:
            detail[key] = "n/a"
            continue
        try:
            client_value = D(raw_client)
        except (InvalidOperation, ValueError):
            detail[key] = "parse_error"
            continue
        difference = abs(client_value - server_value)
        deviation = difference if server_value == ZERO else difference / abs(server_value)
        detail[key] = dec_str(deviation)
        if deviation > max_deviation:
            max_deviation = deviation
    return dec_str(max_deviation), detail


def prepare_engine(
    params_dict: Optional[Dict[str, Any]], options: CalcOptionsIn
) -> Tuple[ScenarioParams, EngineOptions, List[Dict[str, str]]]:
    """解析参数 → 校验 → 构建引擎选项（不含执行）。

    拆出供无状态试算的缓存链路复用：指纹计算只需要参数与选项，
    不必先跑一遍引擎（试算预览的高频路径）。
    """
    params = params_from_dict(params_dict)
    warnings = validate_params(params)
    engine_options = build_engine_options(options, warnings)
    return params, engine_options, warnings


def compute_payload(
    params: ScenarioParams,
    engine_options: EngineOptions,
    warnings: List[Dict[str, str]],
) -> Tuple[Dict[str, Any], int]:
    """执行引擎并 JSON 化。返回 (载荷, 耗时ms)。

    校验告警并入载荷 `validation_warnings`（前端统一在告警条渲染）。
    """
    started = time.perf_counter()
    raw_payload = compute_all(params, engine_options)
    duration_ms = int((time.perf_counter() - started) * 1000)

    payload = to_jsonable(raw_payload)
    payload["validation_warnings"] = warnings
    return payload, duration_ms


def run_engine(
    params_dict: Optional[Dict[str, Any]], options: CalcOptionsIn
) -> Tuple[ScenarioParams, EngineOptions, Dict[str, Any], List[Dict[str, str]], int]:
    """解析参数 → 校验 → 执行引擎。返回 (参数, 选项, JSON 化载荷, 告警, 耗时ms)。"""
    params, engine_options, warnings = prepare_engine(params_dict, options)
    payload, duration_ms = compute_payload(params, engine_options, warnings)
    return params, engine_options, payload, warnings, duration_ms


class CalcService:
    """计算编排服务。"""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.session = uow.session
        self.results: ResultRepository = uow.results
        self.cashflows: CashflowRepository = uow.cashflows

    async def calculate(
        self,
        tenant_id: int,
        user_id: Optional[int],
        params_dict: Optional[Dict[str, Any]],
        options: CalcOptionsIn,
        scenario_id: Optional[int] = None,
        scenario_version: int = 1,
        persist: bool = True,
        client_kpis: Optional[Dict[str, str]] = None,
        result_cache: Optional[ResultCache] = None,
    ) -> CalcOutcome:
        """执行一次权威计算，可选落库。

        `result_cache`：仅对无状态试算（persist=False）生效——同参数指纹命中
        缓存时跳过引擎重算。引擎为纯函数，同键必同值，缓存不改变任何计算结果，
        只省一次 CPU；指纹含引擎/公式版本号，升级自动失效。
        """
        params, engine_options, warnings = prepare_engine(params_dict, options)
        fingerprint = params_fingerprint(params, engine_options)

        if result_cache is not None and not persist:
            cached = await result_cache.get(fingerprint)
            if cached is not None:
                return CalcOutcome(
                    payload=cached,
                    kpi_summary=_kpi_summary(cached),
                    params_hash=fingerprint,
                    duration_ms=0,
                    warnings=warnings,
                )

        payload, duration_ms = compute_payload(params, engine_options, warnings)

        kpi_summary = _kpi_summary(payload)
        server_kpis = _server_kpi_decimals(payload)
        deviation, deviation_detail = compare_with_client(server_kpis, client_kpis)
        if deviation is not None and D(deviation) > CLIENT_TOLERANCE:
            payload.setdefault("warnings", []).append(
                f"前端预算结果与后端权威结果最大相对偏差 {deviation}，超过容差 "
                f"{dec_str(CLIENT_TOLERANCE)}，页面已按后端结果刷新。"
            )

        record: Optional[CalcResult] = None
        if persist and scenario_id is not None:
            record = await self.results.create(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                scenario_version=scenario_version,
                created_by=user_id,
                params=to_jsonable(params_to_dict(params)),
                payload=payload,
                kpi_summary=kpi_summary,
                params_hash=fingerprint,
                engine_version=ENGINE_VERSION,
                formula_spec_version=FORMULA_SPEC_VERSION,
                duration_ms=duration_ms,
                client_deviation=deviation,
            )
            cashflow_rows = payload.get("financials", {}).get("cashflows", [])
            await self.cashflows.bulk_insert(
                tenant_id=tenant_id, result_id=record.id, rows=cashflow_rows, plan="A"
            )

        if result_cache is not None and not persist:
            await result_cache.set(fingerprint, payload, RESULT_CACHE_DEFAULT_TTL)

        return CalcOutcome(
            payload=payload,
            kpi_summary=kpi_summary,
            params_hash=fingerprint,
            duration_ms=duration_ms,
            warnings=warnings,
            client_deviation=deviation,
            deviation_detail=deviation_detail or None,
            record=record,
        )

    async def get_result(self, tenant_id: int, result_id: int) -> Optional[CalcResult]:
        """读取历史结果。"""
        return await self.results.get(tenant_id, result_id)

    async def latest_for_scenario(
        self, tenant_id: int, scenario_id: int
    ) -> Optional[CalcResult]:
        """读取方案最近一次结果。"""
        return await self.results.latest_for_scenario(tenant_id, scenario_id)


def _kpi_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从载荷抽取扁平 KPI 摘要（值为字符串或 None）。"""
    summary: Dict[str, Any] = {}
    for item in payload.get("kpis", []):
        summary[str(item.get("key"))] = item.get("value")
    unit_cost = payload.get("unit_cost", {})
    summary["cost_per_m_demand"] = unit_cost.get("cost_per_m_demand")
    summary["C_total"] = unit_cost.get("C_total")
    crossover = payload.get("crossover") or {}
    summary["crossover_count"] = len(crossover.get("crossovers", []))
    return summary


def _server_kpi_decimals(payload: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    """把载荷中的字符串 KPI 还原为 Decimal（供偏差比对）。"""
    result: Dict[str, Optional[Decimal]] = {}
    for item in payload.get("kpis", []):
        key = str(item.get("key"))
        value = item.get("value")
        if value is None or item.get("kind") == "text":
            result[key] = None
            continue
        try:
            result[key] = D(value)
        except (InvalidOperation, ValueError):
            result[key] = None
    return result


def kpi_meta(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """抽取 KPI 元信息（对比页表头）。"""
    return [
        {
            "key": item.get("key"),
            "label": item.get("label"),
            "unit": item.get("unit"),
            "kind": item.get("kind"),
            "formula_id": item.get("formula_id"),
        }
        for item in payload.get("kpis", [])
    ]


def flat_kpis(payload: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    """便捷导出：把已 JSON 化载荷的 KPI 还原为 Decimal（用于内部数值分析）。"""
    return _server_kpi_decimals(payload)
