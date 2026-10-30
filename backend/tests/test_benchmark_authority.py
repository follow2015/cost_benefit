"""基准库权威化：投票裁决 / 跨源匹配 / 解析器 单测（全离线）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ai_roi.domain.benchmark_authority import (
    Observation,
    VERDICT_CONFLICT,
    VERDICT_CONSENSUS,
    VERDICT_EMPTY,
    VERDICT_SINGLE,
    lookup,
    norm_key,
    relative_change,
    vote,
)
from ai_roi.domain.model_spec import infer_model_spec
from ai_roi.infrastructure.collectors.benchmark_sources import (
    SOURCE_LITELLM,
    SOURCE_MODELSDEV,
    SOURCE_OPENROUTER,
    SourceSnapshot,
    parse_litellm,
    parse_modelsdev,
    parse_openrouter,
)

D = Decimal


def _obs(source: str, i: str, o: str | None = None) -> Observation:
    return Observation(
        source=source, url=f"https://x/{source}", input_value=D(i),
        output_value=D(o) if o is not None else None,
    )


class TestVote:
    def test_no_observation(self) -> None:
        v = vote([])
        assert v.verdict == VERDICT_EMPTY
        assert v.input_value is None
        assert not v.applicable

    def test_single_source_medium_confidence(self) -> None:
        v = vote([_obs("a", "1.0", "2.0")])
        assert v.verdict == VERDICT_SINGLE
        assert v.confidence == "medium"
        assert v.input_value == D("1.0")
        assert not v.applicable
        assert v.needs_review

    def test_two_sources_agree(self) -> None:
        v = vote([_obs("a", "1.0", "2.0"), _obs("b", "1.0", "2.0")])
        assert v.verdict == VERDICT_CONSENSUS
        assert v.applicable
        assert v.agreement_ratio == 1.0

    def test_two_sources_differ_two_fold_is_conflict(self) -> None:
        """实测场景：deepseek-v4-pro 在 LiteLLM $1.32、models.dev $0.66。"""
        v = vote([_obs("litellm", "1.32", "3.96"), _obs("modelsdev", "0.66", "1.98")])
        assert v.verdict == VERDICT_CONFLICT
        assert v.input_value is None, "冲突时绝不能挑一个当结论"
        assert not v.applicable

    def test_same_input_but_output_differs_is_conflict(self) -> None:
        """输入价巧合相同不能骗过一致性判定。"""
        v = vote([_obs("a", "1.00", "2.00"), _obs("b", "1.00", "4.00")])
        assert v.verdict == VERDICT_CONFLICT

    def test_majority_wins_with_three_sources(self) -> None:
        v = vote([_obs("a", "3.30", "16.5"), _obs("b", "3.31", "16.5"), _obs("c", "9.9", "40")])
        assert v.verdict == VERDICT_CONSENSUS
        assert v.agreeing_sources == ("a", "b")
        assert v.input_value == D("3.305")
        assert round(v.agreement_ratio, 2) == 0.67

    def test_tolerance_boundary(self) -> None:
        v = vote([_obs("a", "1.000"), _obs("b", "1.015")])
        assert v.verdict == VERDICT_CONFLICT
        v2 = vote([_obs("a", "1.000"), _obs("b", "1.015")], rel_tolerance=D("0.02"))
        assert v2.verdict == VERDICT_CONSENSUS

    def test_relative_change(self) -> None:
        assert relative_change(D("2"), D("3")) == D("0.5")
        assert relative_change(D("0"), D("3")) is None
        assert relative_change(None, D("3")) is None


class TestDimensionWiseVote:
    """输入价与输出价分别裁决：一处分歧不该连累另一处的明确结论。"""

    def test_input_agrees_but_output_conflicts(self) -> None:
        """实测场景：deepseek-v3.2 三源输入价同为 $0.28，输出价 0.40 / 0.42。"""
        v = vote([_obs("litellm", "0.28", "0.40"), _obs("openrouter", "0.28", "0.42")])
        assert v.verdict == VERDICT_CONFLICT
        assert not v.applicable
        assert v.in_verdict == VERDICT_CONSENSUS
        assert v.input_value == D("0.28")
        assert v.input_agreeing == ("litellm", "openrouter")
        assert v.out_verdict == VERDICT_CONFLICT
        assert v.output_value is None
        assert v.partial is True

    def test_full_consensus_is_not_partial(self) -> None:
        v = vote([_obs("a", "1.0", "2.0"), _obs("b", "1.0", "2.0")])
        assert v.verdict == VERDICT_CONSENSUS
        assert v.partial is False
        assert v.to_dict()["input_verdict"] == VERDICT_CONSENSUS

    def test_absolute_tolerance_absorbs_cent_jitter(self) -> None:
        """便宜价位档上 1% 只有 $0.0015，靠绝对容差吸收半分钱抖动。"""
        v = vote([_obs("a", "0.15", "0.60"), _obs("b", "0.152", "0.60")])
        assert v.in_verdict == VERDICT_CONSENSUS
        v2 = vote([_obs("a", "10.00", "30"), _obs("b", "10.152", "30")])
        assert v2.verdict == VERDICT_CONFLICT

    def test_output_only_in_one_source_is_single_not_conflict(self) -> None:
        """三源都有输入价、只有一源报输出价：输出维度是「单一来源」不是「冲突」。"""
        v = vote([
            _obs("a", "1.00", None),
            _obs("b", "1.00", None),
            _obs("c", "1.00", "2.00"),
        ])
        assert v.in_verdict == VERDICT_CONSENSUS
        assert v.out_verdict == VERDICT_SINGLE
        assert v.output_agreeing == ("c",)
        assert v.verdict == VERDICT_SINGLE
        assert v.output_value == D("2.00")

    def test_no_output_anywhere_stays_consensus(self) -> None:
        """全都没报输出价时，不该把整条拉成 no_data。"""
        v = vote([_obs("a", "1.0"), _obs("b", "1.0")])
        assert v.verdict == VERDICT_CONSENSUS
        assert v.out_verdict == VERDICT_EMPTY
        assert v.input_value == D("1.0")


class TestLookup:
    def test_norm_key_unifies_space_and_underscore(self) -> None:
        assert norm_key("DeepSeek-V4-Pro") == norm_key("deepseek v4 pro")
        assert norm_key("deepseek_v4_pro") == norm_key("DeepSeek-V4-Pro")

    def test_norm_key_keeps_dot_to_avoid_collision(self) -> None:
        """`qwen3-8b` 与 `qwen3.8-8b` 是不同的模型，不能归一到同一个键。"""
        assert norm_key("qwen3-8b") != norm_key("qwen3.8-8b")

    def test_alias_resolution(self) -> None:
        lit = SourceSnapshot(
            source=SOURCE_LITELLM, url="u", fetched_at="",
            entries={(norm_key("deepseek"), norm_key("deepseek-v4-pro")): _obs("litellm", "1.32")},
        )
        md = SourceSnapshot(
            source=SOURCE_MODELSDEV, url="u", fetched_at="",
            entries={(norm_key("deepseek"), norm_key("deepseek-v4-pro")): _obs("modelsdev", "0.66")},
        )
        obs = lookup([lit, md], "DeepSeek", "deepseek-v4-pro")
        assert {o.source for o in obs} == {"litellm", "modelsdev"}

    def test_unknown_provider_returns_empty(self) -> None:
        snap = SourceSnapshot(source=SOURCE_LITELLM, url="u", fetched_at="", entries={})
        assert lookup([snap], "不存在的厂商", "x") == []

    def test_one_observation_per_source(self) -> None:
        lit = SourceSnapshot(
            source=SOURCE_LITELLM, url="u", fetched_at="",
            entries={
                (norm_key("moonshot"), norm_key("kimi-k2.5")): _obs("litellm", "0.6"),
                (norm_key("moonshotai"), norm_key("kimi-k2.5")): _obs("litellm", "0.7"),
            },
        )
        obs = lookup([lit], "Kimi", "kimi-k2.5")
        assert len(obs) == 1


class TestParsers:
    def test_litellm_converts_per_token_to_per_mtok(self) -> None:
        snap = parse_litellm({"deepseek/deepseek-v4-pro": {
            "input_cost_per_token": 1.32e-06, "output_cost_per_token": 3.96e-06,
        }})
        o = snap.entries[(norm_key("deepseek"), norm_key("deepseek-v4-pro"))]
        assert o.input_value == D("1.3200")
        assert o.output_value == D("3.9600")

    def test_litellm_prefers_official_over_aggregator(self) -> None:
        snap = parse_litellm({
            "azure/gpt-5": {"input_cost_per_token": 9e-06, "output_cost_per_token": 9e-06},
            "openai/gpt-5": {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06},
        })
        keys = {k for k in snap.entries}
        o = snap.entries[(norm_key("openai"), norm_key("gpt-5"))]
        assert o.input_value == D("1.0000")

    def test_litellm_skips_variant_suffix(self) -> None:
        snap = parse_litellm({"openai/gpt-5:free": {"input_cost_per_token": 0}})
        assert snap.entries == {}

    def test_modelsdev_reads_cost_block(self) -> None:
        snap = parse_modelsdev({"deepseek": {"models": {"deepseek-v4-pro": {
            "cost": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
            "limit": {"context": 1048576},
        }}}})
        o = snap.entries[(norm_key("deepseek"), norm_key("deepseek-v4-pro"))]
        assert o.input_value == D("0.66")
        assert o.extra["context"] == 1048576
        assert o.extra["cache"] == "0.022"

    def test_openrouter_converts_and_normalizes_cache(self) -> None:
        snap = parse_openrouter({"data": [{
            "id": "deepseek/deepseek-v4-pro",
            "pricing": {"prompt": "0.00000066", "completion": "0.00000198", "input_cache_read": "0.000000022"},
            "context_length": 1048576,
        }]})
        o = snap.entries[(norm_key("deepseek"), norm_key("deepseek-v4-pro"))]
        assert o.input_value == D("0.6600")
        assert D(o.extra["cache"]) == D("0.0220")


class TestModelSpec:
    @pytest.mark.parametrize(
        ("name", "is_moe", "active"),
        [
            ("Kimi K3（2.8T MoE/104B 激活，原生多模态）", True, D("104")),
            ("DeepSeek-V4-Pro（1.6T MoE/49B 激活）", True, D("49")),
            ("Qwen3-235B（A22B MoE）", True, D("22")),
            ("Qwen3.8-27B（稠密）", False, None),
            ("GLM-5.2（743B MoE）", True, None),
            ("Llama-70B", None, None),
        ],
    )
    def test_infer(self, name: str, is_moe: bool | None, active: Decimal | None) -> None:
        g = infer_model_spec(name)
        assert g.is_moe is is_moe
        assert g.active_params_b == active

    def test_active_implies_moe(self) -> None:
        g = infer_model_spec("Foo（49B 激活）")
        assert g.is_moe is True

    def test_dense_contradiction_drops_active(self) -> None:
        g = infer_model_spec("Foo（稠密，37B 激活）")
        assert g.is_moe is False
        assert g.active_params_b is None

    def test_empty(self) -> None:
        assert not infer_model_spec("").has_any


class _Row:
    """API 价 DTO 的最小替身（只用到 status() 关心的四个字段）。"""

    def __init__(
        self,
        source: str,
        as_of: Any = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.as_of = as_of
        self.meta = meta or {}


class _TinyRepo:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    async def list_api_prices(self, tenant_id: Any) -> list[_Row]:
        return self.rows


class _TinyUoW:
    def __init__(self, rows: list[_Row]) -> None:
        self.benchmarks = _TinyRepo(rows)


class TestAuthorityStatus:
    """状态接口：纯读库，回答「同步到哪天了、还剩多少条人工值」。"""

    async def test_counts_authority_coverage(self) -> None:
        from ai_roi.application.use_cases.benchmark_authority_service import (
            BenchmarkAuthorityService,
        )

        rows = [
            _Row("authority:modelsdev ×6.68", date(2026, 10, 28), {"authority_synced_at": "2026-10-28T03:00:00Z"}),
            _Row("authority:litellm ×6.68", date(2026, 10, 28), {"authority_synced_at": "2026-10-28T04:00:00Z"}),
            _Row("web:2026-08 USD1.25/10×6.76", date(2026, 8, 1)),
        ]
        svc = BenchmarkAuthorityService(_TinyUoW(rows), client=None, current_fx=D("6.68"))
        st = await svc.status()

        assert st["total"] == 3
        assert st["from_authority"] == 2
        assert st["manual"] == 1
        assert st["fx_usd_cny"] == "6.68"
        assert st["as_of"] == "2026-10-28"
        assert st["last_synced_at"] == "2026-10-28T04:00:00Z"

    async def test_empty_library(self) -> None:
        from ai_roi.application.use_cases.benchmark_authority_service import (
            BenchmarkAuthorityService,
        )

        st = await BenchmarkAuthorityService(_TinyUoW([]), client=None).status()
        assert st["total"] == 0
        assert st["as_of"] is None
        assert st["last_synced_at"] is None
