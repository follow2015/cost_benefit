"""基准库仓储。读取时同时返回平台内置（tenant_id IS NULL）与租户自建数据。

P1 起补齐写方法（新增 / 更新 / 删除）。写入的租户归属与权限判定放在服务层，
仓储只负责 SQL；RLS 策略（`benchmark_*_write` / `_update` / `_delete`）作为最后一道防线。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_roi.application.schemas.benchmark import (
    ApiPriceOut,
    CloudPriceOut,
    GpuOut,
    ModelOut,
)
from ai_roi.domain.benchmark import BENCHMARK_LABELS, BENCHMARK_UNIQUE_KEYS
from ai_roi.infrastructure.db.models.benchmark import (
    BenchmarkApiPrice,
    BenchmarkCloudPrice,
    BenchmarkGpu,
    BenchmarkModel,
)
from ai_roi.infrastructure.repositories.benchmark_mappers import (
    api_out,
    cloud_out,
    entity_summary,
    gpu_out,
    model_out,
)

BenchmarkEntity = Union[
    BenchmarkGpu, BenchmarkModel, BenchmarkCloudPrice, BenchmarkApiPrice
]

BENCHMARK_MODELS: Dict[str, Type[BenchmarkEntity]] = {
    "gpus": BenchmarkGpu,
    "models": BenchmarkModel,
    "cloud-prices": BenchmarkCloudPrice,
    "api-prices": BenchmarkApiPrice,
}

def model_for(kind: str) -> Type[BenchmarkEntity]:
    """按种类取 ORM 模型，未知种类抛 KeyError（路由层已用枚举收窄）。"""
    if kind not in BENCHMARK_MODELS:
        raise KeyError(f"未知基准种类：{kind}")
    return BENCHMARK_MODELS[kind]


class BenchmarkRepository:
    """基准库统一仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_gpus(self, tenant_id: Optional[int]) -> List[GpuOut]:
        """列出 GPU 基准。"""
        stmt = (
            select(BenchmarkGpu)
            .where(
                BenchmarkGpu.is_active.is_(True),
                or_(BenchmarkGpu.tenant_id.is_(None), BenchmarkGpu.tenant_id == tenant_id),
            )
            .order_by(BenchmarkGpu.vendor, BenchmarkGpu.code)
        )
        result = await self.session.execute(stmt)
        return [gpu_out(item) for item in result.unique().scalars().all()]

    async def list_models(self, tenant_id: Optional[int]) -> List[ModelOut]:
        """列出模型基准。"""
        stmt = (
            select(BenchmarkModel)
            .where(
                BenchmarkModel.is_active.is_(True),
                or_(
                    BenchmarkModel.tenant_id.is_(None), BenchmarkModel.tenant_id == tenant_id
                ),
            )
            .order_by(BenchmarkModel.params_b, BenchmarkModel.code)
        )
        result = await self.session.execute(stmt)
        return [model_out(item) for item in result.unique().scalars().all()]

    async def list_cloud_prices(self, tenant_id: Optional[int]) -> List[CloudPriceOut]:
        """列出云租赁价基准。"""
        stmt = (
            select(BenchmarkCloudPrice)
            .where(
                BenchmarkCloudPrice.is_active.is_(True),
                or_(
                    BenchmarkCloudPrice.tenant_id.is_(None),
                    BenchmarkCloudPrice.tenant_id == tenant_id,
                ),
            )
            .order_by(BenchmarkCloudPrice.provider, BenchmarkCloudPrice.gpu_code)
        )
        result = await self.session.execute(stmt)
        return [cloud_out(item) for item in result.unique().scalars().all()]

    async def list_api_prices(self, tenant_id: Optional[int]) -> List[ApiPriceOut]:
        """列出 API 价基准。"""
        stmt = (
            select(BenchmarkApiPrice)
            .where(
                BenchmarkApiPrice.is_active.is_(True),
                or_(
                    BenchmarkApiPrice.tenant_id.is_(None),
                    BenchmarkApiPrice.tenant_id == tenant_id,
                ),
            )
            .order_by(BenchmarkApiPrice.provider, BenchmarkApiPrice.model_code)
        )
        result = await self.session.execute(stmt)
        return [api_out(item) for item in result.unique().scalars().all()]

    async def get_model(self, tenant_id: Optional[int], model_id: int) -> Optional[BenchmarkModel]:
        """按主键取模型基准（用于 k 系数回退）。"""
        result = await self.session.execute(
            select(BenchmarkModel).where(
                BenchmarkModel.id == model_id,
                or_(
                    BenchmarkModel.tenant_id.is_(None), BenchmarkModel.tenant_id == tenant_id
                ),
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_gpu(self, tenant_id: Optional[int], gpu_id: int) -> Optional[BenchmarkGpu]:
        """按主键取 GPU 基准。"""
        result = await self.session.execute(
            select(BenchmarkGpu).where(
                BenchmarkGpu.id == gpu_id,
                or_(BenchmarkGpu.tenant_id.is_(None), BenchmarkGpu.tenant_id == tenant_id),
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_cloud_price(
        self, tenant_id: Optional[int], cloud_id: int
    ) -> Optional[BenchmarkCloudPrice]:
        """按主键取云租赁价基准。"""
        result = await self.session.execute(
            select(BenchmarkCloudPrice).where(
                BenchmarkCloudPrice.id == cloud_id,
                or_(
                    BenchmarkCloudPrice.tenant_id.is_(None),
                    BenchmarkCloudPrice.tenant_id == tenant_id,
                ),
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_api_price(
        self, tenant_id: Optional[int], api_id: int
    ) -> Optional[BenchmarkApiPrice]:
        """按主键取 API 价基准。"""
        result = await self.session.execute(
            select(BenchmarkApiPrice).where(
                BenchmarkApiPrice.id == api_id,
                or_(
                    BenchmarkApiPrice.tenant_id.is_(None),
                    BenchmarkApiPrice.tenant_id == tenant_id,
                ),
            )
        )
        return result.unique().scalar_one_or_none()

    async def find_model_meta(
        self, model_code: str, tenant_id: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """按 code 取模型 meta（租户优先，回退平台内置）。"""
        row = (
            await self.session.execute(
                select(BenchmarkModel).where(
                    BenchmarkModel.code == model_code,
                    BenchmarkModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await self.session.execute(
                    select(BenchmarkModel).where(
                        BenchmarkModel.code == model_code,
                        BenchmarkModel.tenant_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
        return dict(row.meta or {}) if row is not None else None

    async def find_builtin_model(self, code: str) -> Optional[BenchmarkModel]:
        """按 code 取**平台内置**模型行（采集写回的唯一目标）。

        采集只更新平台内置行（``tenant_id IS NULL``）：租户自建的同名模型是
        用户自己维护的口径，外部采集无权覆盖。
        """
        result = await self.session.execute(
            select(BenchmarkModel).where(
                BenchmarkModel.code == code, BenchmarkModel.tenant_id.is_(None)
            )
        )
        return result.unique().scalar_one_or_none()

    async def find_builtin_gpu(self, code: str) -> Optional[BenchmarkGpu]:
        """按 code 取**平台内置** GPU 行（租赁行情采集的写回目标）。

        与模型侧同理：租户自建的 GPU 条目是用户自己的口径，采集无权覆盖。
        """
        result = await self.session.execute(
            select(BenchmarkGpu).where(
                BenchmarkGpu.code == code, BenchmarkGpu.tenant_id.is_(None)
            )
        )
        return result.unique().scalar_one_or_none()

    async def find_builtin_cloud(
        self, provider: str, gpu_code: str
    ) -> Optional[BenchmarkCloudPrice]:
        """按 (云厂商, GPU 型号) 取**平台内置**云租赁价行。

        同一家云对同一型号可能建了多行（不同 region），取 id 最小的一行作为写回目标：
        官方价格接口当前只查单区域，多行场景下不应把同一个区域价写进多个 region 行。
        """
        result = await self.session.execute(
            select(BenchmarkCloudPrice)
            .where(
                BenchmarkCloudPrice.provider == provider,
                BenchmarkCloudPrice.gpu_code == gpu_code,
                BenchmarkCloudPrice.tenant_id.is_(None),
            )
            .order_by(BenchmarkCloudPrice.id)
            .limit(1)
        )
        return result.unique().scalar_one_or_none()

    async def get_by_id(
        self, kind: str, tenant_id: Optional[int], row_id: int
    ) -> Optional[BenchmarkEntity]:
        """按种类 + 主键取一行（可见范围：平台内置 + 本租户自建）。

        可写性（内置条目仅超管可改）由服务层判定，仓储不做权限决策。
        """
        model = model_for(kind)
        result = await self.session.execute(
            select(model).where(
                model.id == row_id,
                or_(model.tenant_id.is_(None), model.tenant_id == tenant_id),
            )
        )
        return result.unique().scalar_one_or_none()

    async def insert(
        self, kind: str, tenant_id: Optional[int], values: Dict[str, Any]
    ) -> BenchmarkEntity:
        """新增一条基准。`tenant_id=None` 表示平台内置（仅超管可用）。"""
        model = model_for(kind)
        row = model(tenant_id=tenant_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def apply_update(
        self, row: BenchmarkEntity, values: Dict[str, Any]
    ) -> BenchmarkEntity:
        """把字段字典逐项写回实体（仅覆盖显式提供的键）。"""
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    def entity_summary(self, kind: str, row: BenchmarkEntity) -> Dict[str, Any]:
        """审计摘要：业务唯一键 + 版本（避免整行大 JSON 入审计表）。"""
        return entity_summary(kind, row)

    async def remove(self, row: BenchmarkEntity) -> None:
        """物理删除一条基准。

        历史方案参数为「值快照」（params JSONB 冻结当时取值），
        删除基准条目不会污染或改变任何已保存的测算结果。
        """
        await self.session.delete(row)
        await self.session.flush()
