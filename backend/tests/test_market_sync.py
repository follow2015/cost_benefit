"""租赁价采集（GPU 行情 / 云官价）的解析与比对规则测试。

重点覆盖三类「会悄悄算错」的地方：
1. 计费方式混入（Spot / Low Priority / 包年包月）——单价会低 3~7 倍；
2. 整机价 vs 单卡价——Azure 按 VM 规格卖，8 卡整机价直接入库会虚高 8 倍；
3. 同型号多规格取舍——1 卡 / 2 卡 / 8 卡并存时必须统一口径。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ai_roi.domain.cloud_official import (
    CloudQuote,
    cheapest_per_gpu,
    parse_aws_entries,
    parse_azure_items,
    provider_status,
    source_site,
    usd_to_cny as cloud_usd_to_cny,
)
from ai_roi.domain.rental_market import (
    GPU_TO_SLUG,
    NO_MARKET_GPUS,
    RentalQuote,
    latest_by_slug,
    market_status,
    parse_weekly_csv,
    usd_to_cny as rental_usd_to_cny,
)

D = Decimal

CSV_HEADER = (
    "gpu_slug,date,billing_type,reservation_months,min_price,max_price,"
    "median_price,provider_median_price,provider_count,offering_count\n"
)


def _csv(*lines: str) -> str:
    return CSV_HEADER + "\n".join(lines) + "\n"


class TestParseWeeklyCsv:
    def test_parses_basic_row(self) -> None:
        text = _csv("nvidia-h100,2026-10-26,ON_DEMAND,,1.79,12.29,3.99,3.715,40,120")
        quotes = parse_weekly_csv(text)
        assert len(quotes) == 1
        q = quotes[0]
        assert q.gpu_slug == "nvidia-h100"
        assert q.week == date(2026, 10, 26)
        assert q.billing_type == "ON_DEMAND"
        assert q.median_usd == D("3.99")
        assert q.min_usd == D("1.79")
        assert q.provider_count == 40

    def test_skips_rows_without_price_or_date(self) -> None:
        """上游每天重生成该文件，偶发空值比整批失败常见——不能因一行脏数据全丢。"""
        text = _csv(
            "nvidia-h100,2026-10-26,ON_DEMAND,,1.79,12.29,3.99,3.7,40,120",
            "nvidia-a100,,ON_DEMAND,,0.89,8.26,1.79,1.7,38,110",
            "nvidia-l40s,2026-10-26,ON_DEMAND,,0.55,7.57,,1.8,32,90",
            "",
        )
        quotes = parse_weekly_csv(text)
        assert [q.gpu_slug for q in quotes] == ["nvidia-h100"]

    def test_rejects_non_positive_price(self) -> None:
        text = _csv("nvidia-h100,2026-10-26,ON_DEMAND,,1,2,0,1,3,3")
        assert parse_weekly_csv(text) == []

    def test_empty_input_is_not_an_error(self) -> None:
        assert parse_weekly_csv("") == []
        assert parse_weekly_csv(CSV_HEADER) == []


class TestLatestBySlug:
    def test_takes_latest_week_per_slug(self) -> None:
        """按型号各取最新周，而不是按全局最新日期筛——否则断更型号会被整批丢掉。"""
        quotes = [
            RentalQuote("nvidia-h100", date(2026, 10, 12), "ON_DEMAND", None, D("3.5"), None, 40, 100),
            RentalQuote("nvidia-h100", date(2026, 10, 26), "ON_DEMAND", None, D("3.99"), None, 40, 120),
            RentalQuote("nvidia-a100", date(2026, 10, 19), "ON_DEMAND", None, D("1.79"), None, 38, 110),
        ]
        best, latest = latest_by_slug(quotes)
        assert best["nvidia-h100"].median_usd == D("3.99")
        assert best["nvidia-a100"].median_usd == D("1.79")
        assert latest == date(2026, 10, 26)

    def test_only_on_demand_counts(self) -> None:
        quotes = [
            RentalQuote("nvidia-h100", date(2026, 10, 26), "SPOT", None, D("2.0"), None, 10, 20),
            RentalQuote("nvidia-h100", date(2026, 10, 26), "ON_DEMAND", None, D("3.99"), None, 40, 120),
            RentalQuote("nvidia-h100", date(2026, 10, 26), "RESERVATION", None, D("1.5"), None, 5, 8),
        ]
        best, _ = latest_by_slug(quotes)
        assert best["nvidia-h100"].median_usd == D("3.99")

    def test_pure_spot_market_yields_nothing(self) -> None:
        """只有竞价价时宁可返回空，也不要拿竞价价冒充按需价。"""
        quotes = [
            RentalQuote("nvidia-h100", date(2026, 10, 26), "SPOT", None, D("2.0"), None, 10, 20)
        ]
        best, latest = latest_by_slug(quotes)
        assert best == {}
        assert latest is None


class TestRentalDomainHelpers:
    def test_usd_to_cny_quantizes_to_four_places(self) -> None:
        assert rental_usd_to_cny(D("3.99"), D("6.68")) == D("26.6532")

    def test_thin_market_flag(self) -> None:
        thin = RentalQuote("nvidia-a800", date(2026, 10, 26), "ON_DEMAND", None, D("1.178"), None, 1, 1)
        thick = RentalQuote("nvidia-h100", date(2026, 10, 26), "ON_DEMAND", None, D("3.99"), None, 39, 120)
        assert thin.is_thin is True
        assert thick.is_thin is False

    def test_meta_keeps_usd_and_fx_for_audit(self) -> None:
        q = RentalQuote(
            "nvidia-h100", date(2026, 10, 26), "ON_DEMAND", D("1.79"), D("3.99"), D("12.29"), 39, 120
        )
        meta = q.to_meta(D("6.68"))
        assert meta["gpu_rental_usd_per_hour"] == "3.99"
        assert meta["gpu_rental_fx_usd_cny"] == "6.68"
        assert meta["gpu_rental_providers"] == 39
        assert meta["gpu_rental_week"] == "2026-10-26"
        assert meta["gpu_rental_thin_market"] is False

    def test_market_status_separates_auto_from_no_market(self) -> None:
        assert market_status("H100") == "auto"
        for code in ("ASCEND910B", "CAMB590", "H800", "H20"):
            assert market_status(code) == "manual"
        assert set(NO_MARKET_GPUS).issubset({c for c in GPU_TO_SLUG} | set(NO_MARKET_GPUS))
        assert not set(NO_MARKET_GPUS) & set(GPU_TO_SLUG)


def _azure(
    vm_size: str,
    price: object,
    *,
    sku: str | None = None,
    region: str = "eastus",
    unit: str = "1 Hour",
    type_: str = "Consumption",
    currency: str = "USD",
    reservation: str | None = None,
) -> dict:
    return {
        "armSkuName": vm_size,
        "skuName": sku if sku is not None else vm_size.replace("Standard_", ""),
        "retailPrice": price,
        "unitOfMeasure": unit,
        "type": type_,
        "priceType": type_,
        "currencyCode": currency,
        "armRegionName": region,
        "reservationTerm": reservation,
    }


class TestParseAzureItems:
    def test_maps_vm_size_to_gpu_and_count(self) -> None:
        quotes = parse_azure_items([_azure("Standard_NC40ads_H100_v5", 6.98)])
        assert len(quotes) == 1
        q = quotes[0]
        assert q.provider == "Azure"
        assert q.gpu_code == "H100"
        assert q.gpu_count == 1
        assert q.usd_per_gpu_hour == D("6.98")

    def test_whole_machine_price_is_split_by_gpu_count(self) -> None:
        """8 卡整机 $98.32 → 单卡 $12.29；直接入库会虚高 8 倍。"""
        quotes = parse_azure_items([_azure("Standard_ND96isr_H100_v5", 98.32)])
        assert quotes[0].gpu_count == 8
        assert quotes[0].usd_per_gpu_hour == D("12.29")

    @pytest.mark.parametrize(
        "sku",
        ["NC40adsH100v5 Spot", "NC40adsH100v5 Low Priority", "NC40adsH100v5 LowPriority"],
    )
    def test_excludes_spot_and_low_priority(self, sku: str) -> None:
        """竞价 / 低优先级价低 3~7 倍，混进来会把按需租赁成本算成抢得到机器时的成本。"""
        assert parse_azure_items([_azure("Standard_NC40ads_H100_v5", 1.28, sku=sku)]) == []

    def test_excludes_reservation_term(self) -> None:
        item = _azure("Standard_ND96isr_H100_v5", 551221.0, reservation="1 Year")
        assert parse_azure_items([item]) == []

    def test_excludes_non_hourly_and_non_usd(self) -> None:
        assert parse_azure_items([_azure("Standard_NC40ads_H100_v5", 5000, unit="1/Month")]) == []
        assert parse_azure_items([_azure("Standard_NC40ads_H100_v5", 44.5, currency="CNY")]) == []

    def test_ignores_unmapped_and_blocked_sizes(self) -> None:
        assert parse_azure_items([_azure("Standard_NC6s_v3", 3.06)]) == []
        assert parse_azure_items([_azure("Standard_NV6ads_A10_v5", 0.9)]) == []

    def test_skips_missing_price(self) -> None:
        assert parse_azure_items([_azure("Standard_NC40ads_H100_v5", None)]) == []


class TestCheapestPerGpu:
    def test_picks_lowest_per_gpu_across_sizes(self) -> None:
        quotes = parse_azure_items(
            [
                _azure("Standard_NC40ads_H100_v5", 6.98),
                _azure("Standard_ND96isr_H100_v5", 98.32),
            ]
        )
        best = cheapest_per_gpu(quotes)
        assert best[("Azure", "H100")].vm_size == "Standard_NC40ads_H100_v5"
        assert best[("Azure", "H100")].usd_per_gpu_hour == D("6.98")

    def test_keeps_providers_and_models_separate(self) -> None:
        quotes = [
            CloudQuote("Azure", "H100", "eastus", "S1", 1, D("6.98")),
            CloudQuote("Azure", "A100", "eastus", "S2", 8, D("40.0")),
        ]
        best = cheapest_per_gpu(quotes)
        assert set(best) == {("Azure", "H100"), ("Azure", "A100")}


class TestCloudHelpers:
    def test_usd_to_cny(self) -> None:
        assert cloud_usd_to_cny(D("12.29"), D("6.68")) == D("82.0972")

    def test_provider_status(self) -> None:
        for p in ("Azure", "AWS"):
            assert provider_status(p) == "auto"
        for p in ("GCP", "阿里云", "腾讯云", "华为云", "火山引擎", "AutoDL"):
            assert provider_status(p) == "manual"

    def test_source_site_is_per_provider(self) -> None:
        assert "azure" in source_site("Azure")
        assert "aws.amazon.com" in source_site("AWS")
        assert source_site("阿里云").startswith("https://")

    def test_meta_records_vm_size_for_manual_check(self) -> None:
        q = CloudQuote("Azure", "H100", "eastus", "Standard_NC40ads_H100_v5", 1, D("6.98"))
        meta = q.to_meta(D("6.68"))
        assert meta["cloud_official_vm_size"] == "Standard_NC40ads_H100_v5"
        assert meta["cloud_official_gpu_count"] == 1
        assert meta["cloud_official_usd_per_gpu"] == "6.9800"


class TestParseAwsEntries:
    """AWS b0 价目表的解析：卡数折算、按 family 过滤、不采集未收录规格。"""

    @staticmethod
    def _payload(entries: list) -> dict:
        box = {}
        for itype, family, price in entries:
            box[f"{itype.replace('.', ' ')} US East N. Virginia Linux"] = {
                "Instance Type": itype,
                "Instance Family": family,
                "price": price,
            }
        return {"manifest": {"currencyCode": "USD"}, "regions": {"US East (N. Virginia)": box}}

    def test_eight_card_instance_is_split_per_gpu(self) -> None:
        quotes = parse_aws_entries(
            self._payload([("p5.48xlarge", "GPU instance", "55.0400000000")]), region="us-east-1"
        )
        q = quotes[0]
        assert (q.provider, q.gpu_code, q.region) == ("AWS", "H100", "us-east-1")
        assert q.gpu_count == 8
        assert q.usd_per_gpu_hour == D("6.88")

    def test_same_per_gpu_price_across_sizes(self) -> None:
        """p5 一个 1 卡一个 8 卡，折算后应同为 6.88 —— 这是「卡数没数错」的证据。"""
        quotes = parse_aws_entries(
            self._payload(
                [
                    ("p5.4xlarge", "GPU instance", "6.88"),
                    ("p5.48xlarge", "GPU instance", "55.04"),
                ]
            ),
            region="us-east-1",
        )
        assert {q.usd_per_gpu_hour for q in quotes} == {D("6.88")}

    def test_skips_non_gpu_family(self) -> None:
        quotes = parse_aws_entries(
            self._payload([("m7g.xlarge", "General purpose", "0.1632")]), region="us-east-1"
        )
        assert quotes == []

    def test_skips_blocked_family_g6e(self) -> None:
        """g6e(L40S) 各规格折算价差 2.4 倍，feed 不自洽，整族不收录。"""
        quotes = parse_aws_entries(
            self._payload(
                [
                    ("g6e.16xlarge", "GPU instance", "7.5771900000"),
                    ("g6e.48xlarge", "GPU instance", "30.1311800000"),
                ]
            ),
            region="us-east-1",
        )
        assert quotes == []

    def test_skips_unmapped_instance(self) -> None:
        """p3(V100) 不在本库 GPU 型号里，不建行也不猜。"""
        quotes = parse_aws_entries(
            self._payload([("p3.16xlarge", "GPU instance", "24.48")]), region="us-east-1"
        )
        assert quotes == []

    @pytest.mark.parametrize("bad", [None, "", "0", "-1", "abc", "NaN"])
    def test_skips_invalid_price(self, bad: object) -> None:
        quotes = parse_aws_entries(
            self._payload([("p5.48xlarge", "GPU instance", bad)]), region="us-east-1"
        )
        assert quotes == []

    def test_missing_regions_returns_empty(self) -> None:
        assert parse_aws_entries({"manifest": {}}, region="us-east-1") == []
        assert parse_aws_entries({}, region="us-east-1") == []
