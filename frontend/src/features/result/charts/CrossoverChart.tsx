/** 三方案成本线对比图：自建 / 租用 / API 的总成本随需求 Q 变化，标注临界规模。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import type { CrossoverPayload } from '@/shared/types';

export function CrossoverChart({ crossover }: { crossover: CrossoverPayload }): React.ReactElement {
  const series = crossover.curves.map((curve) => ({
    name: curve.label,
    type: 'line',
    showSymbol: false,
    smooth: true,
    data: curve.points.map((p) => [Number(p.Q), Number(p.total_cost)]),
  }));

  const crossovers = crossover.crossovers
    .filter((c) => c.Q !== null)
    .map((c) => ({
      xAxis: Number(c.Q),
    }));

  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: crossover.curves.map((c) => c.label) },
    grid: { left: 70, right: 30, top: 40, bottom: 50 },
    xAxis: { type: 'value', name: '等效月需求 Mtok', axisLabel: { formatter: (v: number) => v.toFixed(0) } },
    yAxis: { type: 'value', name: '总成本 元/月', axisLabel: { formatter: (v: number) => `${(v / 1e4).toFixed(0)}w` } },
    series: [
      ...series,
      ...(crossovers.length
        ? [{ name: '临界规模', type: 'line' as const, markLine: { silent: true, symbol: 'none', data: crossovers, label: { formatter: '临界' } } }]
        : []),
    ],
  };
  return <ReactECharts option={option} style={{ height: 340 }} notMerge />;
}
