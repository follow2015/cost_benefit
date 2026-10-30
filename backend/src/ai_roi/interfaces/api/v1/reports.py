"""报告导出路由（P1 REQ-12）。

`GET /reports/{scenario_id}?fmt=pdf|excel` 返回文件流下载：
- 取方案详情 + 最近一次权威计算结果（若无结果则触发一次落库计算，保证可导）；
- 经 `ai_roi.infrastructure.reports.template.assemble_report` 组装；
- 由 `ai_roi.infrastructure.reports.pdf` / `.excel` 渲染为字节流；
- 必须包含口径摘要与免责声明（已在 template 中保证）。

权限：`scenario:read`（租户内全部角色具备）。导出动作落审计。
"""

from __future__ import annotations

from io import BytesIO
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ai_roi.interfaces.api.deps import Ctx, CurrentUser, UoW, require_permission
from ai_roi.infrastructure.db.models.audit import ACTION_REPORT_EXPORT
from ai_roi.infrastructure.reports.excel import render_excel
from ai_roi.infrastructure.reports.pdf import render_pdf
from ai_roi.infrastructure.reports.template import assemble_report
from ai_roi.application.schemas.calc import CalcOptionsIn
from ai_roi.application.use_cases.audit_service import AuditService
from ai_roi.application.use_cases.calc_service import CalcService
from ai_roi.application.use_cases.scenario_service import ScenarioService

router = APIRouter(prefix="/reports", tags=["reports"])

_FORMATS = {
    "pdf": ("application/pdf", "pdf"),
    "excel": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
}


@router.get(
    "/{scenario_id}",
    dependencies=[Depends(require_permission("scenario:read"))],
)
async def export_report(
    scenario_id: int,
    user: CurrentUser,
    uow: UoW,
    ctx: Ctx,
    fmt: str = Query("pdf", pattern="^(pdf|excel|xinchuang)$"),
    compliance: Optional[str] = Query(None, pattern="^(localization)?$"),
) -> StreamingResponse:
    """导出方案 ROI 报告（PDF / Excel）。

    - `fmt=pdf|excel`：标准报告；
    - `fmt=xinchuang`：信创合规变体（等价于 `compliance=localization`，默认导出 Excel）；
    - `compliance=localization`：在标准 fmt 基础上追加「信创合规」专项段落。
    """
    is_localization = compliance == "localization" or fmt == "xinchuang"
    effective_fmt = "excel" if fmt == "xinchuang" else fmt

    scenario = await ScenarioService(uow).detail(user.tenant_id, scenario_id)
    scenario_dict = scenario.model_dump()

    calc_service = CalcService(uow)
    record = await calc_service.latest_for_scenario(user.tenant_id, scenario_id)
    if record is None:
        outcome = await calc_service.calculate(
            tenant_id=user.tenant_id,
            user_id=user.id,
            params_dict=dict(scenario.params or {}),
            options=CalcOptionsIn(),
            scenario_id=scenario_id,
            scenario_version=int(scenario.version),
            persist=True,
        )
        payload = outcome.payload
    else:
        payload = dict(record.payload or {})

    report = assemble_report(
        scenario_dict,
        payload,
        compliance="localization" if is_localization else None,
    )

    media_type, ext = _FORMATS[effective_fmt]
    data = render_excel(report) if effective_fmt == "excel" else render_pdf(report)

    filename = f"{scenario.name}_ROI报告.{ext}"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Report-Engine": str(report.get("engine_version", "")),
    }

    await AuditService(uow).log(
        ctx,
        ACTION_REPORT_EXPORT,
        target_type="scenario",
        target_id=scenario_id,
        detail={
            "format": effective_fmt,
            "compliance": "localization" if is_localization else None,
            "engine_version": report.get("engine_version", ""),
        },
    )

    return StreamingResponse(BytesIO(data), media_type=media_type, headers=headers)
