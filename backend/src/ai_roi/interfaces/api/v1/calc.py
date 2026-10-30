"""计算路由（P0 四大能力的后端权威入口）。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import dataclasses

from fastapi import APIRouter, Depends, Query

from ai_roi.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ai_roi.interfaces.api.deps import Ctx, CurrentUser, UoW, require_permission
from ai_roi.interfaces.api.errors import NotFoundError
from ai_roi.infrastructure.db.models.audit import ACTION_SCENARIO_CALC
from ai_roi.infrastructure.redis.cache import get_result_cache
from ai_roi.application.ports import ResultCache
from ai_roi.application.schemas.calc import (
    CalcOptionsIn,
    CalcRequest,
    CalcResultOut,
    CalcSummaryOut,
    CompareItem,
    CompareRequest,
    CompareResponse,
    HardwareRecommendIn,
    MonteCarloRequest,
)
from ai_roi.application.schemas.common import ApiResponse
from ai_roi.application.use_cases.audit_service import AuditService
from ai_roi.application.use_cases.calc_service import CalcService, kpi_meta
from ai_roi.application.use_cases.network_catalog_service import NetworkCatalogService
from ai_roi.application.use_cases.scenario_service import ScenarioService
from ai_roi.domain.calc.codec import params_from_dict, params_to_dict
from ai_roi.domain.calc.decimal_config import D, dec_str
from ai_roi.domain.calc.hardware_recommend import (
    GpuSpec,
    HardwareCandidate,
    HardwareRecommendationResult,
    HardwareRequirement,
    recommend_hardware,
)
from ai_roi.domain.calc.supporting_cost import NetworkCatalogPrices
from ai_roi.domain.calc.hardware_recommend import apply_model_preset
from ai_roi.domain.calc.montecarlo import montecarlo_compute
from ai_roi.infrastructure.db.models.benchmark import BenchmarkModel
from sqlalchemy import select

router = APIRouter(prefix="/calc", tags=["calc"])


@router.post(
    "",
    response_model=ApiResponse[CalcResultOut],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def calculate(
    payload: CalcRequest, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[CalcResultOut]:
    """执行权威计算。

    - `scenario_id` 存在 → 读库参数（除非显式传 `params` 覆盖），结果落库；
    - 仅 `params` → 无状态试算，不落库。
    """
    scenario_service = ScenarioService(uow)
    params_dict = payload.params
    scenario_version = 1
    persist = payload.persist

    if payload.scenario_id is not None:
        scenario = await scenario_service.get_or_404(user.tenant_id, payload.scenario_id)
        scenario_version = int(scenario.version)
        if params_dict is None:
            params_dict = dict(scenario.params or {})
    else:
        persist = False
        if params_dict is None:
            raise NotFoundError("请提供 scenario_id 或 params 之一")

    service = CalcService(uow)
    outcome = await service.calculate(
        tenant_id=user.tenant_id,
        user_id=user.id,
        params_dict=params_dict,
        options=payload.options,
        scenario_id=payload.scenario_id,
        scenario_version=scenario_version,
        persist=persist,
        client_kpis=payload.client_kpis,
    )

    if payload.scenario_id is not None:
        await AuditService(uow).log(
            ctx,
            ACTION_SCENARIO_CALC,
            target_type="scenario",
            target_id=payload.scenario_id,
            detail={
                "result_id": outcome.record.id if outcome.record else None,
                "duration_ms": outcome.duration_ms,
                "client_deviation": outcome.client_deviation,
                "params_hash": outcome.params_hash[:16],
            },
        )

    return ApiResponse.ok(
        CalcResultOut(
            id=outcome.record.id if outcome.record else None,
            scenario_id=payload.scenario_id,
            scenario_version=scenario_version,
            engine_version=str(outcome.payload.get("engine_version", "")),
            formula_spec_version=str(outcome.payload.get("formula_spec_version", "")),
            params_hash=outcome.params_hash,
            duration_ms=outcome.duration_ms,
            payload=outcome.payload,
            client_deviation=outcome.client_deviation,
            created_at=outcome.record.created_at if outcome.record else None,
        )
    )


@router.get("/results/{result_id}", response_model=ApiResponse[CalcResultOut])
async def get_result(
    result_id: int, user: CurrentUser, uow: UoW
) -> ApiResponse[CalcResultOut]:
    """读取历史计算结果。"""
    service = CalcService(uow)
    record = await service.get_result(user.tenant_id, result_id)
    if record is None:
        raise NotFoundError(f"计算结果不存在或无权访问（id={result_id}）")
    return ApiResponse.ok(
        CalcResultOut(
            id=record.id,
            scenario_id=record.scenario_id,
            scenario_version=record.scenario_version,
            engine_version=record.engine_version,
            formula_spec_version=record.formula_spec_version,
            params_hash=record.params_hash,
            duration_ms=record.duration_ms,
            payload=dict(record.payload or {}),
            client_deviation=record.client_deviation,
            created_at=record.created_at,
        )
    )


@router.get(
    "/scenarios/{scenario_id}/latest", response_model=ApiResponse[CalcResultOut]
)
async def latest_result(
    scenario_id: int, user: CurrentUser, uow: UoW
) -> ApiResponse[CalcResultOut]:
    """读取方案最近一次结果（结果页刷新直接命中，免重算）。"""
    service = CalcService(uow)
    record = await service.latest_for_scenario(user.tenant_id, scenario_id)
    if record is None:
        raise NotFoundError("该方案还没有计算记录，请先执行测算")
    return ApiResponse.ok(
        CalcResultOut(
            id=record.id,
            scenario_id=record.scenario_id,
            scenario_version=record.scenario_version,
            engine_version=record.engine_version,
            formula_spec_version=record.formula_spec_version,
            params_hash=record.params_hash,
            duration_ms=record.duration_ms,
            payload=dict(record.payload or {}),
            client_deviation=record.client_deviation,
            created_at=record.created_at,
        )
    )


@router.get(
    "/scenarios/{scenario_id}/history", response_model=ApiResponse[List[CalcSummaryOut]]
)
async def result_history(
    scenario_id: int,
    user: CurrentUser,
    uow: UoW,
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[List[CalcSummaryOut]]:
    """方案的历史结果摘要。"""
    scenario_service = ScenarioService(uow)
    scenario = await scenario_service.get_or_404(user.tenant_id, scenario_id)
    records = await CalcService(uow).results.list_for_scenario(
        user.tenant_id, scenario_id, limit
    )
    return ApiResponse.ok(
        [
            CalcSummaryOut(
                id=item.id,
                scenario_id=item.scenario_id,
                scenario_name=scenario.name,
                kpi_summary=dict(item.kpi_summary or {}),
                engine_version=item.engine_version,
                created_at=item.created_at,
            )
            for item in records
        ]
    )


@router.post(
    "/compare",
    response_model=ApiResponse[CompareResponse],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def compare(
    payload: CompareRequest, user: CurrentUser, uow: UoW
) -> ApiResponse[CompareResponse]:
    """多方案横向对比（对每个方案执行一次无状态权威计算，保证口径同步）。"""
    scenario_service = ScenarioService(uow)
    calc_service = CalcService(uow)
    items: List[CompareItem] = []
    meta: List[Dict[str, Any]] = []

    for scenario_id in payload.scenario_ids:
        scenario = await scenario_service.get_or_404(user.tenant_id, scenario_id)
        outcome = await calc_service.calculate(
            tenant_id=user.tenant_id,
            user_id=user.id,
            params_dict=dict(scenario.params or {}),
            options=payload.options,
            scenario_id=scenario_id,
            scenario_version=int(scenario.version),
            persist=False,
        )
        kpis = list(outcome.payload.get("kpis", []))
        if not meta:
            meta = kpi_meta(outcome.payload)
        items.append(
            CompareItem(
                scenario_id=scenario_id,
                scenario_name=scenario.name,
                kpis=kpis,
                kpi_map=outcome.kpi_summary,
                warnings=[str(item) for item in outcome.payload.get("warnings", [])],
            )
        )

    return ApiResponse.ok(CompareResponse(items=items, kpi_meta=meta))


@router.post(
    "/preview",
    response_model=ApiResponse[Dict[str, Any]],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def preview(
    params: Dict[str, Any],
    user: CurrentUser,
    uow: UoW,
    options: CalcOptionsIn = Depends(),
    cache: ResultCache = Depends(get_result_cache),
) -> ApiResponse[Dict[str, Any]]:
    """无状态试算（向导「实时预览」的后端校验通道，不落库、不写审计）。

    同参数指纹命中结果缓存时跳过引擎重算（引擎为纯函数，同键必同值，
    缓存仅省 CPU，不改变任何计算结果）。
    """
    service = CalcService(uow)
    outcome = await service.calculate(
        tenant_id=user.tenant_id,
        user_id=user.id,
        params_dict=params,
        options=options,
        scenario_id=None,
        persist=False,
        result_cache=cache,
    )
    return ApiResponse.ok(outcome.payload)


@router.post(
    "/montecarlo",
    response_model=ApiResponse[Dict[str, Any]],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def montecarlo(
    payload: MonteCarloRequest, user: CurrentUser, uow: UoW
) -> ApiResponse[Dict[str, Any]]:
    """蒙特卡洛模拟（P2-4 / REQ-18）：对关键变量随机抽样，复用 financials 口径统计 NPV/IRR 分布。

    - `scenario_id` 存在 → 读库参数模拟（不落库）；仅 `params` → 无状态模拟。
    """
    params_dict = payload.params
    if payload.scenario_id is not None:
        scenario = await ScenarioService(uow).get_or_404(user.tenant_id, payload.scenario_id)
        if params_dict is None:
            params_dict = dict(scenario.params or {})
    if params_dict is None:
        raise NotFoundError("请提供 scenario_id 或 params 之一")

    params = params_from_dict(params_dict)
    result = montecarlo_compute(params, n=payload.n, seed=payload.seed)
    return ApiResponse.ok(dataclasses.asdict(result))


def _build_requirement(payload: HardwareRecommendIn) -> HardwareRequirement:
    """把请求 DTO（字符串 Decimal）转引擎需求对象；非法数值容错回退默认（与全站宽容风格一致）。"""

    def _dec(raw: Optional[str], fallback: Optional[Decimal] = None) -> Optional[Decimal]:
        if raw is None or raw == "":
            return fallback
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return fallback

    base = params_from_dict(payload.base_params) if payload.base_params else None
    return HardwareRequirement(
        T_eff_target=_dec(payload.T_eff_target),
        D_eq_target=_dec(payload.D_eq_target),
        U_target=_dec(payload.U_target, D("0.7")) or D("0.7"),
        growth_headroom=_dec(payload.growth_headroom, D("0.2")) or D("0.2"),
        M_param=_dec(payload.M_param, D(70)) or D(70),
        quant=payload.quant or "FP8",
        Ctx=_dec(payload.Ctx, D(8192)) or D(8192),
        Mem_w_override=_dec(payload.Mem_w_override),
        SLA_ttft=_dec(payload.SLA_ttft),
        SLA_tpot=_dec(payload.SLA_tpot),
        CN_cfg=payload.CN_cfg or "none",
        capex_budget=_dec(payload.capex_budget),
        power_budget_kw=_dec(payload.power_budget_kw),
        objective=payload.objective or "balanced",
        fabric=(payload.fabric or "").strip(),
        extra_nodes=max(0, int(payload.extra_nodes or 0)),
        port_speed=payload.port_speed,
        spine_port_speed=payload.spine_port_speed,
        base_params=base,
    )


async def _apply_model_preset(
    req: HardwareRequirement, model_code: Optional[str], tenant_id: Optional[int], uow: SqlAlchemyUnitOfWork
) -> Tuple[HardwareRequirement, List[str]]:
    """方案构建向导「选模型」：按基准库模型 code 填充 M_param / 显存快照。

    查询范围同时覆盖平台内置（tenant_id IS NULL）与当前租户自建模型；
    当两者存在同 code 时，租户自建优先（order_by tenant_id IS NULL DESC）。
    """
    if not model_code:
        return req, []
    row = (
        (
            await uow.session.execute(
                select(BenchmarkModel)
                .where(
                    BenchmarkModel.code == model_code,
                    (BenchmarkModel.tenant_id.is_(None)) | (BenchmarkModel.tenant_id == tenant_id),
                )
                .order_by(BenchmarkModel.tenant_id.is_(None).desc())
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFoundError(f"基准库中不存在模型 code={model_code}")
    return apply_model_preset(req, D(str(row.params_b)))


def _gpu_dict(gpu: GpuSpec) -> Dict[str, Any]:
    """候选卡规格序列化（Decimal → 字符串）。"""
    return {
        "id": gpu.id,
        "name": gpu.name,
        "vendor": gpu.vendor,
        "mem_gb": dec_str(gpu.mem_gb),
        "tdp_w": dec_str(gpu.tdp_w),
        "price_per_card": dec_str(gpu.price_per_card),
        "perf_index": dec_str(gpu.perf_index),
        "max_cards_per_node": dec_str(gpu.max_cards_per_node),
        "domestic": gpu.domestic,
        "supported_quant": list(gpu.supported_quant),
        "fabric_recommended": gpu.fabric_recommended,
        "notes": gpu.notes,
    }


def _candidate_dict(candidate: HardwareCandidate) -> Dict[str, Any]:
    """候选结果序列化：完整 `ScenarioParams`（params_to_dict）供前端一键回填表单。"""
    kpis: Dict[str, Any] = {}
    for key, value in candidate.kpis.items():
        kpis[key] = dec_str(value) if isinstance(value, Decimal) else value
    storage = candidate.storage
    network = candidate.network
    return {
        "gpu": _gpu_dict(candidate.gpu),
        "N_gpu": dec_str(candidate.N_gpu),
        "feasible": candidate.feasible,
        "T_eff_achieved": dec_str(candidate.T_eff_achieved),
        "mem_required_gb": dec_str(candidate.mem_required_gb),
        "capex": dec_str(candidate.capex),
        "power_kw": dec_str(candidate.power_kw),
        "over_budget": candidate.over_budget,
        "score": dec_str(candidate.score),
        "params": params_to_dict(candidate.params) if candidate.params is not None else None,
        "kpis": kpis,
        "assumptions": candidate.assumptions,
        "warnings": candidate.warnings,
        "node_count": candidate.node_count,
        "supporting_capex": dec_str(candidate.supporting_capex),
        "supporting_power_kw": dec_str(candidate.supporting_power_kw),
        "storage": (
            {
                "capacity_gb": dec_str(storage.capacity_gb),
                "weights_gb": dec_str(storage.weights_gb),
                "kv_cache_gb": dec_str(storage.kv_cache_gb),
                "dataset_gb": dec_str(storage.dataset_gb),
                "log_snapshot_gb": dec_str(storage.log_snapshot_gb),
                "capex": dec_str(storage.capex),
                "monthly": dec_str(storage.monthly),
                "power_kw": dec_str(storage.power_kw),
            }
            if storage is not None
            else None
        ),
        "network": (
            {
                "node_count": network.node_count,
                "fabric": network.fabric,
                "port_speed_gbps": dec_str(network.port_speed_gbps),
                "spine_port_speed_gbps": dec_str(network.spine_port_speed_gbps),
                "switches": network.switches,
                "storage_switch_qty": network.storage_switch_qty,
                "mgmt_switch_qty": network.mgmt_switch_qty,
                "nic_qty": network.nic_qty,
                "optics_400g_qty": network.optics_400g_qty,
                "optics_100g_qty": network.optics_100g_qty,
                "aoc_qty": network.aoc_qty,
                "mpo_qty": network.mpo_qty,
                "capex": dec_str(network.capex),
                "monthly": dec_str(network.monthly),
                "power_kw": dec_str(network.power_kw),
                "interconnect_loss": dec_str(network.interconnect_loss),
            }
            if network is not None
            else None
        ),
        "hardware_bom": _bom_dict(candidate.hardware_bom),
    }


def _bom_dict(bom: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """BOM 序列化：所有 Decimal 转字符串。"""
    if bom is None:
        return None

    def dec(v: Any) -> Any:
        return dec_str(v) if isinstance(v, Decimal) else v

    out: Dict[str, Any] = {}
    for key, value in bom.items():
        if isinstance(value, dict):
            out[key] = {k: dec(v) for k, v in value.items()}
        else:
            out[key] = dec(value)
    return out


def _recommendation_dict(result: HardwareRecommendationResult) -> Dict[str, Any]:
    """推荐结果序列化。"""
    return {
        "target_tok_s": dec_str(result.target_tok_s),
        "mem_required_gb": dec_str(result.mem_required_gb),
        "candidates": [_candidate_dict(c) for c in result.candidates],
        "recommended": [_candidate_dict(c) for c in result.recommended],
        "notes": result.notes,
    }


@router.post(
    "/recommend",
    response_model=ApiResponse[Dict[str, Any]],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def recommend_hardware_api(
    payload: HardwareRecommendIn, user: CurrentUser, uow: UoW
) -> ApiResponse[Dict[str, Any]]:
    """硬件反选推荐（架构 §3.13）：按需求（吞吐/需求量/SLA/模型/合规/预算）反推
    GPU 候选配置并生成完整测算方案（与手工配置同源同口径），按目标函数打分排序。

    - 无状态，不落库、不写审计（结果由前端一键回填表单后走既有保存流程）。
    """
    req = _build_requirement(payload)
    req, model_notes = await _apply_model_preset(req, payload.model_code, user.tenant_id, uow)
    catalog_prices = await NetworkCatalogService(uow).resolve_prices(user.tenant_id)
    catalog = _catalog_from_prices(catalog_prices)
    result = recommend_hardware(req, top_n=payload.top_n, catalog=catalog)
    if model_notes:
        result = dataclasses.replace(result, notes=list(result.notes) + model_notes)
    return ApiResponse.ok(_recommendation_dict(result))


def _catalog_from_prices(
    prices: Dict[str, Dict[str, Any]],
) -> Optional[NetworkCatalogPrices]:
    """配件库价格/规格 → 引擎目录覆盖（仅覆盖有库内数据的类别，缺省回落内置常量）。

    除单价外，还解析交换机类目的 `spec.ports` / `spec.speed`（真实机型端口数与速率），
    驱动拓扑推导（如 MQM9790-NS2F 录入 64 口 / 400G，则 Leaf/Spine 按 64 端口而非硬编码 32）。
    """
    if not prices:
        return None

    def price_of(category: str) -> Optional[Decimal]:
        v = prices.get(category, {}).get("price_cny")
        return D(v) if v is not None and v != "" else None

    def spec_of(category: str) -> Dict[str, Any]:
        return prices.get(category, {}).get("spec") or {}

    def int_of(val: Any) -> Optional[int]:
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    fields: Dict[str, Any] = {}
    price_mapping = {
        "compute_switch_ib": "compute_switch_ib_capex",
        "compute_switch_roce": "compute_switch_roce_capex",
        "storage_switch": "storage_switch_capex",
        "mgmt_switch": "mgmt_switch_capex",
        "nic_ib": "nic_ib_capex",
        "nic_roce": "nic_roce_capex",
        "optics_400g": "optics_400g_capex",
        "optics_100g": "optics_100g_capex",
        "aoc_cable": "aoc_capex",
        "mpo_cable": "mpo_capex",
        "storage_per_gb": "storage_per_gb",
        "storage_monthly_per_gb": "storage_monthly_per_gb",
    }
    for category, field_name in price_mapping.items():
        v = price_of(category)
        if v is not None:
            fields[field_name] = v
    for cat in ("compute_switch_ib", "compute_switch_roce"):
        spec = spec_of(cat)
        ports = int_of(spec.get("ports"))
        speed = int_of(spec.get("speed"))
        if ports is not None and fields.get("compute_switch_ports") is None:
            fields["compute_switch_ports"] = ports
        if speed is not None and fields.get("compute_switch_speed") is None:
            fields["compute_switch_speed"] = speed
    return NetworkCatalogPrices(**fields) if fields else None
