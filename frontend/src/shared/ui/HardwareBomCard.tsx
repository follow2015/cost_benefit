/**
 * 硬件 BOM 展示卡片（方案确定后）：服务器 / 算力·存储·管理交换机 / NIC / 光模块 /
 * AOC·MPO 线缆 / 存储，逐项单价 × 数量 = 小计，底部合计配套 CAPEX。
 *
 * 数据来源：方案参数（反选装配快照 `supporting_fabric/mem_gb/cards_per_node`）+ 前端
 * `supportingCost` 镜像引擎重算（与后端推荐引擎同口径）；非反选来源显示提示。
 */
import React from 'react';
import { Card, Descriptions, Alert, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ScenarioParams } from '@/features/calc/engine/parameters';
import { buildBomFromParams } from '@/features/calc/engine/supportingCost';

const fmt = (v: unknown, digits = 0): string => {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
};

interface Props {
  params: ScenarioParams;
}

export function HardwareBomCard({ params }: Props): React.ReactElement {
  const bom = buildBomFromParams(params);
  if (!bom) {
    return (
      <Alert
        type="info"
        showIcon
        title="非硬件反选来源方案，无配套 BOM"
        description="通过「硬件反选推荐」生成方案后，此处将展示算力服务器、算力/存储/管理交换机、NIC、光模块、AOC/MPO 线缆与存储的完整清单。"
      />
    );
  }

  // 防御式取值：任何 line item 缺失（理论上 buildBomFromParams 已保证完整）也不白屏
  const cs = bom.compute_switch ?? ({ unit_price: undefined, unit: '台', qty: 0, fabric: undefined } as typeof bom.compute_switch);
  const sp = bom.spine_switch ?? ({ unit_price: undefined, unit: '台', qty: 0, fabric: undefined } as typeof bom.spine_switch);
  const ss = bom.storage_switch ?? ({ unit_price: undefined, unit: '台', qty: 0 } as typeof bom.storage_switch);
  const ms = bom.mgmt_switch ?? ({ unit_price: undefined, unit: '台', qty: 0 } as typeof bom.mgmt_switch);
  const ni = bom.nic ?? ({ unit_price: undefined, unit: '卡', qty: 0 } as typeof bom.nic);
  const o4 = bom.optics_400g ?? ({ unit_price: undefined, unit: '个', qty: 0 } as typeof bom.optics_400g);
  const o1 = bom.optics_100g ?? ({ unit_price: undefined, unit: '个', qty: 0 } as typeof bom.optics_100g);
  const ao = bom.aoc ?? ({ unit_price: undefined, unit: '根', qty: 0 } as typeof bom.aoc);
  const mp = bom.mpo ?? ({ unit_price: undefined, unit: '根', qty: 0 } as typeof bom.mpo);
  const rows = [
    { key: 'servers', name: `算力服务器（每台 ${bom.servers.cards_per_node} 卡）`, unit: '台', qty: bom.servers.qty, unit_price: bom.servers.unit_price, subtotal: bom.servers.subtotal },
    { key: 'compute_switch', name: `算力交换机（Leaf / ${cs.fabric ?? '—'}）`, unit: cs.unit, qty: cs.qty, unit_price: cs.unit_price, subtotal: undefined },
    { key: 'spine_switch', name: `Spine 核心交换机（${sp.fabric ?? '—'}）`, unit: sp.unit, qty: sp.qty, unit_price: sp.unit_price, subtotal: undefined },
    { key: 'storage_switch', name: '存储交换机（IP SAN）', unit: ss.unit, qty: ss.qty, unit_price: ss.unit_price, subtotal: undefined },
    { key: 'mgmt_switch', name: '管理交换机', unit: ms.unit, qty: ms.qty, unit_price: ms.unit_price, subtotal: undefined },
    { key: 'nic', name: '跨机 NIC（含通用节点）', unit: ni.unit, qty: ni.qty, unit_price: ni.unit_price, subtotal: undefined },
    { key: 'optics_400g', name: '400G 光模块', unit: o4.unit, qty: o4.qty, unit_price: o4.unit_price, subtotal: undefined },
    { key: 'optics_100g', name: '100G 光模块', unit: o1.unit, qty: o1.qty, unit_price: o1.unit_price, subtotal: undefined },
    { key: 'aoc', name: 'AOC 有源光缆', unit: ao.unit, qty: ao.qty, unit_price: ao.unit_price, subtotal: undefined },
    { key: 'mpo', name: 'MPO 主干线缆（Leaf↔Spine）', unit: mp.unit, qty: mp.qty, unit_price: mp.unit_price, subtotal: undefined },
  ];

  const columns: ColumnsType<(typeof rows)[number]> = [
    { title: '配置项', dataIndex: 'name', key: 'name', width: 220 },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 80, align: 'right', render: (v: number) => fmt(v, 0) },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 70 },
    { title: '单价（元）', dataIndex: 'unit_price', key: 'unit_price', width: 120, align: 'right', render: (v: unknown) => fmt(v, 0) },
    {
      title: '小计（元）',
      key: 'subtotal',
      width: 130,
      align: 'right',
      render: (_: unknown, r) =>
        r.key === 'servers' ? fmt(r.subtotal, 0) : fmt(Number(r.unit_price) * Number(r.qty), 0),
    },
  ];

  return (
    <Card size="small" title="硬件配置清单（BOM）">
      <Table
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={false}
        summary={() => (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={4}>
              <Typography.Text strong>配套 CAPEX 合计（存储 + 组网）</Typography.Text>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={1} align="right">
              <Typography.Text strong>{fmt(bom.total_supporting_capex, 0)} 元</Typography.Text>
            </Table.Summary.Cell>
          </Table.Summary.Row>
        )}
      />
      <Descriptions size="small" column={3} style={{ marginTop: 12 }}>
        <Descriptions.Item label="GPU 卡投资">{fmt(bom.servers.subtotal, 0)} 元</Descriptions.Item>
        <Descriptions.Item label="总硬件投资">
          {fmt(Number(bom.servers.subtotal) + Number(bom.total_supporting_capex), 0)} 元
        </Descriptions.Item>
        <Descriptions.Item label="存储容量">{fmt(bom.storage.capacity_gb, 0)} GB</Descriptions.Item>
        <Descriptions.Item label="存储 CAPEX">{fmt(bom.storage.capex, 0)} 元</Descriptions.Item>
        <Descriptions.Item label="存储月费">{fmt(bom.storage.monthly, 2)} 元/月</Descriptions.Item>
        <Descriptions.Item label="组网形态">{cs.fabric ?? '—'}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}
