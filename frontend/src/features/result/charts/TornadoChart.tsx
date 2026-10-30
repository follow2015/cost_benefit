/** 敏感性龙卷风图：各参数 ±Δ 对目标（NPV）的摆动幅度，降序。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import type { SensitivityPayload } from '@/shared/types';

export function TornadoChart({ sensitivity }: { sensitivity: SensitivityPayload }): React.ReactElement {
  const items = [...sensitivity.items].sort((a, b) => Math.abs(Number(b.swing)) - Math.abs(Number(a.swing)));
  const labels = items.map((it) => it.label);
  const low = items.map((it) => -Math.abs(Number(it.delta_low)));
  const high = items.map((it) => Math.abs(Number(it.delta_high)));

  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['-Δ', '+Δ'] },
    grid: { left: 140, right: 40, top: 30, bottom: 30 },
    xAxis: { type: 'value', name: '对目标的相对影响', axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` } },
    yAxis: { type: 'category', data: labels },
    series: [
      { name: '-Δ', type: 'bar', stack: 'total', itemStyle: { color: '#ff7875' }, data: low },
      { name: '+Δ', type: 'bar', stack: 'total', itemStyle: { color: '#52c41a' }, data: high },
    ],
  };
  return <ReactECharts option={option} style={{ height: 360 }} notMerge />;
}
