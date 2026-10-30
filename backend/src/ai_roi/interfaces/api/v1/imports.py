"""批量导入路由（P2-2）。

- `GET /imports/template`：返回 xlsx 录入模板（含字段说明 + 来源列），用 openpyxl 生成；
- 解析与校验在**前端**完成（优先 CSV，轻依赖），后端仅提供模板与字段元数据。

模板列：`组别, 字段(key), 标签, 单位, 类型, 必填, 来源(measured/estimated/benchmark), 填入值`
前端按相同列解析 CSV；来源列标记该值属实测 / 估算 / 基准。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ai_roi.interfaces.api.deps import CurrentUser, UoW, require_permission
from ai_roi.application.schemas.common import ApiResponse

router = APIRouter(prefix="/imports", tags=["imports"])

IMPORT_FIELDS = [
    ("hw", "N_gpu", "GPU 数量", "张", "number", True),
    ("hw", "P_gpu", "单卡价格", "元/卡", "number", True),
    ("hw", "P_aux", "辅助设备 CAPEX", "元", "number", False),
    ("hw", "Y_dep", "折旧年限", "年", "number", False),
    ("hw", "S_pct", "残值率", "比率", "number", False),
    ("power", "TDP", "单卡 TDP", "W", "number", False),
    ("power", "PUE", "PUE", "", "number", False),
    ("power", "E_price", "电价", "元/kWh", "number", True),
    ("power", "Co_loc", "机位租金", "元/月", "number", False),
    ("perf", "T_eff", "有效吞吐", "tok/s", "number", True),
    ("perf", "T_pf", "Prefill 吞吐", "tok/s", "number", False),
    ("perf", "T_dc", "Decode 吞吐", "tok/s", "number", False),
    ("perf", "SLA_ttft", "SLA TTFT", "ms", "number", False),
    ("perf", "SLA_tpot", "SLA TPOT", "ms", "number", False),
    ("demand", "rho", "输入/输出比", "", "number", False),
    ("demand", "D_eq", "等效月需求", "Mtok/月", "number", True),
    ("demand", "h", "缓存命中率", "比率", "number", False),
    ("demand", "U", "利用率", "比率", "number", True),
    ("pricing", "p_in", "输入单价", "元/Mtok", "number", False),
    ("pricing", "p_out", "输出单价", "元/Mtok", "number", True),
    ("pricing", "Rent_gpu", "租用单价", "元/GPU·时", "number", False),
    ("pricing", "API_in", "API 输入价", "元/Mtok", "number", False),
    ("pricing", "API_out", "API 输出价", "元/Mtok", "number", False),
    ("finance", "T_horizon", "投资期", "月", "number", False),
    ("finance", "r_w", "年化折现率", "比率", "number", False),
    ("finance", "Tax", "税率", "比率", "number", False),
]

HEADERS = ["组别", "字段(key)", "标签", "单位", "类型", "必填", "来源(measured/estimated/benchmark)", "填入值"]


@router.get("/template", dependencies=[Depends(require_permission("scenario:read"))])
async def download_template(user: CurrentUser, uow: UoW) -> StreamingResponse:
    """下载 xlsx 录入模板（含字段说明与来源列）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "参数录入模板"
    ws.append(["AI 算力 ROI 测算 · 批量参数录入模板"])
    ws["A1"].font = Font(name="微软雅黑", bold=True, size=14, color="1F3A93")
    ws.append(["填写说明：按「填入值」列录入数值，「来源」列标注 measured(实测)/estimated(估算)/benchmark(基准)；必填项缺失将阻断导入。"])
    ws.append([])
    ws.append(HEADERS)
    for col_idx in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=4, column=col_idx)
        cell.fill = PatternFill("solid", fgColor="EEF2FF")
        cell.font = Font(name="微软雅黑", bold=True, color="1F3A93")
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    for group, field, label, unit, ftype, required in IMPORT_FIELDS:
        ws.append([group, field, label, unit, ftype, "是" if required else "否", "", ""])

    for col_idx in range(1, len(HEADERS) + 1):
        letter = __import__("openpyxl.utils", fromlist=["get_column_letter"]).get_column_letter(col_idx)
        width = [12, 16, 18, 12, 10, 8, 34, 14][col_idx - 1]
        ws.column_dimensions[letter].width = width

    out = BytesIO()
    wb.save(out)
    data = out.getvalue()
    filename = "ROI参数录入模板.xlsx"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Template-Fields": str(len(IMPORT_FIELDS)),
    }
    return StreamingResponse(BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@router.post(
    "/network-bom-estimate",
    response_model=ApiResponse[Dict[str, Any]],
    dependencies=[Depends(require_permission("scenario:calc"))],
)
async def estimate_network_bom(file: UploadFile = File(...)) -> ApiResponse[Dict[str, Any]]:
    """智算组网配置清单（xlsx）自动解析 + 方案估算（用户需求 2026-08-19）。

    - 解析清单为结构化 BOM（GPU 服务器/推理·存储·管理交换机/线缆/存储/服务）；
    - 映射 `ScenarioParams`（GPU 目录匹配、配套 CAPEX 用清单实际值、系统集成入
      pre_launch、维保入 Co_ops）并走计算引擎估算；
    - 无状态：返回 params dict（可一键回填 Wizard）+ 估算 KPI + 假设说明。
    """
    data = await file.read()
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 配置清单")
    try:
        from ai_roi.domain.calc.bom_estimate import estimate_from_bom
        from ai_roi.infrastructure.files.bom_xlsx import parse_network_bom

        bom = parse_network_bom(data)
        result = estimate_from_bom(bom)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse.ok(result, "配置清单解析并完成估算")
