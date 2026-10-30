/**
 * 独立验证 harness（供 scripts/verify-consistency.mjs 打包执行，非 vitest 测试）。
 *
 * 本文件是**仓库内唯一起源**：选项组装逻辑来自 ./goldenOptions（与
 * consistency.test.ts、后端 test_consistency.py 三端同口径）。验证脚本只负责
 * esbuild 打包本文件并执行，不得再内联生成残缺 harness（历史缺陷见 goldenOptions 注释）。
 */

import { Decimal } from '../decimalConfig';
import { computeAll } from '../engine';
import { paramsFromDict } from '../codec';
import { resolve } from '../pathResolve';
import { GOLDEN_CASES, GOLDEN_TOLERANCE, optionsFromCase } from './goldenOptions';

const ZERO = new Decimal(0);
function dev(server: Decimal, client: Decimal): Decimal {
  const d = server.minus(client).abs();
  return server.eq(ZERO) ? d : d.div(server.abs());
}

const tol = GOLDEN_TOLERANCE;
let total = 0, failed = 0;
let maxDev = new Decimal(0);
let maxInfo = '';
for (const c of GOLDEN_CASES) {
  const opts = optionsFromCase(c.options);
  const payload = computeAll(paramsFromDict(c.params), opts);
  for (const [path, expected] of Object.entries(c.expect as Record<string, any>)) {
    total++;
    const actual = resolve(payload, path);
    if (expected === null) {
      if (actual !== null && !(actual instanceof Decimal && actual.isNaN())) failed++;
      continue;
    }
    if (typeof expected === 'string') {
      const actualStr = actual instanceof Decimal ? actual.toString() : String(actual);
      if (actualStr !== expected) { failed++; console.log('STR MISMATCH', c.id, path, 'expected', expected, 'got', actualStr); }
      continue;
    }
    if (typeof expected === 'boolean') {
      if (actual !== expected) failed++;
      continue;
    }
    const expD = new Decimal(String(expected));
    const actD = actual as Decimal;
    const d = dev(expD, actD);
    if (d.gt(tol)) { failed++; console.log('NUM FAIL', c.id, path, 'exp', expD.toString(), 'got', actD.toString(), 'dev', d.toString()); }
    if (d.gt(maxDev)) { maxDev = d; maxInfo = c.id + ' ' + path; }
  }
}
console.log(JSON.stringify({ total, failed, maxDeviation: maxDev.toString(), maxAt: maxInfo }));
