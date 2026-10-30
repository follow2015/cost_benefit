"""租赁价采集用例的编排逻辑：分类、比对、写回。

域层单测已覆盖「怎么算」，这里只验「怎么分」与「怎么写」：
库内哪几行能自动采、哪几行只能人工维护、哪些上游数据没有落点，
以及应用时绝不写入本次采集没覆盖的条目。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from ai_roi.application.use_cases.market_sync_service import (
    KIND_CLOUD,
    KIND_GPU,
    MarketSyncService,
)
from ai_roi.domain.errors import DomainError, UpstreamUnavailableError

D = Decimal

CSV_HEADER = (
    "gpu_slug,date,billing_type,reservation_months,min_price,max_price,"
    "median_price,provider_median_price,provider_count,offering_count\n"
)


class _Row:
    """基准行的轻量替身（只带用例关心的字段）。"""

    def __init__(self, **kw: Any) -> None:
        self.id = kw.get("id", 1)
        self.code = kw.get("code", "H100")
        self.provider = kw.get("provider")
        self.gpu_code = kw.get("gpu_code")
        self.rent_cny_per_hour = kw.get("rent_cny_per_hour")
        self.price_cny_per_hour = kw.get("price_cny_per_hour")
        self.source = kw.get("source", "web:2026-08")
        self.as_of = kw.get("as_of")
        self.version = kw.get("version", 1)
        self.meta: Dict[str, Any] = dict(kw.get("meta") or {})


class _Bench:
    def __init__(self, gpus: List[_Row], clouds: List[_Row]) -> None:
        self._gpus = gpus
        self._clouds = clouds
        self.updated: List[Dict[str, Any]] = []

    async def list_gpus(self, tenant_id: Optional[int]) -> List[_Row]:
        return self._gpus

    async def list_cloud_prices(self, tenant_id: Optional[int]) -> List[_Row]:
        return self._clouds

    async def get_gpu(self, tenant_id: Optional[int], gpu_id: int) -> Optional[_Row]:
        return next((g for g in self._gpus if g.id == gpu_id), None)

    async def get_cloud_price(
        self, tenant_id: Optional[int], row_id: int
    ) -> Optional[_Row]:
        return next((c for c in self._clouds if c.id == row_id), None)

    async def apply_update(self, row: Any, values: Dict[str, Any]) -> Any:
        for k, v in values.items():
            setattr(row, k, v)
        self.updated.append({"id": row.id, **values})
        return row


class _Audit:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def write(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _UoW:
    def __init__(self, gpus: List[_Row], clouds: List[_Row]) -> None:
        self.benchmarks = _Bench(gpus, clouds)
        self.audit = _Audit()


class _RegionalClient:
    def __init__(self, csv_text: str = "") -> None:
        self._csv = csv_text
        self.calls = 0

    async def fetch_weekly_csv(self) -> str:
        self.calls += 1
        return self._csv


class _CloudClient:
    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self._items = items

    async def fetch_items(self, vm_sizes: List[str], region: str = "eastus") -> List[Dict[str, Any]]:
        return self._items


def _csv(*lines: str) -> str:
    return CSV_HEADER + "\n".join(lines) + "\n"


def _azure(vm_size: str, price: Any, sku: Optional[str] = None) -> Dict[str, Any]:
    return {
        "armSkuName": vm_size,
        "skuName": sku or vm_size.replace("Standard_", ""),
        "retailPrice": price,
        "unitOfMeasure": "1 Hour",
        "type": "Consumption",
        "priceType": "Consumption",
        "currencyCode": "USD",
        "armRegionName": "eastus",
        "reservationTerm": None,
    }


class _AwsClient:
    """AWS b0 客户端替身：只回一个地区的价目表，可指定抛错。"""

    def __init__(self, payload: Optional[Dict[str, Any]] = None, error: Optional[Exception] = None) -> None:
        self._payload = payload or {}
        self._error = error
        self.calls: List[str] = []

    async def fetch_region(self, region_path: str) -> Dict[str, Any]:
        self.calls.append(region_path)
        if self._error is not None:
            raise self._error
        return self._payload


def _aws_payload(*pairs: Any) -> Dict[str, Any]:
    """按 b0 的真实结构造价目表：``{manifest, regions: {地区名: {键: 条目}}}``。"""
    entries: Dict[str, Any] = {}
    for instance_type, price in pairs:
        entries[f"{instance_type.replace('.', ' ')} US East N. Virginia Linux"] = {
            "Instance Type": instance_type,
            "Instance Family": "GPU instance",
            "price": str(price),
        }
    entries["m7g xlarge US East N. Virginia Linux"] = {
        "Instance Type": "m7g.xlarge",
        "Instance Family": "General purpose",
        "price": "0.1632",
    }
    return {
        "manifest": {"currencyCode": "USD", "serviceId": "ec2"},
        "regions": {"US East (N. Virginia)": entries},
    }


class TestPreviewGpuRental:
    @pytest.mark.asyncio
    async def test_splits_auto_capable_from_no_market(self) -> None:
        """国产卡进 manual_only，能采的进 items——两者绝不能混成「待采集」。"""
        uow = _UoW(
            gpus=[
                _Row(id=1, code="H100", rent_cny_per_hour=D("30")),
                _Row(id=2, code="ASCEND910B", rent_cny_per_hour=D("3.58")),
                _Row(id=3, code="H800", rent_cny_per_hour=D("8.88")),
            ],
            clouds=[],
        )
        csv_text = _csv("nvidia-h100,2026-10-26,ON_DEMAND,,1.79,12.29,3.99,3.7,39,120")
        svc = MarketSyncService(
            uow, fx_usd_cny=D("6.68"), regional_client=_RegionalClient(csv_text)
        )

        preview = await svc.preview_gpu_rental()

        assert [i.label for i in preview.items] == ["H100"]
        assert preview.manual_only == ["ASCEND910B", "H800"]
        assert preview.missing == []
        assert preview.as_of == date(2026, 10, 26)

    @pytest.mark.asyncio
    async def test_computes_change_and_direction(self) -> None:
        uow = _UoW(gpus=[_Row(id=1, code="H100", rent_cny_per_hour=D("30"))], clouds=[])
        csv_text = _csv("nvidia-h100,2026-10-26,ON_DEMAND,,1.79,12.29,3.99,3.7,39,120")
        svc = MarketSyncService(
            uow, fx_usd_cny=D("6.68"), regional_client=_RegionalClient(csv_text)
        )

        preview = await svc.preview_gpu_rental()
        item = preview.items[0]

        assert item.proposed_cny == D("26.6532")
        assert item.direction == "down"
        assert preview.summary["down"] == 1

    @pytest.mark.asyncio
    async def test_settled_when_change_within_noise(self) -> None:
        """变动 ≤0.5% 视为汇率/口径噪声，不算真实调价。"""
        uow = _UoW(gpus=[_Row(id=1, code="L40S", rent_cny_per_hour=D("12"))], clouds=[])
        csv_text = _csv("nvidia-l40s,2026-10-26,ON_DEMAND,,0.55,7.57,1.8,1.8,32,90")
        svc = MarketSyncService(
            uow, fx_usd_cny=D("6.68"), regional_client=_RegionalClient(csv_text)
        )

        item = (await svc.preview_gpu_rental()).items[0]
        assert item.proposed_cny == D("12.0240")
        assert item.settled is True
        assert item.direction == "settled"

    @pytest.mark.asyncio
    async def test_missing_when_upstream_has_no_row_this_week(self) -> None:
        uow = _UoW(gpus=[_Row(id=1, code="H100", rent_cny_per_hour=D("30"))], clouds=[])
        csv_text = _csv("nvidia-a100,2026-10-26,ON_DEMAND,,0.89,8.26,1.79,1.7,38,110")
        svc = MarketSyncService(
            uow, fx_usd_cny=D("6.68"), regional_client=_RegionalClient(csv_text)
        )

        preview = await svc.preview_gpu_rental()
        assert preview.items == []
        assert preview.missing == ["H100"]

    @pytest.mark.asyncio
    async def test_empty_upstream_raises_instead_of_wiping_library(self) -> None:
        """上游结构变更导致解析为空时必须报错，绝不能「0 条 = 全部清空」。"""
        uow = _UoW(gpus=[_Row(id=1, code="H100")], clouds=[])
        svc = MarketSyncService(
            uow, fx_usd_cny=D("6.68"), regional_client=_RegionalClient(CSV_HEADER)
        )
        with pytest.raises(DomainError):
            await svc.preview_gpu_rental()


class TestPreviewCloudOfficial:
    @pytest.mark.asyncio
    async def test_manual_only_covers_domestic_clouds(self) -> None:
        """只有「没有公开接口的厂商」才进 manual_only；AWS 已接接口，不该再混进来。"""
        uow = _UoW(
            gpus=[],
            clouds=[
                _Row(id=1, provider="Azure", gpu_code="H100", price_cny_per_hour=D("23.7")),
                _Row(id=2, provider="阿里云", gpu_code="H100", price_cny_per_hour=D("30")),
                _Row(id=3, provider="AWS", gpu_code="H100", price_cny_per_hour=D("20.3")),
            ],
        )
        svc = MarketSyncService(
            uow,
            fx_usd_cny=D("6.68"),
            cloud_client=_CloudClient([_azure("Standard_NC40ads_H100_v5", 6.98)]),
        )

        preview = await svc.preview_cloud_official()

        assert [i.label for i in preview.items] == ["Azure · H100"]
        assert preview.manual_only == ["阿里云·H100"]
        assert preview.missing == ["AWS·H100"]
        assert preview.summary["manual_only"] == 1

    @pytest.mark.asyncio
    async def test_aws_and_azure_fill_their_own_rows(self) -> None:
        """同一型号在不同厂商是两条独立报价，不能互相顶替。"""
        uow = _UoW(
            gpus=[],
            clouds=[
                _Row(id=1, provider="Azure", gpu_code="H100", price_cny_per_hour=D("23.7")),
                _Row(id=3, provider="AWS", gpu_code="H100", price_cny_per_hour=D("20.3")),
                _Row(id=4, provider="AWS", gpu_code="A100", price_cny_per_hour=D("10.8")),
            ],
        )
        svc = MarketSyncService(
            uow,
            fx_usd_cny=D("6.68"),
            cloud_client=_CloudClient([_azure("Standard_NC40ads_H100_v5", 6.98)]),
            aws_client=_AwsClient(
                _aws_payload(("p5.48xlarge", "55.04"), ("p4d.24xlarge", "21.957642"))
            ),
        )

        preview = await svc.preview_cloud_official()
        by_label = {i.label: i for i in preview.items}

        assert set(by_label) == {"Azure · H100", "AWS · H100", "AWS · A100"}
        assert by_label["AWS · H100"].proposed_cny == D("45.9584")
        assert by_label["AWS · A100"].proposed_cny == D("18.3346")
        assert preview.source_name == "Azure 零售价格接口 + AWS 批量价目表（官方公开）"
        assert preview.warnings == []

    @pytest.mark.asyncio
    async def test_aws_failure_keeps_azure_preview(self) -> None:
        """AWS 挂了不该让 Azure 已拿到的报价作废，但必须留下警告。"""
        uow = _UoW(
            gpus=[],
            clouds=[_Row(id=1, provider="Azure", gpu_code="H100", price_cny_per_hour=D("23.7"))],
        )
        svc = MarketSyncService(
            uow,
            fx_usd_cny=D("6.68"),
            cloud_client=_CloudClient([_azure("Standard_NC40ads_H100_v5", 6.98)]),
            aws_client=_AwsClient(error=UpstreamUnavailableError("AWS 价格源不可用：超时")),
        )

        preview = await svc.preview_cloud_official()

        assert [i.label for i in preview.items] == ["Azure · H100"]
        assert any("AWS" in w and "超时" in w for w in preview.warnings)
        assert preview.source_name == "Azure 零售价格接口（官方公开）"

    @pytest.mark.asyncio
    async def test_proposed_uses_per_gpu_price(self) -> None:
        uow = _UoW(
            gpus=[],
            clouds=[_Row(id=1, provider="Azure", gpu_code="H100", price_cny_per_hour=D("23.7"))],
        )
        svc = MarketSyncService(
            uow,
            fx_usd_cny=D("6.68"),
            cloud_client=_CloudClient([_azure("Standard_ND96isr_H100_v5", 98.32)]),
        )

        item = (await svc.preview_cloud_official()).items[0]
        assert item.proposed_cny == D("82.0972")
        assert "8 卡整机" in item.note


class TestApply:
    @pytest.mark.asyncio
    async def test_refuses_without_collected_proposals(self) -> None:
        """没有本次采集值就拒绝写——否则等于拿当前值自我覆盖，版本涨了数据没变。"""
        uow = _UoW(gpus=[_Row(id=1, code="H100")], clouds=[])
        svc = MarketSyncService(uow, fx_usd_cny=D("6.68"))

        with pytest.raises(DomainError):
            await svc.apply_gpu_rental([1], proposals=None)

    @pytest.mark.asyncio
    async def test_writes_source_date_from_collection_not_from_row(self) -> None:
        """source 里的日期必须是**本次采集周**，用库内旧 as_of 会让界面看起来没更新。"""
        row = _Row(id=1, code="H100", rent_cny_per_hour=D("30"), as_of=date(2026, 8, 31))
        uow = _UoW(gpus=[row], clouds=[])
        svc = MarketSyncService(uow, fx_usd_cny=D("6.68"))

        result = await svc.apply_gpu_rental(
            [1],
            as_of=date(2026, 10, 26),
            tenant_id=7,
            actor_id=1,
            actor_email="a@b.c",
            proposals={1: D("26.6532")},
            metas={1: {"gpu_rental_week": "2026-10-26"}},
        )

        assert result["applied"][0]["after"]["source"] == "gpu-rental:2026-10-26"
        assert row.as_of == date(2026, 10, 26)
        assert row.version == 2
        assert row.meta["gpu_rental_week"] == "2026-10-26"
        assert uow.audit.calls[0]["action"] == "benchmark.market_sync"

    @pytest.mark.asyncio
    async def test_skips_rows_not_covered_by_this_run(self) -> None:
        uow = _UoW(gpus=[_Row(id=1, code="H100"), _Row(id=2, code="A100")], clouds=[])
        svc = MarketSyncService(uow, fx_usd_cny=D("6.68"))

        result = await svc.apply_gpu_rental(
            [1, 2], as_of=date(2026, 10, 26), proposals={1: D("26.65")}
        )

        assert len(result["applied"]) == 1
        assert result["skipped"] == [{"id": 2, "reason": "本次采集未覆盖该型号"}]

    @pytest.mark.asyncio
    async def test_cloud_apply_merges_vm_size_meta(self) -> None:
        row = _Row(id=1, provider="Azure", gpu_code="H100", price_cny_per_hour=D("23.7"))
        uow = _UoW(gpus=[], clouds=[row])
        svc = MarketSyncService(uow, fx_usd_cny=D("6.68"))

        await svc.apply_cloud_official(
            [1],
            proposals={1: D("46.6264")},
            metas={1: {"cloud_official_vm_size": "Standard_NC40ads_H100_v5"}},
        )

        assert row.source.startswith("cloud-sync:")
        assert row.meta["cloud_official_vm_size"] == "Standard_NC40ads_H100_v5"
        assert row.version == 2
