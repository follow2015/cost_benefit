/** 盈亏平衡图：收入 vs 成本 随利用率 U 变化，标注 U_be。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import type { CalcPayload } from '@/shared/types';

export function BreakevenChart({ payload }: { payload: CalcPayload }): React.ReactElement {
  const curve = (payload.breakeven?.curve as { U: string; revenue: string; cost: string }[]) ?? [];
  const u = curve.map((p) => Number(p.U));
  const rev = curve.map((p) => Number(p.revenue));
  const cost = curve.map((p) => Number(p.cost));
  const uBe = payload.breakeven?.U_be ? Number(payload.breakeven.U_be) : null;

  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['收入', '成本'] },
    grid: { left: 64, right: 24, top: 40, bottom: 40 },
    xAxis: { type: 'category', name: '利用率 U', data: u.map((x) => `${(x * 100).toFixed(0)}%`), axisLabel: { rotate: 45 } },
    yAxis: { type: 'value', name: '元/月', axisLabel: { formatter: (v: number) => `${(v / 1e4).toFixed(0)}w` } },
    series: [
      { name: '收入', type: 'line', data: rev, smooth: true },
      { name: '成本', type: 'line', data: cost, smooth: true },
      ...(uBe !== null
        ? [{ name: '盈亏平衡', type: 'line' as const, markLine: { silent: true, symbol: 'none', data: [{ xAxis: `${((uBe) * 100).toFixed(0)}%` }], label: { formatter: 'U_be' } } }]
        : []),
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}
