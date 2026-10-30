"""基准库回滚的差异计算（纯函数，不触库）。

回滚只提交「与快照不同」的字段：多提交会把用户后来有意保留的改动一起冲掉，
少提交则回滚不完整。这里钉住四条边界：数值、日期、快照空值、未知列。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from ai_roi.application.use_cases.benchmark_service import diff_snapshot


def _row(**kwargs: Any) -> SimpleNamespace:
    """伪造一条 ORM 行（只用到属性访问）。"""
    return SimpleNamespace(**kwargs)


def _gpu_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=7,
        code="H100",
        name="NVIDIA H100",
        vendor="NVIDIA",
        price_cny=Decimal("250000"),
        tdp_w=Decimal("700"),
        vram_gb=Decimal("80"),
        rent_cny_per_hour=Decimal("18"),
        source="官方",
        as_of=date(2026, 1, 1),
        version=3,
        meta={},
    )
    base.update(overrides)
    return _row(**base)


_SNAPSHOT = {
    "id": 7,
    "code": "H100",
    "name": "NVIDIA H100",
    "vendor": "NVIDIA",
    "price_cny": "250000",
    "tdp_w": "700",
    "vram_gb": "80.00",
    "rent_cny_per_hour": "18",
    "source": "官方",
    "as_of": "2026-01-01",
    "version": 1,
    "is_builtin": False,
    "meta": {},
}


def test_identical_row_produces_no_diff() -> None:
    """数值按 Decimal 比较、日期按 ISO 比较：`80` 与 `80.00` 不算差异。"""
    assert diff_snapshot("gpus", _gpu_row(), _SNAPSHOT) == {}


def test_numeric_and_text_changes_are_detected() -> None:
    row = _gpu_row(price_cny=Decimal("222222"), name="改过的名字", version=4)
    assert diff_snapshot("gpus", row, _SNAPSHOT) == {
        "price_cny": "250000",
        "name": "NVIDIA H100",
    }


def test_date_change_is_detected() -> None:
    row = _gpu_row(as_of=date(2026, 6, 1))
    assert diff_snapshot("gpus", row, _SNAPSHOT) == {"as_of": "2026-01-01"}


def test_null_in_snapshot_never_overwrites_current_value() -> None:
    """快照里为空表示「当时未填」，不能拿 NULL 去覆盖现值（数值列多为可空，覆盖会引入约束风险）。"""
    snapshot = dict(_SNAPSHOT, rent_cny_per_hour=None)
    row = _gpu_row(rent_cny_per_hour=Decimal("20"))
    assert diff_snapshot("gpus", row, snapshot) == {}


def test_control_fields_and_unknown_keys_are_ignored() -> None:
    """id/version/is_builtin 由服务端决定；快照里多出的非列字段直接忽略。"""
    snapshot = dict(_SNAPSHOT, version=99, is_builtin=True, not_a_column="x")
    assert diff_snapshot("gpus", _gpu_row(version=3), snapshot) == {}


def test_cloud_price_uses_composite_identity() -> None:
    def cloud_row(**kwargs: Any) -> SimpleNamespace:
        base = dict(
            id=3,
            provider="阿里云",
            gpu_code="H100",
            region="cn",
            price_cny_per_hour=Decimal("20"),
            include_power=True,
            include_hosting=False,
            billing_mode="hourly",
            rent_inc="power",
            source="官网",
            as_of=date(2026, 1, 1),
            version=2,
            meta={},
        )
        base.update(kwargs)
        return _row(**base)

    snapshot = {
        "id": 3,
        "provider": "阿里云",
        "gpu_code": "H100",
        "region": "cn",
        "price_cny_per_hour": "18",
        "include_power": True,
        "include_hosting": True,
        "billing_mode": "hourly",
        "rent_inc": "power",
        "source": "官网",
        "as_of": "2026-01-01",
        "version": 1,
        "meta": {},
    }
    assert diff_snapshot("cloud-prices", cloud_row(), snapshot) == {
        "price_cny_per_hour": "18",
        "include_hosting": True,
    }
