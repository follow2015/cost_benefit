"""基准库路由。

- 读取（P0）：bundle + 四类列表，平台内置与租户自建一并返回；
- 写入（P1，REQ-13）：四类基准的 `POST / PUT / DELETE`，
  需 `benchmark:write` 权限（owner / 超管），并受 RLS 与服务层归属校验双重约束；
  写操作全部落审计（who / what / when / before-after 摘要）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ai_roi.interfaces.api.deps import Ctx, CurrentUser, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import (
    ACTION_BENCHMARK_CREATE,
    ACTION_BENCHMARK_DELETE,
    ACTION_BENCHMARK_PUBLISH,
    ACTION_BENCHMARK_ROLLBACK,
    ACTION_BENCHMARK_UPDATE,
)
from ai_roi.application.schemas.benchmark import (
    ApiPriceCreate,
    ApiPriceOut,
    ApiPriceUpdate,
    BenchmarkBundleOut,
    CloudPriceCreate,
    CloudPriceOut,
    CloudPriceUpdate,
    GpuCreate,
    GpuOut,
    GpuUpdate,
    BenchmarkPublishOut,
    BenchmarkPublishSummaryOut,
    AuthorityApplyIn,
    BenchmarkRollbackItem,
    BenchmarkRollbackOut,
    MarketApplyIn,
    ModelCreate,
    ModelOut,
    ModelUpdate,
)
from ai_roi.application.schemas.common import ApiResponse, OkData
from ai_roi.application.use_cases.inferencex_sync_service import InferencexSyncService
from ai_roi.application.use_cases.market_sync_service import (
    KIND_CLOUD,
    KIND_GPU,
    MarketSyncService,
)
from ai_roi.domain.inferencex import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
)
from ai_roi.domain.errors import NotFoundError
from ai_roi.domain.calc.decimal_config import D, dec_str
from ai_roi.application.use_cases.audit_service import AuditService
from ai_roi.application.use_cases.benchmark_service import BenchmarkService
from ai_roi.infrastructure.collectors.inferencex import InferencexClient
from ai_roi.shared.config import settings
from ai_roi.infrastructure.repositories.benchmark_mappers import (
    api_out,
    cloud_out,
    entity_summary,
    gpu_out,
    model_out,
)

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

_WRITE = Depends(require_permission("benchmark:write"))


@router.get("", response_model=ApiResponse[BenchmarkBundleOut])
async def get_bundle(
    user: CurrentUser, uow: UoW
) -> ApiResponse[BenchmarkBundleOut]:
    """一次性返回全部基准（GPU/模型/云价/API 价）。"""
    service = BenchmarkService(uow)
    return ApiResponse.ok(await service.bundle(user.tenant_id))


@router.get("/gpus", response_model=ApiResponse[List[GpuOut]])
async def list_gpus(user: CurrentUser, uow: UoW) -> ApiResponse[List[GpuOut]]:
    """GPU 基准列表。"""
    bundle = await BenchmarkService(uow).bundle(user.tenant_id)
    return ApiResponse.ok(bundle.gpus)


@router.get("/models", response_model=ApiResponse[List[ModelOut]])
async def list_models(user: CurrentUser, uow: UoW) -> ApiResponse[List[ModelOut]]:
    """模型基准列表。"""
    bundle = await BenchmarkService(uow).bundle(user.tenant_id)
    return ApiResponse.ok(bundle.models)


@router.get("/cloud-prices", response_model=ApiResponse[List[CloudPriceOut]])
async def list_cloud_prices(
    user: CurrentUser, uow: UoW
) -> ApiResponse[List[CloudPriceOut]]:
    """云租赁价基准列表。"""
    bundle = await BenchmarkService(uow).bundle(user.tenant_id)
    return ApiResponse.ok(bundle.cloud_prices)


@router.get("/api-prices", response_model=ApiResponse[List[ApiPriceOut]])
async def list_api_prices(
    user: CurrentUser, uow: UoW
) -> ApiResponse[List[ApiPriceOut]]:
    """第三方 API 价基准列表。"""
    bundle = await BenchmarkService(uow).bundle(user.tenant_id)
    return ApiResponse.ok(bundle.api_prices)


async def _audit(
    uow: UoW, ctx: Ctx, action: str, detail: Dict[str, Any], row_id: Optional[int]
) -> None:
    """写一条基准库审计。"""
    await AuditService(uow).log(
        ctx,
        action,
        target_type="benchmark",
        target_id=row_id,
        detail=detail,
    )


@router.post("/gpus", response_model=ApiResponse[GpuOut], dependencies=[_WRITE])
async def create_gpu(
    payload: GpuCreate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[GpuOut]:
    """新增 GPU 基准。"""
    service = BenchmarkService(uow)
    row = await service.create(
        "gpus", user.tenant_id, payload.model_dump(), is_super=user.is_super
    )
    await _audit(uow, ctx, ACTION_BENCHMARK_CREATE, entity_summary("gpus", row), row.id)
    return ApiResponse.ok(gpu_out(row), "已新增 GPU 基准")


@router.put("/gpus/{row_id}", response_model=ApiResponse[GpuOut], dependencies=[_WRITE])
async def update_gpu(
    row_id: int, payload: GpuUpdate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[GpuOut]:
    """更新 GPU 基准（仅提交的字段生效，版本号自增）。"""
    service = BenchmarkService(uow)
    row = await service.update(
        "gpus",
        user.tenant_id,
        row_id,
        payload.model_dump(exclude_unset=True),
        is_super=user.is_super,
    )
    await _audit(uow, ctx, ACTION_BENCHMARK_UPDATE, entity_summary("gpus", row), row.id)
    return ApiResponse.ok(gpu_out(row), f"已更新至 v{row.version}")


@router.delete(
    "/gpus/{row_id}", response_model=ApiResponse[OkData], dependencies=[_WRITE]
)
async def delete_gpu(
    row_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除 GPU 基准。"""
    service = BenchmarkService(uow)
    summary = await service.delete("gpus", user.tenant_id, row_id, is_super=user.is_super)
    await _audit(uow, ctx, ACTION_BENCHMARK_DELETE, summary, row_id)
    return ApiResponse.ok(OkData(ok=True), "已删除 GPU 基准")


@router.post("/models", response_model=ApiResponse[ModelOut], dependencies=[_WRITE])
async def create_model(
    payload: ModelCreate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[ModelOut]:
    """新增模型基准。"""
    service = BenchmarkService(uow)
    row = await service.create(
        "models", user.tenant_id, payload.model_dump(), is_super=user.is_super
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_CREATE, entity_summary("models", row), row.id
    )
    return ApiResponse.ok(model_out(row), "已新增模型基准")


@router.put("/models/{row_id}", response_model=ApiResponse[ModelOut], dependencies=[_WRITE])
async def update_model(
    row_id: int, payload: ModelUpdate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[ModelOut]:
    """更新模型基准。"""
    service = BenchmarkService(uow)
    row = await service.update(
        "models",
        user.tenant_id,
        row_id,
        payload.model_dump(exclude_unset=True),
        is_super=user.is_super,
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_UPDATE, entity_summary("models", row), row.id
    )
    return ApiResponse.ok(model_out(row), f"已更新至 v{row.version}")


@router.delete(
    "/models/{row_id}", response_model=ApiResponse[OkData], dependencies=[_WRITE]
)
async def delete_model(
    row_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除模型基准。"""
    service = BenchmarkService(uow)
    summary = await service.delete("models", user.tenant_id, row_id, is_super=user.is_super)
    await _audit(uow, ctx, ACTION_BENCHMARK_DELETE, summary, row_id)
    return ApiResponse.ok(OkData(ok=True), "已删除模型基准")


@router.post(
    "/cloud-prices", response_model=ApiResponse[CloudPriceOut], dependencies=[_WRITE]
)
async def create_cloud_price(
    payload: CloudPriceCreate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[CloudPriceOut]:
    """新增云租赁价基准。"""
    service = BenchmarkService(uow)
    row = await service.create(
        "cloud-prices", user.tenant_id, payload.model_dump(), is_super=user.is_super
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_CREATE, entity_summary("cloud-prices", row), row.id
    )
    return ApiResponse.ok(cloud_out(row), "已新增云价基准")


@router.put(
    "/cloud-prices/{row_id}",
    response_model=ApiResponse[CloudPriceOut],
    dependencies=[_WRITE],
)
async def update_cloud_price(
    row_id: int,
    payload: CloudPriceUpdate,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
) -> ApiResponse[CloudPriceOut]:
    """更新云租赁价基准。"""
    service = BenchmarkService(uow)
    row = await service.update(
        "cloud-prices",
        user.tenant_id,
        row_id,
        payload.model_dump(exclude_unset=True),
        is_super=user.is_super,
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_UPDATE, entity_summary("cloud-prices", row), row.id
    )
    return ApiResponse.ok(cloud_out(row), f"已更新至 v{row.version}")


@router.delete(
    "/cloud-prices/{row_id}", response_model=ApiResponse[OkData], dependencies=[_WRITE]
)
async def delete_cloud_price(
    row_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除云租赁价基准。"""
    service = BenchmarkService(uow)
    summary = await service.delete(
        "cloud-prices", user.tenant_id, row_id, is_super=user.is_super
    )
    await _audit(uow, ctx, ACTION_BENCHMARK_DELETE, summary, row_id)
    return ApiResponse.ok(OkData(ok=True), "已删除云价基准")


@router.post(
    "/api-prices", response_model=ApiResponse[ApiPriceOut], dependencies=[_WRITE]
)
async def create_api_price(
    payload: ApiPriceCreate, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[ApiPriceOut]:
    """新增第三方 API 价基准。"""
    service = BenchmarkService(uow)
    row = await service.create(
        "api-prices", user.tenant_id, payload.model_dump(), is_super=user.is_super
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_CREATE, entity_summary("api-prices", row), row.id
    )
    return ApiResponse.ok(api_out(row), "已新增 API 价基准")


@router.put(
    "/api-prices/{row_id}",
    response_model=ApiResponse[ApiPriceOut],
    dependencies=[_WRITE],
)
async def update_api_price(
    row_id: int,
    payload: ApiPriceUpdate,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
) -> ApiResponse[ApiPriceOut]:
    """更新第三方 API 价基准。"""
    service = BenchmarkService(uow)
    row = await service.update(
        "api-prices",
        user.tenant_id,
        row_id,
        payload.model_dump(exclude_unset=True),
        is_super=user.is_super,
    )
    await _audit(
        uow, ctx, ACTION_BENCHMARK_UPDATE, entity_summary("api-prices", row), row.id
    )
    return ApiResponse.ok(api_out(row), f"已更新至 v{row.version}")


@router.delete(
    "/api-prices/{row_id}", response_model=ApiResponse[OkData], dependencies=[_WRITE]
)
async def delete_api_price(
    row_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[OkData]:
    """删除第三方 API 价基准。"""
    service = BenchmarkService(uow)
    summary = await service.delete(
        "api-prices", user.tenant_id, row_id, is_super=user.is_super
    )
    await _audit(uow, ctx, ACTION_BENCHMARK_DELETE, summary, row_id)
    return ApiResponse.ok(OkData(ok=True), "已删除 API 价基准")


@router.get("/cost-benchmark", response_model=ApiResponse[Dict[str, Any]])
async def get_cost_benchmark(
    user: CurrentUser,
    uow: UoW,
    model_code: str = Query(..., description="模型代号，如 qwen-3.5-397b-a17b"),
    hardware_code: str = Query(..., description="硬件代号，如 GB300_NVL72"),
    scenario: str = Query("AgentX", description="场景：8K/1K | AgentX"),
    fx: str = Query("7.2", description="CNY/USD 汇率（S-3 标注，运行期可按实时汇率覆盖）"),
) -> ApiResponse[Dict[str, Any]]:
    """S-3 只读：按「模型×硬件×场景」解析 InferenceX 市场成本标杆（元/Mtok）。

    用于一键校准 `PricingParams.cost_benchmark`（C-1 的市场公允成本口径）。
    口径：meta.inferencex_cost_usd_per_mtok[hardware][scenario] × fx → CNY/Mtok。
    无需写权限；无匹配返回 found=False（提示先 seed）。
    """
    try:
        fx_decimal = D(fx)
    except (Exception,):  # noqa: BLE001
        return ApiResponse.ok(
            {
                "found": False,
                "model_code": model_code,
                "hardware_code": hardware_code,
                "scenario": scenario,
                "cost_benchmark_cny_per_mtok": None,
                "currency": "CNY",
                "message": f"汇率参数非法：{fx!r}",
            }
        )
    value = await BenchmarkService(uow).cost_benchmark(
        model_code, hardware_code, scenario, fx_decimal, user.tenant_id
    )
    if value is None:
        return ApiResponse.ok(
            {
                "found": False,
                "model_code": model_code,
                "hardware_code": hardware_code,
                "scenario": scenario,
                "cost_benchmark_cny_per_mtok": None,
                "currency": "CNY",
                "message": "基准库中无该组合的成本数据（请先运行 python -m scripts.seed_inferencex）",
            }
        )
    return ApiResponse.ok(
        {
            "found": True,
            "model_code": model_code,
            "hardware_code": hardware_code,
            "scenario": scenario,
            "cost_benchmark_cny_per_mtok": dec_str(value),
            "currency": "CNY",
            "fx_usd_cny": dec_str(fx_decimal),
            "source": "InferenceX+SemiAnalysis",
        }
    )


@router.post(
    "/sync", response_model=ApiResponse[Dict[str, Any]], dependencies=[_WRITE]
)
async def sync_from_inferencex(
    user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[Dict[str, Any]]:
    """手动触发一次 InferenceX 基准采集（强制，忽略 7 天周期）。

    采集失败仍返回 200：这是「任务结果」不是「请求失败」——前端要能拿到
    status/error 并提示「沿用上次数据」。真正不可恢复的异常（DB 故障）才会走到
    全局 500。
    """
    service = _sync_service(uow)
    outcome = await service.run(
        trigger=TRIGGER_MANUAL,
        force=True,
        tenant_id=user.tenant_id,
        actor_id=ctx.user_id,
        actor_email=ctx.user_email,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
    )
    return ApiResponse.ok(outcome.to_dict(), _sync_message(outcome))


@router.get("/sync-status", response_model=ApiResponse[Dict[str, Any]])
async def get_sync_status(user: CurrentUser, uow: UoW) -> ApiResponse[Dict[str, Any]]:
    """采集状态：数据源、周期、上次结果、下次计划时间（无需写权限）。"""
    return ApiResponse.ok(await _sync_service(uow).status())


@router.get("/model-coverage", response_model=ApiResponse[Dict[str, Any]])
async def model_coverage(user: CurrentUser, uow: UoW) -> ApiResponse[Dict[str, Any]]:
    """模型基准的逐行采集覆盖：已采到 / 上游无值 / 上游不测 / 未判定（纯读库）。

    这个接口存在的唯一理由是把**两件后果完全不同的事**分开：

    - 「本次缺数据」：上游在测这个模型，只是这一轮没给可用成本值 → 等下一轮；
    - 「上游不测」：上游的模型清单里没有它 → 换任何数据源都一样，只能人工维护。

    早前界面上 18 条空值长得一模一样，用户无法判断该不该等。
    """
    return ApiResponse.ok(await _sync_service(uow).model_coverage(user.tenant_id))


def _sync_service(uow: Any) -> InferencexSyncService:
    """装配采集用例（客户端只在需要时建，status 查询不发请求）。"""
    base_url = settings.INFERENCEX_BASE_URL
    return InferencexSyncService(
        uow,
        InferencexClient(base_url),
        fx_usd_cny=D(settings.inferencex_fx),
        interval_days=settings.INFERENCEX_SYNC_INTERVAL_DAYS,
        base_url=base_url,
    )


def _sync_message(outcome: Any) -> str:
    """把采集结果翻成一句人话（前端直接 toast）。"""
    if outcome.status == STATUS_SUCCESS:
        return (
            f"采集完成：{outcome.matched_count} 个模型、"
            f"{outcome.point_count} 个成本点（新增 {outcome.added} / 更新 {outcome.updated}）"
        )
    if outcome.status == STATUS_PARTIAL:
        return f"采集部分完成：{outcome.error}"
    if outcome.status == STATUS_FAILED:
        return f"采集失败：{outcome.error}"
    return outcome.error or "已跳过"


@router.post(
    "/publish", response_model=ApiResponse[BenchmarkPublishOut], dependencies=[_WRITE]
)
async def publish_benchmarks(
    user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[BenchmarkPublishOut]:
    """发布当前基准库版本（冻结全量快照，供后续回滚）。

    快照直接落在审计 `detail.snapshot` 里：这是唯一「整库 JSON」入审计的场景，
    因此绕开 `AuditService._truncate`（截断会破坏可回滚性），改走仓储原样写入。
    """
    service = BenchmarkService(uow)
    snapshot = await service.snapshot(user.tenant_id)
    counts = {key: len(rows) for key, rows in snapshot.items()}
    entry = await uow.audit.write(
        tenant_id=user.tenant_id,
        action=ACTION_BENCHMARK_PUBLISH,
        actor_id=ctx.user_id,
        actor_email=ctx.user_email,
        target_type="benchmark_library",
        detail={"counts": counts, "snapshot": snapshot},
        ip=ctx.ip,
        user_agent=ctx.user_agent[:512],
    )
    return ApiResponse.ok(
        BenchmarkPublishOut(publish_id=entry.id, counts=counts),
        f"已发布基准库版本 #{entry.id}（{sum(counts.values())} 条）",
    )


@router.get(
    "/publishes", response_model=ApiResponse[List[BenchmarkPublishSummaryOut]]
)
async def list_benchmark_publishes(
    user: CurrentUser, uow: UoW, limit: int = Query(20, ge=1, le=100)
) -> ApiResponse[List[BenchmarkPublishSummaryOut]]:
    """发布历史（倒序；不含快照正文）。"""
    entries = await uow.audit.list_by_action(
        user.tenant_id, ACTION_BENCHMARK_PUBLISH, limit
    )
    items = [
        BenchmarkPublishSummaryOut(
            publish_id=entry.id,
            published_at=entry.created_at,
            actor_email=entry.actor_email,
            counts=(entry.detail or {}).get("counts", {}),
        )
        for entry in entries
    ]
    return ApiResponse.ok(items)


@router.post(
    "/publishes/{publish_id}/rollback",
    response_model=ApiResponse[BenchmarkRollbackOut],
    dependencies=[_WRITE],
)
async def rollback_benchmarks(
    publish_id: int, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[BenchmarkRollbackOut]:
    """把基准库回滚到指定发布版本（只提交差异字段，行版本自增）。"""
    entry = await uow.audit.get(user.tenant_id, publish_id)
    if entry is None or entry.action != ACTION_BENCHMARK_PUBLISH:
        raise NotFoundError(f"发布版本不存在或无权访问（id={publish_id}）")
    snapshot = (entry.detail or {}).get("snapshot") or {}
    result = await BenchmarkService(uow).rollback(
        user.tenant_id, snapshot, is_super=user.is_super
    )
    skipped = result["skipped"]
    reasons: Dict[str, int] = {}
    for item in skipped:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    await _audit(
        uow,
        ctx,
        ACTION_BENCHMARK_ROLLBACK,
        {
            "source_publish_id": publish_id,
            "updated": result["updated"],
            "unchanged": result["unchanged"],
            "skipped_count": len(skipped),
            "skip_reasons": reasons,
        },
        None,
    )
    reason_text = "；".join(f"{reason}（{count} 条）" for reason, count in reasons.items())
    message = (
        f"已回滚 {len(result['updated'])} 条，无差异 {result['unchanged']} 条"
        + (f"；跳过 {len(skipped)} 条：{reason_text}" if skipped else "")
    )
    return ApiResponse.ok(
        BenchmarkRollbackOut(
            source_publish_id=publish_id,
            updated=[BenchmarkRollbackItem(**item) for item in result["updated"]],
            unchanged=result["unchanged"],
            skipped=skipped,
        ),
        message,
    )


def _authority_service(uow: UoW) -> Any:
    """装配权威同步用例（三源客户端 + 当前汇率）。"""
    from ai_roi.application.use_cases.benchmark_authority_service import (
        BenchmarkAuthorityService,
    )
    from ai_roi.infrastructure.collectors.benchmark_sources import AuthorityClient

    return BenchmarkAuthorityService(
        uow, AuthorityClient(), current_fx=D(settings.FX_USD_CNY)
    )


@router.get("/authority-preview", response_model=ApiResponse[Dict[str, Any]])
async def authority_preview(user: CurrentUser, uow: UoW) -> ApiResponse[Dict[str, Any]]:
    """拉取多源权威数据并与库内逐条比对（只读，不写库）。

    返回每条的价格现状、各源观测、投票结论（多源一致 / 单源 / 冲突 / 无数据）
    以及建议值。前端据此展示差异并让用户勾选应用——**冲突项不会被自动采信**。
    """
    result = await _authority_service(uow).preview()
    summary = result.summary()
    ok_sources = sum(1 for s in result.sources if s["ok"])
    return ApiResponse.ok(
        result.to_dict(),
        f"已比对 {summary['total']} 条 API 价："
        f"多源一致 {summary['consensus']} / 单源 {summary['single_source']} "
        f"/ 冲突 {summary['conflict']} / 无数据 {summary['no_data']}"
        f"（{ok_sources}/3 源可用）",
    )


@router.get("/authority-status", response_model=ApiResponse[Dict[str, Any]])
async def authority_status(user: CurrentUser, uow: UoW) -> ApiResponse[Dict[str, Any]]:
    """权威同步现状：覆盖条数、上次同步时间、生效日、三源清单。

    纯读本库、不访问外网——按钮旁边要即时回答「上次同步到什么时候」，
    不能让它跟着一次 20 秒的三源下载一起等。
    """
    from ai_roi.infrastructure.collectors.benchmark_sources import (
        SOURCE_LITELLM,
        SOURCE_LABELS,
        SOURCE_MODELSDEV,
        SOURCE_OPENROUTER,
        URL_LITELLM,
        URL_MODELSDEV,
        URL_OPENROUTER,
    )

    data = await _authority_service(uow).status()
    data["sources"] = [
        {"source": SOURCE_LITELLM, "label": SOURCE_LABELS[SOURCE_LITELLM], "url": URL_LITELLM},
        {"source": SOURCE_MODELSDEV, "label": SOURCE_LABELS[SOURCE_MODELSDEV], "url": URL_MODELSDEV},
        {"source": SOURCE_OPENROUTER, "label": SOURCE_LABELS[SOURCE_OPENROUTER], "url": URL_OPENROUTER},
    ]
    message = (
        f"API 价共 {data['total']} 条：权威同步 {data['from_authority']} 条 / 人工 {data['manual']} 条"
        if data["total"]
        else "基准库暂无 API 价条目"
    )
    return ApiResponse.ok(data, message)


@router.post(
    "/authority-apply", response_model=ApiResponse[Dict[str, Any]], dependencies=[_WRITE]
)
async def authority_apply(
    payload: AuthorityApplyIn, user: CurrentUser, uow: UoW, ctx: Ctx
) -> ApiResponse[Dict[str, Any]]:
    """应用用户确认的权威价（逐条写审计快照，可回滚）。"""
    if not payload.items:
        return ApiResponse.ok({"applied": [], "skipped": [], "applied_count": 0}, "未选择任何条目")
    fx = D(payload.fx_usd_cny) if payload.fx_usd_cny else None
    result = await _authority_service(uow).apply(
        [item.model_dump() for item in payload.items],
        fx_usd_cny=fx,
        tenant_id=user.tenant_id,
        actor_id=ctx.user_id,
        actor_email=ctx.user_email,
    )
    msg = f"已应用 {result['applied_count']} 条（汇率 {result['fx_usd_cny']}）"
    if result["skipped"]:
        msg += f"；跳过 {len(result['skipped'])} 条"
    return ApiResponse.ok(result, msg)


_MARKET_KINDS = (KIND_GPU, KIND_CLOUD)


def _market_service(uow: UoW) -> MarketSyncService:
    """装配租赁价采集用例（三个客户端 + 当前汇率）。"""
    from ai_roi.infrastructure.collectors.market_prices import (
        AwsBulkPricingClient,
        AzureRetailClient,
        GetDeployingClient,
    )

    return MarketSyncService(
        uow,
        fx_usd_cny=D(settings.FX_USD_CNY),
        regional_client=GetDeployingClient(),
        cloud_client=AzureRetailClient(),
        aws_client=AwsBulkPricingClient(),
    )


def _check_kind(kind: str) -> str:
    if kind not in _MARKET_KINDS:
        raise NotFoundError(f"未知的采集类型：{kind}（支持 {' / '.join(_MARKET_KINDS)}）")
    return kind


@router.get("/market-preview", response_model=ApiResponse[Dict[str, Any]])
async def market_preview(
    user: CurrentUser, uow: UoW, kind: str = Query(KIND_GPU)
) -> ApiResponse[Dict[str, Any]]:
    """拉取外部价格并与库内逐条比对（只读，不写库）。

    返回每条「现网值 → 采集值 → 变动幅度」，以及三类边界清单：

    - `missing`：库里有该型号，但上游这次没数据；
    - `manual_only`：该型号/厂商**根本没有公开数据源**（国产卡、国内云），只能人工维护；
    - `unmatched`：上游有、库里没建行（便于人工决定是否补录）。

    把这三类分开列出来，是为了让「采集率」这个数字诚实：14 个 GPU 型号里
    只有 6 个能自动采，剩下 8 个不是采失败了，是国际市场没这个 SKU。
    """
    service = _market_service(uow)
    preview = (
        await service.preview_gpu_rental(user.tenant_id)
        if _check_kind(kind) == KIND_GPU
        else await service.preview_cloud_official(user.tenant_id)
    )
    s = preview.summary
    msg = (
        f"{preview.to_dict()['label']}：可采集 {s['total']} 条"
        f"（上调 {s['up']} / 下调 {s['down']} / 仅汇率口径 {s['settled']}），"
        f"无公开数据源 {s['manual_only']} 条"
    )
    if s["missing"]:
        msg += f"，上游本次缺 {s['missing']} 条"
    return ApiResponse.ok(preview.to_dict(), msg)


@router.post(
    "/market-apply", response_model=ApiResponse[Dict[str, Any]], dependencies=[_WRITE]
)
async def market_apply(
    payload: MarketApplyIn,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
    kind: str = Query(KIND_GPU),
) -> ApiResponse[Dict[str, Any]]:
    """应用用户确认的租赁价（逐条写审计快照，可回滚）。"""
    from decimal import Decimal as _Decimal

    if not payload.items:
        return ApiResponse.ok(
            {"kind": kind, "applied": [], "skipped": []}, "未选择任何条目"
        )

    service = _market_service(uow)
    proposals: Dict[int, _Decimal] = {}
    metas: Dict[int, Dict[str, Any]] = {}
    as_of_dates = []
    for item in payload.items:
        try:
            proposals[item.id] = _Decimal(item.proposed_cny)
        except (ArithmeticError, ValueError):
            continue
        metas[item.id] = item.meta
        if item.as_of is not None:
            as_of_dates.append(item.as_of)

    row_ids = list(proposals.keys())
    effective = min(as_of_dates) if as_of_dates else None

    if _check_kind(kind) == KIND_GPU:
        result = await service.apply_gpu_rental(
            row_ids,
            as_of=effective,
            tenant_id=user.tenant_id,
            actor_id=ctx.user_id,
            actor_email=ctx.user_email,
            proposals=proposals,
            metas=metas,
        )
    else:
        result = await service.apply_cloud_official(
            row_ids,
            tenant_id=user.tenant_id,
            actor_id=ctx.user_id,
            actor_email=ctx.user_email,
            proposals=proposals,
            metas=metas,
        )
    msg = f"已应用 {len(result['applied'])} 条"
    if result["skipped"]:
        msg += f"；跳过 {len(result['skipped'])} 条"
    return ApiResponse.ok(result, msg)


@router.get("/sync-overview", response_model=ApiResponse[Dict[str, Any]])
async def sync_overview(user: CurrentUser, uow: UoW) -> ApiResponse[Dict[str, Any]]:
    """四条采集链路的当前覆盖率（纯读本库 + 一次轻量状态查询，不访问外网）。

    面板要同时回答四个问题：「哪张表能自动更新、上次采到几条、还有多少只能人工维护」。
    四个接口串起来查会让面板首屏多等好几秒，所以在这里一次聚合。
    """
    from ai_roi.domain.cloud_official import SOURCE_ROW_PREFIX as CLOUD_PREFIX
    from ai_roi.domain.cloud_official import provider_status
    from ai_roi.domain.rental_market import (
        GPU_TO_SLUG,
        NO_MARKET_GPUS,
        SOURCE_ROW_PREFIX as RENTAL_PREFIX,
    )

    gpus = await uow.benchmarks.list_gpus(user.tenant_id)
    clouds = await uow.benchmarks.list_cloud_prices(user.tenant_id)

    def _count(rows: List[Any], prefix: str) -> int:
        return sum(1 for r in rows if str(getattr(r, "source", "") or "").startswith(prefix))

    return ApiResponse.ok(
        {
            "gpu_rental": {
                "kind": KIND_GPU,
                "total": len(gpus),
                "from_source": _count(gpus, RENTAL_PREFIX),
                "auto_capable": sum(1 for g in gpus if str(g.code) in GPU_TO_SLUG),
                "no_market": [str(g.code) for g in gpus if str(g.code) in NO_MARKET_GPUS],
            },
            "cloud_official": {
                "kind": KIND_CLOUD,
                "total": len(clouds),
                "from_source": _count(clouds, CLOUD_PREFIX),
                "auto_capable": sum(
                    1 for c in clouds if provider_status(str(c.provider)) == "auto"
                ),
            },
        },
        "已统计 GPU 行情与云官价覆盖率",
    )
