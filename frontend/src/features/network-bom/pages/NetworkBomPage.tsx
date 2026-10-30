/**
 * 组网配套清单估算（独立工具页，不走后端 /calc/recommend）：
 * 在已知 GPU 卡数 / 通用计算节点 / 存储容量 的前提下，选择互联形态（IB / RoCE）
 * 与各平面端口速率（算力网 GPU·通算 = 400G、存储网 = 200G 等独立可调），
 * 前端镜像引擎 `estimateNetwork` 直接算出：算力交换机（Leaf）、Spine 核心交换机、
 * 存储交换机、管理交换机、NIC、光模块、AOC、MPO 的数量与 BOM 金额。
 *
 * 与后端零耦合：纯前端估算，便于快速出"组网配套物料清单"。
 */
import React from 'react';
import { Card, Row, Col, InputNumber, Select, Button, Table, Statistic, Typography, Divider, Tag, Alert } from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { Decimal } from '@/features/calc/engine/decimalConfig';
import {
  estimateNetwork,
  DEFAULT_CATALOG,
  type NetworkEstimate,
} from '@/features/calc/engine/supportingCost';

const FABRIC_OPTIONS = [
  { value: 'ib', label: 'IB（InfiniBand，H 系列）' },
  { value: 'roce', label: 'RoCE（以太网，消费级/国产）' },
  { value: 'rdma', label: 'RDMA（兼容旧值）' },
];
const SPEED_OPTIONS = [
  { value: 100, label: '100G' },
  { value: 200, label: '200G' },
  { value: 400, label: '400G' },
  { value: 800, label: '800G' },
];

function fmt(v: unknown, digits = 0): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(digits || 2)}万`;
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

export default function NetworkBomPage(): React.ReactElement {
  const [nGpu, setNGpu] = React.useState<number | null>(128);
  const [cardsPerNode, setCardsPerNode] = React.useState<number>(8);
  const [extraNodes, setExtraNodes] = React.useState<number>(0);
  const [storageTb, setStorageTb] = React.useState<number>(300);
  const [fabric, setFabric] = React.useState<string>('ib');
  const [computeSpeed, setComputeSpeed] = React.useState<number>(400);
  const [storageSpeed, setStorageSpeed] = React.useState<number>(200);
  const [spineSpeed, setSpineSpeed] = React.useState<number | undefined>(undefined);

  const est: NetworkEstimate = React.useMemo(() => {
    const n = Decimal(nGpu && nGpu > 0 ? String(nGpu) : '0');
    const storageGb = Decimal(String((storageTb || 0) * 1000));
    return estimateNetwork(
      n,
      Decimal(String(cardsPerNode || 1)),
      fabric,
      DEFAULT_CATALOG,
      storageGb,
      extraNodes || 0,
      undefined,
      computeSpeed,
      spineSpeed,
      storageSpeed,
    );
  }, [nGpu, cardsPerNode, extraNodes, storageTb, fabric, computeSpeed, storageSpeed, spineSpeed]);

  const rows = React.useMemo(() => {
    const p = est.prices;
    const items: Array<{
      key: string;
      name: string;
      qty: number;
      unit: string;
      unitPrice: string;
      subtotal: string;
      speed?: string;
    }> = [
      {
        key: 'compute_switch',
        name: `算力交换机 Leaf（${fabric.toUpperCase()}）`,
        qty: p.compute_switch.qty,
        unit: p.compute_switch.unit,
        unitPrice: fmt(p.compute_switch.unit_price),
        subtotal: fmt(est.compute_switch_capex),
        speed: p.compute_switch.port_speed_gbps ? `${p.compute_switch.port_speed_gbps}G` : undefined,
      },
      {
        key: 'spine_switch',
        name: 'Spine 核心交换机',
        qty: p.spine_switch.qty,
        unit: p.spine_switch.unit,
        unitPrice: fmt(p.spine_switch.unit_price),
        subtotal: fmt(est.spine_switch_capex),
        speed: p.spine_switch.port_speed_gbps ? `${p.spine_switch.port_speed_gbps}G` : undefined,
      },
      {
        key: 'storage_switch',
        name: '存储交换机（IP SAN）',
        qty: p.storage_switch.qty,
        unit: p.storage_switch.unit,
        unitPrice: fmt(p.storage_switch.unit_price),
        subtotal: fmt(est.storage_switch_capex),
        speed: p.storage_switch.port_speed_gbps ? `${p.storage_switch.port_speed_gbps}G` : undefined,
      },
      {
        key: 'mgmt_switch',
        name: '管理交换机',
        qty: p.mgmt_switch.qty,
        unit: p.mgmt_switch.unit,
        unitPrice: fmt(p.mgmt_switch.unit_price),
        subtotal: fmt(est.mgmt_switch_capex),
      },
      {
        key: 'nic',
        name: '跨机 NIC（含通用节点）',
        qty: p.nic.qty,
        unit: p.nic.unit,
        unitPrice: fmt(p.nic.unit_price),
        subtotal: fmt(est.nic_capex),
      },
      {
        key: 'optics_400g',
        name: `${est.port_speed_gbps.toString()}G 光模块（Leaf 上联）`,
        qty: p.optics_400g.qty,
        unit: p.optics_400g.unit,
        unitPrice: fmt(p.optics_400g.unit_price),
        subtotal: fmt(est.optics_400g_capex),
      },
      {
        key: 'optics_100g',
        name: `${est.storage_port_speed_gbps.toString()}G 光模块（存储上联）`,
        qty: p.optics_100g.qty,
        unit: p.optics_100g.unit,
        unitPrice: fmt(p.optics_100g.unit_price),
        subtotal: fmt(est.optics_100g_capex),
      },
      {
        key: 'aoc',
        name: 'AOC 有源光缆（服务器→TOR）',
        qty: p.aoc.qty,
        unit: p.aoc.unit,
        unitPrice: fmt(p.aoc.unit_price),
        subtotal: fmt(est.aoc_capex),
      },
      {
        key: 'mpo',
        name: 'MPO 主干线缆（Leaf↔Spine）',
        qty: p.mpo.qty,
        unit: p.mpo.unit,
        unitPrice: fmt(p.mpo.unit_price),
        subtotal: fmt(est.mpo_capex),
      },
    ];
    return items;
  }, [est, fabric]);

  const columns = [
    { title: '配置项', dataIndex: 'name', key: 'name', width: 230 },
    {
      title: '速率',
      dataIndex: 'speed',
      key: 'speed',
      width: 70,
      render: (v: string) => (v ? <Tag color="blue">{v}</Tag> : <span style={{ color: '#bbb' }}>—</span>),
    },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 80, align: 'right' as const, render: (v: number) => fmt(v, 0) },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 60 },
    { title: '单价（元）', dataIndex: 'unitPrice', key: 'unitPrice', width: 120, align: 'right' as const },
    { title: '小计（元）', dataIndex: 'subtotal', key: 'subtotal', width: 130, align: 'right' as const, render: (v: string) => <b>{v}</b> },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Typography.Title level={3}>
        <ApiOutlined /> 组网配套清单估算
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        已知 GPU 卡数 / 通用计算节点 / 存储容量，选择互联形态（IB 或 RoCE）与各平面端口速率，
        自动算出所需交换机、NIC、光模块、线缆的数量与物料清单（BOM）。纯前端估算，与后端推荐引擎同口径。
      </Typography.Paragraph>

      <Card size="small" title="输入参数" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]}>
          <Col span={8}>
            <Typography.Text>GPU 卡数</Typography.Text>
            <InputNumber style={{ width: '100%', marginTop: 4 }} min={0} value={nGpu} onChange={(v) => setNGpu(v ?? 0)} placeholder="如 128" />
          </Col>
          <Col span={8}>
            <Typography.Text>单机可插卡数</Typography.Text>
            <InputNumber style={{ width: '100%', marginTop: 4 }} min={1} value={cardsPerNode} onChange={(v) => setCardsPerNode(v ?? 8)} />
          </Col>
          <Col span={8}>
            <Typography.Text>通用计算节点数</Typography.Text>
            <InputNumber style={{ width: '100%', marginTop: 4 }} min={0} value={extraNodes} onChange={(v) => setExtraNodes(v ?? 0)} />
          </Col>
          <Col span={8}>
            <Typography.Text>存储容量（TB）</Typography.Text>
            <InputNumber style={{ width: '100%', marginTop: 4 }} min={0} value={storageTb} onChange={(v) => setStorageTb(v ?? 0)} />
          </Col>
          <Col span={8}>
            <Typography.Text>互联形态</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={fabric} onChange={setFabric} options={FABRIC_OPTIONS} />
          </Col>
          <Col span={8}>
            <Typography.Text>算力网速率（GPU·通算）</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={computeSpeed} onChange={setComputeSpeed} options={SPEED_OPTIONS} />
          </Col>
          <Col span={8}>
            <Typography.Text>存储网速率</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={storageSpeed} onChange={setStorageSpeed} options={SPEED_OPTIONS} />
          </Col>
          <Col span={8}>
            <Typography.Text>Spine 速率（留空=复用算力网）</Typography.Text>
            <Select
              style={{ width: '100%', marginTop: 4 }}
              value={spineSpeed}
              onChange={(v: number | undefined) => setSpineSpeed(v)}
              options={[{ value: undefined, label: '复用算力网' }, ...SPEED_OPTIONS]}
            />
          </Col>
        </Row>
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="组网 CAPEX（元）" value={fmt(est.capex)} /></Card></Col>
        <Col span={6}><Card><Statistic title="月费（元/月）" value={fmt(est.monthly)} /></Card></Col>
        <Col span={6}><Card><Statistic title="功耗（kW）" value={fmt(est.power_kw, 1)} /></Card></Col>
        <Col span={6}><Card><Statistic title="节点数（GPU 机）" value={est.node_count} /></Card></Col>
      </Row>

      <Card size="small" title="组网配套 BOM 清单" extra={<Tag color="geekblue">{fabric.toUpperCase()} · 算力网 {est.port_speed_gbps.toString()}G / 存储网 {est.storage_port_speed_gbps.toString()}G{est.spine_port_speed_gbps.toString() !== est.port_speed_gbps.toString() ? ` / Spine ${est.spine_port_speed_gbps.toString()}G` : ''}</Tag>}>
        <Table
          columns={columns}
          dataSource={rows}
          pagination={false}
          size="small"
          rowKey="key"
          summary={() => (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={5}><b>合计组网 CAPEX</b></Table.Summary.Cell>
              <Table.Summary.Cell index={1} align="right"><b>{fmt(est.capex)}</b></Table.Summary.Cell>
            </Table.Summary.Row>
          )}
        />
        <Divider />
        <Alert
          type="info"
          showIcon
          title="估算假设"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {est.assumptions.map((a, i) => (
                <li key={i} style={{ marginBottom: 2 }}>{a}</li>
              ))}
            </ul>
          }
        />
      </Card>
    </div>
  );
}
