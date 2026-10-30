"""PDF 报告渲染（P1 REQ-12）。

使用 reportlab Platypus + 内置 CID 中文字体 `STSong-Light`（无需外部字体文件，
已验证可正确渲染中文）。输出字节流，由路由层包装为 `StreamingResponse` 下载。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_FONT_REGISTERED = False


def _ensure_font() -> str:
    """确保 CJK 字体已注册，返回字体名。"""
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONT_REGISTERED = True
    return "STSong-Light"


def _styles() -> Dict[str, ParagraphStyle]:
    """构造报告样式集合（中文字体）。"""
    font = _ensure_font()
    base = getSampleStyleSheet()
    title = ParagraphStyle("TitleCJK", parent=base["Title"], fontName=font, fontSize=18, leading=24)
    h2 = ParagraphStyle("H2CJK", parent=base["Heading2"], fontName=font, fontSize=13, leading=18, textColor=colors.HexColor("#1f3a93"), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("BodyCJK", parent=base["BodyText"], fontName=font, fontSize=9, leading=13, alignment=TA_LEFT)
    note = ParagraphStyle("NoteCJK", parent=body, fontSize=8, textColor=colors.HexColor("#888888"))
    cell = ParagraphStyle("CellCJK", parent=body, fontSize=8, leading=11)
    return {"title": title, "h2": h2, "body": body, "note": note, "cell": cell}


_TABLE_STYLE = TableStyle(
    [
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
)


def _kv_table(rows: List[Dict[str, str]], col_labels: List[str]) -> Table:
    """通用键值表（两列：标签 / 值）。"""
    data = [[col_labels[0], col_labels[1]]] + [
        [Paragraph(str(r.get("label", "")), _styles()["cell"]), Paragraph(str(r.get("value", "")), _styles()["cell"])]
        for r in rows
    ]
    return Table(data, colWidths=[60 * mm, 110 * mm], style=_TABLE_STYLE)


def _grid_table(headers: List[str], rows: List[List[str]], widths: List[float]) -> Table:
    """通用网格表。"""
    data = [[Paragraph(str(h), _styles()["cell"]) for h in headers]] + [
        [Paragraph(str(c), _styles()["cell"]) for c in row] for row in rows
    ]
    return Table(data, colWidths=[w * mm for w in widths], style=_TABLE_STYLE, repeatRows=1)


def render_pdf(report: Dict[str, Any]) -> bytes:
    """把报告数据渲染为 PDF 字节流。"""
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=report.get("title", "ROI 报告"),
        author="AI 算力投资 ROI 测算平台",
    )
    flow: List[Any] = []

    flow.append(Paragraph(report.get("title", "AI 算力投资 ROI 测算报告"), styles["title"]))
    flow.append(
        Paragraph(
            f"方案：{report.get('scenario_name', '')}　版本 v{report.get('version', 1)}　"
            f"生成时间：{report.get('generated_at', '')}",
            styles["note"],
        )
    )
    flow.append(Spacer(1, 4))

    flow.append(Paragraph("一、测算口径摘要", styles["h2"]))
    flow.append(_kv_table(report.get("conventions", []), ["口径项", "取值"]))

    flow.append(Paragraph("二、核心经济指标（KPI）", styles["h2"]))
    kpi_rows = [[r["label"], f"{r['value']} {r['unit']}".strip()] for r in report.get("kpis", [])]
    flow.append(_kv_table([{"label": a, "value": b} for a, b in kpi_rows], ["指标", "数值"]))
    rec = report.get("recommended_plan")
    if rec:
        flow.append(Spacer(1, 3))
        flow.append(Paragraph(f"推荐方案：{rec}", styles["body"]))

    flow.append(Paragraph("三、投资财务摘要", styles["h2"]))
    flow.append(_kv_table(report.get("financials", []), ["财务指标", "数值"]))

    flow.append(Paragraph("四、单位成本结构", styles["h2"]))
    flow.append(
        _grid_table(
            ["成本项", "金额(元)", "占比"],
            [[r["label"], r["amount"], r["share"]] for r in report.get("cost_breakdown", [])],
            [70, 50, 40],
        )
    )

    flow.append(Paragraph("五、输入参数明细", styles["h2"]))
    for section in report.get("param_sections", []):
        flow.append(Paragraph(section.get("label", ""), styles["body"]))
        flow.append(_kv_table(section.get("rows", []), ["参数", "取值"]))

    flow.append(Paragraph("六、逐年现金流", styles["h2"]))
    cf = report.get("cashflows_yearly", [])
    if cf:
        flow.append(
            _grid_table(
                list(cf[0].keys()),
                [list(r.values()) for r in cf],
                [14] * len(cf[0]),
            )
        )
    else:
        flow.append(Paragraph("（无现金流数据）", styles["note"]))

    sens = report.get("sensitivity")
    if sens:
        flow.append(Paragraph(f"七、敏感性分析（目标：{sens.get('target_label', '')}）", styles["h2"]))
        flow.append(
            _grid_table(
                ["参数", "基准", "悲观(-)", "乐观(+)", "波动幅度"],
                [[r["label"], r["base"], r["low"], r["high"], r["swing_pct"]] for r in sens.get("items", [])],
                [50, 30, 30, 30, 30],
            )
        )

    loc = report.get("localization")
    if loc:
        flow.append(Paragraph("信创合规专项（国产化）", styles["h2"]))
        loc_rows = [
            {"label": "关键算力国产化率", "value": str(loc.get("domestic_gpu_share", ""))},
            {"label": "国产化口径（CN_cfg）", "value": str(loc.get("cn_cfg_label", ""))},
            {"label": "专项结论", "value": str(loc.get("conclusion", ""))},
        ]
        flow.append(_kv_table(loc_rows, ["项目", "内容"]))
        prompts = loc.get("prompts", []) or []
        if prompts:
            flow.append(
                ListFlowable(
                    [ListItem(Paragraph(str(p), styles["body"]), leftIndent=8) for p in prompts],
                    bulletType="bullet",
                )
            )

    warnings = report.get("warnings", [])
    if warnings:
        flow.append(Paragraph("八、口径提示", styles["h2"]))
        flow.append(
            ListFlowable(
                [ListItem(Paragraph(str(w), styles["body"]), leftIndent=8) for w in warnings],
                bulletType="bullet",
            )
        )

    flow.append(Spacer(1, 8))
    flow.append(Paragraph("免责声明", styles["h2"]))
    flow.append(Paragraph(report.get("disclaimer", ""), styles["note"]))

    doc.build(flow)
    return buffer.getvalue()
