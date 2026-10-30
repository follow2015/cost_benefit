"""计算口径（Conventions）。

主理人已确认的硬约束：
- 币种 = CNY（本位币，FX=1）；
- 口径 = 税前（taxed=False）；
- 利用率 U = "实际有效负载占满负荷算力比例"，电费随 U 变动，折旧/托管固定（PRD §1.2-H）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Dict

from ai_roi.domain.calc.decimal_config import D, ONE

UTILIZATION_DEF_EFFECTIVE_LOAD = "effective_load_over_capacity"

ENGINE_VERSION = "calc-py-0.2.0"
FORMULA_SPEC_VERSION = "1.2.0"


@dataclass(frozen=True)
class Conventions:
    """全局口径。所有金额均已按 `fx` 折算为本位币后再进入引擎。"""

    currency: str = "CNY"
    taxed: bool = False
    utilization_def: str = UTILIZATION_DEF_EFFECTIVE_LOAD
    fx: Decimal = ONE

    def to_dict(self) -> Dict[str, Any]:
        """序列化（Decimal → 字符串由上层 to_jsonable 处理）。"""
        return {
            "currency": self.currency,
            "taxed": self.taxed,
            "utilization_def": self.utilization_def,
            "fx": self.fx,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "Conventions":
        """反序列化，缺省回落到确认过的默认口径。"""
        if not data:
            return cls()
        return cls(
            currency=str(data.get("currency", "CNY")),
            taxed=bool(data.get("taxed", False)),
            utilization_def=str(
                data.get("utilization_def", UTILIZATION_DEF_EFFECTIVE_LOAD)
            ),
            fx=D(data.get("fx", 1)),
        )

    def with_taxed(self, taxed: bool) -> "Conventions":
        """返回切换含税口径后的新口径对象（不可变语义）。"""
        return replace(self, taxed=taxed)


DEFAULT_CONVENTIONS = Conventions()
