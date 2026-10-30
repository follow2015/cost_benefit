/**
 * KPI 数值展示（标题 + 数值 + 单位），用于无卡片容器的场合（如向导实时预览侧栏）。
 *
 * 存在的理由：antd `Statistic` 的 content 是 `display:block; white-space:normal`，
 * 值与单位作为行内内容按**字符**断行——窄列（实测 1024px 下每个 KPI 只有 118px）
 * 会把「118.20万 / 元」拆成三行、「Token/度」被拆成「Token/」+「度」，
 * 且同排卡片高度参差。这里改成：数值与单位各自 `nowrap`，容器 `flex-wrap`，
 * 装不下时单位**整块**换到第二行，数值永远完整。
 *
 * 卡片容器场景请用 `StatCard`（已同步同样的 nowrap 约束）。
 */
import React from 'react';
import { DESIGN_TOKENS as T } from '@/shared/theme';

type Tone = 'up' | 'down' | 'neutral';

const TONE_COLOR: Record<Tone, string> = {
  up: T.colors.up,
  down: T.colors.down,
  neutral: T.colors.fg,
};

interface Props {
  /** 指标名（允许折行，它是说明性文本）。 */
  label: string;
  /** 已格式化的数值文本（由 `formatKpiValue` 产出）。 */
  value: string;
  /** 已格式化的单位（由 `formatKpiUnit` 产出，可能为空）。 */
  unit?: string;
  tone?: Tone;
  /** 数值字号，默认 20（侧栏场景比结果页的 22 略小）。 */
  valueSize?: number;
  /** 悬浮提示，默认给 label 兜底（长标签被截断时可看全）。 */
  hint?: string;
}

export function KpiStat({
  label,
  value,
  unit,
  tone = 'neutral',
  valueSize = 20,
  hint,
}: Props): React.ReactElement {
  return (
    <div title={hint ?? label}>
      <div style={{ fontSize: 12, color: T.colors.fgSecondary, lineHeight: 1.4, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 4 }}>
        <span
          className="num-mono"
          data-kpi-value=""
          style={{
            fontSize: valueSize,
            fontWeight: 600,
            lineHeight: 1.2,
            color: TONE_COLOR[tone],
            whiteSpace: 'nowrap',
          }}
        >
          {value}
        </span>
        {unit ? (
          <span data-kpi-unit="" style={{ fontSize: 12, color: T.colors.fgMuted, whiteSpace: 'nowrap' }}>{unit}</span>
        ) : null}
      </div>
    </div>
  );
}
