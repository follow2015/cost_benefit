"""基准库服务：写入编排 + 成本标杆解析（纯应用层）。

映射与 SQL 已下沉：
- ORM → DTO 映射在 `infrastructure.repositories.benchmark_mappers`；
- 查询/写在 `infrastructure.repositories.benchmark_repo`（经 UoW 端口注入）；
- 种类标签/唯一键/rent_inc 枚举映射在 `ai_roi.domain.benchmark`。

写入规则（REQ-13 / REQ-14）：
- 需 `benchmark:write` 权限（路由层依赖校验，owner 与超管具备）；
- 租户管理员只能写本租户条目；平台内置条目（`tenant_id IS NULL`）**仅超管可写**；
- 数值以字符串入参并用 `D()` 转 Decimal，禁止 float 中转；
- `version` 新建为 1、更新自增，`as_of`（生效日期）与 `source`（来源）随写入落库。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from ai_roi.application.ports import BenchmarkRepository, UnitOfWork
from ai_roi.application.schemas.benchmark import BenchmarkBundleOut
from ai_roi.domain.benchmark import (
    BENCHMARK_LABELS,
    BENCHMARK_UNIQUE_KEYS,
    resolve_rent_inc,
)
from ai_roi.domain.calc.decimal_config import D
from ai_roi.domain.errors import NotFoundError, PermissionDeniedError, ValidationFailedError

NUMERIC_FIELDS: Dict[str, Tuple[str, ...]] = {
    "gpus": ("price_cny", "tdp_w", "vram_gb", "rent_cny_per_hour"),
    "models": (
        "params_b",
        "active_params_b",
        "throughput_prefill",
        "throughput_decode",
        "throughput_effective",
        "k_ratio",
        "vram_required_gb",
        "ctx_default",
    ),
    "cloud-prices": ("price_cny_per_hour",),
    "api-prices": (
        "price_in_cny_per_m",
        "price_out_cny_per_m",
        "price_cache_cny_per_m",
    ),
}

_NON_NEGATIVE = True

_CONTROL_FIELDS = ("is_builtin",)

SNAPSHOT_KINDS: Tuple[Tuple[str, str], ...] = (
    ("gpus", "gpus"),
    ("models", "models"),
    ("cloud-prices", "cloud_prices"),
    ("api-prices", "api_prices"),
)

_ROLLBACK_SKIP_FIELDS = frozenset({"id", "version", "is_builtin", "created_at", "updated_at"})


def _row_code(kind: str, row: Dict[str, Any]) -> str:
    """把唯一键拼成人读代号（GPU/模型取 code，云价/API 价取 provider+对象）。"""
    keys = BENCHMARK_UNIQUE_KEYS.get(kind, ("code",))
    parts = [str(row.get(key) or "") for key in keys]
    return " / ".join(part for part in parts if part)


def _comparable(value: Any) -> Any:
    """把 ORM 列值归一成可与快照（JSON 字符串/原生标量）直接比较的形态。"""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


def diff_snapshot(kind: str, row: Any, snapshot_row: Dict[str, Any]) -> Dict[str, Any]:
    """算出「把当前行还原成快照值」需要提交的字段（纯函数，可单测）。

    Args:
        kind: 基准种类（决定哪些字段是 Decimal）。
        row: 当前 ORM 实体。
        snapshot_row: 快照中的同一行（JSON 形态）。

    Returns:
        仅差异字段的 payload；空字典表示当前值已与快照一致。
    """
    numeric = NUMERIC_FIELDS.get(kind, ())
    diff: Dict[str, Any] = {}
    for key, snapshot_value in snapshot_row.items():
        if key in _ROLLBACK_SKIP_FIELDS or not hasattr(row, key):
            continue
        if snapshot_value is None:
            continue
        current = getattr(row, key)
        if key in numeric:
            if current is None or _to_decimal(key, snapshot_value) != current:
                diff[key] = snapshot_value
            continue
        if _comparable(current) != _comparable(snapshot_value):
            diff[key] = snapshot_value
    return diff


def _to_decimal(field: str, raw: object) -> Decimal:
    """字符串数值 → Decimal，非法值抛 422。"""
    try:
        value = D(raw)  # type: ignore[arg-type]
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationFailedError(
            f"字段 {field} 不是合法数值：{raw!r}", {"field": field, "value": str(raw)}
        ) from exc
    if not value.is_finite():
        raise ValidationFailedError(
            f"字段 {field} 必须为有限数值", {"field": field, "value": str(raw)}
        )
    if _NON_NEGATIVE and value < 0:
        raise ValidationFailedError(
            f"字段 {field} 不能为负数", {"field": field, "value": str(raw)}
        )
    return value


def normalize_values(kind: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """把写入 DTO 的字典规范化为可直接落库的列值字典。

    - 剔除控制位（`is_builtin`）与 `version`（由调用方单独决定）；
    - 数值字段字符串 → Decimal；
    - `None` 在**更新**场景由调用方先行剔除，故这里保留的 None 视为「显式置空」。
    """
    numeric = NUMERIC_FIELDS.get(kind, ())
    values: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _CONTROL_FIELDS or key == "version":
            continue
        if key in numeric and value is not None:
            values[key] = _to_decimal(key, value)
        else:
            values[key] = value
    return values


def resolve_cost_benchmark_from_meta(
    model_meta: Optional[Dict[str, Any]],
    hardware_code: str,
    scenario: str,
    fx_usd_cny: Decimal,
) -> Optional[Decimal]:
    """S-3：从模型 meta 的 InferenceX 成本源解析「市场成本标杆」（元/Mtok）。

    口径：`meta.inferencex_cost_usd_per_mtok[hardware][scenario]`（USD/Mtok）
    × 汇率 → CNY/Mtok，等价于 `PricingParams.cost_benchmark`。
    任一维度缺失或非法返回 None（调用方退化为不展示 / 不触发亏损告警）。
    纯函数，可单测，不触库。
    """
    if not model_meta:
        return None
    usd_map = model_meta.get("inferencex_cost_usd_per_mtok") or {}
    hw_map = usd_map.get(hardware_code)
    if not hw_map:
        return None
    usd = hw_map.get(scenario)
    if usd is None:
        return None
    try:
        return D(usd) * D(fx_usd_cny)
    except (InvalidOperation, ValueError, TypeError):
        return None


class BenchmarkService:
    """基准库服务（用例编排；实体经 UoW 端口读写）。"""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.session = uow.session
        self.repo: BenchmarkRepository = uow.benchmarks

    async def bundle(self, tenant_id: Optional[int]) -> BenchmarkBundleOut:
        """一次性返回四类基准（向导首屏；仓储已映射为 DTO）。"""
        gpus = await self.repo.list_gpus(tenant_id)
        models = await self.repo.list_models(tenant_id)
        clouds = await self.repo.list_cloud_prices(tenant_id)
        apis = await self.repo.list_api_prices(tenant_id)
        return BenchmarkBundleOut(
            gpus=list(gpus),
            models=list(models),
            cloud_prices=list(clouds),
            api_prices=list(apis),
        )

    async def cost_benchmark(
        self,
        model_code: str,
        hardware_code: str,
        scenario: str,
        fx_usd_cny: Decimal,
        tenant_id: Optional[int],
    ) -> Optional[Decimal]:
        """S-3 只读：按「模型×硬件×场景」解析市场成本标杆（元/Mtok）。

        查模型基准（租户优先、回退内置），从 meta 取 InferenceX USD 成本经汇率换算。
        用于一键校准 `PricingParams.cost_benchmark`；无匹配返回 None。
        """
        meta = await self.repo.find_model_meta(model_code, tenant_id)
        if meta is None:
            return None
        return resolve_cost_benchmark_from_meta(
            meta, hardware_code, scenario, fx_usd_cny
        )

    async def create(
        self,
        kind: str,
        tenant_id: int,
        payload: Dict[str, Any],
        is_super: bool = False,
    ) -> Any:
        """新增一条基准。`is_builtin=True` 需超管权限。返回落库实体（由接口层映射）。"""
        as_builtin = bool(payload.get("is_builtin", False))
        if as_builtin and not is_super:
            raise PermissionDeniedError(
                "平台内置基准仅平台超级管理员可维护，请改为创建本租户基准",
                {"required": "is_super"},
            )
        values = normalize_values(kind, payload)
        values["version"] = int(payload.get("version") or 1)
        values.setdefault("is_active", True)
        if values.get("is_active") is None:
            values["is_active"] = True
        owner = None if as_builtin else tenant_id
        try:
            return await self.repo.insert(kind, owner, values)
        except IntegrityError as exc:
            raise _integrity_to_domain(kind, values, exc) from exc

    async def update(
        self,
        kind: str,
        tenant_id: int,
        row_id: int,
        payload: Dict[str, Any],
        is_super: bool = False,
    ) -> Any:
        """更新一条基准（仅提供的字段生效，`version` 自增）。"""
        row = await self._writable_row(kind, tenant_id, row_id, is_super)
        values = normalize_values(kind, payload)
        explicit_version = payload.get("version")
        values["version"] = (
            int(explicit_version) if explicit_version else int(row.version or 1) + 1
        )
        try:
            return await self.repo.apply_update(row, values)
        except IntegrityError as exc:
            raise _integrity_to_domain(kind, values, exc) from exc

    async def delete(
        self, kind: str, tenant_id: int, row_id: int, is_super: bool = False
    ) -> Dict[str, Any]:
        """删除一条基准，返回删除前摘要（供审计）。"""
        row = await self._writable_row(kind, tenant_id, row_id, is_super)
        summary = self.repo.entity_summary(kind, row)
        await self.repo.remove(row)
        return summary

    async def snapshot(self, tenant_id: Optional[int]) -> Dict[str, Any]:
        """导出基准库当前全量快照（平台内置 + 本租户，JSON 安全）。

        快照即「发布物」：`{gpus:[…], models:[…], cloud_prices:[…], api_prices:[…]}`，
        每行是 `*Out` DTO 的 JSON 形态（数值为字符串、日期为 ISO），可直接回写。
        """
        bundle = await self.bundle(tenant_id)
        return {
            "gpus": [row.model_dump(mode="json") for row in bundle.gpus],
            "models": [row.model_dump(mode="json") for row in bundle.models],
            "cloud_prices": [row.model_dump(mode="json") for row in bundle.cloud_prices],
            "api_prices": [row.model_dump(mode="json") for row in bundle.api_prices],
        }

    async def rollback(
        self,
        tenant_id: int,
        snapshot: Dict[str, Any],
        is_super: bool = False,
    ) -> Dict[str, Any]:
        """把基准库回滚到某次发布的快照值。

        规则：
        - 逐行按 `id` 定位当前行，只提交**与快照不同**的字段（版本自增，回滚本身也留痕）；
        - 快照中为 `None` 的字段不参与回写（视为「当时未填」，不拿 NULL 去覆盖现值）；
        - 已删除的行**不重建**（重建会牵扯归属与权限，宁可显式报告 skipped）；
        - 平台内置行仅超管可回滚，其余计入 skipped。

        Returns:
            `{"updated": [...], "unchanged": int, "skipped": [...]}`
        """
        updated: list = []
        skipped: list = []
        unchanged = 0

        for kind, snapshot_key in SNAPSHOT_KINDS:
            label = BENCHMARK_LABELS.get(kind, kind)
            for snapshot_row in snapshot.get(snapshot_key) or []:
                row_id = int(snapshot_row.get("id") or 0)
                if row_id <= 0:
                    continue
                code = _row_code(kind, snapshot_row)
                row = await self.repo.get_by_id(kind, tenant_id, row_id)
                if row is None:
                    skipped.append(
                        {
                            "kind": kind,
                            "id": row_id,
                            "code": code,
                            "reason": f"{label}已不存在，回滚不重建已删除条目",
                        }
                    )
                    continue
                if row.tenant_id is None and not is_super:
                    skipped.append(
                        {
                            "kind": kind,
                            "id": row_id,
                            "code": code,
                            "reason": "平台内置条目仅平台超级管理员可回滚",
                        }
                    )
                    continue
                diff = diff_snapshot(kind, row, snapshot_row)
                if not diff:
                    unchanged += 1
                    continue
                from_version = int(row.version or 1)
                await self.update(kind, tenant_id, row_id, diff, is_super)
                updated.append(
                    {
                        "kind": kind,
                        "id": row_id,
                        "code": code,
                        "fields": sorted(diff),
                        "from_version": from_version,
                        "to_version": from_version + 1,
                    }
                )
        return {"updated": updated, "unchanged": unchanged, "skipped": skipped}

    async def _writable_row(
        self, kind: str, tenant_id: int, row_id: int, is_super: bool
    ) -> Any:
        """取可写行：不存在 → 404；内置条目非超管 → 403。"""
        row = await self.repo.get_by_id(kind, tenant_id, row_id)
        if row is None:
            label = BENCHMARK_LABELS.get(kind, kind)
            raise NotFoundError(f"{label}不存在或无权访问（id={row_id}）")
        if row.tenant_id is None and not is_super:
            raise PermissionDeniedError(
                "平台内置基准仅平台超级管理员可修改；如需调整请复制为本租户基准",
                {"id": row_id, "kind": kind},
            )
        if row.tenant_id is not None and row.tenant_id != tenant_id:
            raise PermissionDeniedError(
                "不可跨租户修改基准数据", {"id": row_id, "kind": kind}
            )
        return row


def _conflict_error(kind: str, values: Dict[str, Any]) -> ValidationFailedError:
    """唯一键冲突 → 422，并回显冲突字段，便于前端定位。"""
    keys = BENCHMARK_UNIQUE_KEYS.get(kind, [])
    conflict = {key: values.get(key) for key in keys if key in values}
    label = BENCHMARK_LABELS.get(kind, kind)
    return ValidationFailedError(
        f"{label}唯一键冲突（{'/'.join(keys) or 'id'} 已存在），请修改后重试",
        {"conflict": conflict},
    )


def _integrity_to_domain(
    kind: str, values: Dict[str, Any], exc: IntegrityError
) -> Exception:
    """把数据库完整性错误翻译成可读的领域错误。

    只有唯一键冲突（SQLSTATE 23505）才该说「已存在」。此前所有 IntegrityError 一律
    报「唯一键冲突」，把调用方引向完全错误的修改方向——实测踩到过：PUT 传
    `source=null` 触发的是 NOT NULL 违约（23502），却被提示「code 已存在」。
    """
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    label = BENCHMARK_LABELS.get(kind, kind)
    if sqlstate == "23505":
        return _conflict_error(kind, values)
    if sqlstate == "23502":
        column = getattr(orig, "column_name", "") or ""
        return ValidationFailedError(
            f"{label}的字段不可为空：{column}" if column else f"{label}存在必填字段为空",
            {"column": column},
        )
    if sqlstate == "23503":
        return ValidationFailedError(f"{label}引用了不存在的关联对象", {"sqlstate": sqlstate})
    return exc


__all__ = [
    "BenchmarkService",
    "SNAPSHOT_KINDS",
    "diff_snapshot",
    "normalize_values",
    "resolve_cost_benchmark_from_meta",
    "resolve_rent_inc",
]
