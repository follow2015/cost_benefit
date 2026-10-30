"""采集客户端的行为契约：URL 构造、结构校验、失败语义。

只用 ``httpx.MockTransport`` 打桩，不联网 —— 这里要固定的是「上游变形时我们的反应」，
而不是上游今天返回什么。真实链路由 e2e 覆盖。

重点在 AWS b0 这条：它的路径里带空格与括号（``US East (N. Virginia)``），
转义错一个字符就是 400，而错误信息只会说「HTTP 400」，很难倒推。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from ai_roi.domain.errors import UpstreamUnavailableError
from ai_roi.infrastructure.collectors.market_prices import AwsBulkPricingClient

OK_PAYLOAD: Dict[str, Any] = {
    "manifest": {"currencyCode": "USD", "serviceId": "ec2"},
    "regions": {
        "US East (N. Virginia)": {
            "p5 48xlarge US East N. Virginia Linux": {
                "Instance Type": "p5.48xlarge",
                "Instance Family": "GPU instance",
                "price": "55.0400000000",
            }
        }
    },
}


def _client(handler: Any, *, attempts: int = 1) -> AwsBulkPricingClient:
    return AwsBulkPricingClient(
        transport=httpx.MockTransport(handler), attempts=attempts, timeout=5.0
    )


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


class TestAwsUrl:
    def test_escapes_spaces_but_keeps_parentheses(self) -> None:
        url = AwsBulkPricingClient().url_for("US East (N. Virginia)")
        assert url.endswith("/US%20East%20(N.%20Virginia)/Linux/index.json")
        assert "%28" not in url


class TestAwsFetch:
    @pytest.mark.asyncio
    async def test_returns_payload(self) -> None:
        seen: List[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return _json_response(OK_PAYLOAD)

        payload = await _client(handler).fetch_region("US East (N. Virginia)")

        assert payload["regions"]
        assert "ec2-ondemand-without-sec-sel" in seen[0]
        assert "US%20East" in seen[0]

    @pytest.mark.asyncio
    async def test_missing_regions_field_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"manifest": {"currencyCode": "USD"}})

        with pytest.raises(UpstreamUnavailableError, match="regions"):
            await _client(handler).fetch_region("US East (N. Virginia)")

    @pytest.mark.asyncio
    async def test_non_usd_manifest_raises(self) -> None:
        """币种变了还照收，会把欧元价当美元价折算，差一个数量级的事故。"""

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(json.dumps(OK_PAYLOAD))
            payload["manifest"]["currencyCode"] = "EUR"
            return _json_response(payload)

        with pytest.raises(UpstreamUnavailableError, match="EUR"):
            await _client(handler).fetch_region("US East (N. Virginia)")

    @pytest.mark.asyncio
    async def test_4xx_does_not_retry(self) -> None:
        calls: List[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(404, text="not found")

        with pytest.raises(UpstreamUnavailableError, match="404"):
            await _client(handler, attempts=3).fetch_region("US East (N. Virginia)")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_5xx_retries_then_succeeds(self) -> None:
        calls: List[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(503, text="busy")
            return _json_response(OK_PAYLOAD)

        payload = await _client(handler, attempts=2).fetch_region("US East (N. Virginia)")

        assert payload["regions"]
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_network_error_raises_upstream(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timeout", request=request)

        with pytest.raises(UpstreamUnavailableError, match="AWS"):
            await _client(handler).fetch_region("US East (N. Virginia)")
