/** 多方案横向对比：选择多个方案，调用 /calc/compare 同口径重算并展示 KPI 矩阵。 */
import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Select, Table, Tag, Button, Space, Typography, App as AntApp } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useScenarioList } from '@/features/scenarios/hooks/useScenarios';
import { useCompare } from '@/features/calc/hooks/useCalc';
import { formatKpiValue } from '@/shared/ui/formatKpi';
import type { CompareMeta, CompareItem, Kpi } from '@/shared/types';

export default function ComparePage(): React.ReactElement {
  const { id } = useParams();
  const currentId = Number(id);
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const { data: list } = useScenarioList({ page: 1, page_size: 200 });
  const compareMut = useCompare();
  const [selected, setSelected] = React.useState<number[]>(id ? [currentId] : []);
  const [result, setResult] = React.useState<{ items: CompareItem[]; meta: CompareMeta[] } | null>(null);
  // 选择项相对「上一次对比」是否已变更，用于提示用户需点击按钮刷新。
  const [dirty, setDirty] = React.useState(false);

  // 单次对比逻辑：由「开始对比」按钮显式触发（不再在选中变化时自动重算，
  // 否则按钮会因结果与自动重算一致而显得「点了没反应」）。
  const run = React.useCallback(() => {
    if (selected.length < 1) {
      message.warning('请至少选择一个方案');
      return;
    }
    setDirty(false);
    compareMut
      .mutateAsync({ scenario_ids: selected })
      .then((res) => setResult({ items: res.items, meta: res.kpi_meta }))
      .catch((e) => message.error((e as Error).message));
  }, [selected, compareMut, message]);

  const handleChange = (vals: number[]) => {
    setSelected(vals);
    setDirty(true);
  };

  const options = (list?.items ?? []).map((s) => ({ value: s.id, label: `${s.name}（v${s.version}）` }));
  const columns = [
    { title: '指标', dataIndex: 'label', key: 'label', fixed: 'left' as const, width: 160 },
    ...(result?.items ?? []).map((item) => ({
      title: item.scenario_name,
      dataIndex: `v${item.scenario_id}`,
      key: `v${item.scenario_id}`,
      render: (_: unknown, row: Record<string, unknown>) => {
        const kpi = row[`v${item.scenario_id}`] as Kpi | undefined;
        if (!kpi || kpi.value === null || kpi.value === undefined) return '—';
        if (kpi.kind === 'text') {
          // 文本型 KPI（recommended_plan）：按可行性状态渲染告警标签
          if (kpi.status === 'loss') {
            return (
              <Space size={4}>
                <span>{String(kpi.value)}</span>
                <Tag color="red">亏损</Tag>
              </Space>
            );
          }
          if (kpi.status === 'no_demand') return <Tag color="orange">无解</Tag>;
          return String(kpi.value);
        }
        return formatKpiValue(kpi, '—');
      },
    })),
  ];

  const dataSource = (result?.meta ?? []).map((meta) => {
    const row: Record<string, unknown> = { label: `${meta.label}${meta.unit ? `（${meta.unit}）` : ''}` };
    for (const item of result?.items ?? []) {
      const kpi = item.kpis.find((k) => k.key === meta.key);
      // 存 Kpi 对象而非格式化字符串，render 内按 kind/status 渲染
      row[`v${item.scenario_id}`] = kpi;
    }
    return row;
  });

  return (
    <Card
      title="多方案横向对比"
      extra={
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/scenarios/${currentId}`)}>
          返回结果
        </Button>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          mode="multiple"
          allowClear
          style={{ minWidth: 420 }}
          placeholder="选择对比方案"
          value={selected}
          options={options}
          onChange={handleChange}
        />
        <Button type="primary" loading={compareMut.isPending} onClick={() => void run()}>
          开始对比
        </Button>
        <Tag color="blue">CNY·税前·同口径权威重算</Tag>
        {dirty && result && (
          <Typography.Text type="warning">选择已变更，点击「开始对比」刷新对比结果</Typography.Text>
        )}
      </Space>
      {result ? (
        <>
          <Table columns={columns} dataSource={dataSource} pagination={false} size="small" scroll={{ x: 600 }} rowKey="label" />
          {result.items.some((i) => i.warnings.length > 0) && (
            <Typography.Paragraph type="warning" style={{ marginTop: 12 }}>
              部分方案存在口径提示，详见各自结果页。
            </Typography.Paragraph>
          )}
        </>
      ) : (
        <Typography.Paragraph type="secondary">
          请选择至少一个方案，点击「开始对比」生成同口径 KPI 矩阵。
        </Typography.Paragraph>
      )}
    </Card>
  );
}
