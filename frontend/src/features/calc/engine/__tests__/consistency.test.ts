/**
 * 双端一致性测试：前端 decimal.js 引擎复现 `goldenVectors.json` 全部断言，偏差 ≤0.1%。
 * 该文件由后端 `scripts/gen_golden.py` 权威生成，前端镜像实现须对齐。
 *
 * 运行：在 frontend/ 下 `npx vitest run src/calc-engine/__tests__/consistency.test.ts`
 */

import { describe, it, expect } from 'vitest';
import { Decimal } from '../decimalConfig';
import { computeAll } from '../engine';
import { paramsFromDict } from '../codec';
import { resolve, resolveStr } from '../pathResolve';
import { GOLDEN_CASES, GOLDEN_TOLERANCE, optionsFromCase } from './goldenOptions';

function relativeDeviation(server: Decimal, client: Decimal): Decimal {
  const difference = server.minus(client).abs();
  return server.eq(ZERO) ? difference : difference.div(server.abs());
}

const ZERO = new Decimal(0);

describe('前端引擎与黄金向量一致性 (≤0.1%)', () => {
  for (const testCase of GOLDEN_CASES) {
    it(`${testCase.id} - ${testCase.name}`, () => {
      const payload = computeAll(paramsFromDict(testCase.params), optionsFromCase(testCase.options));
      for (const [path, expected] of Object.entries(testCase.expect)) {
        // null 期望：实际应为 null 或 NaN（如不可解时的 irr）
        if (expected === null) {
          const actual = resolve(payload, path);
          expect(actual === null || (actual instanceof Decimal && actual.isNaN())).toBe(true);
          continue;
        }
        // 布尔期望（如 low_feasible / high_feasible）
        if (typeof expected === 'boolean') {
          expect(resolve(payload, path)).toBe(expected);
          continue;
        }
        // 字符串期望（如 k_source、status、best_plan、method、note）
        if (typeof expected === 'string') {
          const actualStr = resolveStr(payload, path);
          expect(actualStr).toBe(expected);
          continue;
        }
        // 数值期望（Decimal 字符串）：校验类型 + ≤0.1% 偏差
        const actual = resolve(payload, path);
        const expectedDecimal = new Decimal(String(expected));
        expect(actual).toBeInstanceOf(Decimal);
        const actualDecimal = actual as Decimal;
        const dev = relativeDeviation(expectedDecimal, actualDecimal);
        expect(dev.lte(GOLDEN_TOLERANCE)).toBe(true);
        if (!dev.lte(GOLDEN_TOLERANCE)) {
          expect(`${path}: golden=${expectedDecimal.toString()} frontend=${actualDecimal.toString()} dev=${dev.toString()}`).toBe('within tolerance');
        }
      }
    });
  }
});
