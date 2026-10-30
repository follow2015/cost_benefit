"""预置种子数据（P0 演示用）。

- 演示租户 `demo` + 所有者账号（邮箱见 `SEED_DEMO_EMAIL`，默认 `demo@airoi.dev`）；
- 平台内置基准库（GPU / 模型 / 云价 / API 价，`tenant_id = NULL`，全租户可读）。

运行：`python -m scripts.seed`（在 backend/ 下，且 .env 已配置 DATABASE_URL）。
重置密码：`python -m scripts.seed --reset-password`。

密码从哪来
----------
**不再写死在代码里**。优先读环境变量 `SEED_DEMO_PASSWORD`；留空则本次随机生成
并在 stdout 打印一次。硬编码的演示密码会随仓库流向每一份部署，而这个账号带
owner 权限 —— 源码里有密码，等于每份部署都有后门。

幂等：租户与基准数据已存在则跳过；账号已存在时**不动密码**，
除非显式 `--reset-password`（避免每次重跑把人工改过的密码打回去）。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import secrets
import sys
from typing import Tuple

from sqlalchemy import select, text

from ai_roi.shared.config import settings
from ai_roi.infrastructure.security import hash_password
from ai_roi.domain.model_spec import infer_model_spec
from ai_roi.infrastructure.db.base import Base
from ai_roi.infrastructure.db import models  # noqa: F401  注册模型
from ai_roi.infrastructure.db.session import SessionFactory
from ai_roi.infrastructure.db.models.tenant import ROLE_OWNER, Tenant, User
from ai_roi.domain.as_of import infer_as_of
from ai_roi.infrastructure.db.models.benchmark import (
    BenchmarkApiPrice,
    BenchmarkCloudPrice,
    BenchmarkGpu,
    BenchmarkModel,
)
from ai_roi.infrastructure.db.models.network_catalog import NetworkCatalogItem

MIN_PASSWORD_LENGTH = 12
GENERATED_PASSWORD_BYTES = 15


def resolve_password() -> Tuple[str, str, bool]:
    """决定本次要用的演示密码。

    Returns:
        ``(密码, 来源描述, 是否需要打印到终端)``。
        环境变量给的值不打印（用户自己设的，打印反而会落进 CI 日志）；
        随机生成的必须打印，否则没人知道它。
    """
    configured = (settings.SEED_DEMO_PASSWORD or "").strip()
    if configured:
        if len(configured) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"[seed] SEED_DEMO_PASSWORD 至少 {MIN_PASSWORD_LENGTH} 位"
                f"（当前 {len(configured)} 位）。该账号是 owner 权限，弱口令等于没有密码。"
            )
        return configured, "环境变量 SEED_DEMO_PASSWORD", False
    return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES), "本次随机生成", True


def print_password_once(password: str, origin: str) -> None:
    """把随机密码打到终端，明确告知只显示这一次。"""
    bar = "=" * 68
    print(bar)
    print(f"  演示账号密码（{origin}）—— 只显示这一次，请立即保存到密码管理器：")
    print(f"  {password}")
    print(bar)


async def _seed(reset_password: bool = False) -> None:
    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL app.is_super = 'on';"))

        slug = "demo"
        existing = (await session.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
        if existing is None:
            tenant = Tenant(name="演示租户", slug=slug, settings={})
            session.add(tenant)
            await session.flush()
            tenant_id = tenant.id
            print(f"[seed] 创建租户 demo (id={tenant_id})")
        else:
            tenant_id = existing.id
            print(f"[seed] 租户 demo 已存在 (id={tenant_id})")

        email = settings.SEED_DEMO_EMAIL
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.email == email)
            )
        ).scalar_one_or_none()
        if user is None:
            password, origin, must_show = resolve_password()
            user = User(
                tenant_id=tenant_id,
                email=email,
                display_name="演示管理员",
                password_hash=hash_password(password),
                role=ROLE_OWNER,
                is_active=True,
            )
            session.add(user)
            print(f"[seed] 创建用户 {email} (role=owner)，密码来源：{origin}")
            if must_show:
                print_password_once(password, origin)
        elif reset_password:
            password, origin, must_show = resolve_password()
            user.password_hash = hash_password(password)
            user.is_active = True
            print(f"[seed] 已重置 {email} 的密码，来源：{origin}")
            if must_show:
                print_password_once(password, origin)
        else:
            print(f"[seed] 用户 {email} 已存在（密码未改动；需要重置加 --reset-password）")

        gpus = [
            BenchmarkGpu(code="H100", name="NVIDIA H100 SXM", vendor="NVIDIA", price_cny=250000, tdp_w=700, vram_gb=80, rent_cny_per_hour=30.0, source="seed+web:2026-08", as_of=infer_as_of("seed+web:2026-08")),
            BenchmarkGpu(code="H800", name="NVIDIA H800 SXM", vendor="NVIDIA", price_cny=250000, tdp_w=700, vram_gb=80, rent_cny_per_hour=8.88, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkGpu(code="H20", name="NVIDIA H20", vendor="NVIDIA", price_cny=110000, tdp_w=400, vram_gb=96, rent_cny_per_hour=6.2, source="web:JYGPU 2026-08", as_of=infer_as_of("web:JYGPU 2026-08")),
            BenchmarkGpu(code="A100", name="NVIDIA A100 80G", vendor="NVIDIA", price_cny=150000, tdp_w=400, vram_gb=80, rent_cny_per_hour=18.0, source="seed+web:2026-08", as_of=infer_as_of("seed+web:2026-08")),
            BenchmarkGpu(code="A800", name="NVIDIA A800 80G", vendor="NVIDIA", price_cny=140000, tdp_w=400, vram_gb=80, rent_cny_per_hour=15.0, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkGpu(code="L40S", name="NVIDIA L40S", vendor="NVIDIA", price_cny=65000, tdp_w=350, vram_gb=48, rent_cny_per_hour=12.0, source="web:2026-06", as_of=infer_as_of("web:2026-06")),
            BenchmarkGpu(code="L20", name="NVIDIA L20", vendor="NVIDIA", price_cny=90000, tdp_w=350, vram_gb=48, rent_cny_per_hour=6.0, source="seed", as_of=infer_as_of("seed")),
            BenchmarkGpu(code="RTX5090", name="NVIDIA RTX 5090", vendor="NVIDIA", price_cny=25000, tdp_w=575, vram_gb=32, rent_cny_per_hour=2.78, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkGpu(code="RTX4090", name="NVIDIA RTX 4090", vendor="NVIDIA", price_cny=18000, tdp_w=450, vram_gb=24, rent_cny_per_hour=1.88, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkGpu(code="ASCEND910B", name="华为昇腾 910B", vendor="Huawei", price_cny=100000, tdp_w=310, vram_gb=64, rent_cny_per_hour=3.58, source="web:JYGPU 2026-08", as_of=infer_as_of("web:JYGPU 2026-08")),
            BenchmarkGpu(code="ASCEND910C", name="华为昇腾 910C", vendor="Huawei", price_cny=80000, tdp_w=310, vram_gb=64, rent_cny_per_hour=5.0, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkGpu(code="CAMB590", name="寒武纪思元 590", vendor="Cambricon", price_cny=55000, tdp_w=300, vram_gb=64, rent_cny_per_hour=None, source="web:infoq 2026-08", as_of=infer_as_of("web:infoq 2026-08")),
            BenchmarkGpu(code="HYGON_K100", name="海光 K100", vendor="Hygon", price_cny=52000, tdp_w=300, vram_gb=64, rent_cny_per_hour=None, source="web:infoq 2026-08", as_of=infer_as_of("web:infoq 2026-08")),
            BenchmarkGpu(code="MUXI_C500", name="沐曦 C500", vendor="Muxi", price_cny=58000, tdp_w=350, vram_gb=128, rent_cny_per_hour=None, source="web:infoq 2026-08", as_of=infer_as_of("web:infoq 2026-08")),
        ]
        models_ = [
            BenchmarkModel(code="llama-70b", name="Llama-70B", params_b=70, k_ratio=0.10, vram_required_gb=140, source="seed", as_of=infer_as_of("seed")),
            BenchmarkModel(code="llama-13b", name="Llama-13B", params_b=13, k_ratio=0.12, vram_required_gb=40, source="seed", as_of=infer_as_of("seed")),
            BenchmarkModel(code="llama-4-scout", name="Llama 4 Scout（109B MoE/17B 激活）", params_b=109, k_ratio=0.06, vram_required_gb=160, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="qwen-7b", name="Qwen-7B", params_b=7, k_ratio=0.14, vram_required_gb=24, source="seed", as_of=infer_as_of("seed")),
            BenchmarkModel(code="qwen3-235b", name="Qwen3-235B（A22B MoE）", params_b=235, k_ratio=0.05, vram_required_gb=160, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="qwen3-32b", name="Qwen3-32B", params_b=32, k_ratio=0.09, vram_required_gb=64, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="qwen3-8b", name="Qwen3-8B", params_b=8, k_ratio=0.13, vram_required_gb=24, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="deepseek-v3", name="DeepSeek-V3（671B MoE/37B 激活）", params_b=671, k_ratio=0.03, vram_required_gb=512, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="deepseek-r1", name="DeepSeek-R1（671B 推理）", params_b=671, k_ratio=0.03, vram_required_gb=512, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="deepseek-v4-flash", name="DeepSeek-V4-Flash（284B MoE/13B 激活）", params_b=284, k_ratio=0.04, vram_required_gb=320, source="web:deepseek model card 2026-08（1M 上下文，FP4/FP8）", as_of=infer_as_of("web:deepseek model card 2026-08（1M 上下文，FP4/FP8）")),
            BenchmarkModel(code="deepseek-v4-pro", name="DeepSeek-V4-Pro（1.6T MoE/49B 激活）", params_b=1600, k_ratio=0.02, vram_required_gb=1200, source="web:deepseek model card 2026-08（1M 上下文，多机部署）", as_of=infer_as_of("web:deepseek model card 2026-08（1M 上下文，多机部署）")),
            BenchmarkModel(code="glm-4.5", name="GLM-4.5（355B MoE 估算）", params_b=355, k_ratio=0.04, vram_required_gb=400, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="glm-5.2", name="GLM-5.2（743B MoE）", params_b=743, k_ratio=0.03, vram_required_gb=743, source="web:2026-08（与 5.3 共享基座，MIT）", as_of=infer_as_of("web:2026-08（与 5.3 共享基座，MIT）")),
            BenchmarkModel(code="glm-5.3", name="GLM-5.3（743B MoE，后训练升级）", params_b=743, k_ratio=0.03, vram_required_gb=743, source="web:智谱官方 2026-08-14（编程+50%，DeepSWE 66.9，1M 上下文）", as_of=infer_as_of("web:智谱官方 2026-08-14（编程+50%，DeepSWE 66.9，1M 上下文）")),
            BenchmarkModel(code="kimi-k2", name="Kimi K2（1T MoE）", params_b=1024, k_ratio=0.03, vram_required_gb=640, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="kimi-k3", name="Kimi K3（2.8T MoE/104B 激活，原生多模态）", params_b=2800, k_ratio=0.02, vram_required_gb=1600, source="web:Moonshot 2026-07-16 开源（1M 上下文）", as_of=infer_as_of("web:Moonshot 2026-07-16 开源（1M 上下文）")),
            BenchmarkModel(code="qwen3.8-2.4t", name="Qwen3.8-2.4T（MoE/95B 激活）", params_b=2400, k_ratio=0.02, vram_required_gb=1400, source="web:阿里开源 2026-08-13（262K 原生可延 1M）", as_of=infer_as_of("web:阿里开源 2026-08-13（262K 原生可延 1M）")),
            BenchmarkModel(code="qwen3.8-27b", name="Qwen3.8-27B（稠密）", params_b=27, k_ratio=0.09, vram_required_gb=54, source="web:阿里开源 2026-08（Apache2.0，本地 Agent）", as_of=infer_as_of("web:阿里开源 2026-08（Apache2.0，本地 Agent）")),
            BenchmarkModel(code="mistral-large", name="Mistral Large", params_b=123, k_ratio=0.07, vram_required_gb=256, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="phi-4", name="Phi-4", params_b=14, k_ratio=0.12, vram_required_gb=32, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkModel(code="gemma-3-27b", name="Gemma 3 27B", params_b=27, k_ratio=0.09, vram_required_gb=54, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
        ]
        for _m in models_:
            _guess = infer_model_spec(_m.name)
            if _guess.is_moe is not None:
                _m.is_moe = _guess.is_moe
            if _guess.active_params_b is not None:
                _m.active_params_b = _guess.active_params_b
            _m.meta = {**(_m.meta or {}), "spec_evidence": _guess.evidence}

        clouds = [
            BenchmarkCloudPrice(provider="阿里云", gpu_code="H100", region="cn", price_cny_per_hour=30.0, source="web:2026-06", as_of=infer_as_of("web:2026-06")),
            BenchmarkCloudPrice(provider="阿里云", gpu_code="H20", region="cn", price_cny_per_hour=6.2, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkCloudPrice(provider="腾讯云", gpu_code="H100", region="cn", price_cny_per_hour=30.0, source="web:2026-06", as_of=infer_as_of("web:2026-06")),
            BenchmarkCloudPrice(provider="腾讯云", gpu_code="A100", region="cn", price_cny_per_hour=18.0, source="seed+web:2026-06", as_of=infer_as_of("seed+web:2026-06")),
            BenchmarkCloudPrice(provider="华为云", gpu_code="H20", region="cn", price_cny_per_hour=6.2, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkCloudPrice(provider="华为云", gpu_code="ASCEND910B", region="cn", price_cny_per_hour=3.58, source="web:JYGPU 2026-08", as_of=infer_as_of("web:JYGPU 2026-08")),
            BenchmarkCloudPrice(provider="火山引擎", gpu_code="L20", region="cn", price_cny_per_hour=6.0, source="seed", as_of=infer_as_of("seed")),
            BenchmarkCloudPrice(provider="火山引擎", gpu_code="RTX5090", region="cn", price_cny_per_hour=2.78, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkCloudPrice(provider="AutoDL", gpu_code="H800", region="cn", price_cny_per_hour=8.88, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkCloudPrice(provider="AutoDL", gpu_code="H20", region="cn", price_cny_per_hour=7.58, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkCloudPrice(provider="AutoDL", gpu_code="RTX4090", region="cn", price_cny_per_hour=1.88, source="web:AutoDL 2026-08", as_of=infer_as_of("web:AutoDL 2026-08")),
            BenchmarkCloudPrice(provider="AWS", gpu_code="H100", region="us-east-1", price_cny_per_hour=20.3, source="web:2026-08 USD3/h×6.76", as_of=infer_as_of("web:2026-08 USD3/h×6.76")),
            BenchmarkCloudPrice(provider="AWS", gpu_code="A100", region="us-east-1", price_cny_per_hour=10.8, source="web:2026-08 USD1.6/h×6.76", as_of=infer_as_of("web:2026-08 USD1.6/h×6.76")),
            BenchmarkCloudPrice(provider="Azure", gpu_code="H100", region="global", price_cny_per_hour=23.7, source="web:2026-08 USD3.5/h×6.76", as_of=infer_as_of("web:2026-08 USD3.5/h×6.76")),
            BenchmarkCloudPrice(provider="GCP", gpu_code="H100", region="global", price_cny_per_hour=23.7, source="web:2026-08 USD3.5/h×6.76", as_of=infer_as_of("web:2026-08 USD3.5/h×6.76")),
        ]
        apis = [
            BenchmarkApiPrice(provider="OpenAI", model_code="gpt-5", price_in_cny_per_m=8.45, price_out_cny_per_m=67.6, source="web:2026-08 USD1.25/10×6.76", as_of=infer_as_of("web:2026-08 USD1.25/10×6.76")),
            BenchmarkApiPrice(provider="OpenAI", model_code="gpt-4.1", price_in_cny_per_m=13.5, price_out_cny_per_m=54.1, price_cache_cny_per_m=2.7, source="web:2026-03 USD2/8×6.76", as_of=infer_as_of("web:2026-03 USD2/8×6.76")),
            BenchmarkApiPrice(provider="OpenAI", model_code="gpt-4o", price_in_cny_per_m=18.0, price_out_cny_per_m=70.0, price_cache_cny_per_m=9.0, source="seed", as_of=infer_as_of("seed")),
            BenchmarkApiPrice(provider="Anthropic", model_code="claude-sonnet-4-6", price_in_cny_per_m=20.3, price_out_cny_per_m=101.4, source="web:2026-08 USD3/15×6.76", as_of=infer_as_of("web:2026-08 USD3/15×6.76")),
            BenchmarkApiPrice(provider="Anthropic", model_code="claude-opus-4-6", price_in_cny_per_m=33.8, price_out_cny_per_m=169.0, source="web:2026-08 USD5/25×6.76", as_of=infer_as_of("web:2026-08 USD5/25×6.76")),
            BenchmarkApiPrice(provider="Anthropic", model_code="claude-haiku-4-5", price_in_cny_per_m=6.76, price_out_cny_per_m=33.8, source="web:2026-08 USD1/5×6.76", as_of=infer_as_of("web:2026-08 USD1/5×6.76")),
            BenchmarkApiPrice(provider="Google", model_code="gemini-2.5-pro", price_in_cny_per_m=8.45, price_out_cny_per_m=67.6, source="web:2026-08 USD1.25/10×6.76", as_of=infer_as_of("web:2026-08 USD1.25/10×6.76")),
            BenchmarkApiPrice(provider="Google", model_code="gemini-2.5-flash", price_in_cny_per_m=2.03, price_out_cny_per_m=16.9, source="web:2026-08 USD0.3/2.5×6.76", as_of=infer_as_of("web:2026-08 USD0.3/2.5×6.76")),
            BenchmarkApiPrice(provider="DeepSeek", model_code="deepseek-v4-flash", price_in_cny_per_m=1.0, price_out_cny_per_m=2.0, price_cache_cny_per_m=0.02, source="web:deepseek api-docs 2026-08", as_of=infer_as_of("web:deepseek api-docs 2026-08")),
            BenchmarkApiPrice(provider="DeepSeek", model_code="deepseek-v4-pro", price_in_cny_per_m=3.0, price_out_cny_per_m=6.0, price_cache_cny_per_m=0.025, source="web:deepseek api-docs 2026-08", as_of=infer_as_of("web:deepseek api-docs 2026-08")),
            BenchmarkApiPrice(provider="DeepSeek", model_code="deepseek-v3.2", price_in_cny_per_m=1.89, price_out_cny_per_m=2.84, price_cache_cny_per_m=0.19, source="web:2026-03 USD0.28/0.42×6.76", as_of=infer_as_of("web:2026-03 USD0.28/0.42×6.76")),
            BenchmarkApiPrice(provider="通义千问", model_code="qwen-max", price_in_cny_per_m=10.0, price_out_cny_per_m=30.0, price_cache_cny_per_m=5.0, source="seed", as_of=infer_as_of("seed")),
            BenchmarkApiPrice(provider="通义千问", model_code="qwen3-max", price_in_cny_per_m=3.0, price_out_cny_per_m=10.0, source="web:2026-08", as_of=infer_as_of("web:2026-08")),
            BenchmarkApiPrice(provider="豆包", model_code="seed-2.0-pro", price_in_cny_per_m=3.18, price_out_cny_per_m=16.0, source="web:2026-08 USD0.47/2.37×6.76", as_of=infer_as_of("web:2026-08 USD0.47/2.37×6.76")),
            BenchmarkApiPrice(provider="智谱", model_code="glm-4-plus", price_in_cny_per_m=12.0, price_out_cny_per_m=40.0, price_cache_cny_per_m=6.0, source="seed", as_of=infer_as_of("seed")),
            BenchmarkApiPrice(provider="智谱", model_code="glm-5", price_in_cny_per_m=5.4, price_out_cny_per_m=17.3, source="web:2026-08 USD0.8/2.56×6.76", as_of=infer_as_of("web:2026-08 USD0.8/2.56×6.76")),
            BenchmarkApiPrice(provider="Kimi", model_code="kimi-k2.5", price_in_cny_per_m=4.06, price_out_cny_per_m=20.3, source="web:2026-08 USD0.6/3×6.76", as_of=infer_as_of("web:2026-08 USD0.6/3×6.76")),
            BenchmarkApiPrice(provider="百度文心", model_code="ernie-5.0", price_in_cny_per_m=3.9, price_out_cny_per_m=7.8, source="web:2026-08 USD0.58/1.16×6.76", as_of=infer_as_of("web:2026-08 USD0.58/1.16×6.76")),
            BenchmarkApiPrice(provider="MiniMax", model_code="minimax-m2.5", price_in_cny_per_m=3.38, price_out_cny_per_m=13.5, source="web:2026-08 USD0.5/2×6.76", as_of=infer_as_of("web:2026-08 USD0.5/2×6.76")),
        ]

        catalog_items = [
            NetworkCatalogItem(category="compute_switch_ib", code="ib-32x400g", name="算力交换机 IB（32×400G）", price_cny=250000, unit="台", spec={"ports": 32, "speed_gbps": 400}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="compute_switch_roce", code="roce-32x400g", name="算力交换机 RoCE（32×400G）", price_cny=200000, unit="台", spec={"ports": 32, "speed_gbps": 400}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="storage_switch", code="48x100g", name="存储交换机（48×100G IP SAN）", price_cny=120000, unit="台", spec={"ports": 48, "speed_gbps": 100}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="mgmt_switch", code="48x1g", name="管理交换机（48×1G/10G）", price_cny=8000, unit="台", spec={"ports": 48}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="nic_ib", code="cx7-400g", name="IB 网卡 ConnectX-7 400G", price_cny=15000, unit="卡", spec={"speed_gbps": 400}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="nic_roce", code="400g-roce", name="RoCE 网卡 400G", price_cny=8000, unit="卡", spec={"speed_gbps": 400}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="optics_400g", code="qsfp-dd-400g", name="400G 光模块 QSFP-DD", price_cny=5000, unit="个", spec={"speed_gbps": 400}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="optics_100g", code="qsfp28-100g", name="100G 光模块 QSFP28", price_cny=1500, unit="个", spec={"speed_gbps": 100}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="aoc_cable", code="aoc-400g-3m", name="AOC 有源光缆 400G 3m", price_cny=3000, unit="根", spec={"speed_gbps": 400, "length_m": 3}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="mpo_cable", code="mpo12-50m", name="MPO 主干线缆 12 芯 50m", price_cny=2000, unit="根", spec={"cores": 12, "length_m": 50}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="storage_per_gb", code="nvme-mixed", name="存储采购（NVMe 混合盘，元/GB）", price_cny=1.0, unit="元/GB", spec={}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
            NetworkCatalogItem(category="storage_monthly_per_gb", code="monthly-ops", name="存储月费（元/GB/月）", price_cny=0.02, unit="元/GB/月", spec={}, source="seed（现状经验值）", as_of=infer_as_of("seed（现状经验值）")),
        ]
        for row in catalog_items:
            existing_row = (
                await session.execute(
                    select(NetworkCatalogItem).where(
                        NetworkCatalogItem.tenant_id.is_(None),
                        NetworkCatalogItem.category == row.category,
                        NetworkCatalogItem.code == row.code,
                    )
                )
            ).scalar_one_or_none()
            if existing_row is None:
                session.add(row)
                print(f"[seed] 基准 network_catalog.{row.category}/{row.code}")
            else:
                print(f"[seed] 基准 network_catalog.{row.category}/{row.code} 已存在")

        for rows, cls, keys in [
            (gpus, BenchmarkGpu, ("code",)),
            (models_, BenchmarkModel, ("code",)),
            (clouds, BenchmarkCloudPrice, ("provider", "gpu_code")),
            (apis, BenchmarkApiPrice, ("provider", "model_code")),
        ]:
            for row in rows:
                conds = [getattr(cls, k) == getattr(row, k) for k in keys] + [cls.tenant_id.is_(None)]
                existing_row = (await session.execute(select(cls).where(*conds))).scalar_one_or_none()
                label = "/".join(str(getattr(row, k)) for k in keys)
                if existing_row is None:
                    session.add(row)
                    print(f"[seed] 基准 {cls.__tablename__}.{label}")
                else:
                    print(f"[seed] 基准 {cls.__tablename__}.{label} 已存在")

        await session.commit()
        print("[seed] 完成。")


def mask_dsn(dsn: str) -> str:
    """隐去连接串里的口令，免得它出现在终端、CI 日志与截图里。"""
    return re.sub(r"(://[^:/@]*:)[^@]*@", r"\1***@", dsn)


def main() -> None:
    parser = argparse.ArgumentParser(description="预置演示租户与内置基准库（幂等）")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="重置演示账号密码（不传时，账号已存在则保持原密码不动）",
    )
    args = parser.parse_args()

    print(f"[seed] 连接数据库：{mask_dsn(settings.DATABASE_URL)}")
    asyncio.run(_seed(reset_password=args.reset_password))


if __name__ == "__main__":
    sys.exit(main())
