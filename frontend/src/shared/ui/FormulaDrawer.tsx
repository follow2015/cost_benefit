/** 公式速查抽屉：渲染 Formula Spec（ⓘ 口径溯源），按分组展示。 */
import React from 'react';
import { Drawer, Table, Tag, Typography, Tabs } from 'antd';
import { FORMULAS, GROUP_COST, GROUP_REVENUE, GROUP_BREAKEVEN, GROUP_FINANCE, GROUP_COMPARE, type FormulaDef } from '@/features/calc/engine/formulaSpec';

const GROUP_LABELS: Record<string, string> = {
  [GROUP_COST]: '成本链路推导',
  [GROUP_REVENUE]: '收入与毛利',
  [GROUP_BREAKEVEN]: '盈亏平衡',
  [GROUP_FINANCE]: '投资财务指标',
  [GROUP_COMPARE]: '多方案对比',
};

const GROUP_ORDER = [GROUP_COST, GROUP_REVENUE, GROUP_BREAKEVEN, GROUP_FINANCE, GROUP_COMPARE];

export function FormulaDrawer({ open, onClose }: { open: boolean; onClose: () => void }): React.ReactElement {
  const tabs = GROUP_ORDER.map((group) => ({
    key: group,
    label: GROUP_LABELS[group],
    children: (
      <Table<FormulaDef>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={FORMULAS.filter((f) => f.group === group)}
        columns={[
          { title: '编号', dataIndex: 'id', width: 70 },
          { title: '名称', dataIndex: 'name', width: 150 },
          {
            title: '公式',
            dataIndex: 'expr',
            render: (expr: string) => <Typography.Text code>{expr}</Typography.Text>,
          },
          {
            title: '单位',
            dataIndex: 'unit',
            width: 90,
            render: (u: string) => (u ? <Tag>{u}</Tag> : null),
          },
          {
            title: '说明',
            dataIndex: 'note',
            render: (note: string) => note || '—',
          },
        ]}
      />
    ),
  }));

  return (
    <Drawer title="公式速查 · 口径溯源" size={720} open={open} onClose={onClose}>
      <Tabs items={tabs} />
    </Drawer>
  );
}
