"""基准库 DTO。数值以字符串返回，避免前端 float 精度损失。

P1 起新增写入 DTO（`*Create` / `*Update`）：
- 数值同样以**字符串**入参（Decimal 字符串交换，禁止 float 中转）；
- 生效日期字段名为 `as_of`，同时接受别名 `effective_from`（架构 §5 契约用词）；
- `is_builtin=True` 仅平台超管可用（写入 `tenant_id IS NULL` 的平台内置条目）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class GpuOut(BaseModel):
    """GPU 基准。"""

    id: int
    code: str
    name: str
    vendor: str = ""
    price_cny: str = "0"
    tdp_w: str = "0"
    vram_gb: str = "0"
    rent_cny_per_hour: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    as_of: Optional[date] = None
    version: int = 1
    is_builtin: bool = True


class ModelOut(BaseModel):
    """模型基准。"""

    id: int
    code: str
    name: str
    params_b: str = "0"
    active_params_b: Optional[str] = None
    is_moe: bool = False
    throughput_prefill: Optional[str] = None
    throughput_decode: Optional[str] = None
    throughput_effective: Optional[str] = None
    k_ratio: Optional[str] = None
    vram_required_gb: str = "0"
    quant: Optional[str] = None
    ctx_default: Optional[int] = None
    spec_method: Optional[str] = None
    disagg_support: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    as_of: Optional[date] = None
    version: int = 1
    is_builtin: bool = True


class CloudPriceOut(BaseModel):
    """云租赁价基准。"""

    id: int
    provider: str
    gpu_code: str
    region: str = "cn"
    price_cny_per_hour: str = "0"
    include_power: bool = True
    include_hosting: bool = True
    billing_mode: str = "hourly"
    rent_inc: str = "power"
    meta: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    as_of: Optional[date] = None
    version: int = 1
    is_builtin: bool = True


class ApiPriceOut(BaseModel):
    """第三方 API 价基准。"""

    id: int
    provider: str
    model_code: str
    price_in_cny_per_m: str = "0"
    price_out_cny_per_m: str = "0"
    price_cache_cny_per_m: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    as_of: Optional[date] = None
    version: int = 1
    is_builtin: bool = True


class BenchmarkBundleOut(BaseModel):
    """一次性返回全部基准（向导页首屏加载，避免 4 次请求）。"""

    gpus: List[GpuOut] = Field(default_factory=list)
    models: List[ModelOut] = Field(default_factory=list)
    cloud_prices: List[CloudPriceOut] = Field(default_factory=list)
    api_prices: List[ApiPriceOut] = Field(default_factory=list)


_AS_OF_ALIASES = AliasChoices("as_of", "effective_from")


class _WriteBase(BaseModel):
    """写入 DTO 公共部分（来源 / 生效日期 / 版本 / 归属）。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    meta: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="", max_length=255)
    as_of: Optional[date] = Field(default=None, validation_alias=_AS_OF_ALIASES)
    version: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
    is_builtin: bool = False


class _UpdateBase(BaseModel):
    """更新 DTO 公共部分：未提供的字段保持原值。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    meta: Optional[Dict[str, Any]] = None
    source: Optional[str] = Field(default=None, max_length=255)
    as_of: Optional[date] = Field(default=None, validation_alias=_AS_OF_ALIASES)
    version: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class GpuCreate(_WriteBase):
    """新增 GPU 基准。"""

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    vendor: str = Field(default="", max_length=64)
    price_cny: str = "0"
    tdp_w: str = "0"
    vram_gb: str = "0"
    rent_cny_per_hour: Optional[str] = None


class GpuUpdate(_UpdateBase):
    """更新 GPU 基准。"""

    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    vendor: Optional[str] = Field(default=None, max_length=64)
    price_cny: Optional[str] = None
    tdp_w: Optional[str] = None
    vram_gb: Optional[str] = None
    rent_cny_per_hour: Optional[str] = None


class ModelCreate(_WriteBase):
    """新增模型基准。"""

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    params_b: str = "0"
    active_params_b: Optional[str] = None
    is_moe: bool = False
    throughput_prefill: Optional[str] = None
    throughput_decode: Optional[str] = None
    throughput_effective: Optional[str] = None
    k_ratio: Optional[str] = None
    vram_required_gb: str = "0"
    quant: Optional[str] = None
    ctx_default: Optional[int] = None
    spec_method: Optional[str] = None
    disagg_support: bool = False


class ModelUpdate(_UpdateBase):
    """更新模型基准。"""

    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    params_b: Optional[str] = None
    active_params_b: Optional[str] = None
    is_moe: Optional[bool] = None
    throughput_prefill: Optional[str] = None
    throughput_decode: Optional[str] = None
    throughput_effective: Optional[str] = None
    k_ratio: Optional[str] = None
    vram_required_gb: Optional[str] = None
    quant: Optional[str] = None
    ctx_default: Optional[int] = None
    spec_method: Optional[str] = None
    disagg_support: Optional[bool] = None


class CloudPriceCreate(_WriteBase):
    """新增云租赁价基准。"""

    provider: str = Field(min_length=1, max_length=64)
    gpu_code: str = Field(min_length=1, max_length=64)
    region: str = Field(default="cn", max_length=64)
    price_cny_per_hour: str = "0"
    include_power: bool = True
    include_hosting: bool = True
    billing_mode: str = Field(default="hourly", max_length=32)


class CloudPriceUpdate(_UpdateBase):
    """更新云租赁价基准。"""

    provider: Optional[str] = Field(default=None, min_length=1, max_length=64)
    gpu_code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    region: Optional[str] = Field(default=None, max_length=64)
    price_cny_per_hour: Optional[str] = None
    include_power: Optional[bool] = None
    include_hosting: Optional[bool] = None
    billing_mode: Optional[str] = Field(default=None, max_length=32)


class ApiPriceCreate(_WriteBase):
    """新增第三方 API 价基准。"""

    provider: str = Field(min_length=1, max_length=64)
    model_code: str = Field(min_length=1, max_length=96)
    price_in_cny_per_m: str = "0"
    price_out_cny_per_m: str = "0"
    price_cache_cny_per_m: Optional[str] = None


class ApiPriceUpdate(_UpdateBase):
    """更新第三方 API 价基准。"""

    provider: Optional[str] = Field(default=None, min_length=1, max_length=64)
    model_code: Optional[str] = Field(default=None, min_length=1, max_length=96)
    price_in_cny_per_m: Optional[str] = None
    price_out_cny_per_m: Optional[str] = None
    price_cache_cny_per_m: Optional[str] = None


class BenchmarkPublishOut(BaseModel):
    """一次基准库发布的结果（发布号即审计条目 id，回滚时按它定位快照）。"""

    publish_id: int
    counts: Dict[str, int] = Field(default_factory=dict)


class BenchmarkPublishSummaryOut(BaseModel):
    """发布历史条目（不含全量快照，避免列表响应膨胀）。"""

    publish_id: int
    published_at: Optional[datetime] = None
    actor_email: str = ""
    counts: Dict[str, int] = Field(default_factory=dict)


class BenchmarkRollbackItem(BaseModel):
    """被回滚的一行：改了哪些字段、版本从几到几。"""

    kind: str
    id: int
    code: str = ""
    fields: List[str] = Field(default_factory=list)
    from_version: int = 0
    to_version: int = 0


class BenchmarkRollbackOut(BaseModel):
    """回滚结果：已还原 / 无差异 / 跳过（附原因）。"""

    source_publish_id: int
    updated: List[BenchmarkRollbackItem] = Field(default_factory=list)
    unchanged: int = 0
    skipped: List[Dict[str, Any]] = Field(default_factory=list)


class AuthorityApplyItem(BaseModel):
    """一条待应用的权威价（USD / 百万 token，由人工确认后提交）。"""

    id: int
    usd_in: str
    usd_out: Optional[str] = None
    usd_cache: Optional[str] = None
    source_label: str = ""


class AuthorityApplyIn(BaseModel):
    """应用权威同步：只写调用方显式选中的条目。"""

    items: List[AuthorityApplyItem] = Field(default_factory=list)
    fx_usd_cny: Optional[str] = None


class MarketApplyItem(BaseModel):
    """一条待应用的租赁价（CNY / GPU / 小时，由人工在预览里勾选后提交）。

    必须带上 ``proposed_cny`` 与 ``as_of``：它们是**本次采集的结果**，
    后端据此写库与打 ``source`` 标记。不带这两个字段就等于让后端
    「按当前值再写一遍」，那样版本号会涨、来源日期却不动，比不写更糟。
    """

    id: int
    proposed_cny: str
    as_of: Optional[date] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class MarketApplyIn(BaseModel):
    """应用租赁价采集结果：只写显式选中的条目。"""

    items: List[MarketApplyItem] = Field(default_factory=list)
