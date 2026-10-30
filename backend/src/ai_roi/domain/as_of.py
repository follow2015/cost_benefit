"""生效日期（`as_of`）的语义：它是「这条基准值是哪天的」，不是「哪天录进系统」。

历史包袱：种子数据把 69 条基准全部写成 `date(2026, 8, 1)` —— 那是个**占位常量**。
真实粒度只到月，而且写在 `source` 文本里（`web:2026-08`、`web:JYGPU 2026-08`），
有些条目（`source=seed`）根本没有日期依据。后果：

- 界面上看起来像「8 月 1 日采到的」，实际上没有任何一天与之对应；
- 无法判断一条基准有多老，也就做不了过期提醒 —— 而这正是「基准库数据都很老」
  却说不清老到什么程度的根因。

本模块只做一件事：**从 source 文本还原可辩护的日期，还原不出来就承认不知道（None）**，
而不是拿一个假日期顶上去。显示层据此区分「未核实」与「事实生效日」。

规则（保守优先）：

1. 自动链路写入的（`inferencex:` / `authority:` 前缀）日期就是真采集日，
   不归本模块管辖，调用方应先 `is_auto_source()` 判掉；
2. `source` 里有完整 `YYYY-MM-DD` → 用它（作者写到日，说明那天有确切依据）；
3. 只有 `YYYY-MM` → 取**该月最后一天**，语义是「不晚于该月末」；
   宁可把数据说新一点，也不要把「8 月看到的价」谎称成「8 月 1 日的价」；
4. 都没有 → `None`（界面显示「未核实」）。
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date

AUTO_SOURCE_PREFIXES: tuple[str, ...] = ("inferencex:", "authority:")

SOURCE_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")

STALE_DAYS = 90

__all__ = [
    "AUTO_SOURCE_PREFIXES",
    "STALE_DAYS",
    "SOURCE_DATE_RE",
    "has_explicit_day",
    "infer_as_of",
    "is_auto_source",
    "staleness_days",
]


def is_auto_source(source: str | None) -> bool:
    """来源是否由自动链路写入（这类行的 as_of 是真日期，不应被推断覆盖）。"""
    return bool(source) and str(source).startswith(AUTO_SOURCE_PREFIXES)


def infer_as_of(source: str | None) -> date | None:
    """从 `source` 文本还原可辩护的生效日期；无依据时返回 None。

    >>> infer_as_of("web:智谱官方 2026-08-14（编程+50%）")
    datetime.date(2026, 8, 14)
    >>> infer_as_of("web:JYGPU 2026-08")   # 只到月 → 该月末，语义「不晚于 8 月底」
    datetime.date(2026, 8, 31)
    >>> infer_as_of("seed") is None        # 常识值，根本没有日期依据
    True
    """
    m = SOURCE_DATE_RE.search(str(source or ""))
    if m is None:
        return None

    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None

    day = m.group(3)
    if day is None:
        return date(year, month, monthrange(year, month)[1])
    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def has_explicit_day(source: str | None) -> bool:
    """`source` 里是否写到了「日」。用来区分「确切日期」与「只到月的还原值」。"""
    m = SOURCE_DATE_RE.search(str(source or ""))
    return bool(m and m.group(3))


def staleness_days(as_of: date | None, today: date) -> int | None:
    """距今天数；`as_of` 为空（未核实）或落在未来时返回 None。

    未来日期不当作「新鲜」，而是当作可疑：源头时钟错、或人工把年份敲错，
    这时候给出「-37 天前更新」比不给更误导。
    """
    if as_of is None or as_of > today:
        return None
    return (today - as_of).days
