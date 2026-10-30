/** 多因素联合敏感性图表（P3 增量）：确定性 NPV 区间 + 主效应 + 交互。
 *  与蒙特卡洛严格区分：本图为确定性全因子网格边界与方差分解，非概率分布。
 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import { Row, Col, Statistic, Card, Table, Tag, Typography } from 'antd';
import type { JointSensitivityPayload } from '@/shared/types';

function fmtMoney(v: string | null | undefined): string {
  if (v === null || v === undefined) return '无解';
  const num = Number(v);
  if (!Number.isFinite(num)) return '无解';
  if (Math.abs(num) >= 1e8) return `${(num / 1e8).toFixed(2)}亿`;
  if (Math.abs(num) >= 1e4) return `${(num / 1e4).toFixed(2)}万`;
  return num.toFixed(2);
}

export function JointSensitivityChart({
  joint,
  variableLabels,
}: {
  joint: JointSensitivityPayload;
  variableLabels?: Record<string, string>;
}): React.ReactElement {
  const labels = (key: string): string => variableLabels?.[key] ?? key;
  const mainEffects = Object.entries(joint.main_effects ?? {}).sort(
    (a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])),
  );
  const interactions = Object.entries(joint.interactions ?? {});

  const mainOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 120, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: '|ΔE[NPV]|（元）' },
    yAxis: { type: 'category', data: mainEffects.map(([k]) => labels(k)) },
    series: [
      {
        name: '主效应 S_i',
        type: 'bar',
        itemStyle: { color: '#1677ff' },
        data: mainEffects.map(([, v]) => Number(v)),
      },
    ],
  };

  const interOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 120, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: '二阶交互 I_ij（元）' },
    yAxis: { type: 'category', data: interactions.map(([k]) => labels(k)) },
    series: [
      {
        name: '交互效应',
        type: 'bar',
        itemStyle: { color: '#fa8c16' },
        data: interactions.map(([, v]) => Number(v)),
      },
    ],
  };

  const columns = [
    { title: '变量', dataIndex: 'key', render: (k: string) => labels(k) },
    { title: '主效应 S_i（元）', dataIndex: 'main', render: (v: string) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
  ];

  const interColumns = [
    { title: '变量对', dataIndex: 'key', render: (k: string) => labels(k) },
    { title: '二阶交互 I_ij（元）', dataIndex: 'value', render: (v: string) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
  ];

  const p = joint.percentiles ?? {};

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col xs={12} sm={6}>
          <Statistic title="联合 NPV 最小" value={fmtMoney(joint.npv_min)} suffix="元" valueStyle={{ color: '#cf1322' }} />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic title="联合 NPV P5" value={fmtMoney(p.p5)} suffix="元" />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic title="联合 NPV P50" value={fmtMoney(p.p50)} suffix="元" />
        </Col>
        <Col xs={12} sm={6}>
          <Statistic title="联合 NPV 最大" value={fmtMoney(joint.npv_max)} suffix="元" valueStyle={{ color: '#389e0d' }} />
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <Card size="small" title="一阶主效应 S_i（对其余变量全网格平均）">
            {mainEffects.length ? <ReactECharts option={mainOption} style={{ height: 240 }} notMerge /> : <Typography.Text type="secondary">无主效应数据</Typography.Text>}
            <Table size="small" rowKey="key" pagination={false} dataSource={mainEffects.map(([key, main]) => ({ key, main }))} columns={columns} style={{ marginTop: 8 }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="二阶交互效应 I_ij（混合差分）">
            {interactions.length ? <ReactECharts option={interOption} style={{ height: 240 }} notMerge /> : <Typography.Text type="secondary">无交互数据</Typography.Text>}
            <Table size="small" rowKey="key" pagination={false} dataSource={interactions.map(([key, value]) => ({ key, value }))} columns={interColumns} style={{ marginTop: 8 }} />
          </Card>
        </Col>
      </Row>
      {joint.notes?.length ? (
        <div style={{ marginTop: 8 }}>
          {joint.notes.map((n, i) => <Tag key={i} color="orange">{n}</Tag>)}
        </div>
      ) : null}
    </div>
  );
}
