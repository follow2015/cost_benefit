"""十进制高精度配置（单一事实来源之一）。

硬约束（架构 §1.4 / §3.12）：
- precision = 34，rounding = ROUND_HALF_UP；
- 非整数幂 `x^y` 统一实现为 `exp(ln(x) * y)`，与前端 decimal.js 完全同法；
- 内部全程高精度，**仅在 API 边界/展示层量化**：金额 2 位、比率/单位成本 6 位有效、NPV/IRR 2 位；
- Decimal 以字符串出入 JSON，禁止经由 float 中转。

精度安装（redesign 显式化）：本模块不再于 import 期篡改全局 decimal 上下文
（旧实现的三行 `DefaultContext/setcontext` 是隐式全局副作用，破坏领域层纯度约定）。
现由 `install_calc_context()` 显式安装，唯一调用点是领域包边界
`ai_roi/domain/calc/__init__.py`——精度策略由包入口单一持有、可测试、可审计。
安装同时覆盖当前线程与新线程默认上下文（FastAPI threadpool 亦生效）。

前端对应文件：`frontend/src/calc-engine/decimalConfig.ts`
"""

from __future__ import annotations

import decimal
from decimal import Context, Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Union

DECIMAL_PRECISION: int = 34
DECIMAL_ROUNDING: str = ROUND_HALF_UP

CALC_CONTEXT: Context = Context(prec=DECIMAL_PRECISION, rounding=DECIMAL_ROUNDING)


def install_calc_context() -> None:
    """把计算精度策略安装为进程级 decimal 上下文（幂等）。

    覆盖当前线程上下文与新线程默认上下文（FastAPI threadpool 亦生效）。
    调用方必须是领域包边界（`ai_roi.domain.calc.__init__`），禁止在叶子模块调用。
    """
    decimal.DefaultContext.prec = DECIMAL_PRECISION
    decimal.DefaultContext.rounding = DECIMAL_ROUNDING
    decimal.setcontext(CALC_CONTEXT)

Numeric = Union[int, str, float, Decimal]

ZERO: Decimal = Decimal(0)
ONE: Decimal = Decimal(1)
HUNDRED: Decimal = Decimal(100)

H: Decimal = Decimal(720)
SEC: Decimal = Decimal(2_592_000)
DAYS: Decimal = Decimal(30)
MTOK: Decimal = Decimal(1_000_000)
MONTHS_PER_YEAR: Decimal = Decimal(12)


def D(value: Numeric) -> Decimal:
    """把任意数值安全转为 Decimal。

    float 输入先转 `repr` 字符串，避免二进制浮点污染（PRD §2.8 硬约束）。
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, bool):
        return ONE if value else ZERO
    return Decimal(str(value))


def dpow(base: Decimal, exponent: Decimal) -> Decimal:
    """幂运算：整数指数走 `**`，非整数指数走 `exp(ln(x)·y)`（与前端同法）。"""
    if exponent == exponent.to_integral_value() and abs(exponent) < Decimal(10_000):
        return base ** int(exponent)
    if base <= ZERO:
        raise ValueError(f"非整数幂要求底数 > 0，实际 base={base}")
    return (base.ln() * exponent).exp()


def safe_div(numerator: Decimal, denominator: Decimal, default: Decimal = ZERO) -> Decimal:
    """除法：分母为 0 时返回 default（避免抛异常中断整条推导链）。"""
    if denominator == ZERO:
        return default
    return numerator / denominator


def pct_to_ratio(percent: Numeric) -> Decimal:
    """百分数 → 比率（30 → 0.3）。"""
    return D(percent) / HUNDRED


def ratio_to_pct(ratio: Numeric) -> Decimal:
    """比率 → 百分数（0.3 → 30）。"""
    return D(ratio) * HUNDRED


def q_money(value: Decimal) -> Decimal:
    """金额量化：2 位小数（分）。"""
    return D(value).quantize(Decimal("0.01"), rounding=DECIMAL_ROUNDING)


def q_rate(value: Decimal) -> Decimal:
    """比率/IRR 量化：6 位小数。"""
    return D(value).quantize(Decimal("0.000001"), rounding=DECIMAL_ROUNDING)


def q_sig6(value: Decimal) -> Decimal:
    """单位成本量化：6 位有效数字。"""
    dec = D(value)
    if dec == ZERO:
        return ZERO
    ctx = Context(prec=6, rounding=DECIMAL_ROUNDING)
    return ctx.create_decimal(dec)


def dec_str(value: Decimal) -> str:
    """Decimal → JSON 字符串（定点表示，不使用科学计数法）。"""
    dec = D(value)
    if dec == dec.to_integral_value() and abs(dec) < Decimal("1e16"):
        return str(dec.quantize(Decimal(1)))
    normalized = dec.normalize()
    sign, digits, exponent = normalized.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def to_jsonable(value: Any) -> Any:
    """递归把结构体中的 Decimal 转成字符串，供 JSON 交换。"""
    if isinstance(value, Decimal):
        return dec_str(value)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        return dec_str(D(value))
    return value


def dsum(values: Iterable[Decimal]) -> Decimal:
    """Decimal 求和（避免 sum() 的 int 起点类型混用）。"""
    total = ZERO
    for item in values:
        total += D(item)
    return total


def dmax(left: Decimal, right: Decimal) -> Decimal:
    """两个 Decimal 取大。"""
    return left if left >= right else right


def dmin(left: Decimal, right: Decimal) -> Decimal:
    """两个 Decimal 取小。"""
    return left if left <= right else right
