/**
 * 十进制高精度配置（前端单一事实来源之一）。
 * 与后端 `app/calc/decimal_config.py` 严格对齐：
 * - precision = 34，rounding = ROUND_HALF_UP；
 * - 非整数幂 `x^y` 统一实现为 `exp(ln(x)·y)`；
 * - Decimal 全程以字符串出入 JSON，禁止经由 float 中转。
 * 依赖：decimal.js（npm i decimal.js）。
 */

import Decimal from 'decimal.js';

Decimal.set({ precision: 34, rounding: Decimal.ROUND_HALF_UP });

// 部分 decimal.js 构建（如 10.6.0）未挂载 `ne` 实例方法，这里做一次性 Polyfill，
// 保持与 `.eq`(=cmp===0) 语义一致，使引擎内所有 `.ne(...)` 调用无需改动。
declare module 'decimal.js' {
  interface Decimal {
    ne(y: Decimal | number | string): boolean;
  }
}

if (typeof (Decimal.prototype as { ne?: unknown }).ne !== 'function') {
  (Decimal.prototype as { ne: (y: unknown) => boolean }).ne = function (this: Decimal, y: unknown): boolean {
    return this.cmp(y as Decimal) !== 0;
  };
}

export type Numeric = Decimal | number | string | boolean;

export const ZERO = new Decimal(0);
export const ONE = new Decimal(1);
export const HUNDRED = new Decimal(100);

// 每月小时数（24×30）
export const H = new Decimal(720);
// 每月秒数（2,592,000）
export const SEC = new Decimal(2592000);
export const DAYS = new Decimal(30);
// 百万 token
export const MTOK = new Decimal(1000000);
// 每年月数
export const MONTHS_PER_YEAR = new Decimal(12);

/** 把任意数值安全转为 Decimal（float 经 String() 防止二进制污染）。 */
export function D(value: Numeric): Decimal {
  if (typeof value === 'boolean') return value ? ONE : ZERO;
  if (typeof value === 'number') return new Decimal(String(value));
  // 统一走字符串构造，避免 `new Decimal(0)` 自动装箱为原始 number 的问题
  return new Decimal(String(value));
}

/** 幂运算：整数指数走原生 `^`，非整数指数走 `exp(ln(x)·y)`（与后端同法）。 */
export function dpow(base: Decimal, exponent: Decimal): Decimal {
  if (exponent.isInteger() && exponent.abs().lt(10000)) {
    return base.pow(exponent.toNumber());
  }
  if (base.lte(ZERO)) {
    throw new Error(`非整数幂要求底数 > 0，实际 base=${base.toString()}`);
  }
  return base.ln().times(exponent).exp();
}

/** 安全除法：分母为 0 时返回 default。 */
export function safeDiv(numerator: Decimal, denominator: Decimal, fallback: Decimal = ZERO): Decimal {
  if (denominator.eq(ZERO)) return fallback;
  return numerator.div(denominator);
}

export function pctToRatio(percent: Numeric): Decimal {
  return D(percent).div(HUNDRED);
}

export function ratioToPct(ratio: Numeric): Decimal {
  return D(ratio).times(HUNDRED);
}

/** 金额量化：2 位小数。 */
export function qMoney(value: Decimal): Decimal {
  return D(value).toDecimalPlaces(2, Decimal.ROUND_HALF_UP);
}

/** 比率/IRR 量化：6 位小数。 */
export function qRate(value: Decimal): Decimal {
  return D(value).toDecimalPlaces(6, Decimal.ROUND_HALF_UP);
}

/** 单位成本量化：6 位有效数字。 */
export function qSig6(value: Decimal): Decimal {
  const dec = D(value);
  if (dec.eq(ZERO)) return ZERO;
  return dec.toSignificantDigits(6, Decimal.ROUND_HALF_UP);
}

/** Decimal → 定点字符串（不使用科学计数法）。 */
export function decStr(value: Decimal): string {
  const dec = D(value);
  if (dec.isInteger() && dec.abs().lt(new Decimal('1e16'))) {
    return dec.toDecimalPlaces(0, Decimal.ROUND_HALF_UP).toString();
  }
  const normalized = dec;
  return normalized.toFixed();
}

/** 递归把结构体中的 Decimal 转为字符串，供 JSON 交换（对齐后端 to_jsonable）。 */
export function toJsonable(value: unknown): unknown {
  if (value instanceof Decimal) return decStr(value);
  if (value && typeof value === 'object') {
    if (Array.isArray(value)) return value.map(toJsonable);
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>)) {
      out[key] = toJsonable((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

/** Decimal 求和。 */
export function dsum(values: Decimal[]): Decimal {
  return values.reduce((acc, v) => acc.plus(D(v)), ZERO);
}

export function dmax(left: Decimal, right: Decimal): Decimal {
  return left.gte(right) ? left : right;
}

export function dmin(left: Decimal, right: Decimal): Decimal {
  return left.lte(right) ? left : right;
}

export { Decimal };
