/** 成本结构饼图：单位成本拆解（固定会计 / 可变 / 等）。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import type { CalcPayload } from '@/shared/types';

export function CostStructurePie({ payload }: { payload: CalcPayload }): React.ReactElement {
  const breakdown = (payload.unit_cost?.breakdown as { key: string; label: string; amount: string; share: string }[]) ?? [];
  const data = breakdown.map((b) => ({ name: b.label, value: Number(b.amount) }));

  const option = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        name: '成本结构',
        type: 'pie',
        radius: ['40%', '70%'],
        data,
        label: { formatter: '{b}\n{d}%' },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}
