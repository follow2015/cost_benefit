/** 自定义情景并列图（P3 增量）：任意 K 组参数覆盖 → KPI 并列对比。
 *  突破保守/基准/乐观三档；复用 evaluate_kpis 口径。
 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import { Table, Tag, Typography } from 'antd';
import type { CustomScenarioSetPayload } from '@/shared/types';

export function CustomScenarioChart({
  customScenarios,
  metric = 'npv',
}: {
  customScenarios: CustomScenarioSetPayload;
  metric?: 'npv' | 'irr' | 'roi' | 'cost_per_m' | 'payback_static';
}): React.ReactElement {
  const cases = customScenarios.cases ?? [];
  const fmt = (v: string | null | undefined): string => {
    if (v === null || v === undefined) return '无解';
    const num = Number(v);
    if (!Number.isFinite(num)) return '无解';
    return num.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  };

  const labels = cases.map((c) => c.label || c.key);
  const values = cases.map((c) => {
    const kpi = (c.kpis ?? []).find((k) => k.key === metric);
    return kpi?.value != null ? Number(kpi.value) : null;
  });

  const metricLabels: Record<string, string> = {
    npv: 'NPV（元）',
    irr: 'IRR（年化）',
    roi: 'ROI',
    cost_per_m: '每百万 token 成本（元/Mtok）',
    payback_static: '静态回本（月）',
  };

  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 60, right: 40, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', name: metricLabels[metric] ?? metric },
    series: [
      {
        name: metricLabels[metric] ?? metric,
        type: 'bar',
        data: values.map((v) => (v === null ? '-' : v)),
        itemStyle: { color: '#722ed1' },
        label: { show: true, position: 'top', formatter: (p: { value: number | string }) => (p.value === '-' ? '无解' : Number(p.value).toLocaleString('zh-CN', { maximumFractionDigits: 1 })) },
      },
    ],
  };

  const columns = [
    { title: '情景', dataIndex: 'label', render: (v: string, r: { key: string; label: string }) => r.label || r.key },
    {
      title: '可行性',
      dataIndex: 'feasible',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="green">可行</Tag> : <Tag color="red">不可行</Tag>),
    },
    { title: 'NPV', dataIndex: ['kpis', 'npv'], render: (v: string | null | undefined) => fmt(v) },
    { title: 'IRR（年化）', dataIndex: ['kpis', 'irr'], render: (v: string | null | undefined) => (v == null ? '无解' : `${(Number(v) * 100).toFixed(2)}%`) },
    { title: 'ROI', dataIndex: ['kpis', 'roi'], render: (v: string | null | undefined) => (v == null ? '无解' : `${(Number(v) * 100).toFixed(2)}%`) },
    { title: '成本（元/Mtok）', dataIndex: ['kpis', 'cost_per_m'], render: (v: string | null | undefined) => fmt(v) },
    { title: '回本（月）', dataIndex: ['kpis', 'payback_static'], render: (v: string | null | undefined) => (v == null ? '无解' : Number(v).toFixed(1)) },
  ];

  const rows = cases.map((c) => {
    const kpiMap: Record<string, string | null> = {};
    for (const k of c.kpis ?? []) kpiMap[k.key] = k.value;
    return { key: c.key, label: c.label, feasible: c.feasible, kpis: kpiMap, note: c.note };
  });

  return (
    <div>
      {cases.length ? <ReactECharts option={option} style={{ height: 300 }} notMerge /> : <Typography.Text type="secondary">暂无自定义情景</Typography.Text>}
      <Table size="small" rowKey="key" pagination={false} dataSource={rows} columns={columns} style={{ marginTop: 8 }} />
    </div>
  );
}
