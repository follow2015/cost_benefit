/**
 * 计算口径（Conventions）。与后端 `app/calc/context.py` 对齐。
 * 硬约束：CNY 本位币、税前、利用率 U = 有效负载 / 满负荷算力。
 */

import { D, Decimal } from './decimalConfig';

export const UTILIZATION_DEF_EFFECTIVE_LOAD = 'effective_load_over_capacity';

export const ENGINE_VERSION = 'calc-ts-0.2.0';
// 1.2.0：新增硬件反选公式 F100/F101（§3.13，2026-08-19）
export const FORMULA_SPEC_VERSION = '1.2.0';

export interface Conventions {
  currency: string;
  taxed: boolean;
  utilization_def: string;
  fx: Decimal;
}

export const DEFAULT_CONVENTIONS: Conventions = {
  currency: 'CNY',
  taxed: false,
  utilization_def: UTILIZATION_DEF_EFFECTIVE_LOAD,
  fx: ONE_PLACEHOLDER(),
};

function ONE_PLACEHOLDER(): Decimal {
  return D(1);
}

export function defaultConventions(): Conventions {
  return {
    currency: 'CNY',
    taxed: false,
    utilization_def: UTILIZATION_DEF_EFFECTIVE_LOAD,
    fx: D(1),
  };
}
