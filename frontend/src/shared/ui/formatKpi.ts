/**
 * KPI 数值展示格式化（结果页 / 对比页 / 向导实时预览共用同一口径）。
 *
 * 分工约定：**单位由容器承载**（结果页与预览用卡片后缀，对比页用行标题），
 * 本模块只负责「数值 → 文本」，因此不得把单位需要的换算塞进来。
 *
 * 历史缺陷：`months` 曾与 `ratio` 合并处理（`num × 100 + '%'`），
 * 导致「静态回本 21.79 月」被渲染成「2179.28%月」；`interest_coverage`（倍数）
 * 也被当成比率放大 100 倍。此文件是唯一实现，避免三处副本再次漂移。
 */
import type { Kpi } from '@/shared/types';

export type KpiLike = Pick<Kpi, 'kind' | 'value'>;

/** 千分位以上改用「万 / 亿」，与中文财务口径一致。 */
function formatMagnitude(num: number): string {
  if (Math.abs(num) >= 1e8) return `${(num / 1e8).toFixed(2)}亿`;
  if (Math.abs(num) >= 1e4) return `${(num / 1e4).toFixed(2)}万`;
  return num.toFixed(2);
}

/**
 * 把 KPI 数值转成展示文本。
 *
 * @param kpi KPI（只读 `kind` / `value`）
 * @param fallback 空值时的占位文案（结果页用「无解」，对比页与预览用「—」）
 */
export function formatKpiValue(kpi: KpiLike, fallback = '—'): string {
  const raw = kpi.value;
  if (raw === null || raw === undefined) return fallback;
  // 文本型 KPI（如 recommended_plan 的方案名）原样展示，不做数值解释
  if (kpi.kind === 'text') return String(raw);
  const num = Number(raw);
  if (!Number.isFinite(num)) return fallback;
  switch (kpi.kind) {
    case 'ratio':
      // 比率（毛利率 / IRR / ROI / 资产负债率）：0.4646 → 46.46%
      return `${(num * 100).toFixed(2)}%`;
    case 'months':
    case 'number':
      // 月数（回本周期）与倍数（利息覆盖）：量纲不是百分比，单位由后缀承载
      return num.toFixed(2);
    default:
      // money / cost / count：金额与单价按万·亿进位
      return formatMagnitude(num);
  }
}

/**
 * 把 KPI 单位转成**紧邻数值展示**用的文本（与 `formatKpiValue` 配套）。
 *
 * 与数值不同，单位只在「信息增量」时才显示：
 * - `ratio`：数值已渲染成 `46.46%`，元数据里的「比率 / 比率/年」是量纲说明而非
 *   单位，紧跟在百分号后面只会制造噪音（且它宽 88–94px，是窄列换行的主因之一）；
 *   「年化」由 label「IRR（年化）」承载，故返回空。
 * - 其余（元 / 月 / 元/卡/天 / Token/度 …）原样保留。
 *
 * 注意：tooltip、对比页表头这类**说明性**场合应继续用 `kpi.unit` 原文，
 * 只有紧贴数值的后缀才走本函数。
 */
export function formatKpiUnit(kpi: KpiLike): string {
  if (kpi.kind === 'ratio' || kpi.kind === 'text') return '';
  const unit = (kpi as { unit?: string | null }).unit;
  return unit ?? '';
}

/** KPI 是否按语义着色（收益类指标盈亏用红/绿）。 */
export const PROFIT_KPIS: ReadonlySet<string> = new Set([
  'npv',
  'roi',
  'irr',
  'levered_npv',
  'levered_irr',
  'roe',
  'gross_margin',
  'gm_pct',
  'gross_margin_benchmark',
]);
