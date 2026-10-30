"""智算组网配置清单自动解析 + 估算测试。

fixture：`5090配置方案-智算组网配置清单-EHT-20270716.xlsx`（项目根目录，真实清单）。

⚠️ 该 xlsx 是**真实采购清单**（含设备单价、采购量、总价与具体型号，属商业敏感），
因此不随公开交付仓分发（`scripts/sync-to-deploy.sh` 的 EXCLUDE 含 `*.xlsx`）。
公开仓 / GitHub Actions 上 `bom` fixture 取不到文件，本模块 6 个用例会 skip，
这是**预期行为**而非故障：缺的是数据，不是代码缺陷，硬造一份脱敏夹具反而会让
「能解析真实清单」这个承诺失去意义。在持有该文件的开发机上，6 项全部执行。

覆盖：合并单元格前向填充、分类聚合、清单合计核对、GPU 识别、params 映射、估算不崩溃。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_roi.domain.calc.bom_estimate import (
    CATEGORY_MAP,
    estimate_from_bom,
    parse_network_bom_rows,
)
from ai_roi.domain.calc.decimal_config import D

_FIXTURE = Path(__file__).resolve().parents[6] / "5090配置方案-智算组网配置清单-EHT-20270716.xlsx"


@pytest.fixture(scope="module")
def bom():
    if not _FIXTURE.exists():
        pytest.skip(
            "真实 BOM 清单未随仓分发（含采购单价与规模，属商业敏感）——"
            "公开仓预期跳过；把该 xlsx 放到仓库根目录即可全部执行"
        )
    from ai_roi.infrastructure.files.bom_xlsx import read_bom_rows

    return parse_network_bom_rows(read_bom_rows(_FIXTURE.read_bytes()))


class TestParseNetworkBom:
    def test_line_count_and_total(self, bom) -> None:
        assert len(bom.lines) == 23
        assert bom.all_capex() == D("327301750")

    def test_category_aggregation(self, bom) -> None:
        assert bom.category_total("storage_net") == D("4883440")
        assert bom.category_total("storage") == D("9150000")
        assert bom.category_total("compute_net") == D("3884352")
        assert bom.category_total("gpu_server") == D("304567200")
        servers = [l for l in bom.gpu_servers if "服务器" in l.name]
        assert sum((l.total for l in servers), D(0)) == D("302400000")

    def test_gpu_server_lines(self, bom) -> None:
        servers = [l for l in bom.gpu_servers if "服务器" in l.name]
        assert len(servers) == 1
        assert servers[0].qty == D(504)


class TestEstimateFromBom:
    def test_estimate_mapping(self, bom) -> None:
        r = estimate_from_bom(bom)
        s = r["bom_summary"]
        assert s["gpu"]["id"] == "rtx5090"
        assert s["n_gpu"] == "2520"
        assert s["supporting_capex"] == "24901750"
        assert s["gpu_server_body"] == "302400000"
        assert s["total_estimate"] == "327301750"
        assert s["oob_net"] == "199960"
        p = r["params"]
        assert p["hw"]["N_gpu"] == "2520"
        assert p["hw"]["P_gpu"] == "120000"
        assert p["hw"]["P_aux"] == "24901750"
        assert p["hw"]["pre_launch_cost"] == "1200000"
        assert p["hw"]["supporting_port_speed"] == 100
        assert p["power"]["Co_ops"] == "228333.3333333333333333333333333333"

    def test_assumptions_explicit(self, bom) -> None:
        r = estimate_from_bom(bom)
        text = "\n".join(r["assumptions"])
        assert "N_gpu=2520" in text
        assert "单卡参考价" in text
        assert "100GE" in text
        assert "维保" in text and "Co_ops" in text
        assert "pre_launch_cost" in text

    def test_kpis_returned(self, bom) -> None:
        r = estimate_from_bom(bom)
        assert "npv" in r["financials"]
        assert "tco" in r["financials"]
        assert "cost_per_m" in r["kpis"]

    def test_unknown_gpu_rejected(self) -> None:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["序号", "类型", "设备名称", "参数描述", "数量", "单价（含税）", "总价", "备注"])
        ws.append(["1", "GPU服务器", "神秘加速服务器", "", "1", "100000", "100000", ""])
        import io

        buf = io.BytesIO()
        wb.save(buf)
        with pytest.raises(ValueError, match="无法识别 GPU 型号"):
            from ai_roi.infrastructure.files.bom_xlsx import parse_network_bom

            estimate_from_bom(parse_network_bom(buf.getvalue()))
