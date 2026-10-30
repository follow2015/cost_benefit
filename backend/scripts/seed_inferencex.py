"""E-8 种子：接入 InferenceX（SemiAnalysis）公开推理基准数据。

源：https://inferencex.semianalysis.com —— 开源、持续更新的真实推理基准平台。
数据口径：USD / 百万总 token（含 prefill+decode+cache，即 InferenceX 的 `y_costh`），
属**成本侧**（hyperscaler 最优 serving 包络），非对外售价；本项目本位币 CNY，
接入层经 S-3 汇率折算并标注采集日（见 `meta.inferencex_as_of`）。

本脚本一次性校准 inferencex-analysis-recommendations.md 中指出的「待核实默认值」：
- C-2：为 MoE 模型补 `active_params_b`（激活参数），`is_moe=True`；
- C-3：补 `quant`（FP4 等）、`spec_method`（MTP/STP/EAGLE）；
- C-4：补 `ctx_default`（长上下文默认长度）；
- E-8：将每 token 成本基准写入模型 `meta.inferencex_cost_usd_per_mtok`（供 E-10 标杆告警）；
- S-12：GPU `meta` 补代际 / spec 支持（无 TFLOPS 时留空，避免编造）。

运行：`python -m scripts.seed_inferencex`（backend/ 下，.env 已配 DATABASE_URL）。
幂等：模型按 code upsert（已存在则合并新字段 + meta，不覆盖 seed.py 既有价格/吞吐）；
GPU 按 code upsert（InferenceX 硬件码为新增，通常插入）。

⚠️ 这是**一次性人工校准**脚本，成本数值写死在下方常量里。日常刷新成本标杆请走自动采集
（服务内每 7 天一次 / 基准库页「立即采集」/ `make sync-benchmarks`，见
`ai_roi.application.use_cases.inferencex_sync_service`）——重跑本脚本会把
`as_of` 与成本值打回人工日期，覆盖掉自动采集的最新数据。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from sqlalchemy import select, text

from ai_roi.shared.config import settings
from ai_roi.infrastructure.db import models  # noqa: F401  注册模型
from ai_roi.infrastructure.db.session import SessionFactory
from ai_roi.infrastructure.db.models.benchmark import BenchmarkGpu, BenchmarkModel

INFERENCEX_AS_OF = date(2026, 8, 1)
FX_USD_CNY = 7.2

GPU_META: Dict[str, Dict[str, Any]] = {
    "B200": {"generation": "Blackwell", "spec_support": ["FP4", "MXFP4", "NVFP4", "MTP"]},
    "B300": {"generation": "Blackwell", "spec_support": ["FP4", "MXFP4", "NVFP4", "MTP"]},
    "GB200_NVL72": {"generation": "Blackwell", "spec_support": ["FP4", "MXFP4", "NVFP4", "MTP"], "form_factor": "NVL72"},
    "GB300_NVL72": {"generation": "Blackwell", "spec_support": ["FP4", "MXFP4", "NVFP4", "MTP"], "form_factor": "NVL72"},
    "MI355X": {"generation": "CDNA4", "spec_support": ["FP4", "MTP"], "vendor": "AMD"},
}

COST_USD_PER_MTOK: Dict[str, Dict[str, Dict[str, float]]] = {
    "deepseek-v4-pro": {
        "B200": {"8K/1K": 0.300, "AgentX": 0.024},
        "MI355X": {"8K/1K": 0.355, "AgentX": 0.047},
        "B300": {"8K/1K": 0.245, "AgentX": 0.019},
        "GB200_NVL72": {"8K/1K": 0.514},
        "GB300_NVL72": {"AgentX": 0.011},
    },
    "kimi-k3": {
        "B200": {"AgentX": 0.121},
        "MI355X": {"AgentX": 0.257},
        "B300": {"AgentX": 0.103},
        "GB200_NVL72": {"AgentX": 0.113},
        "GB300_NVL72": {"AgentX": 0.080},
    },
    "minimax-m3": {
        "B200": {"8K/1K": 0.067, "AgentX": 0.079},
        "MI355X": {"8K/1K": 0.113, "AgentX": 0.079},
        "B300": {"8K/1K": 0.056},
        "GB200_NVL72": {"8K/1K": 0.108, "AgentX": 0.016},
        "GB300_NVL72": {"8K/1K": 0.110},
    },
    "glm-5.3": {
        "MI355X": {"AgentX": 0.040},
    },
    "qwen-3.5-397b-a17b": {
        "B200": {"8K/1K": 0.038, "AgentX": 0.036},
        "MI355X": {"8K/1K": 0.067, "AgentX": 0.036},
        "B300": {"8K/1K": 0.040, "AgentX": 0.014},
        "GB200_NVL72": {"8K/1K": 0.142},
        "GB300_NVL72": {"8K/1K": 0.133, "AgentX": 0.007},
    },
}

MODELS: List[Dict[str, Any]] = [
    {
        "code": "deepseek-v4-pro",
        "name": "DeepSeek-V4-Pro（1.6T MoE/49B 激活）",
        "params_b": 1600, "active_params_b": 49, "is_moe": True,
        "quant": "FP4", "spec_method": "MTP", "ctx_default": 128000,
    },
    {
        "code": "kimi-k3",
        "name": "Kimi-K3（2.8T MoE/104B 激活）",
        "params_b": 2800, "active_params_b": 104, "is_moe": True,
        "quant": "FP4", "spec_method": "MTP", "ctx_default": 128000,
    },
    {
        "code": "minimax-m3",
        "name": "MiniMax-M3 428B",
        "params_b": 428, "active_params_b": None, "is_moe": False,
        "quant": "FP4", "spec_method": "MTP", "ctx_default": 8192,
    },
    {
        "code": "glm-5.3",
        "name": "GLM-5.3 743B MoE",
        "params_b": 743, "active_params_b": None, "is_moe": True,
        "quant": "FP4", "spec_method": "MTP", "ctx_default": 128000,
    },
    {
        "code": "qwen-3.5-397b-a17b",
        "name": "Qwen-3.5 397B-A17B（激活 17B）",
        "params_b": 397, "active_params_b": 17, "is_moe": True,
        "quant": "FP4", "spec_method": "MTP", "ctx_default": 128000,
    },
]

GPU_CODE_NAME = {
    "B200": "NVIDIA B200",
    "B300": "NVIDIA B300",
    "GB200_NVL72": "NVIDIA GB200 NVL72",
    "GB300_NVL72": "NVIDIA GB300 NVL72",
    "MI355X": "AMD MI355X",
}


def cny_cost_benchmark(
    usd_per_mtok: float, fx_usd_cny: float = FX_USD_CNY
) -> float:
    """S-3 汇率换算：InferenceX USD/Mtok 成本侧 → 本项目 CNY/Mtok 成本标杆。

    纯函数，可单测，不触库。口径：InferenceX `y_costh` 为 hyperscaler 最优 serving
    包络（含 prefill+decode+cache），等价于「等效输出 token」全包成本，可直接作为
    `cost_benchmark`（元/Mtok）对标，无需再折算 token 口径。
    """
    return round(float(usd_per_mtok) * float(fx_usd_cny), 6)


def build_gpu_rows() -> List[BenchmarkGpu]:
    """构造 GPU 基准行（纯函数，可单测，不触库）。"""
    rows: List[BenchmarkGpu] = []
    for code, meta in GPU_META.items():
        rows.append(
            BenchmarkGpu(
                code=code,
                name=GPU_CODE_NAME.get(code, code),
                vendor=meta.get("vendor", "NVIDIA"),
                price_cny=0.0,
                tdp_w=0.0,
                vram_gb=0.0,
                source="InferenceX+SemiAnalysis",
                as_of=INFERENCEX_AS_OF,
                meta={**meta, "inferencex_as_of": INFERENCEX_AS_OF.isoformat(), "fx_usd_cny": FX_USD_CNY},
            )
        )
    return rows


def build_model_rows() -> List[BenchmarkModel]:
    """构造模型基准行（纯函数，可单测，不触库）。"""
    rows: List[BenchmarkModel] = []
    for spec in MODELS:
        cost_usd = COST_USD_PER_MTOK.get(spec["code"], {})
        cost_cny: Dict[str, Dict[str, float]] = {}
        for hw, scen_map in cost_usd.items():
            cost_cny[hw] = {
                scen: cny_cost_benchmark(usd, FX_USD_CNY)
                for scen, usd in scen_map.items()
            }
        meta = {
            "inferencex_cost_usd_per_mtok": cost_usd,
            "cost_benchmark_cny_per_mtok": cost_cny,
            "inferencex_as_of": INFERENCEX_AS_OF.isoformat(),
            "fx_usd_cny": FX_USD_CNY,
        }
        rows.append(
            BenchmarkModel(
                code=spec["code"],
                name=spec["name"],
                params_b=spec["params_b"],
                active_params_b=spec["active_params_b"],
                is_moe=spec["is_moe"],
                quant=spec["quant"],
                spec_method=spec["spec_method"],
                ctx_default=spec["ctx_default"],
                vram_required_gb=0.0,
                source="InferenceX+SemiAnalysis",
                as_of=INFERENCEX_AS_OF,
                meta=meta,
            )
        )
    return rows


async def _seed() -> None:
    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL app.is_super = 'on';"))

        for gpu in build_gpu_rows():
            existing = (
                await session.execute(
                    select(BenchmarkGpu).where(
                        BenchmarkGpu.tenant_id.is_(None), BenchmarkGpu.code == gpu.code
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(gpu)
                print(f"[seed_inferencex] GPU 新增 {gpu.code}")
            else:
                existing.meta = {**(existing.meta or {}), **gpu.meta}
                existing.source = gpu.source
                existing.as_of = gpu.as_of
                print(f"[seed_inferencex] GPU 合并 meta {gpu.code}")

        for model in build_model_rows():
            existing = (
                await session.execute(
                    select(BenchmarkModel).where(
                        BenchmarkModel.tenant_id.is_(None), BenchmarkModel.code == model.code
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(model)
                print(f"[seed_inferencex] 模型新增 {model.code}")
            else:
                existing.active_params_b = model.active_params_b
                existing.is_moe = model.is_moe
                existing.quant = model.quant
                existing.spec_method = model.spec_method
                existing.ctx_default = model.ctx_default
                existing.meta = {**(existing.meta or {}), **model.meta}
                existing.source = model.source
                existing.as_of = model.as_of
                print(f"[seed_inferencex] 模型合并 {model.code}")

        await session.commit()
        print("[seed_inferencex] 完成：InferenceX 基准已接入（模型×硬件×场景 成本见 meta.inferencex_cost_usd_per_mtok）。")


def main() -> None:
    print(f"[seed_inferencex] 连接数据库：{settings.DATABASE_URL}")
    import asyncio

    asyncio.run(_seed())


if __name__ == "__main__":
    main()
