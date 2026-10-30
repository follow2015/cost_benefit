"""InferenceX 采集链路单测：解析 / 合并 / 周期判定 / HTTP 容错。

全部离线：解析用真实接口结构的精简样本，HTTP 用 ``httpx.MockTransport``，
不依赖外网与数据库——采集功能的失败模式恰恰发生在网络和结构变更时，
这些必须能稳定复现，不能靠"跑一次真站点"来验证。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
import pytest

from ai_roi.application.use_cases.inferencex_sync_service import (
    InferencexSyncService,
)
from ai_roi.domain.errors import UpstreamUnavailableError
from ai_roi.domain.inferencex import (
    META_AS_OF,
    META_COST_CNY,
    META_COST_USD,
    META_MANUAL_SOURCE,
    META_SYNCED_AT,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
    merge_model_meta,
    normalize_code,
    parse_overview,
    resolve_hardware,
    resolve_scenario,
)
from ai_roi.infrastructure.collectors.inferencex import InferencexClient

PAYLOAD: Dict[str, Any] = {
    "models": [
        {
            "model": "DeepSeek-V4-Pro",
            "modelLabel": "DeepSeek V4 Pro 0813 1.6T",
            "scenario": "agentx",
            "platforms": [
                {
                    "hardware": "b200",
                    "hardwareLabel": "B200",
                    "precision": "fp4",
                    "costPerMtok": 0.00728371560167419,
                    "config": {
                        "latestDate": "2026-10-23",
                        "sourceRunUrls": [
                            "https://github.com/SemiAnalysisAI/InferenceX/actions/runs/1"
                        ],
                    },
                },
                {
                    "hardware": "b300",
                    "hardwareLabel": "B300",
                    "precision": "fp4",
                    "costPerMtok": None,
                    "missingReason": "no_exact_at_tier",
                    "config": {},
                },
                {
                    "hardware": "gb300",
                    "hardwareLabel": "GB300 NVL72",
                    "precision": "fp4",
                    "costPerMtok": 0.00481,
                    "config": {"latestDate": "2026-10-21"},
                },
            ],
        },
        {
            "model": "Qwen-3.5-397B-A17B",
            "modelLabel": "Qwen 3.5 397B A17B",
            "scenario": "single_turn_8k1k",
            "platforms": [
                {
                    "hardware": "b200",
                    "hardwareLabel": "B200",
                    "precision": "fp4",
                    "costPerMtok": 0.04916821756866927,
                    "config": {"latestDate": "2026-10-24"},
                }
            ],
        },
    ]
}

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DeepSeek-V4-Pro", "deepseek-v4-pro"),
        ("Qwen-3.5-397B-A17B", "qwen-3.5-397b-a17b"),
        ("GB200 NVL72", "gb200-nvl72"),
        ("MiniMax-M3.1-Flash", "minimax-m3.1-flash"),
        ("  Kimi-K3  ", "kimi-k3"),
        ("Qwen3.8-Flash-Next", "qwen3.8-flash-next"),
    ],
)
def test_normalize_code(raw: str, expected: str) -> None:
    """上游模型名归一：小写、非字母数字转横线、保留点号。"""
    assert normalize_code(raw) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("B200", "B200"),
        ("B300", "B300"),
        ("GB200 NVL72", "GB200_NVL72"),
        ("GB300 NVL72", "GB300_NVL72"),
        ("MI355X", "MI355X"),
        ("TPUv7 Ironwood", "TPUv7 Ironwood"),
    ],
)
def test_resolve_hardware(label: str, expected: str) -> None:
    assert resolve_hardware(label) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("agentx", "AgentX"),
        ("single_turn_8k1k", "8K/1K"),
        ("8k1k", "8K/1K"),
        ("some_new_scenario", "some_new_scenario"),
    ],
)
def test_resolve_scenario(raw: str, expected: str) -> None:
    assert resolve_scenario(raw) == expected


def test_parse_overview_maps_real_payload() -> None:
    """真实载荷能解析出成本点，且缺值平台计入 skipped 而非编造。"""
    parsed = parse_overview(PAYLOAD)

    assert parsed.model_count == 2
    assert parsed.platform_count == 4
    assert parsed.skipped == 1
    assert len(parsed.points) == 3

    b200 = next(
        p for p in parsed.points if p.model_code == "deepseek-v4-pro" and p.hardware_code == "B200"
    )
    assert b200.scenario == "AgentX"
    assert b200.usd_per_mtok == Decimal("0.00728371560167419")
    assert b200.evidence_date == date(2026, 10, 23)
    assert b200.run_urls and b200.run_urls[0].startswith("https://github.com/SemiAnalysisAI")

    nvl72 = next(p for p in parsed.points if p.hardware_code == "GB300_NVL72")
    assert nvl72.scenario == "AgentX"

    qwen = next(p for p in parsed.points if p.model_code == "qwen-3.5-397b-a17b")
    assert qwen.scenario == "8K/1K"


def test_parse_overview_rejects_zero_and_negative_cost() -> None:
    """0 / 负数不是有效成本（会让毛利爆表），一律丢弃。"""
    payload = {
        "models": [
            {
                "model": "X",
                "scenario": "agentx",
                "platforms": [
                    {"hardwareLabel": "B200", "costPerMtok": 0},
                    {"hardwareLabel": "B300", "costPerMtok": -1.5},
                    {"hardwareLabel": "B200", "costPerMtok": "abc"},
                ],
            }
        ]
    }
    parsed = parse_overview(payload)
    assert parsed.points == ()
    assert parsed.skipped == 3
    assert parsed.warnings


def test_parse_overview_survives_schema_change() -> None:
    """上游把 models 改成对象（而非数组）时，返回空结果 + 警告，不抛异常。"""
    parsed = parse_overview({"models": {"DeepSeek": {}}})
    assert parsed.points == ()
    assert parsed.warnings
    assert "不是数组" in parsed.warnings[0]


def _merge(points: Any, existing: Optional[Dict[str, Any]] = None, fx: str = "7.2"):
    return merge_model_meta(
        existing,
        points,
        fx_usd_cny=Decimal(fx),
        synced_at=datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc),
        source_url="https://inferencex.semianalysis.com",
    )


def test_merge_into_empty_meta() -> None:
    """首次合并：USD 原值 + CNY 派生 + as_of 取证据日期。"""
    parsed = parse_overview(PAYLOAD)
    points = [p for p in parsed.points if p.model_code == "deepseek-v4-pro"]
    merged = _merge(points)

    usd = merged.meta[META_COST_USD]
    assert usd["B200"]["AgentX"] == pytest.approx(0.00728371560167419)
    assert usd["GB300_NVL72"]["AgentX"] == pytest.approx(0.00481)

    assert Decimal(merged.meta[META_COST_CNY]["B200"]["AgentX"]) == (
        Decimal("0.00728371560167419") * Decimal("7.2")
    )
    assert merged.meta[META_AS_OF] == "2026-10-23"
    assert merged.added == 2
    assert merged.updated == 0


def test_merge_keeps_absent_combinations() -> None:
    """上游本次缺某组合时保留旧值——缺口不该让历史标杆消失。"""
    existing = {
        META_COST_USD: {"B200": {"AgentX": 0.02, "8K/1K": 0.3}},
        META_COST_CNY: {"B200": {"AgentX": "0.144", "8K/1K": "2.16"}},
    }
    parsed = parse_overview(PAYLOAD)
    points = [p for p in parsed.points if p.model_code == "deepseek-v4-pro"]
    merged = _merge(points, existing)

    usd = merged.meta[META_COST_USD]
    assert usd["B200"]["8K/1K"] == 0.3
    assert usd["B200"]["AgentX"] == pytest.approx(0.00728371560167419)
    assert merged.updated == 1
    assert merged.added == 1


def test_merge_falls_back_to_sync_date_without_evidence_date() -> None:
    """上游有成本值却不带日期时，as_of 回退采集日。

    实测真实接口就是这样：有 ``costPerMtok`` 的平台 ``config`` 是空对象。
    若只认证据日期，界面会永远停在人工 seed 的旧日期上（2026-08-01）。
    """
    payload = {
        "models": [
            {
                "model": "DeepSeek-V4-Pro",
                "scenario": "agentx",
                "platforms": [{"hardwareLabel": "B200", "costPerMtok": 0.008, "config": {}}],
            }
        ]
    }
    merged = _merge(parse_overview(payload).points)

    assert merged.as_of == date(2026, 10, 28)
    assert merged.meta[META_AS_OF] == "2026-10-28"
    assert "inferencex_evidence_date" not in merged.meta


def test_merge_detects_no_change() -> None:
    """同值重采：added/updated 均为 0，避免把"刷新"刷成版本噪音。"""
    parsed = parse_overview(PAYLOAD)
    points = [p for p in parsed.points if p.model_code == "deepseek-v4-pro"]
    first = _merge(points)
    second = _merge(points, first.meta)

    assert second.added == 0
    assert second.updated == 0
    assert second.unchanged == 2
    assert second.meta[META_AS_OF] == "2026-10-23"
    assert META_SYNCED_AT in second.meta


def _client(handler, attempts: int = 2) -> InferencexClient:
    return InferencexClient(
        "https://inferencex.semianalysis.com",
        transport=httpx.MockTransport(handler),
        attempts=attempts,
        timeout=5.0,
    )


async def test_client_returns_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("ai-roi-benchmark-collector")
        return httpx.Response(200, json=PAYLOAD)

    client = _client(handler)
    payload = await client.fetch_overview()
    assert payload["models"][0]["model"] == "DeepSeek-V4-Pro"
    assert client.endpoint.endswith("/api/v1/overview")


async def test_client_does_not_retry_4xx() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"error": "not found"})

    with pytest.raises(UpstreamUnavailableError) as excinfo:
        await _client(handler, attempts=3).fetch_overview()

    assert calls["n"] == 1
    assert "HTTP 404" in str(excinfo.value.detail.get("reason"))


async def test_client_retries_then_raises_on_network_error() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(UpstreamUnavailableError):
        await _client(handler, attempts=2).fetch_overview()

    assert calls["n"] == 2


async def test_client_rejects_non_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(UpstreamUnavailableError) as excinfo:
        await _client(handler).fetch_overview()
    assert "JSON" in excinfo.value.message


class _FakeRun:
    """采集记录替身：字段与 ORM 行同构（缺字段会掩盖真实缺陷，故给全默认值）。"""

    _next_id = 1

    _DEFAULTS: Dict[str, Any] = {
        "tenant_id": None,
        "source": "inferencex",
        "endpoint": "",
        "trigger": "scheduled",
        "status": "running",
        "started_at": datetime(2026, 10, 28, tzinfo=timezone.utc),
        "finished_at": None,
        "as_of": None,
        "model_count": 0,
        "platform_count": 0,
        "point_count": 0,
        "matched_count": 0,
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "error": "",
        "detail": {},
    }

    def __init__(self, **values: Any) -> None:
        self.id = _FakeRun._next_id
        _FakeRun._next_id += 1
        self.__dict__.update({**self._DEFAULTS, **values})


class _FakeRuns:
    """采集记录仓储替身：只实现用例用到的方法。"""

    def __init__(self, existing: Optional[List[_FakeRun]] = None) -> None:
        self.rows: List[_FakeRun] = list(existing or [])
        self.locked = True

    async def record(self, **values: Any) -> _FakeRun:
        row = _FakeRun(**values)
        self.rows.append(row)
        return row

    async def latest(self, *, include_skipped: bool = True):
        return self.rows[-1] if self.rows else None

    async def latest_effective(self):
        rows = [r for r in self.rows if r.status != STATUS_SKIPPED]
        return rows[-1] if rows else None

    async def latest_success(self):
        rows = [r for r in self.rows if r.status == STATUS_SUCCESS]
        return rows[-1] if rows else None

    async def list_recent(self, limit: int = 20):
        return self.rows[-limit:]

    async def try_lock(self, key: int) -> bool:
        return self.locked

    async def unlock(self, key: int) -> None:
        return None


class _FakeModel:
    def __init__(
        self,
        code: str,
        meta: Optional[Dict[str, Any]] = None,
        source: str = "web:2026-08",
    ) -> None:
        self.code = code
        self.meta: Dict[str, Any] = dict(meta or {})
        self.as_of: Optional[date] = None
        self.source = source


class _FakeBenchmarks:
    def __init__(self, models: Dict[str, _FakeModel]) -> None:
        self.models = models

    async def find_builtin_model(self, code: str):
        return self.models.get(code)


class _FakeSession:
    async def flush(self) -> None:
        return None


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    async def write(self, **values: Any) -> None:
        self.entries.append(values)


class _FakeUoW:
    def __init__(self, models: Dict[str, _FakeModel], runs: Optional[_FakeRuns] = None):
        self.benchmarks = _FakeBenchmarks(models)
        self.inferencex_runs = runs or _FakeRuns()
        self.audit = _FakeAudit()
        self.session = _FakeSession()


class _FakeClient:
    def __init__(self, payload: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        self.endpoint = "https://inferencex.semianalysis.com/api/v1/overview"
        self._payload = payload or PAYLOAD
        self._error = error
        self.calls = 0

    async def fetch_overview(self) -> Dict[str, Any]:
        self.calls += 1
        if self._error:
            raise UpstreamUnavailableError(self._error, {"reason": "down"})
        return self._payload


def _service(uow: _FakeUoW, client: Any, *, now: Optional[datetime] = None,
             interval_days: int = 7) -> InferencexSyncService:
    return InferencexSyncService(
        uow,
        client,
        fx_usd_cny=Decimal("7.2"),
        interval_days=interval_days,
        now=now or datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc),
    )


async def test_run_writes_back_matched_models() -> None:
    uow = _FakeUoW(
        {
            "deepseek-v4-pro": _FakeModel("deepseek-v4-pro"),
            "qwen-3.5-397b-a17b": _FakeModel("qwen-3.5-397b-a17b"),
        }
    )
    client = _FakeClient()
    outcome = await _service(uow, client).run(trigger=TRIGGER_MANUAL, force=True)

    assert outcome.status == STATUS_SUCCESS
    assert outcome.matched_count == 2
    assert outcome.point_count == 3
    assert outcome.added == 3
    assert uow.benchmarks.models["deepseek-v4-pro"].as_of == date(2026, 10, 23)
    assert outcome.as_of == date(2026, 10, 24)
    assert META_COST_USD in uow.benchmarks.models["deepseek-v4-pro"].meta


async def test_run_updates_source_and_keeps_manual_origin() -> None:
    """采集必须同时刷新 `source`，否则界面上「来源」永远停在人工录入值。

    原人工依据转存 `meta.manual_source`，且**只留最早那一条**——
    第二次采集时 source 已是 `inferencex:`，不该再被覆盖成上一次的自动值。
    """
    model = _FakeModel("deepseek-v4-pro", source="web:2026-08")
    uow = _FakeUoW({"deepseek-v4-pro": model})
    await _service(uow, _FakeClient()).run(trigger=TRIGGER_MANUAL, force=True)

    assert model.source == "inferencex:2026-10-23"
    assert model.meta[META_MANUAL_SOURCE] == "web:2026-08"

    await _service(uow, _FakeClient()).run(trigger=TRIGGER_MANUAL, force=True)
    assert model.source == "inferencex:2026-10-23"
    assert model.meta[META_MANUAL_SOURCE] == "web:2026-08"


async def test_run_reports_unmatched_models_without_failing() -> None:
    """上游有、库里无的模型只告警不失败（否则每次采集都是"失败"）。"""
    uow = _FakeUoW({"deepseek-v4-pro": _FakeModel("deepseek-v4-pro")})
    outcome = await _service(uow, _FakeClient()).run(trigger=TRIGGER_MANUAL, force=True)

    assert outcome.status == STATUS_SUCCESS
    assert outcome.unmatched == ["qwen-3.5-397b-a17b"]
    assert any("无同名 code" in item for item in outcome.warnings)


async def test_run_fails_when_nothing_matches() -> None:
    uow = _FakeUoW({})
    outcome = await _service(uow, _FakeClient()).run(trigger=TRIGGER_MANUAL, force=True)

    assert outcome.status == STATUS_FAILED
    assert "无交集" in outcome.error
    assert uow.inferencex_runs.rows[-1].status == STATUS_FAILED


async def test_run_keeps_old_data_when_upstream_down() -> None:
    """上游挂掉：返回 failed + 原因，且不触碰已有数据。"""
    model = _FakeModel("deepseek-v4-pro", {META_COST_USD: {"B200": {"AgentX": 0.02}}})
    uow = _FakeUoW({"deepseek-v4-pro": model})
    outcome = await _service(uow, _FakeClient(error="InferenceX 数据接口不可达")).run(
        trigger=TRIGGER_MANUAL, force=True
    )

    assert outcome.status == STATUS_FAILED
    assert "不可达" in outcome.error
    assert model.meta[META_COST_USD]["B200"]["AgentX"] == 0.02
    assert model.as_of is None


async def test_scheduled_run_skips_within_interval() -> None:
    """定时触发（force=False）在周期内直接跳过，且不落库、不发请求。"""
    recent = _FakeRun(
        status=STATUS_SUCCESS,
        started_at=datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc),
        trigger="scheduled",
    )
    runs = _FakeRuns([recent])
    uow = _FakeUoW({"deepseek-v4-pro": _FakeModel("deepseek-v4-pro")}, runs)
    client = _FakeClient()

    outcome = await _service(
        uow, client, now=datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc)
    ).run(trigger="scheduled", force=False)

    assert outcome.status == STATUS_SKIPPED
    assert client.calls == 0
    assert len(runs.rows) == 1
    assert outcome.next_run_at == datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)


async def test_scheduled_run_executes_after_interval() -> None:
    """超过 7 天则定时任务真正执行（重启后补采依赖这条）。"""
    stale = _FakeRun(
        status=STATUS_SUCCESS,
        started_at=datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc),
        trigger="scheduled",
    )
    uow = _FakeUoW({"deepseek-v4-pro": _FakeModel("deepseek-v4-pro")}, _FakeRuns([stale]))
    client = _FakeClient()

    outcome = await _service(uow, client).run(trigger="scheduled", force=False)

    assert outcome.status == STATUS_SUCCESS
    assert client.calls == 1


async def test_run_skips_when_lock_held_by_another_worker() -> None:
    """并发保护：拿不到锁就跳过，绝不并行写同一批模型。"""
    runs = _FakeRuns()
    runs.locked = False
    uow = _FakeUoW({"deepseek-v4-pro": _FakeModel("deepseek-v4-pro")}, runs)
    client = _FakeClient()

    outcome = await _service(uow, client).run(trigger=TRIGGER_MANUAL, force=True)

    assert outcome.status == STATUS_SKIPPED
    assert "正在执行" in outcome.error
    assert client.calls == 0


async def test_status_reports_interval_and_next_run() -> None:
    """状态接口：给出周期、上次结果、下次计划时间与是否到期。"""
    last = _FakeRun(
        status=STATUS_SUCCESS,
        started_at=datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc),
        trigger=TRIGGER_MANUAL,
        point_count=21,
        matched_count=4,
        added=2,
        updated=1,
        error="",
    )
    uow = _FakeUoW({}, _FakeRuns([last]))
    status = await _service(uow, _FakeClient()).status()

    assert status["interval_days"] == 7
    assert status["source_url"].startswith("https://inferencex.semianalysis.com")
    assert status["due"] is False
    assert status["next_run_at"].startswith("2026-11-02")
    assert status["last"]["point_count"] == 21
