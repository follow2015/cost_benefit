"""点号路径解析（纯函数，供黄金向量断言与 UI 追溯使用）。

支持形如：`derived.CAPEX`、`cost_models[0].b`、`crossover.recommended[1].best_plan`。
前端对应实现：`frontend/src/calc-engine/pathResolve.ts`（算法一致）。
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def parse_path(path: str) -> List[Tuple[str, Any]]:
    """把路径解析为 `[('key', name) | ('index', i)]` 序列。"""
    tokens: List[Tuple[str, Any]] = []
    for match in _TOKEN_RE.finditer(path):
        key, index = match.group(1), match.group(2)
        if key is not None:
            tokens.append(("key", key))
        elif index is not None:
            tokens.append(("index", int(index)))
    return tokens


def resolve(payload: Any, path: str) -> Any:
    """按路径取值，路径不存在返回 None。"""
    current: Any = payload
    for kind, token in parse_path(path):
        if current is None:
            return None
        if kind == "key":
            if isinstance(current, dict):
                current = current.get(token)
            else:
                current = getattr(current, token, None)
        else:
            if isinstance(current, (list, tuple)) and 0 <= token < len(current):
                current = current[token]
            else:
                return None
    return current
