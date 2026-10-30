"""模型基准「采集覆盖」判决：把「本次缺数据」和「上游不测」分开。

为什么值得单测：这两个结论对用户的含义相反——
「本次缺数据」等下一轮就好，「上游不测」只能人工维护。
一旦判据写错，界面会给出一个看着确定、其实错误的结论，比不显示更糟。

全部离线：载荷用真实接口结构的裁剪样本（含一个成本点都没有的模型）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from ai_roi.application.use_cases.inferencex_sync_service import (
    InferencexSyncService,
)
from ai_roi.domain.inferencex import (
    COVERAGE_COVERED,
    COVERAGE_NO_VALUE,
    COVERAGE_UNKNOWN,
    COVERAGE_UNTESTED,
    META_COST_CNY,
    META_UPSTREAM_MODELS,
    build_upstream_inventory,
    classify_model_coverage,
    inventory_from_dicts,
    parse_overview,
)

PAYLOAD: Dict[str, Any] = {
    "models": [
        {
            "model": "Muse-Spark-Open",
            "scenario": "agentx",
            "platforms": [
                {"hardwareLabel": "B200", "costPerMtok": None},
                {"hardwareLabel": "B300", "missingReason": "no_exact_at_tier"},
            ],
        },
        {
            "model": "DeepSeek-V4-Pro",
            "scenario": "agentx",
            "platforms": [
                {
                    "hardwareLabel": "B200",
                    "costPerMtok": 0.0634,
                    "config": {"latestDate": "2026-10-28"},
                }
            ],
        },
        {
            "model": "Qwen-3.5-397B-A17B",
            "scenario": "agentx",
            "platforms": [{"hardwareLabel": "B200", "costPerMtok": 0.21}],
        },
        {
            "model": "Qwen-3.5-397B-A17B",
            "scenario": "single_turn_8k1k",
            "platforms": [{"hardwareLabel": "B200", "costPerMtok": 0.19}],
        },
    ]
}


def test_parse_keeps_models_without_any_cost_point() -> None:
    """零成本点的上游模型必须留在 model_slugs 里。"""
    parsed = parse_overview(PAYLOAD)
    assert parsed.model_count == 4
    assert parsed.model_slugs == (
        "Muse-Spark-Open",
        "DeepSeek-V4-Pro",
        "Qwen-3.5-397B-A17B",
    )
    assert len(parsed.points) == 3


def test_inventory_marks_zero_point_models() -> None:
    """清单里的 point_count=0 就是「上游在测但本次没值」的证据。"""
    inventory = build_upstream_inventory(parse_overview(PAYLOAD))
    by_slug = {item.slug: item for item in inventory}
    assert set(by_slug) == {"Muse-Spark-Open", "DeepSeek-V4-Pro", "Qwen-3.5-397B-A17B"}
    assert by_slug["Muse-Spark-Open"].point_count == 0
    assert by_slug["DeepSeek-V4-Pro"].point_count == 1
    assert by_slug["Qwen-3.5-397B-A17B"].point_count == 2
    assert by_slug["Qwen-3.5-397B-A17B"].scenarios == ("AgentX", "8K/1K")


def test_coverage_separates_no_value_from_untested() -> None:
    """核心断言：上游在测但没值 ≠ 上游不测。"""
    inventory = build_upstream_inventory(parse_overview(PAYLOAD))
    verdicts = {
        item.code: item
        for item in classify_model_coverage(
            [
                ("deepseek-v4-pro", True),
                ("muse-spark-open", False),
                ("qwen-3.5-397b-a17b", False),
            ],
            inventory,
        )
    }
    assert verdicts["deepseek-v4-pro"].status == COVERAGE_COVERED
    assert verdicts["muse-spark-open"].status == COVERAGE_NO_VALUE
    assert "没有可用成本值" in verdicts["muse-spark-open"].detail
    assert verdicts["qwen-3.5-397b-a17b"].status == COVERAGE_NO_VALUE
    assert "有 2 个成本点" in verdicts["qwen-3.5-397b-a17b"].detail


def test_coverage_says_untested_only_when_absent_from_inventory() -> None:
    inventory = build_upstream_inventory(parse_overview(PAYLOAD))
    verdicts = classify_model_coverage([("llama-70b", False)], inventory)
    assert verdicts[0].status == COVERAGE_UNTESTED
    assert "3 个模型" in verdicts[0].detail


def test_coverage_without_inventory_refuses_to_conclude() -> None:
    """没有清单就不下结论——别把「没采过」写成「上游不测」。"""
    assert classify_model_coverage([("llama-70b", False)], ())[0].status == COVERAGE_UNKNOWN
    assert (
        classify_model_coverage([("llama-70b", False)], (), judgeable=False)[0].status
        == COVERAGE_UNKNOWN
    )
    assert (
        classify_model_coverage([("deepseek-v4-pro", True)], (), judgeable=False)[0].status
        == COVERAGE_COVERED
    )


def test_inventory_roundtrip_and_garbage_tolerance() -> None:
    """清单要能从采集记录里原样还原，脏数据不能污染判决。"""
    inventory = build_upstream_inventory(parse_overview(PAYLOAD))
    raw = [item.to_dict() for item in inventory]
    assert inventory_from_dicts(raw) == inventory
    assert inventory_from_dicts(None) == ()
    assert inventory_from_dicts("oops") == ()
    assert inventory_from_dicts([1, "x", {}, {"slug": ""}]) == ()
    restored = inventory_from_dicts([{"slug": "DeepSeek-V4-Pro", "point_count": "bad"}])
    assert restored[0].code == "deepseek-v4-pro"
    assert restored[0].point_count == 0


class _Model:
    """模型基准行替身（只用 code 与 meta）。"""

    def __init__(self, code: str, cost: Optional[Dict[str, Any]] = None) -> None:
        self.code = code
        self.meta: Dict[str, Any] = {META_COST_CNY: cost} if cost is not None else {}


class _Run:
    def __init__(self, detail: Dict[str, Any], as_of: Optional[date] = None) -> None:
        self.id = 7
        self.detail = detail
        self.as_of = as_of


class _Benchmarks:
    def __init__(self, models: List[_Model]) -> None:
        self._models = models

    async def list_models(self, tenant_id: Optional[int]) -> List[_Model]:
        return self._models


class _Runs:
    def __init__(self, run: Optional[_Run]) -> None:
        self._run = run

    async def latest_success(self) -> Optional[_Run]:
        return self._run


class _UoW:
    def __init__(self, models: List[_Model], run: Optional[_Run]) -> None:
        self.benchmarks = _Benchmarks(models)
        self.inferencex_runs = _Runs(run)


def _service(models: List[_Model], run: Optional[_Run]) -> InferencexSyncService:
    return InferencexSyncService(_UoW(models, run), client=object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_service_reports_per_row_verdicts_and_summary() -> None:
    inventory = [item.to_dict() for item in build_upstream_inventory(parse_overview(PAYLOAD))]
    run = _Run(
        {META_UPSTREAM_MODELS: inventory, "unmatched": ["MiniMax-M3.1-Flash"]},
        as_of=date(2026, 10, 28),
    )
    service = _service(
        [
            _Model("deepseek-v4-pro", {"B200": {"AgentX": "0.42"}}),
            _Model("muse-spark-open"),
            _Model("llama-70b"),
        ],
        run,
    )

    data = await service.model_coverage(tenant_id=1)

    assert data["judgeable"] is True
    assert data["run_id"] == 7
    assert data["as_of"] == "2026-10-28"
    assert data["summary"] == {
        "total": 3,
        "covered": 1,
        "no_value": 1,
        "untested": 1,
        "unknown": 0,
    }
    assert data["upstream"]["model_count"] == 3
    assert data["upstream"]["with_value"] == 2
    assert data["upstream"]["without_value"] == ["Muse-Spark-Open"]
    assert data["upstream"]["unmatched"] == ["MiniMax-M3.1-Flash"]
    statuses = {row["code"]: row["status"] for row in data["rows"]}
    assert statuses["muse-spark-open"] == COVERAGE_NO_VALUE
    assert statuses["llama-70b"] == COVERAGE_UNTESTED


@pytest.mark.asyncio
async def test_service_marks_old_record_unjudgeable() -> None:
    """改动前的采集记录没有清单：只能判「未判定」，不能假装知道。"""
    run = _Run({"unmatched": ["MiniMax-M3.1-Flash"]}, as_of=date(2026, 10, 1))
    service = _service([_Model("llama-70b"), _Model("deepseek-v4-pro", {"B200": {}})], run)

    data = await service.model_coverage(tenant_id=1)

    assert data["judgeable"] is False
    assert data["summary"]["unknown"] == 1
    assert data["summary"]["covered"] == 1
    assert data["upstream"]["model_count"] == 0


@pytest.mark.asyncio
async def test_service_without_any_run_reports_unknown() -> None:
    service = _service([_Model("llama-70b")], None)
    data = await service.model_coverage(tenant_id=1)
    assert data["judgeable"] is False
    assert data["run_id"] is None
    assert data["summary"]["unknown"] == 1
