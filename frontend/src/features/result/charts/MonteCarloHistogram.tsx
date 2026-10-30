/** 蒙特卡洛 NPV 分布直方图 + 分布统计（P2-4 / REQ-18）。 */
import React from 'react';
import ReactECharts from '@/shared/ui/EChart';
import { Card, Row, Col, Statistic, Descriptions, Tag, Alert } from 'antd';
import type { MonteCarloResult } from '@/features/calc/engine/montecarlo';

function fmtMoney(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

export function MonteCarloHistogram({ result }: { result: MonteCarloResult }): React.ReactElement {
  const bins = result.histogram;
  const midpoints = bins.map((b) => (b.bin_start + b.bin_end) / 2);
  const counts = bins.map((b) => b.count);

  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 24, top: 30, bottom: 50 },
    xAxis: {
      type: 'category',
      name: 'NPV (元)',
      data: midpoints.map((m) => fmtMoney(m)),
      axisLabel: { rotate: 30, fontSize: 9 },
    },
    yAxis: { type: 'value', name: '频数' },
    series: [{ type: 'bar', data: counts, itemStyle: { color: '#2f54eb' } }],
  };

  const pPosTag = result.p_npv_positive >= 0.5
    ? <Tag color="green">{(result.p_npv_positive * 100).toFixed(1)}%</Tag>
    : <Tag color="red">{(result.p_npv_positive * 100).toFixed(1)}%</Tag>;

  return (
    <div>
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} md={6}>
          <Statistic title="NPV 均值" value={fmtMoney(result.mean_npv)} />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Statistic title="NPV 标准差" value={fmtMoney(result.std_npv)} />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Statistic title="P5 / P50 / P95" value={`${fmtMoney(result.percentiles_npv.p5)} / ${fmtMoney(result.percentiles_npv.p50)} / ${fmtMoney(result.percentiles_npv.p95)}`} />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Statistic title="P(NPV>0)" valueRender={() => pPosTag} />
        </Col>
      </Row>
      <Descriptions column={2} size="small" style={{ marginTop: 8 }}>
        <Descriptions.Item label="P10 / P25 / P75 / P90">
          {fmtMoney(result.percentiles_npv.p10)} / {fmtMoney(result.percentiles_npv.p25)} / {fmtMoney(result.percentiles_npv.p75)} / {fmtMoney(result.percentiles_npv.p90)}
        </Descriptions.Item>
        <Descriptions.Item label="P(IRR>r_w)">{(result.p_irr_gt_rw * 100).toFixed(1)}%</Descriptions.Item>
        <Descriptions.Item label="确定性 NPV（基准）">{fmtMoney(result.deterministic_npv)}</Descriptions.Item>
        <Descriptions.Item label="抽样次数 N">{result.n}</Descriptions.Item>
      </Descriptions>
      <ReactECharts option={option} style={{ height: 300 }} notMerge />
      {result.notes?.length ? (
        <Alert style={{ marginTop: 8 }} type="info" showIcon title={result.notes[0]} />
      ) : null}
    </div>
  );
}
