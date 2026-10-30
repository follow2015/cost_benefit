/** 点号路径解析（供黄金向量断言与测试读取嵌套字段）。对齐后端 `app/calc/path_resolve.py`。 */

import { Decimal } from './decimalConfig';

function getAt(root: unknown, path: string): unknown {
  const segments = path.split('.');
  let current: unknown = root;
  for (const segment of segments) {
    if (current === null || current === undefined) return null;
    const idxMatch = segment.match(/^(\w+)\[(-?\d+)\]$/);
    if (idxMatch) {
      const list = (current as Record<string, unknown>)[idxMatch[1]];
      if (!Array.isArray(list)) return null;
      const index = Number(idxMatch[2]);
      if (index < 0 || index >= list.length) return null;
      current = list[index];
      continue;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current === undefined ? null : current;
}

/** 解析点号路径（支持 `a[0].b` 形式），返回 Decimal 或原始值。 */
export function resolve(root: unknown, path: string): unknown {
  const value = getAt(root, path);
  if (value instanceof Decimal) return value;
  return value;
}

export function resolveStr(root: unknown, path: string): string | null {
  const value = resolve(root, path);
  if (value === null || value === undefined) return null;
  if (value instanceof Decimal) return value.toString();
  return String(value);
}
