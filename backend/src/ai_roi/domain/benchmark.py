"""基准库领域词汇：种类标签与业务唯一键。

与 ORM/路由解耦：仓储（infrastructure）与应用层（application）共同引用，
避免应用层反向依赖基础设施。
"""

from __future__ import annotations

from typing import Dict, List

from ai_roi.domain.calc.parameters import RENT_INC_NONE, RENT_INC_POWER, RENT_INC_POWER_HOSTING

KIND_GPUS = "gpus"
KIND_MODELS = "models"
KIND_CLOUD_PRICES = "cloud-prices"
KIND_API_PRICES = "api-prices"

BENCHMARK_LABELS: Dict[str, str] = {
    KIND_GPUS: "GPU 基准",
    KIND_MODELS: "模型基准",
    KIND_CLOUD_PRICES: "云租赁价基准",
    KIND_API_PRICES: "第三方 API 价基准",
}

BENCHMARK_UNIQUE_KEYS: Dict[str, List[str]] = {
    KIND_GPUS: ["code"],
    KIND_MODELS: ["code"],
    KIND_CLOUD_PRICES: ["provider", "gpu_code", "region"],
    KIND_API_PRICES: ["provider", "model_code"],
}

def resolve_rent_inc(include_power: bool, include_hosting: bool) -> str:
    """把基准库的两个布尔位映射到引擎的 `rent_inc` 枚举（口径单一来源）。"""
    if include_power and include_hosting:
        return RENT_INC_POWER_HOSTING
    if include_power:
        return RENT_INC_POWER
    return RENT_INC_NONE


__all__ = [
    "resolve_rent_inc",
    "KIND_GPUS",
    "KIND_MODELS",
    "KIND_CLOUD_PRICES",
    "KIND_API_PRICES",
    "BENCHMARK_LABELS",
    "BENCHMARK_UNIQUE_KEYS",
]
