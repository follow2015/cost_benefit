"""`as_of` 推断规则的单测（`ai_roi.domain.as_of`）。

这些断言的意义在于**守住「不造假」这条底线**：宁可承认「不知道」（None），
也不要把「8 月看到的价格」写成「8 月 1 日的价格」。
"""

from __future__ import annotations

from datetime import date

from ai_roi.domain.as_of import (
    STALE_DAYS,
    has_explicit_day,
    infer_as_of,
    is_auto_source,
    staleness_days,
)


class TestInferAsOf:
    def test_explicit_day_is_used_as_is(self) -> None:
        assert infer_as_of("web:智谱官方 2026-08-14（编程+50%）") == date(2026, 8, 14)
        assert infer_as_of("web:阿里开源 2026-08-13（262K 原生可延 1M）") == date(2026, 8, 13)
        assert infer_as_of("web:Moonshot 2026-07-16 开源（1M 上下文）") == date(2026, 7, 16)

    def test_month_only_falls_back_to_month_end(self) -> None:
        assert infer_as_of("web:JYGPU 2026-08") == date(2026, 8, 31)
        assert infer_as_of("web:2026-06") == date(2026, 6, 30)
        assert infer_as_of("seed+web:2026-08") == date(2026, 8, 31)
        assert infer_as_of("web:2028-02") == date(2028, 2, 29)
        assert infer_as_of("web:2026-02") == date(2026, 2, 28)

    def test_no_date_means_unknown(self) -> None:
        assert infer_as_of("seed") is None
        assert infer_as_of("") is None
        assert infer_as_of(None) is None

    def test_digits_glued_to_other_text_are_not_dates(self) -> None:
        assert infer_as_of("web:20260801") is None
        assert infer_as_of("batch 12026-08 x") is None

    def test_invalid_calendar_date_returns_none(self) -> None:
        assert infer_as_of("web:2026-02-30") is None
        assert infer_as_of("web:2026-13") is None


class TestAutoSource:
    def test_auto_prefixes_are_recognised(self) -> None:
        assert is_auto_source("inferencex:2026-10-28") is True
        assert is_auto_source("authority:modelsdev ×6.68") is True

    def test_manual_sources_are_not_auto(self) -> None:
        assert is_auto_source("web:2026-08") is False
        assert is_auto_source("seed") is False
        assert is_auto_source("") is False
        assert is_auto_source(None) is False


class TestHasExplicitDay:
    def test_distinguishes_day_level_evidence(self) -> None:
        assert has_explicit_day("web:2026-08-14") is True
        assert has_explicit_day("web:2026-08") is False
        assert has_explicit_day("seed") is False


class TestStaleness:
    def test_counts_days_since(self) -> None:
        assert staleness_days(date(2026, 8, 31), date(2026, 10, 28)) == 58
        assert staleness_days(date(2026, 8, 31), date(2026, 8, 31)) == 0

    def test_unknown_is_not_stale(self) -> None:
        assert staleness_days(None, date(2026, 10, 28)) is None

    def test_future_date_is_treated_as_unknown(self) -> None:
        assert staleness_days(date(2027, 1, 1), date(2026, 10, 28)) is None

    def test_threshold_is_quarterly(self) -> None:
        assert STALE_DAYS == 90
