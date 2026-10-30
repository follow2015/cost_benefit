/** 现金流曲线：累计经营现金流 vs 累计折现现金流。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import type { CashflowRow } from '@/shared/types';

export function CashflowChart({ rows }: { rows: CashflowRow[] }): React.ReactElement {
  const periods = rows.map((r) => (r.period_type === 'month' ? `M${r.period}` : `Y${r.period}`));
  const cum = rows.map((r) => Number(r.cum_cf));
  const cumDisc = rows.map((r) => Number(r.cum_discounted_cf));

  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['累计现金流', '累计折现现金流'] },
    grid: { left: 64, right: 24, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: periods, axisLabel: { rotate: 45 } },
    yAxis: { type: 'value', name: '元', axisLabel: { formatter: (v: number) => `${(v / 1e4).toFixed(0)}w` } },
    series: [
      { name: '累计现金流', type: 'line', data: cum, areaStyle: { opacity: 0.1 }, markLine: { silent: true, data: [{ yAxis: 0 }] } },
      { name: '累计折现现金流', type: 'line', data: cumDisc, lineStyle: { type: 'dashed' } },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}
