"""基准数据权威化：多源观测 → 投票裁决。

**为什么要投票而不是取单一源**：实测发现权威源之间会成倍分歧——
`deepseek-v4-pro` 在 LiteLLM 记 $1.32/$3.96，在 models.dev 记 $0.66/$1.98，
正好 2 倍。单源直采会把价格改错，且错误无声无息。因此本模块的原则是：

1. **≥2 源在容差内一致** → `consensus`，高置信，可自动应用；
2. **仅 1 源有数据** → `single_source`，中置信，应用需人工确认；
3. **≥2 源互相矛盾且无多数** → `conflict`，低置信，**拒绝自动应用**，
   把各方数值摆出来交人工裁决。

三个结论**按维度单独给出**（输入价、输出价各一套），整条取最差的那个。
把两个价格捆成一组投票会让一处小分歧连累另一处的明确结论，
`deepseek-v3.2` 就是活例：三源输入价同为 $0.28，只有输出价 0.40 / 0.42 不同。

宁可标「待裁决」，也不把一个可能是错的值写进基准库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

VERDICT_CONSENSUS = "consensus"
VERDICT_SINGLE = "single_source"
VERDICT_CONFLICT = "conflict"
VERDICT_EMPTY = "no_data"

VERDICT_LABELS: Dict[str, str] = {
    VERDICT_CONSENSUS: "多源一致",
    VERDICT_SINGLE: "单一来源",
    VERDICT_CONFLICT: "源间冲突",
    VERDICT_EMPTY: "无权威数据",
}

DEFAULT_REL_TOLERANCE = Decimal("0.01")

DEFAULT_ABS_TOLERANCE = Decimal("0.005")

SOURCE_AUTHORITY_PREFIX = "authority:"


@dataclass(frozen=True)
class Observation:
    """单一数据源对某条目的一条观测。"""

    source: str
    url: str
    input_value: Decimal
    output_value: Optional[Decimal] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def pair(self) -> Tuple[Decimal, Decimal]:
        return (self.input_value, self.output_value if self.output_value is not None else Decimal(0))


@dataclass(frozen=True)
class Vote:
    """投票裁决结果。

    输入价与输出价**分维度各自投票**——这点是重构的核心。
    旧实现把 (in, out) 当整体聚类：`deepseek-v3.2` 三源输入价全是 $0.28，
    仅输出价 0.40 / 0.42 有 5% 分歧，整条就被判「源间冲突」，
    连三源完全一致的输入价一起被废掉，等于因为右鞋有泥就把整双鞋扔了。
    分维度后：输入价 `consensus`（可采信），输出价 `conflict`（不采信），
    整条仍为 `conflict`（不自动应用），但人能看到到底哪一项有分歧。
    """

    verdict: str
    confidence: str
    input_value: Optional[Decimal]
    output_value: Optional[Decimal]
    agreeing_sources: Tuple[str, ...]
    observations: Tuple[Observation, ...]
    agreement_ratio: float
    input_verdict: str = ""
    output_verdict: str = ""
    input_agreeing: Tuple[str, ...] = ()
    output_agreeing: Tuple[str, ...] = ()

    @property
    def in_verdict(self) -> str:
        return self.input_verdict or self.verdict

    @property
    def out_verdict(self) -> str:
        return self.output_verdict or self.verdict

    @property
    def applicable(self) -> bool:
        """是否允许自动写入：只有多源一致才允许。"""
        return self.verdict == VERDICT_CONSENSUS

    @property
    def needs_review(self) -> bool:
        return self.verdict in (VERDICT_CONFLICT, VERDICT_SINGLE)

    @property
    def partial(self) -> bool:
        """部分维度可采信：整条不能自动应用，但存在确定的某一项。

        这类条目（如输入价三源一致、输出价分歧）不应被前端当成
        「完全没数据」隐藏，也不该让人手抄一致的那一半。
        """
        return self.verdict != VERDICT_CONSENSUS and (
            self.in_verdict == VERDICT_CONSENSUS or self.out_verdict == VERDICT_CONSENSUS
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_label": VERDICT_LABELS.get(self.verdict, self.verdict),
            "confidence": self.confidence,
            "input_value": str(self.input_value) if self.input_value is not None else None,
            "output_value": str(self.output_value) if self.output_value is not None else None,
            "input_verdict": self.in_verdict,
            "output_verdict": self.out_verdict,
            "input_verdict_label": VERDICT_LABELS.get(self.in_verdict, self.in_verdict),
            "output_verdict_label": VERDICT_LABELS.get(self.out_verdict, self.out_verdict),
            "input_agreeing": list(self.input_agreeing or self.agreeing_sources),
            "output_agreeing": list(self.output_agreeing),
            "partial": self.partial,
            "agreeing_sources": list(self.agreeing_sources),
            "agreement_ratio": round(self.agreement_ratio, 3),
            "applicable": self.applicable,
            "observations": [
                {
                    "source": o.source,
                    "url": o.url,
                    "input_value": str(o.input_value),
                    "output_value": str(o.output_value) if o.output_value is not None else None,
                    "extra": dict(o.extra),
                }
                for o in self.observations
            ],
        }


def _within(
    a: Decimal,
    b: Decimal,
    rel_tol: Decimal,
    abs_tol: Decimal = DEFAULT_ABS_TOLERANCE,
) -> bool:
    """同值判定：相对容差**或**绝对容差任一满足即可。

    两个都留是因为价格的「噪音尺度」同时受量级和最小计价单位影响：
    $0.15 与 $0.152 相差 1.3%（超相对容差），但只差半分钱；
    $10 与 $10.05 相差 0.5%（在相对容差内），却差了 5 分钱仍需人看一眼。
    取「或」而不是「且」，是为了让便宜模型的小数抖动不要反复制造伪冲突。
    """
    if a == b:
        return True
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    base = abs(b) if b != 0 else Decimal(1)
    return diff / base <= rel_tol


def _cluster(
    observations: Sequence[Observation],
    values: Sequence[Optional[Decimal]],
    rel_tol: Decimal,
    abs_tol: Decimal,
) -> List[List[Observation]]:
    """按给定维度贪心聚类，返回按组成员数降序、并列时靠前者优先的组列表。

    `values` 与 `observations` 一一对应；值为 None 的观测不参与该维度。
    """
    groups: List[List[Observation]] = []
    reps: List[Decimal] = []
    for obs, val in zip(observations, values):
        if val is None:
            continue
        for idx, rep in enumerate(reps):
            if _within(val, rep, rel_tol, abs_tol):
                groups[idx].append(obs)
                break
        else:
            groups.append([obs])
            reps.append(val)
    return [g for _, g in sorted(enumerate(groups), key=lambda p: (-len(p[1]), p[0]))]


def _judge_dimension(group: Sequence[Observation], dimension_size: int) -> str:
    """单维度结论。

    `dimension_size` 是**该维度实际有报价的源数**，不是整条的源数：
    三源都报了输入价却各不相同时，最大组只有 1 个，这是「源间冲突」；
    而三源里只有一源报了输出价时，那是「单一来源」，两者含义不同。
    """
    if not group:
        return VERDICT_EMPTY
    if len(group) >= 2:
        return VERDICT_CONSENSUS
    return VERDICT_SINGLE if dimension_size <= 1 else VERDICT_CONFLICT


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _dimension_value(
    group: Sequence[Observation],
    verdict: str,
    attr: str,
) -> Optional[Decimal]:
    """某维度的采信值。

    只有「多源一致」才可采信共用；「单一来源」（该维度只有一个源有报价）
    时值也是确定的——风险是未被交叉验证，而不是数值不确定，
    所以照样给值，但整条会落进 `needs_review`。
    多源冲突场景下最大组只有一个，不给值——孤证恰恰是最该被质疑的。
    """
    if verdict == VERDICT_CONSENSUS:
        vals = [getattr(o, attr) for o in group if getattr(o, attr) is not None]
        return _median(vals) if vals else None
    if verdict == VERDICT_SINGLE and group:
        return getattr(group[0], attr)
    return None


_VERDICT_SEVERITY = {
    VERDICT_CONSENSUS: 0,
    VERDICT_SINGLE: 1,
    VERDICT_EMPTY: 1,
    VERDICT_CONFLICT: 2,
}


def vote(
    observations: Sequence[Observation],
    rel_tolerance: Decimal = DEFAULT_REL_TOLERANCE,
    abs_tolerance: Decimal = DEFAULT_ABS_TOLERANCE,
) -> Vote:
    """对多条观测投票，输入价与输出价分别裁决。

    分组策略：按观测顺序贪心聚类（同组须与组代表同值），
    取成员最多的组；并列时取「首个来源优先级更高」的组（观测顺序即优先级）。

    整条结论取两个维度里**最差**的那个——任一维度不可信，整条就不能自动写库；
    但另一维度的采信值仍然保留，供人看到「哪一半是确定的」。
    """
    obs = tuple(observations)
    if not obs:
        return Vote(
            VERDICT_EMPTY, CONFIDENCE_LOW, None, None, (), (), 0.0,
            VERDICT_EMPTY, VERDICT_EMPTY,
        )

    in_groups = _cluster(obs, [o.input_value for o in obs], rel_tolerance, abs_tolerance)
    out_groups = _cluster(obs, [o.output_value for o in obs], rel_tolerance, abs_tolerance)

    in_best = in_groups[0] if in_groups else []
    out_best = out_groups[0] if out_groups else []

    in_verdict = _judge_dimension(in_best, sum(len(g) for g in in_groups))
    out_verdict = _judge_dimension(out_best, sum(len(g) for g in out_groups))

    if out_groups:
        verdict = max(
            (in_verdict, out_verdict), key=lambda v: _VERDICT_SEVERITY.get(v, 2)
        )
    else:
        verdict = in_verdict
    confidence = {
        VERDICT_CONSENSUS: CONFIDENCE_HIGH,
        VERDICT_SINGLE: CONFIDENCE_MEDIUM,
    }.get(verdict, CONFIDENCE_LOW)

    in_val = _dimension_value(in_best, in_verdict, "input_value")
    out_val = _dimension_value(out_best, out_verdict, "output_value")

    in_sources = tuple(o.source for o in in_best)
    out_sources = tuple(o.source for o in out_best)
    ratio = max(len(in_best), len(out_best)) / len(obs) if obs else 0.0

    return Vote(
        verdict=verdict,
        confidence=confidence,
        input_value=in_val,
        output_value=out_val,
        agreeing_sources=in_sources or out_sources,
        observations=obs,
        agreement_ratio=ratio,
        input_verdict=in_verdict,
        output_verdict=out_verdict,
        input_agreeing=in_sources,
        output_agreeing=out_sources,
    )


def relative_change(old: Optional[Decimal], new: Optional[Decimal]) -> Optional[Decimal]:
    """相对变动幅度 (new-old)/old；old 为 0 或 None 时返回 None。"""
    if old is None or new is None or old == 0:
        return None
    return (new - old) / old


PROVIDER_ALIASES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "OpenAI": (("openai",), ("openai",)),
    "Anthropic": (("anthropic",), ("anthropic",)),
    "Google": (("gemini", "vertex_ai"), ("google", "google-vertex")),
    "DeepSeek": (("deepseek",), ("deepseek",)),
    "Kimi": (("moonshot", "moonshotai"), ("moonshotai", "moonshotai-cn")),
    "MiniMax": (("minimax",), ("minimax", "minimax-cn")),
    "智谱": (("zai", "zhipu"), ("zai", "zhipuai")),
    "通义千问": (("dashscope", "qwen"), ("alibaba", "alibaba-cn")),
    "豆包": (("volcengine", "doubao"), ("volcengine",)),
    "百度文心": (("ernie", "baidu"), ("baidu",)),
}

MODELSDEV_SOURCE = "modelsdev"


class _HasEntries:
    """结构化类型提示：采集快照至少要有 source / entries 两个属性。

    用 `Protocol` 语义但以基类形式给出，避免 application 层为了标注
    反向依赖 infrastructure 的 dataclass。
    """

    source: str
    entries: Mapping[Tuple[str, str], Observation]


def norm_key(text: str) -> str:
    """归一化模型/厂商标识，使跨源同义写法可比。

    规则：小写；空格与下划线**统一为连字符**（不是删除——删除会让
    `qwen3-8b` 与 `qwen3.8-8b` 撞成同一个键）；保留 `.`（版本号有义），
    其余符号丢弃；压缩连续连字符。
    """
    s = (text or "").lower().strip()
    out: List[str] = []
    for ch in s:
        if ch.isalnum() or ch in ".-":
            out.append(ch)
        elif ch in " _":
            out.append("-")
    normalized = "".join(out)
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-")


def lookup(
    snapshots: Iterable[Any],
    provider: str,
    model_code: str,
) -> List[Observation]:
    """在多个采集快照里查找库内 `(provider, model_code)` 对应的观测。

    每个源最多返回一条；未登记别名的厂商直接返回空（宁可漏，不可错配）。
    """
    aliases = PROVIDER_ALIASES.get(provider)
    if not aliases:
        return []

    lit_prefixes, md_providers = aliases
    model_n = norm_key(model_code)
    found: Dict[str, Observation] = {}

    for snap in snapshots:
        entries = getattr(snap, "entries", None)
        if not entries:
            continue
        source = getattr(snap, "source", "")
        prefixes = md_providers if source == MODELSDEV_SOURCE else lit_prefixes
        for p in prefixes:
            obs = entries.get((norm_key(p), model_n))
            if obs is not None:
                found.setdefault(source, obs)
                break

    return list(found.values())


def format_change(old: Optional[Decimal], new: Optional[Decimal]) -> str:
    """人类可读的变动幅度，如 `+312.5%` / `-0.4%`。"""
    ch = relative_change(old, new)
    if ch is None:
        return "—"
    sign = "+" if ch > 0 else ""
    return f"{sign}{ch * 100:.1f}%"


__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "DEFAULT_ABS_TOLERANCE",
    "DEFAULT_REL_TOLERANCE",
    "MODELSDEV_SOURCE",
    "Observation",
    "PROVIDER_ALIASES",
    "VERDICT_CONFLICT",
    "VERDICT_CONSENSUS",
    "VERDICT_EMPTY",
    "VERDICT_LABELS",
    "VERDICT_SINGLE",
    "Vote",
    "format_change",
    "lookup",
    "norm_key",
    "relative_change",
    "vote",
]
