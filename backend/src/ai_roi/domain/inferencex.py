"""InferenceX（SemiAnalysis）公开基准的解析与合并规则。

数据源：``https://inferencex.semianalysis.com`` 的 ``/api/v1/overview``
（站点「Inference Performance」看板的数据接口，返回 model → platforms →
``costPerMtok`` 的完整矩阵）。

口径对齐（与 ``scripts/seed_inferencex.py`` 一致，勿改）：
- ``costPerMtok`` = USD / 百万**总** token（prefill + decode + cache），即站点
  ``y_costh`` 成本侧，属 hyperscaler 最优 serving 包络，**不是对外售价**；
- 本项目本位币 CNY，落库前经 ``fx`` 折算，并保留 USD 原值便于核对；
- 场景映射：站点 ``agentx`` → ``AgentX``、``single_turn_8k1k`` → ``8K/1K``。

本模块只做纯计算（解析 / 归一化 / 合并），不触网、不触库，便于离线单测；
HTTP 与持久化分别在 ``infrastructure.collectors`` 与用例层完成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ai_roi.domain.calc.decimal_config import D, dec_str

SOURCE_ID = "inferencex"
SOURCE_NAME = "InferenceX（SemiAnalysis）"
SOURCE_SITE = "https://inferencex.semianalysis.com"
SOURCE_ENDPOINT = "/api/v1/overview"
DEFAULT_INTERVAL_DAYS = 7

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

STATUS_LABELS: Dict[str, str] = {
    STATUS_RUNNING: "采集中",
    STATUS_SUCCESS: "采集成功",
    STATUS_PARTIAL: "部分成功",
    STATUS_FAILED: "采集失败",
    STATUS_SKIPPED: "已跳过",
}

META_COST_USD = "inferencex_cost_usd_per_mtok"
META_COST_CNY = "cost_benchmark_cny_per_mtok"
META_AS_OF = "inferencex_as_of"
META_EVIDENCE_DATE = "inferencex_evidence_date"
META_SYNCED_AT = "inferencex_synced_at"
META_SOURCE_URL = "inferencex_source_url"
META_MANUAL_SOURCE = "manual_source"

SOURCE_ROW_PREFIX = "inferencex:"

META_UPSTREAM_MODELS = "upstream_models"

COVERAGE_COVERED = "covered"
COVERAGE_NO_VALUE = "no_value"
COVERAGE_UNTESTED = "untested"
COVERAGE_UNKNOWN = "unknown"

COVERAGE_LABELS: Dict[str, str] = {
    COVERAGE_COVERED: "已采到",
    COVERAGE_NO_VALUE: "上游无值",
    COVERAGE_UNTESTED: "上游不测",
    COVERAGE_UNKNOWN: "未采集",
}

HARDWARE_ALIASES: Dict[str, str] = {
    "b200": "B200",
    "b300": "B300",
    "gb200-nvl72": "GB200_NVL72",
    "gb300-nvl72": "GB300_NVL72",
    "gb200": "GB200_NVL72",
    "gb300": "GB300_NVL72",
    "mi355x": "MI355X",
    "mi350x": "MI350X",
    "mi325x": "MI325X",
    "mi300x": "MI300X",
    "h200": "H200",
    "h100": "H100",
    "a100": "A100",
}

SCENARIO_ALIASES: Dict[str, str] = {
    "agentx": "AgentX",
    "single-turn-8k1k": "8K/1K",
    "8k1k": "8K/1K",
    "single-turn": "8K/1K",
}


def normalize_code(raw: str) -> str:
    """把上游名归一为项目内的 code 形态。

    规则：小写、非字母数字（保留点号）统一转 ``-``、去掉首尾横线。
    例：``DeepSeek-V4-Pro`` → ``deepseek-v4-pro``；
    ``Qwen-3.5-397B-A17B`` → ``qwen-3.5-397b-a17b``（点号保留，与库内 code 一致）；
    ``GB200 NVL72`` → ``gb200-nvl72``。
    """
    text = re.sub(r"[^a-z0-9.]+", "-", str(raw).strip().lower())
    return text.strip("-")


def resolve_hardware(label: str) -> str:
    """硬件标签 → 基准库 GPU code；未知型号原样保留（便于人工核对）。"""
    key = normalize_code(label)
    return HARDWARE_ALIASES.get(key, str(label).strip())


def resolve_scenario(raw: str) -> str:
    """场景标签 → 项目内场景名；未知场景原样保留。"""
    key = normalize_code(raw)
    return SCENARIO_ALIASES.get(key, str(raw).strip())


@dataclass(frozen=True)
class CostPoint:
    """一个「模型 × 硬件 × 场景」的成本观测点。"""

    model_slug: str
    model_code: str
    hardware_code: str
    scenario: str
    usd_per_mtok: Decimal
    evidence_date: Optional[date] = None
    run_urls: Tuple[str, ...] = ()
    precision: str = ""


@dataclass(frozen=True)
class ParseOutcome:
    """解析结果（含被跳过的脏数据计数，便于观测上游质量）。"""

    points: Tuple[CostPoint, ...]
    model_count: int = 0
    platform_count: int = 0
    skipped: int = 0
    warnings: Tuple[str, ...] = ()
    model_slugs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeOutcome:
    """合并结果：新 meta 与各类变更计数。"""

    meta: Dict[str, Any] = field(default_factory=dict)
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    as_of: Optional[date] = None
    model_slug: str = ""


def _to_date(raw: Any) -> Optional[date]:
    """宽松解析 ``YYYY-MM-DD`` / ISO 时间戳；非法返回 None。"""
    if not raw:
        return None
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_decimal(raw: Any) -> Optional[Decimal]:
    """把上游数值转 Decimal；``None``/非数/非正值一律视为不可用。"""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = D(str(raw))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def parse_overview(payload: Mapping[str, Any]) -> ParseOutcome:
    """解析 ``/api/v1/overview`` 载荷为成本观测点列表。

    只接受有 ``costPerMtok`` 的正值平台；缺失/为 0 的缺口（上游 ``missingReason``
    如 ``no_exact_at_tier``）计入 ``skipped``，不编造替代值。
    """
    models = payload.get("models") or []
    points: list[CostPoint] = []
    slugs: list[str] = []
    skipped = 0
    platform_count = 0
    warnings: list[str] = []

    if not isinstance(models, (list, tuple)):
        return ParseOutcome(points=(), warnings=("models 字段不是数组，载荷结构可能已变更",))

    for entry in models:
        if not isinstance(entry, Mapping):
            skipped += 1
            continue
        slug = str(entry.get("model") or "").strip()
        if not slug:
            skipped += 1
            continue
        if slug not in slugs:
            slugs.append(slug)
        model_code = normalize_code(slug)
        scenario = resolve_scenario(str(entry.get("scenario") or ""))
        platforms = entry.get("platforms") or []
        if not isinstance(platforms, (list, tuple)):
            skipped += 1
            continue
        for platform in platforms:
            platform_count += 1
            if not isinstance(platform, Mapping):
                skipped += 1
                continue
            usd = _to_decimal(platform.get("costPerMtok"))
            if usd is None:
                skipped += 1
                continue
            hardware_label = str(
                platform.get("hardwareLabel") or platform.get("hardware") or ""
            ).strip()
            if not hardware_label:
                skipped += 1
                continue
            config = platform.get("config") or {}
            if not isinstance(config, Mapping):
                config = {}
            run_urls = tuple(
                str(url)
                for url in (config.get("sourceRunUrls") or [])
                if isinstance(url, str) and url.startswith("http")
            )
            points.append(
                CostPoint(
                    model_slug=slug,
                    model_code=model_code,
                    hardware_code=resolve_hardware(hardware_label),
                    scenario=scenario,
                    usd_per_mtok=usd,
                    evidence_date=_to_date(config.get("latestDate")),
                    run_urls=run_urls,
                    precision=str(platform.get("precision") or ""),
                )
            )

    if platform_count and not points:
        warnings.append("全部平台均无可用成本值（上游可能处于数据缺口期）")

    return ParseOutcome(
        points=tuple(points),
        model_count=len(models) if isinstance(models, (list, tuple)) else 0,
        platform_count=platform_count,
        skipped=skipped,
        warnings=tuple(warnings),
        model_slugs=tuple(slugs),
    )


def group_by_model(points: Iterable[CostPoint]) -> Dict[str, list[CostPoint]]:
    """按归一化模型 code 分组（保持上游顺序）。"""
    grouped: Dict[str, list[CostPoint]] = {}
    for point in points:
        grouped.setdefault(point.model_code, []).append(point)
    return grouped


def merge_model_meta(
    existing: Optional[Mapping[str, Any]],
    points: Iterable[CostPoint],
    *,
    fx_usd_cny: Decimal,
    synced_at: datetime,
    source_url: str = SOURCE_SITE,
) -> MergeOutcome:
    """把采集点合并进模型 ``meta``（就地语义：返回新 dict，不改入参）。

    合并规则（关键，勿随意改）：
    - 同一 ``hardware × scenario`` **覆盖**为新值（上游为权威成本侧）；
    - 本次未出现的组合**保留**旧值（上游偶发缺口不该让历史标杆消失）；
    - ``cost_benchmark_cny_per_mtok`` 是全量重算的派生视图，跟随 USD 表同步；
    - ``inferencex_as_of`` = 本次证据日期最大值，**证据日期缺失时回退为采集日**
      （实测上游有成本值的平台 ``config`` 是空对象、不带 ``latestDate``，
      若坚持只认证据日期，界面会永远停在人工 seed 的旧日期上）；
    - ``inferencex_evidence_date`` 单独保留上游给的证据日期，二者不混用；
      ``inferencex_synced_at`` 是采集时刻。
    """
    meta: Dict[str, Any] = dict(existing or {})
    cost_usd: Dict[str, Dict[str, Any]] = {
        hw: dict(scen_map)
        for hw, scen_map in (meta.get(META_COST_USD) or {}).items()
        if isinstance(scen_map, Mapping)
    }

    added = updated = unchanged = 0
    latest: Optional[date] = None
    slug = ""

    for point in points:
        if not slug:
            slug = point.model_slug
        bucket = cost_usd.setdefault(point.hardware_code, {})
        previous = bucket.get(point.scenario)
        if previous is None:
            added += 1
        elif dec_str(D(str(previous))) != dec_str(point.usd_per_mtok):
            updated += 1
        else:
            unchanged += 1
        bucket[point.scenario] = float(point.usd_per_mtok)
        if point.evidence_date and (latest is None or point.evidence_date > latest):
            latest = point.evidence_date

    cost_cny: Dict[str, Dict[str, str]] = {}
    for hardware, scen_map in cost_usd.items():
        cost_cny[hardware] = {
            scenario: dec_str(D(str(usd)) * fx_usd_cny)
            for scenario, usd in scen_map.items()
        }

    meta[META_COST_USD] = cost_usd
    meta[META_COST_CNY] = cost_cny
    effective_as_of = latest or synced_at.date()
    meta[META_AS_OF] = effective_as_of.isoformat()
    if latest is not None:
        meta[META_EVIDENCE_DATE] = latest.isoformat()
    meta[META_SYNCED_AT] = synced_at.isoformat()
    meta[META_SOURCE_URL] = source_url
    if slug:
        meta["inferencex_model_slug"] = slug

    return MergeOutcome(
        meta=meta,
        added=added,
        updated=updated,
        unchanged=unchanged,
        as_of=effective_as_of,
        model_slug=slug,
    )


@dataclass(frozen=True)
class UpstreamModel:
    """上游本次清单里的一个模型（含一个成本点都没有的）。"""

    slug: str
    code: str
    point_count: int = 0
    scenarios: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """落进采集记录 ``detail`` 的形态（纯 JSON 可序列化）。"""
        return {
            "slug": self.slug,
            "code": self.code,
            "point_count": self.point_count,
            "scenarios": list(self.scenarios),
        }


@dataclass(frozen=True)
class ModelCoverage:
    """一条模型基准行的采集覆盖判决。"""

    code: str
    status: str
    slug: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "label": COVERAGE_LABELS.get(self.status, self.status),
            "slug": self.slug,
            "detail": self.detail,
        }


def build_upstream_inventory(parsed: ParseOutcome) -> Tuple[UpstreamModel, ...]:
    """把一次解析结果压成「上游模型清单」。

    以 ``model_slugs`` 为骨架而非 ``points`` 分组：一个成本点都没有的模型
    也必须留在清单里，否则界面无法把「上游在测但本次没值」和「上游根本不测」
    区分开——两者对用户的含义完全不同（前者等下次采集，后者只能人工维护）。
    """
    counts: Dict[str, int] = {}
    scenarios: Dict[str, list[str]] = {}
    for point in parsed.points:
        counts[point.model_code] = counts.get(point.model_code, 0) + 1
        bucket = scenarios.setdefault(point.model_code, [])
        if point.scenario and point.scenario not in bucket:
            bucket.append(point.scenario)

    inventory: list[UpstreamModel] = []
    for slug in parsed.model_slugs:
        code = normalize_code(slug)
        inventory.append(
            UpstreamModel(
                slug=slug,
                code=code,
                point_count=counts.get(code, 0),
                scenarios=tuple(scenarios.get(code, ())),
            )
        )
    return tuple(inventory)


def inventory_from_dicts(raw: Any) -> Tuple[UpstreamModel, ...]:
    """从采集记录里还原清单（脏数据一律丢弃，不让它污染判决）。"""
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[UpstreamModel] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code") or "").strip()
        slug = str(item.get("slug") or "").strip()
        if not code and not slug:
            continue
        try:
            points = int(item.get("point_count") or 0)
        except (TypeError, ValueError):
            points = 0
        scenarios = item.get("scenarios")
        out.append(
            UpstreamModel(
                slug=slug or code,
                code=code or normalize_code(slug),
                point_count=max(0, points),
                scenarios=tuple(str(s) for s in scenarios)
                if isinstance(scenarios, (list, tuple))
                else (),
            )
        )
    return tuple(out)


def classify_model_coverage(
    rows: Iterable[Tuple[str, bool]],
    inventory: Iterable[UpstreamModel],
    *,
    judgeable: bool = True,
) -> list[ModelCoverage]:
    """逐行判定「模型基准这一条，上游到底管不管」。

    Args:
        rows: ``(模型 code, 本行是否已有成本标杆值)``。
        inventory: 最近一次成功采集的上游模型清单。
        judgeable: 清单是否可用；空清单或旧采集记录（未存清单）时为 False。

    判决口径（顺序即优先级，勿调换）：
        1. 本行有值 → ``covered``：数据已经在库里，无需再看上游；
        2. 清单不可用 → ``unknown``：不下结论，别把「没采过」说成「上游不测」；
        3. 清单里有、但本次 0 个成本点 → ``no_value``：上游在测，本次没给值；
        4. 清单里没有 → ``untested``：上游这一轮根本没测这个模型。

    第 3 与第 4 是本次要分开的两件事：前者等下一轮，后者换任何数据源都一样。
    """
    by_code = {item.code: item for item in inventory}
    total = len(by_code)
    out: list[ModelCoverage] = []
    for code, has_value in rows:
        key = str(code or "").strip()
        if has_value:
            out.append(ModelCoverage(key, COVERAGE_COVERED, detail="上游已采到成本值"))
            continue
        if not judgeable or total == 0:
            out.append(
                ModelCoverage(
                    key,
                    COVERAGE_UNKNOWN,
                    detail="没有可用的上游模型清单（尚未成功采集，或旧采集记录未存清单）",
                )
            )
            continue
        hit = by_code.get(normalize_code(key))
        if hit is None:
            out.append(
                ModelCoverage(
                    key,
                    COVERAGE_UNTESTED,
                    detail=f"上游本次只返回 {total} 个模型，其中没有它",
                )
            )
        elif hit.point_count > 0:
            out.append(
                ModelCoverage(
                    key,
                    COVERAGE_NO_VALUE,
                    slug=hit.slug,
                    detail=f"上游「{hit.slug}」本次有 {hit.point_count} 个成本点，但没写进本行",
                )
            )
        else:
            out.append(
                ModelCoverage(
                    key,
                    COVERAGE_NO_VALUE,
                    slug=hit.slug,
                    detail=f"上游在测「{hit.slug}」，但本次没有可用成本值（上游缺口，等下一轮）",
                )
            )
    return out


__all__ = [
    "DEFAULT_INTERVAL_DAYS",
    "HARDWARE_ALIASES",
    "COVERAGE_COVERED",
    "COVERAGE_LABELS",
    "COVERAGE_NO_VALUE",
    "COVERAGE_UNKNOWN",
    "COVERAGE_UNTESTED",
    "META_UPSTREAM_MODELS",
    "ModelCoverage",
    "UpstreamModel",
    "build_upstream_inventory",
    "classify_model_coverage",
    "inventory_from_dicts",
    "META_AS_OF",
    "META_EVIDENCE_DATE",
    "META_COST_CNY",
    "META_COST_USD",
    "META_MANUAL_SOURCE",
    "META_SOURCE_URL",
    "META_SYNCED_AT",
    "SCENARIO_ALIASES",
    "SOURCE_ENDPOINT",
    "SOURCE_ID",
    "SOURCE_NAME",
    "SOURCE_ROW_PREFIX",
    "SOURCE_SITE",
    "STATUS_FAILED",
    "STATUS_LABELS",
    "STATUS_PARTIAL",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "STATUS_SUCCESS",
    "TRIGGER_MANUAL",
    "TRIGGER_SCHEDULED",
    "CostPoint",
    "MergeOutcome",
    "ParseOutcome",
    "group_by_model",
    "merge_model_meta",
    "normalize_code",
    "parse_overview",
    "resolve_hardware",
    "resolve_scenario",
]
