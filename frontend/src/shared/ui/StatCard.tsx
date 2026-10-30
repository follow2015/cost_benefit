/** KPI 指标卡（金融语义：涨红 / 跌绿 / 中性；等宽数字对齐）。 */
import React from 'react';
import { Card, Typography } from 'antd';
import { DESIGN_TOKENS as T } from '@/shared/theme';

type Tone = 'up' | 'down' | 'neutral' | 'accent';

const TONE_COLOR: Record<Tone, string> = {
  up: T.colors.up,
  down: T.colors.down,
  neutral: T.colors.fg,
  accent: T.colors.accent,
};

interface Props {
  title: string;
  value: string;
  suffix?: string;
  tone?: Tone;
  icon?: React.ReactNode;
  hint?: string;
  span?: number;
}

export function StatCard({ title, value, suffix, tone = 'neutral', icon, hint, span }: Props): React.ReactElement {
  return (
    <Card
      size="small"
      className="app-card-hover"
      style={{ height: '100%', boxShadow: T.shadow.card }}
      styles={{ body: { padding: '14px 16px' } }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }} ellipsis>
            {title}
          </Typography.Text>
          {/* 数值与单位各自 nowrap + 容器 wrap：窄列下单位整块换行，
              绝不把「118.20万」从中间拆开（flex 子项被压缩时内部仍会折行）。 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 4 }}>
            <span
              className="num-mono"
              data-kpi-value=""
              style={{
                fontSize: 22,
                fontWeight: 600,
                lineHeight: 1.2,
                color: TONE_COLOR[tone],
                whiteSpace: 'nowrap',
              }}
              title={hint}
            >
              {value}
            </span>
            {suffix ? (
              <span data-kpi-unit="" style={{ fontSize: 12, color: T.colors.fgMuted, whiteSpace: 'nowrap' }}>{suffix}</span>
            ) : null}
          </div>
        </div>
        {icon ? <span style={{ fontSize: 20, color: T.colors.fgMuted, flexShrink: 0 }}>{icon}</span> : null}
      </div>
    </Card>
  );
}
