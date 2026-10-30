"""基准数据权威源采集器：LiteLLM / models.dev / OpenRouter。

三个源都是**机器可读、业界通用**的模型价格与规格清单，互为交叉验证：

| 源 | 内容 | 获取方式 | 注意 |
|---|---|---|---|
| LiteLLM | 4324 条，厂商直连挂牌价 + 上下文 | jsDelivr CDN 上的仓库文件 | GitHub raw 在国内不可达；Contents API 超 1MB 会截断，故必须走 CDN 且支持断点续传 |
| models.dev | 232 家 provider，含 cost/limit | `models.dev/api.json` | 与 LiteLLM 存在成体系的 2 倍差异，必须投票 |
| OpenRouter | 464 个可调用模型，含实时 pricing | `openrouter.ai/api/v1/models` | 价格按 per-token 给出，需 ×1e6 归一 |

**只做采集与归一，不做裁决**——裁决在 `domain.benchmark_authority.vote`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

import httpx

from ai_roi.domain.benchmark_authority import (
    PROVIDER_ALIASES,
    Observation,
    lookup,
    norm_key,
)

logger = logging.getLogger(__name__)

SOURCE_LITELLM = "litellm"
SOURCE_MODELSDEV = "modelsdev"
SOURCE_OPENROUTER = "openrouter"
SOURCE_ERAPI = "er-api"
SOURCE_EXCHANGERATE = "exchangerate-api"

SOURCE_LABELS: Dict[str, str] = {
    SOURCE_LITELLM: "LiteLLM 价格表",
    SOURCE_MODELSDEV: "models.dev",
    SOURCE_OPENROUTER: "OpenRouter",
    SOURCE_ERAPI: "open.er-api.com",
    SOURCE_EXCHANGERATE: "exchangerate-api.com",
}

URL_ERAPI = "https://open.er-api.com/v6/latest/USD"
URL_EXCHANGERATE = "https://api.exchangerate-api.com/v4/latest/USD"

URL_LITELLM = (
    "https://cdn.jsdelivr.net/gh/BerriAI/litellm@main/"
    "model_prices_and_context_window.json"
)
URL_MODELSDEV = "https://models.dev/api.json"
URL_OPENROUTER = "https://openrouter.ai/api/v1/models"

_AGGREGATOR_PREFIXES = {
    "bedrock", "azure", "azure_ai", "vertex_ai", "openrouter", "together",
    "fireworks", "groq", "deepinfra", "replicate", "cloudflare", "databricks",
    "sagemaker", "bedrock_converse", "vertex_ai_beta", "vercel_ai_gateway",
}

_REGION_MARKERS = ("us.", "eu.", "apac.", "global.", "us-gov.")


@dataclass(frozen=True)
class SourceSnapshot:
    """一个源的一次抓取结果。"""

    source: str
    url: str
    fetched_at: str
    entries: Mapping[Tuple[str, str], Observation]
    ambiguous: Tuple[str, ...] = ()
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _norm(text: str) -> str:
    """归一化（与 domain 侧同一实现，保证键一致）。"""
    return norm_key(text)


def _usd_mtok(per_token: Any) -> Optional[Decimal]:
    """per-token 美元价 → USD / 百万 token。"""
    if per_token in (None, "", 0, "0"):
        return None
    try:
        return (Decimal(str(per_token)) * Decimal(1_000_000)).quantize(Decimal("0.0001"))
    except Exception:
        return None


def parse_litellm(payload: Mapping[str, Any], url: str = URL_LITELLM) -> SourceSnapshot:
    """解析 LiteLLM 价格表。

    同一模型常有多个键（官方直连、各云市场、区域限定），按优先级取一个：
    官方直连 > 非聚合前缀 > 聚合商；同档取最短键（通常是规范名）。
    """
    buckets: Dict[Tuple[str, str], List[Tuple[int, int, Observation]]] = {}

    for key, raw in payload.items():
        if key == "sample_spec" or not isinstance(raw, Mapping):
            continue
        if ":" in key:
            continue

        parts = key.split("/")
        if len(parts) >= 2:
            prefix, model = parts[0], "/".join(parts[1:])
        else:
            prefix, model = "", key

        per_in = raw.get("input_cost_per_token")
        per_out = raw.get("output_cost_per_token")
        in_v = _usd_mtok(per_in)
        if in_v is None:
            continue
        out_v = _usd_mtok(per_out)

        if prefix.lower() in _AGGREGATOR_PREFIXES:
            rank_prefix = 2
        elif prefix:
            rank_prefix = 0
        else:
            rank_prefix = 1

        rank_region = 1 if any(m in key.lower() for m in _REGION_MARKERS) else 0
        rank_long = len(key)

        obs = Observation(
            source=SOURCE_LITELLM,
            url=url,
            input_value=in_v,
            output_value=out_v,
            extra={
                "vendor": prefix,
                "model": model,
                "source_key": key,
                "context": raw.get("max_input_tokens"),
                "cache": str(_usd_mtok(raw.get("cache_read_input_token_cost")))
                if raw.get("cache_read_input_token_cost")
                else None,
            },
        )
        buckets.setdefault((_norm(prefix), _norm(model)), []).append((rank_prefix, rank_region, rank_long, obs))

    entries: Dict[Tuple[str, str], Observation] = {}
    ambiguous: List[str] = []
    for k, cands in buckets.items():
        cands.sort(key=lambda c: (c[0], c[1], c[2]))
        best = cands[0][3]
        entries[k] = best
        if len(cands) > 1 and any(c[3].input_value != best.input_value for c in cands[1:]):
            ambiguous.append(k[1])

    return SourceSnapshot(
        source=SOURCE_LITELLM,
        url=url,
        fetched_at="",
        entries=entries,
        ambiguous=tuple(sorted(set(ambiguous))),
    )


def parse_modelsdev(payload: Mapping[str, Any], url: str = URL_MODELSDEV) -> SourceSnapshot:
    """解析 models.dev：provider → models → {cost:{input,output,cache_read}, limit:{context}}。

    models.dev 的 `cost` 单位已是 **USD / 百万 token**。
    """
    entries: Dict[Tuple[str, str], Observation] = {}
    for provider, block in payload.items():
        if not isinstance(block, Mapping):
            continue
        for model_code, m in (block.get("models") or {}).items():
            if not isinstance(m, Mapping):
                continue
            cost = m.get("cost") or {}
            raw_in = cost.get("input")
            if raw_in in (None, "", 0):
                continue
            try:
                in_v = Decimal(str(raw_in))
            except Exception:
                continue
            raw_out = cost.get("output")
            try:
                out_v = Decimal(str(raw_out)) if raw_out not in (None, "") else None
            except Exception:
                out_v = None

            limit = m.get("limit") or {}
            entries[(_norm(provider), _norm(model_code))] = Observation(
                source=SOURCE_MODELSDEV,
                url=url,
                input_value=in_v,
                output_value=out_v,
                extra={
                    "vendor": provider,
                    "model": model_code,
                    "context": limit.get("context"),
                    "cache": str(cost.get("cache_read")) if cost.get("cache_read") is not None else None,
                },
            )

    return SourceSnapshot(
        source=SOURCE_MODELSDEV, url=url, fetched_at="", entries=entries
    )


def parse_openrouter(payload: Mapping[str, Any], url: str = URL_OPENROUTER) -> SourceSnapshot:
    """解析 OpenRouter：data[].id 形如 `deepseek/deepseek-v4-pro`，pricing 为 per-token 字符串。"""
    entries: Dict[Tuple[str, str], Observation] = {}
    for item in payload.get("data") or []:
        if not isinstance(item, Mapping):
            continue
        ident = str(item.get("id") or "")
        if not ident or ":" in ident:
            continue
        parts = ident.split("/")
        prefix, model = (parts[0], "/".join(parts[1:])) if len(parts) >= 2 else ("", ident)
        pricing = item.get("pricing") or {}
        in_v = _usd_mtok(pricing.get("prompt"))
        if in_v is None:
            continue
        entries[(_norm(prefix), _norm(model))] = Observation(
            source=SOURCE_OPENROUTER,
            url=url,
            input_value=in_v,
            output_value=_usd_mtok(pricing.get("completion")),
            extra={
                "vendor": prefix,
                "model": model,
                "context": item.get("context_length"),
                "cache": str(_usd_mtok(pricing.get("input_cache_read")))
                if _usd_mtok(pricing.get("input_cache_read")) is not None
                else None,
            },
        )
    return SourceSnapshot(
        source=SOURCE_OPENROUTER, url=url, fetched_at="", entries=entries
    )


class AuthorityClient:
    """三个权威源的抓取客户端（带重试与断点续传）。"""

    _CACHE: Dict[str, "tuple[float, str]"] = {}

    def __init__(
        self,
        timeout: float = 90.0,
        user_agent: str = "ai-roi-benchmark-sync/1.0 (+internal)",
        cache_ttl: float = 600.0,
    ) -> None:
        self._timeout = timeout
        self._ua = user_agent
        self._cache_ttl = cache_ttl

    @classmethod
    def clear_cache(cls) -> None:
        """清空抓取缓存（测试与「强制刷新」用）。"""
        cls._CACHE.clear()

    async def _get_text(self, url: str, retries: int = 3) -> str:
        import time

        cached = self._CACHE.get(url)
        if cached is not None and time.time() - cached[0] < self._cache_ttl:
            return cached[1]

        last: Optional[Exception] = None
        headers = {"User-Agent": self._ua, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            for attempt in range(retries):
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    text = resp.text
                    json.loads(text)
                    self._CACHE[url] = (time.time(), text)
                    return text
                except Exception as exc:  # noqa: BLE001  逐次重试即可
                    last = exc
                    logger.warning(
                        "authority.fetch.retry", extra={"url": url, "attempt": attempt + 1, "err": str(exc)[:120]}
                    )
        raise RuntimeError(f"抓取失败（{retries} 次重试）：{url} :: {last}")

    async def fetch_litellm(self) -> SourceSnapshot:
        try:
            text = await self._get_text(URL_LITELLM)
            return parse_litellm(json.loads(text))
        except Exception as exc:  # noqa: BLE001
            return SourceSnapshot(SOURCE_LITELLM, URL_LITELLM, "", {}, (), str(exc)[:300])

    async def fetch_modelsdev(self) -> SourceSnapshot:
        try:
            text = await self._get_text(URL_MODELSDEV)
            return parse_modelsdev(json.loads(text))
        except Exception as exc:  # noqa: BLE001
            return SourceSnapshot(SOURCE_MODELSDEV, URL_MODELSDEV, "", {}, (), str(exc)[:300])

    async def fetch_openrouter(self) -> SourceSnapshot:
        try:
            text = await self._get_text(URL_OPENROUTER)
            return parse_openrouter(json.loads(text))
        except Exception as exc:  # noqa: BLE001
            return SourceSnapshot(SOURCE_OPENROUTER, URL_OPENROUTER, "", {}, (), str(exc)[:300])

    async def fetch_all(self) -> List[SourceSnapshot]:
        import asyncio

        return list(
            await asyncio.gather(
                self.fetch_litellm(),
                self.fetch_modelsdev(),
                self.fetch_openrouter(),
            )
        )

    async def _fx_one(self, source: str, url: str) -> Observation:
        try:
            text = await self._get_text(url, retries=2)
            payload = json.loads(text)
            rate = (payload.get("rates") or {}).get("CNY")
            if rate is None:
                raise ValueError("响应缺少 rates.CNY")
            return Observation(
                source=source,
                url=url,
                input_value=Decimal(str(rate)),
                extra={"unit": "CNY per USD"},
            )
        except Exception as exc:  # noqa: BLE001
            return Observation(
                source=source,
                url=url,
                input_value=Decimal(0),
                extra={"error": str(exc)[:160]},
            )

    async def fetch_fx(self) -> List[Observation]:
        """抓 USD→CNY 汇率（双源，供投票）。

        失败源以 `input_value = 0` 占位——投票时 0 不会与其他值聚类，
        自然被排除，不会污染中位数。
        """
        import asyncio

        return list(
            await asyncio.gather(
                self._fx_one(SOURCE_ERAPI, URL_ERAPI),
                self._fx_one(SOURCE_EXCHANGERATE, URL_EXCHANGERATE),
            )
        )


__all__ = [
    "AuthorityClient",
    "PROVIDER_ALIASES",
    "SOURCE_LABELS",
    "SOURCE_LITELLM",
    "SOURCE_MODELSDEV",
    "SOURCE_OPENROUTER",
    "SourceSnapshot",
    "URL_LITELLM",
    "URL_MODELSDEV",
    "URL_OPENROUTER",
    "lookup",
    "parse_litellm",
    "parse_modelsdev",
    "parse_openrouter",
]
