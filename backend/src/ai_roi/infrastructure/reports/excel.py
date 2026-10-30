"""Excel 报告渲染（P1 REQ-12）。

使用 openpyxl 生成 `.xlsx`：主表「测算摘要」+「逐年现金流」+「敏感性分析」三张工作表。
单元格写入字符串（Decimal 已字符串化），不丢精度。含口径摘要与免责声明。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="EEF2FF")
_HEADER_FONT = Font(name="微软雅黑", bold=True, color="1F3A93")
_TITLE_FONT = Font(name="微软雅黑", bold=True, size=14, color="1F3A93")
_BODY_FONT = Font(name="微软雅黑", size=10)
_WRAP = Alignment(wrap_text=True, vertical="top")


def _write_sheet(ws: Any, title: str, headers: List[str], rows: List[List[str]]) -> None:
    """写一个带表头的工作表。"""
    ws.append([title])
    ws["A1"].font = _TITLE_FONT
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=2, column=col_idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _WRAP
    for row in rows:
        ws.append(row)
    for r in range(2, ws.max_row + 1):
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = _BODY_FONT
            cell.alignment = _WRAP
    for col_idx in range(1, len(headers) + 1):
        letter = get_column_letter(col_idx)
        width = max((len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(1, ws.max_row + 1)), default=10)
        ws.column_dimensions[letter].width = min(max(width + 2, 12), 40)


def render_excel(report: Dict[str, Any]) -> bytes:
    """把报告数据渲染为 Excel 字节流。"""
    wb = Workbook()

    ws = wb.active
    ws.title = "测算摘要"
    ws.append([report.get("title", "AI 算力投资 ROI 测算报告")])
    ws["A1"].font = _TITLE_FONT
    ws.append([f"方案：{report.get('scenario_name', '')}　版本 v{report.get('version', 1)}　生成时间：{report.get('generated_at', '')}"])
    ws.append([])

    row_cursor = ws.max_row + 1
    ws.cell(row=row_cursor, column=1, value="一、测算口径摘要").font = _HEADER_FONT
    row_cursor += 1
    ws.append(["口径项", "取值"])
    for r in report.get("conventions", []):
        ws.append([r.get("label", ""), r.get("value", "")])
    row_cursor = ws.max_row + 2
    ws.cell(row=row_cursor, column=1, value="二、核心经济指标（KPI）").font = _HEADER_FONT
    row_cursor += 1
    ws.append(["指标", "数值", "单位"])
    for r in report.get("kpis", []):
        ws.append([r.get("label", ""), r.get("value", ""), r.get("unit", "")])
    rec = report.get("recommended_plan")
    if rec:
        ws.append(["推荐方案", rec, ""])
    row_cursor = ws.max_row + 2
    ws.cell(row=row_cursor, column=1, value="三、投资财务摘要").font = _HEADER_FONT
    row_cursor += 1
    ws.append(["财务指标", "数值"])
    for r in report.get("financials", []):
        ws.append([r.get("label", ""), r.get("value", "")])
    row_cursor = ws.max_row + 2
    ws.cell(row=row_cursor, column=1, value="四、单位成本结构").font = _HEADER_FONT
    row_cursor += 1
    ws.append(["成本项", "金额(元)", "占比"])
    for r in report.get("cost_breakdown", []):
        ws.append([r.get("label", ""), r.get("amount", ""), r.get("share", "")])
    row_cursor = ws.max_row + 2
    ws.cell(row=row_cursor, column=1, value="五、输入参数明细").font = _HEADER_FONT
    row_cursor += 1
    for section in report.get("param_sections", []):
        ws.append([section.get("label", "")])
        ws.append(["参数", "取值"])
        for r in section.get("rows", []):
            ws.append([r.get("label", ""), r.get("value", "")])
    row_cursor = ws.max_row + 2
    ws.cell(row=row_cursor, column=1, value="免责声明").font = _HEADER_FONT
    row_cursor += 1
    ws.append([report.get("disclaimer", "")])
    ws.cell(row=ws.max_row, column=1).alignment = _WRAP

    for col_idx in range(1, 4):
        ws.column_dimensions[get_column_letter(col_idx)].width = 28

    ws_cf = wb.create_sheet("逐年现金流")
    cf = report.get("cashflows_yearly", [])
    if cf:
        _write_sheet(ws_cf, "逐年现金流", list(cf[0].keys()), [list(r.values()) for r in cf])
    else:
        _write_sheet(ws_cf, "逐年现金流", ["提示"], [["（无现金流数据）"]])

    ws_sens = wb.create_sheet("敏感性分析")
    sens = report.get("sensitivity")
    if sens:
        _write_sheet(
            ws_sens,
            f"敏感性分析（目标：{sens.get('target_label', '')}）",
            ["参数", "基准", "悲观(-)", "乐观(+)", "波动幅度"],
            [[r["label"], r["base"], r["low"], r["high"], r["swing_pct"]] for r in sens.get("items", [])],
        )
    else:
        _write_sheet(ws_sens, "敏感性分析", ["提示"], [["（未生成敏感性分析）"]])

    loc = report.get("localization")
    ws_loc = wb.create_sheet("信创合规")
    if loc:
        ws_loc.append(["信创合规专项（国产化）"])
        ws_loc["A1"].font = _TITLE_FONT
        ws_loc.append([])
        rows = [
            ["关键算力国产化率", str(loc.get("domestic_gpu_share", ""))],
            ["国产化口径（CN_cfg）", str(loc.get("cn_cfg_label", ""))],
            ["专项结论", str(loc.get("conclusion", ""))],
        ]
        ws_loc.append(["项目", "内容"])
        for r in rows:
            ws_loc.append(r)
        ws_loc.append([])
        ws_loc.append(["合规提示"])
        for p in loc.get("prompts", []) or []:
            ws_loc.append([str(p)])
        for r in range(2, ws_loc.max_row + 1):
            for c in range(1, 3):
                cell = ws_loc.cell(row=r, column=c)
                cell.font = _BODY_FONT
                cell.alignment = _WRAP
        ws_loc.column_dimensions["A"].width = 40
        ws_loc.column_dimensions["B"].width = 60
    else:
        _write_sheet(ws_loc, "信创合规", ["提示"], [["（非信创合规报表，未生成国产化专项段落）"]])

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
