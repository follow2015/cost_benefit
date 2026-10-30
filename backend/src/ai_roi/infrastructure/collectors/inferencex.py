"""外部基准数据源适配器：InferenceX（SemiAnalysis）。

只做 IO：发请求、判状态码、交回原始 JSON。解析与合并规则在
``ai_roi.domain.inferencex``，持久化在用例层——三者分开才能离线单测、
也便于日后换源时只替换本文件。

为什么打 ``/api/v1/overview`` 而不是抓页面：
站点是 Next.js 客户端渲染，HTML 里没有任何基准数值（实测首页 179KB 只有营销文案），
图表数据全部来自该接口；抓页面只能拿到空壳。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

from ai_roi.domain.inferencex import SOURCE_ENDPOINT, SOURCE_SITE
from ai_roi.domain.errors import UpstreamUnavailableError

USER_AGENT = "ai-roi-benchmark-collector/1.0"
DEFAULT_ATTEMPTS = 2


class InferencexClient:
    """``/api/v1/overview`` 客户端。

    失败一律抛 ``UpstreamUnavailableError``（502 语义），由用例层决定
    「记录失败但保留旧数据」，绝不静默回退成空值。
    """

    def __init__(
        self,
        base_url: str = SOURCE_SITE,
        *,
        timeout: float = 30.0,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.attempts = max(1, int(attempts))
        self._transport = transport

    @property
    def endpoint(self) -> str:
        """完整接口地址（写入采集记录，便于事后核对口径）。"""
        return f"{self.base_url}{SOURCE_ENDPOINT}"

    async def fetch_overview(self) -> Dict[str, Any]:
        """拉取看板数据；返回已解压的 JSON 对象。"""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        last_error = ""
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=True
        ) as client:
            for attempt in range(1, self.attempts + 1):
                try:
                    response = await client.get(self.endpoint, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code == 200:
                        try:
                            payload = response.json()
                        except ValueError as exc:
                            raise UpstreamUnavailableError(
                                "InferenceX 返回的不是合法 JSON（接口结构可能已变更）",
                                {"url": self.endpoint, "reason": str(exc)},
                            ) from exc
                        if not isinstance(payload, dict):
                            raise UpstreamUnavailableError(
                                "InferenceX 返回结构不是对象（接口结构可能已变更）",
                                {"url": self.endpoint, "type": type(payload).__name__},
                            )
                        return payload
                    last_error = f"HTTP {response.status_code}"
                    if 400 <= response.status_code < 500:
                        break
                if attempt < self.attempts:
                    await asyncio.sleep(1.5 * attempt)

        raise UpstreamUnavailableError(
            "InferenceX 数据接口不可达，已保留上一次采集结果",
            {"url": self.endpoint, "reason": last_error, "attempts": self.attempts},
        )


__all__ = ["InferencexClient", "USER_AGENT"]
