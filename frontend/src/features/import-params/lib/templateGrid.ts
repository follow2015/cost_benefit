/**
 * 导入模板的表格结构识别（纯函数，与 UI 解耦）。
 *
 * 两种模板的头部结构不同，这是它们各自的「正确形态」而非谁的缺陷：
 * - CSV 模板（前端 `buildCsvTemplate` 生成）：首行即表头，便于粘贴与 diff；
 * - xlsx 模板（后端 openpyxl 生成）：前几行是标题、填写说明与空行，供打印/下发，
 *   表头在第 4 行。
 *
 * 早期解析器一律把 `grid[0]` 当表头，导致「下载官方 xlsx 模板 → 原样上传」必然报
 * 「表头缺少『字段』或『填入值』列」。此处按内容特征定位表头，两种模板都能吃。
 */

/** 表头行识别的扫描上限：正常模板的标题/说明不会超过十几行。 */
const HEADER_SCAN_LIMIT = 10;

/** 判断某行是否为表头：必须同时具备「字段」与「填入值」两列的标识。 */
export function isHeaderRow(row: readonly string[]): boolean {
  const cells = row.map((c) => (c ?? '').trim());
  const hasField = cells.includes('字段') || cells.includes('字段(key)');
  const hasValue = cells.includes('填入值') || cells.includes('值');
  return hasField && hasValue;
}

/**
 * 返回表头所在行号；找不到时返回 0，交由调用方的既有校验给出「表头缺少…」提示。
 * 返回 0 而不是 -1，是为了让错误提示统一从表头缺失路径抛出。
 */
export function findHeaderRow(grid: readonly (readonly string[])[]): number {
  const scan = Math.min(grid.length, HEADER_SCAN_LIMIT);
  for (let i = 0; i < scan; i += 1) {
    if (isHeaderRow(grid[i])) return i;
  }
  return 0;
}
