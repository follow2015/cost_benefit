"""外部**价格**数据源适配器：GetDeploying 行情、Azure 零售价格、AWS 批量价目表。

只做 IO：发请求、判状态码、翻页、交回原始文本/JSON。解析规则在
``ai_roi.domain.rental_market`` 与 ``ai_roi.domain.cloud_official``，
落库在用例层 —— 分开才能离线单测，日后换源也只需替换本文件。

## 三个源的脾气不一样

- **GetDeploying**：一个 1.1MB 的 CSV，一次拿全，没有分页，但会随上游改列名；
  解析侧按列名取值、缺列即跳过该行，不做位置假设。
- **Azure**：REST + 分页（``NextPageLink``），单次最多返回若干百条，必须翻完；
  且同一 SKU 会因地区、币种、计费方式重复出现，过滤全在解析层做。
- **AWS b0**：一个地区一个静态 JSON（us-east-1 实测 679KB / 2.5s），无分页、
  无鉴权，但**必须按地区分别取**，且路径里是展示名而非 ``us-east-1`` 代码。
  自带 ``manifest``（含 ``currencyCode`` 与发布时刻），可用来在采到的东西不对时
  第一眼看出是「上游换版」还是「我们解析错」。

失败一律抛 ``UpstreamUnavailableError``（502 语义），由用例层决定
「记录失败但保留旧数据」，绝不静默回退成空值把基准改成 0。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from ai_roi.domain.cloud_official import SOURCE_ID as CLOUD_SOURCE_ID
from ai_roi.domain.errors import UpstreamUnavailableError
from ai_roi.domain.rental_market import SOURCE_URL as RENTAL_SOURCE_URL

USER_AGENT = "ai-roi-benchmark-collector/1.0"
DEFAULT_ATTEMPTS = 2
MAX_CSV_BYTES = 24 * 1024 * 1024
MAX_AZURE_PAGES = 20
MAX_AWS_BYTES = 8 * 1024 * 1024

AZURE_RETAIL_URL = "https://prices.azure.com/api/retail/prices"
AWS_BULK_URL_TEMPLATE = (
    "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/"
    "ec2-ondemand-without-sec-sel/{region_path}/Linux/index.json"
)


def _raise_upstream(name: str, url: str, detail: str) -> None:
    raise UpstreamUnavailableError(
        f"{name} 价格源不可用：{detail}",
        {"url": url, "reason": detail},
    )


class GetDeployingClient:
    """GPU 租赁行情 CSV 客户端。"""

    def __init__(
        self,
        url: str = RENTAL_SOURCE_URL,
        *,
        timeout: float = 60.0,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.attempts = max(1, int(attempts))
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return self.url

    async def fetch_weekly_csv(self) -> str:
        """拉取周度行情 CSV 全文。"""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,*/*",
            "Accept-Encoding": "gzip",
        }
        last_error = ""
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=True
        ) as client:
            for _ in range(self.attempts):
                try:
                    response = await client.get(self.url, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue
                if response.status_code == 200:
                    body = response.text
                    if not body.strip():
                        last_error = "响应为空"
                        continue
                    if len(response.content) > MAX_CSV_BYTES:
                        _raise_upstream(
                            "GetDeploying",
                            self.url,
                            f"响应超过 {MAX_CSV_BYTES // 1024 // 1024}MB，数据结构可能已变更",
                        )
                    if "gpu_slug" not in body[:2000] or "median_price" not in body[:2000]:
                        _raise_upstream(
                            "GetDeploying", self.url, "CSV 表头缺少 gpu_slug / median_price 列"
                        )
                    return body
                if response.status_code < 500:
                    _raise_upstream(
                        "GetDeploying", self.url, f"HTTP {response.status_code}"
                    )
                last_error = f"HTTP {response.status_code}"
        _raise_upstream("GetDeploying", self.url, last_error or "未知错误")
        return ""


class AzureRetailClient:
    """Azure 零售价格接口客户端（匿名可调，无需鉴权）。

    只查 GPU 相关 SKU：不加过滤会把整个价目表（数十万条）拉下来，慢且无意义。
    """

    def __init__(
        self,
        base_url: str = AZURE_RETAIL_URL,
        *,
        timeout: float = 40.0,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        region: str = "eastus",
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.attempts = max(1, int(attempts))
        self._transport = transport
        self.region = region

    def _filter(self, vm_size: str) -> str:
        return (
            "serviceName eq 'Virtual Machines' "
            f"and armRegionName eq '{self.region}' "
            f"and armSkuName eq '{vm_size}'"
        )

    async def fetch_items(
        self,
        vm_sizes: List[str],
        *,
        region: str = "eastus",
    ) -> List[Dict[str, Any]]:
        """逐个 VM 规格查询其按需价条目（已翻页合并）。"""
        self.region = region
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        items: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=True
        ) as client:
            for vm_size in vm_sizes:
                url: Optional[str] = self.base_url
                params: Optional[Dict[str, str]] = {"$filter": self._filter(vm_size)}
                for _page in range(MAX_AZURE_PAGES):
                    if url is None:
                        break
                    payload = await self._get_json(client, url, params, headers)
                    batch = payload.get("Items")
                    if isinstance(batch, list):
                        items.extend(i for i in batch if isinstance(i, dict))
                    nxt = payload.get("NextPageLink")
                    url = str(nxt) if nxt else None
                    params = None
        if not items:
            _raise_upstream(
                f"Azure({CLOUD_SOURCE_ID})",
                self.base_url,
                f"{region} 区未返回任何 GPU 规格报价",
            )
        return items

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Optional[Dict[str, str]],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        last_error = ""
        for _ in range(self.attempts):
            try:
                response = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    _raise_upstream(
                        "Azure", url, f"返回的不是合法 JSON：{exc}"
                    )
                if not isinstance(data, dict):
                    _raise_upstream("Azure", url, "返回结构不是对象")
                return data
            if response.status_code < 500:
                _raise_upstream("Azure", url, f"HTTP {response.status_code}")
            last_error = f"HTTP {response.status_code}"
        _raise_upstream("Azure", url, last_error or "未知错误")
        return {}


class AwsBulkPricingClient:
    """AWS 官网按需价目表（b0 静态 JSON）客户端，匿名可调、无需鉴权。

    一个地区一个文件：us-east-1 实测 679KB、2.5s。**不要**换成
    ``pricing.us-east-1.amazonaws.com`` 的全量 price list —— 那个单区 46MB，
    下载耗时远超超时阈值，还要自己按 sku 拼 Product/Price 两张表。
    """

    def __init__(
        self,
        url_template: str = AWS_BULK_URL_TEMPLATE,
        *,
        timeout: float = 45.0,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.url_template = url_template
        self.timeout = timeout
        self.attempts = max(1, int(attempts))
        self._transport = transport

    def url_for(self, region_path: str) -> str:
        return self.url_template.format(region_path=quote(region_path, safe="()"))

    async def fetch_region(self, region_path: str) -> Dict[str, Any]:
        """拉取某地区的按需价目表，返回整个 JSON 对象。"""
        url = self.url_for(region_path)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        last_error = ""
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=True
        ) as client:
            for _ in range(self.attempts):
                try:
                    response = await client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue
                if response.status_code == 200:
                    if len(response.content) > MAX_AWS_BYTES:
                        _raise_upstream(
                            "AWS",
                            url,
                            f"响应超过 {MAX_AWS_BYTES // 1024 // 1024}MB，数据结构可能已变更",
                        )
                    try:
                        data = response.json()
                    except ValueError as exc:
                        _raise_upstream("AWS", url, f"返回的不是合法 JSON：{exc}")
                    if not isinstance(data, dict) or not isinstance(
                        data.get("regions"), dict
                    ):
                        _raise_upstream("AWS", url, "缺少 regions 字段，结构可能已变更")
                    manifest = data.get("manifest")
                    if isinstance(manifest, dict):
                        currency = str(manifest.get("currencyCode") or "USD")
                        if currency != "USD":
                            _raise_upstream(
                                "AWS", url, f"价目表币种为 {currency}，不是 USD"
                            )
                    return data
                if response.status_code < 500:
                    _raise_upstream("AWS", url, f"HTTP {response.status_code}")
                last_error = f"HTTP {response.status_code}"
        _raise_upstream("AWS", url, last_error or "未知错误")
        return {}


__all__ = [
    "AWS_BULK_URL_TEMPLATE",
    "AZURE_RETAIL_URL",
    "AwsBulkPricingClient",
    "AzureRetailClient",
    "GetDeployingClient",
    "MAX_AWS_BYTES",
    "MAX_AZURE_PAGES",
    "MAX_CSV_BYTES",
]
