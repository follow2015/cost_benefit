"""方案服务：CRUD + 版本快照 + 参数 diff。

保存流程：
    1. 解析并校验参数（`params_from_dict` + `validate_params`）；
    2. 与旧参数逐字段 diff；
    3. 有实质变更 → version += 1 并写入快照；
    4. 写审计。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ai_roi.application.ports import ResultRepository, ScenarioRepository, SnapshotRepository, UnitOfWork
from ai_roi.domain.calc.codec import params_from_dict, params_to_dict
from ai_roi.domain.calc.context import FORMULA_SPEC_VERSION
from ai_roi.domain.calc.decimal_config import to_jsonable
from ai_roi.application.schemas.scenario import (
    ScenarioCreate,
    ScenarioDetailOut,
    ScenarioListItemOut,
    ScenarioUpdate,
    SnapshotOut,
)
from ai_roi.domain.errors import NotFoundError
from ai_roi.domain.validation.params import validate_params

Scenario = Any
ScenarioSnapshot = Any


def diff_params(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """逐字段比较两份参数字典，返回 `{"group.field": {"before":..,"after":..}}`。"""
    changes: Dict[str, Any] = {}
    groups = set(before.keys()) | set(after.keys())
    for group in sorted(groups):
        old_group = before.get(group)
        new_group = after.get(group)
        if isinstance(old_group, dict) and isinstance(new_group, dict):
            keys = set(old_group.keys()) | set(new_group.keys())
            for key in sorted(keys):
                old_value = old_group.get(key)
                new_value = new_group.get(key)
                if old_value != new_value:
                    changes[f"{group}.{key}"] = {"before": old_value, "after": new_value}
        elif old_group != new_group:
            changes[group] = {"before": old_group, "after": new_group}
    return changes


class ScenarioService:
    """方案编排服务。"""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.session = uow.session
        self.scenarios: ScenarioRepository = uow.scenarios
        self.snapshots: SnapshotRepository = uow.snapshots
        self.results: ResultRepository = uow.results

    async def get_or_404(self, tenant_id: int, scenario_id: int) -> Scenario:
        """取方案，不存在抛 404。"""
        scenario = await self.scenarios.get(tenant_id, scenario_id)
        if scenario is None:
            raise NotFoundError(f"方案不存在或无权访问（id={scenario_id}）")
        return scenario

    async def detail(self, tenant_id: int, scenario_id: int) -> ScenarioDetailOut:
        """方案详情 DTO。"""
        scenario = await self.get_or_404(tenant_id, scenario_id)
        return _to_detail(scenario)

    async def list_page(
        self,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        status: Optional[str] = None,
    ) -> Tuple[List[ScenarioListItemOut], int]:
        """分页列表，附最近一次计算的 KPI 摘要。"""
        scenarios, total = await self.scenarios.list_page(
            tenant_id, page=page, page_size=page_size, keyword=keyword, status=status
        )
        latest = await self.results.latest_for_scenarios(
            tenant_id, [item.id for item in scenarios]
        )
        items: List[ScenarioListItemOut] = []
        for scenario in scenarios:
            record = latest.get(scenario.id)
            items.append(
                ScenarioListItemOut(
                    id=scenario.id,
                    name=scenario.name,
                    description=scenario.description,
                    status=scenario.status,
                    version=scenario.version,
                    tags=list(scenario.tags or []),
                    is_template=scenario.is_template,
                    conventions=dict(scenario.conventions or {}),
                    latest_kpi=dict(record.kpi_summary or {}) if record else None,
                    latest_result_id=record.id if record else None,
                    created_at=scenario.created_at,
                    updated_at=scenario.updated_at,
                )
            )
        return items, total

    async def snapshots_of(
        self, tenant_id: int, scenario_id: int, limit: int = 50
    ) -> List[SnapshotOut]:
        """快照历史。"""
        await self.get_or_404(tenant_id, scenario_id)
        records = await self.snapshots.list_by_scenario(tenant_id, scenario_id, limit)
        return [_to_snapshot(item) for item in records]

    async def create(
        self, tenant_id: int, user_id: Optional[int], payload: ScenarioCreate
    ) -> Tuple[ScenarioDetailOut, List[Dict[str, str]]]:
        """创建方案（缺省参数回落到内置默认模板）。"""
        params = params_from_dict(payload.params)
        warnings = validate_params(params)
        params_json = to_jsonable(params_to_dict(params))
        conventions = _conventions_summary(params_json)

        scenario = await self.scenarios.create(
            tenant_id=tenant_id,
            created_by=user_id,
            name=payload.name,
            description=payload.description,
            params=params_json,
            conventions=conventions,
            tags=list(payload.tags),
            is_template=payload.is_template,
        )
        await self.snapshots.create(
            tenant_id=tenant_id,
            scenario_id=scenario.id,
            version=scenario.version,
            params=params_json,
            conventions=conventions,
            diff={},
            created_by=user_id,
            note="初始版本",
        )
        return _to_detail(scenario), warnings

    async def update(
        self,
        tenant_id: int,
        user_id: Optional[int],
        scenario_id: int,
        payload: ScenarioUpdate,
    ) -> Tuple[ScenarioDetailOut, List[Dict[str, str]], Dict[str, Any]]:
        """更新方案；参数有实质变更时递增版本并留痕。"""
        scenario = await self.get_or_404(tenant_id, scenario_id)
        warnings: List[Dict[str, str]] = []
        changes: Dict[str, Any] = {}

        if payload.name is not None:
            scenario.name = payload.name
        if payload.description is not None:
            scenario.description = payload.description
        if payload.tags is not None:
            scenario.tags = list(payload.tags)
        if payload.status is not None:
            scenario.status = payload.status

        if payload.params is not None:
            params = params_from_dict(payload.params)
            warnings = validate_params(params)
            new_params = to_jsonable(params_to_dict(params))
            changes = diff_params(dict(scenario.params or {}), new_params)
            if changes:
                scenario.params = new_params
                scenario.conventions = _conventions_summary(new_params)
                scenario.version = int(scenario.version) + 1
                await self.snapshots.create(
                    tenant_id=tenant_id,
                    scenario_id=scenario.id,
                    version=scenario.version,
                    params=new_params,
                    conventions=scenario.conventions,
                    diff=changes,
                    created_by=user_id,
                    note=payload.note,
                )

        await self.session.flush()
        await self.session.refresh(scenario, ["updated_at"])
        return _to_detail(scenario), warnings, changes

    async def delete(self, tenant_id: int, scenario_id: int) -> str:
        """删除方案，返回被删方案名（供审计）。"""
        scenario = await self.get_or_404(tenant_id, scenario_id)
        name = scenario.name
        await self.scenarios.delete(tenant_id, scenario_id)
        return name

    async def duplicate(
        self, tenant_id: int, user_id: Optional[int], scenario_id: int, new_name: str = ""
    ) -> ScenarioDetailOut:
        """复制方案（另存为，向导「基于现有方案新建」用）。"""
        source = await self.get_or_404(tenant_id, scenario_id)
        clone = await self.scenarios.create(
            tenant_id=tenant_id,
            created_by=user_id,
            name=new_name or f"{source.name} 副本",
            description=source.description,
            params=dict(source.params or {}),
            conventions=dict(source.conventions or {}),
            tags=list(source.tags or []),
            is_template=False,
        )
        await self.snapshots.create(
            tenant_id=tenant_id,
            scenario_id=clone.id,
            version=clone.version,
            params=dict(clone.params or {}),
            conventions=dict(clone.conventions or {}),
            diff={},
            created_by=user_id,
            note=f"复制自方案 #{source.id}",
        )
        return _to_detail(clone)


def _conventions_summary(params_json: Dict[str, Any]) -> Dict[str, Any]:
    """从参数中抽取口径摘要（列表页展示与筛选）。"""
    conventions = dict(params_json.get("conventions") or {})
    conventions.setdefault("formula_spec_version", FORMULA_SPEC_VERSION)
    finance = params_json.get("finance") or {}
    conventions["T_horizon"] = finance.get("T_horizon")
    conventions["r_w"] = finance.get("r_w")
    return conventions


def _to_detail(scenario: Scenario) -> ScenarioDetailOut:
    """ORM → 详情 DTO。"""
    return ScenarioDetailOut(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        status=scenario.status,
        version=scenario.version,
        tags=list(scenario.tags or []),
        is_template=scenario.is_template,
        params=dict(scenario.params or {}),
        conventions=dict(scenario.conventions or {}),
        created_by=scenario.created_by,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
    )


def _to_snapshot(record: ScenarioSnapshot) -> SnapshotOut:
    """ORM → 快照 DTO。"""
    return SnapshotOut(
        id=record.id,
        version=record.version,
        note=record.note,
        diff=dict(record.diff or {}),
        created_by=record.created_by,
        created_at=record.created_at,
    )
