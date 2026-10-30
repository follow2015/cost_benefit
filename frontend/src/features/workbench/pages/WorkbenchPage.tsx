/** 工作台：方案列表 + 搜索 + 新建 + 行操作（编辑/结果/对比/复制/删除）。 */
import React from 'react';
import { Card, Table, Button, Input, Space, Tag, Popconfirm, Typography } from 'antd';
import { PlusOutlined, SearchOutlined, BarChartOutlined, CopyOutlined, DeleteOutlined, SwapOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useScenarioList, useDeleteScenario, useDuplicateScenario } from '@/features/scenarios/hooks/useScenarios';
import { useUiStore } from '@/shared/ui/uiStore';
import { PageHeader } from '@/shared/ui/PageHeader';
import type { ScenarioListItem } from '@/shared/types';

/** 财务 KPI 语义色（中国惯例：正值/盈=红，负值/亏=绿）。 */
function KpiTag({ label, value }: { label: string; value: unknown }): React.ReactElement {
  const num = typeof value === 'string' ? Number(value) : (value as number);
  if (!Number.isFinite(num)) return <Tag>{label} —</Tag>;
  const color = num > 0 ? 'red' : num < 0 ? 'green' : 'default';
  return <Tag color={color}>{label} {fmt(value)}</Tag>;
}

export default function WorkbenchPage(): React.ReactElement {
  const navigate = useNavigate();
  const [keyword, setKeyword] = React.useState('');
  const [page, setPage] = React.useState(1);
  const { data, isLoading } = useScenarioList({ page, page_size: 20, keyword });
  const del = useDeleteScenario();
  const dup = useDuplicateScenario();

  const columns = [
    { title: '名称', dataIndex: 'name', render: (name: string, row: ScenarioListItem) => (
        <a onClick={() => navigate(`/scenarios/${row.id}`)} style={{ fontWeight: 500 }}>{name}</a>
      ) },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string) => v || '—' },
    { title: '版本', dataIndex: 'version', width: 70, render: (v: number) => <Tag>v{v}</Tag> },
    { title: '标签', dataIndex: 'tags', width: 160, render: (tags: string[]) => (tags || []).map((t) => <Tag key={t}>{t}</Tag>) },
    {
      title: '最近 KPI',
      key: 'kpi',
      render: (_: unknown, row: ScenarioListItem) =>
        row.latest_kpi ? (
          <Space size={4} wrap>
            <KpiTag label="NPV" value={row.latest_kpi.npv} />
            <KpiTag label="ROI" value={row.latest_kpi.roi} />
            <Tag color="purple">元/Mtok {fmt(row.latest_kpi.cost_per_m)}</Tag>
          </Space>
        ) : (
          <Typography.Text type="secondary">未测算</Typography.Text>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 260,
      render: (_: unknown, row: ScenarioListItem) => (
        <Space>
          <Button size="small" icon={<BarChartOutlined />} onClick={() => navigate(`/scenarios/${row.id}`)}>
            结果
          </Button>
          <Button size="small" icon={<SwapOutlined />} onClick={() => navigate(`/scenarios/${row.id}/compare`)}>
            对比
          </Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => dup.mutate({ id: row.id })} loading={dup.isPending}>
            复制
          </Button>
          <Button size="small" icon={<DeleteOutlined />} onClick={() => navigate(`/scenarios/${row.id}/edit`)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该方案？" onConfirm={() => del.mutate(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} loading={del.isPending} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="方案工作台"
        description="管理测算方案：查看结果、对比、复制或删除"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/scenarios/new')}>
            新建测算方案
          </Button>
        }
      />
      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索方案名称"
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1); }}
            style={{ width: 280 }}
          />
        </Space>
        <Table<ScenarioListItem>
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items ?? []}
          columns={columns}
          pagination={{ current: page, pageSize: 20, total: data?.meta.total ?? 0, onChange: setPage }}
        />
        <DeviationBadge />
      </Card>
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—';
  const num = typeof v === 'string' ? Number(v) : (v as number);
  if (!Number.isFinite(num)) return '—';
  if (Math.abs(num) >= 1e6) return `${(num / 1e6).toFixed(2)}M`;
  if (Math.abs(num) >= 1e3) return `${(num / 1e3).toFixed(2)}k`;
  return num.toFixed(2);
}

/** 展示最近一次双端一致性偏差（来自 ui store）。 */
function DeviationBadge(): React.ReactElement {
  const last = useUiStore((s) => s.lastDeviation);
  if (!last) return <></>;
  const ok = last.passed;
  return (
    <Tag color={ok ? 'green' : 'red'} style={{ marginTop: 12 }}>
      双端偏差：{(last.maxRelative * 100).toFixed(3)}% @ {last.maxAt}（{last.duration_ms}ms）
    </Tag>
  );
}
