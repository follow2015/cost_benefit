"""模型规格解析：从人类可读描述中还原结构化 MoE 字段。

**存在理由**：`BenchmarkModel` 有 `is_moe` / `active_params_b` 两个结构化字段
（C-2 订正引入），用于让引擎按「激活参数」而非「总参数」推导显存与吞吐。
但种子数据把这两项信息只写在 `name` 文本里（如「Kimi K3（2.8T MoE/104B 激活）」），
字段本身留空 ⇒ `effective_active_params_b()` 回退 `M_param`（总参数）
⇒ 2.8T 的 MoE 被当作稠密 2800B 推导，显存与吞吐量级失真。

**不臆造原则**：本模块只解析文本中**显式载明**的信息。
文本没说激活参数的（如「GLM-5.2（743B MoE）」），只置 `is_moe=True`，
`active_params_b` 保持 `None` 交人工补录——宁可缺，不可编。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

_RE_ACTIVE_ZH = re.compile(r"(\d+(?:\.\d+)?)\s*B\s*激活", re.IGNORECASE)
_RE_ACTIVE_A = re.compile(r"(?:^|[^\w])A(\d+(?:\.\d+)?)\s*B", re.IGNORECASE)
_RE_TOTAL = re.compile(r"(\d+(?:\.\d+)?)\s*([BT])\b", re.IGNORECASE)

_RE_MOE = re.compile(r"\bMoE\b", re.IGNORECASE)
_RE_DENSE = re.compile(r"稠密|dense", re.IGNORECASE)


@dataclass(frozen=True)
class ModelSpecGuess:
    """从描述文本推断出的规格（字段为 `None` 表示文本未载明）。"""

    is_moe: Optional[bool]
    active_params_b: Optional[Decimal]
    total_params_b: Optional[Decimal]
    evidence: str

    @property
    def has_any(self) -> bool:
        return self.is_moe is not None or self.active_params_b is not None


def _to_billion(value: str, unit: str) -> Decimal:
    d = Decimal(value)
    return d * 1000 if unit.upper() == "T" else d


def infer_model_spec(name: str) -> ModelSpecGuess:
    """从模型名称/描述解析 MoE 结构化字段。

    解析优先级：`XB 激活` > `AXB`；两者都无则为 `None`。
    显式「稠密」优先于 `MoE` 字样（防止「非 MoE 稠密」这类表述被误判）。
    """
    text = name or ""
    if not text:
        return ModelSpecGuess(None, None, None, "空描述")

    evidences: list[str] = []

    is_moe: Optional[bool]
    if _RE_DENSE.search(text):
        is_moe = False
        evidences.append("描述含「稠密」")
    elif _RE_MOE.search(text):
        is_moe = True
        evidences.append("描述含「MoE」")
    else:
        is_moe = None

    active: Optional[Decimal] = None
    m = _RE_ACTIVE_ZH.search(text)
    if m:
        active = Decimal(m.group(1))
        evidences.append(f"「{m.group(0)}」")
    else:
        m = _RE_ACTIVE_A.search(text)
        if m:
            active = Decimal(m.group(1))
            evidences.append(f"「{m.group(0).strip()}」")

    total: Optional[Decimal] = None
    m2 = _RE_TOTAL.search(text)
    if m2:
        total = _to_billion(m2.group(1), m2.group(2))
        evidences.append(f"「{m2.group(0)}」")

    if active is not None and is_moe is None:
        is_moe = True
        evidences.append("有激活参数 ⇒ MoE")

    if is_moe is False and active is not None:
        active = None
        evidences.append("稠密与激活参数矛盾，丢弃激活值")

    return ModelSpecGuess(
        is_moe=is_moe,
        active_params_b=active,
        total_params_b=total,
        evidence="、".join(evidences) or "无可解析信息",
    )


__all__ = ["ModelSpecGuess", "infer_model_spec"]
