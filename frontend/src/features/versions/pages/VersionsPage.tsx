/** 版本快照与审计页（P1 REQ-16）：方案版本时间线 + 参数 diff + 审计日志抽屉。 */
import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { App, Button, Card, Drawer, Empty, Space, Table, Tag, Timeline, Typography } from 'antd';
import { ArrowLeftOutlined, AuditOutlined, DiffOutlined } from '@ant-design/icons';
import { getScenario, listSnapshots } from '@/features/scenarios/api/scenariosApi';
import { listAudit } from '@/features/tenant/api/auditApi';
import type { AuditEntry, SnapshotOut } from '@/shared/types';

/** 把 diff 值规范为可读字符串（对象 JSON 化）。 */
function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') return JSON.stringify(v, null, 2);
  return String(v);
}

function DiffTable({ diff }: { diff: Record<string, unknown> }): React.ReactElement {
  const entries = Object.entries(diff || {});
  if (entries.length === 0) return <Empty description="无参数变更" />;
  const data = entries.map(([key, val]) => {
    const change = (val ?? {}) as { before?: unknown; after?: unknown };
    return { key, before: fmtVal(change.before), after: fmtVal(change.after) };
  });
  return (
    <Table
      size="small"
      pagination={false}
      rowKey="key"
      columns={[
        { title: '参数路径', dataIndex: 'key', width: 220 },
        { title: '原值', dataIndex: 'before' },
        {
          title: '新值',
          dataIndex: 'after',
          render: (v: string) => <Typography.Text style={{ color: '#389e0d' }}>{v}</Typography.Text>,
        },
      ]}
      dataSource={data}
    />
  );
}

export default function VersionsPage(): React.ReactElement {
  const { id } = useParams();
  const scenarioId = Number(id);
  const navigate = useNavigate();
  const { message } = App.useApp();

  const { data: scenario } = useQuery({
    queryKey: ['scenario', scenarioId],
    queryFn: () => getScenario(scenarioId),
  });
  const { data: snapshots, isLoading } = useQuery({
    queryKey: ['snapshots', scenarioId],
    queryFn: () => listSnapshots(scenarioId),
  });

  const [diffSnap, setDiffSnap] = React.useState<SnapshotOut | null>(null);
  const [auditOpen, setAuditOpen] = React.useState(false);

  const { data: audit, refetch: refetchAudit } = useQuery({
    queryKey: ['audit', scenarioId],
    queryFn: () => listAudit({ scenario_id: scenarioId, limit: 200 }),
    enabled: auditOpen,
  });

  const openAudit = () => {
    setAuditOpen(true);
    refetchAudit().catch((e) => message.error((e as Error).message));
  };

  const timelineItems = (snapshots ?? []).map((s) => ({
    color: s.version === scenario?.version ? 'blue' : 'gray',
    content: (
      <Space orientation="vertical" size={4}>
        <Space>
          <Tag color={s.version === scenario?.version ? 'blue' : 'default'}>v{s.version}</Tag>
          <Typography.Text type="secondary">{s.created_at}</Typography.Text>
        </Space>
        <div>{s.note || '（无备注）'}</div>
        <Button type="link" size="small" icon={<DiffOutlined />} onClick={() => setDiffSnap(s)}>
          查看参数变更
        </Button>
      </Space>
    ),
  }));

  const auditCols = [
    { title: '时间', dataIndex: 'created_at', width: 180, render: (v: string) => (v ? v.replace('T', ' ').slice(0, 19) : '—') },
    { title: '动作', dataIndex: 'action_label', width: 110, render: (v: string) => <Tag>{v}</Tag> },
    { title: '操作人', dataIndex: 'actor_email', width: 200 },
    { title: '对象', render: (r: AuditEntry) => (r.target_type ? `${r.target_type}:${r.target_id ?? ''}` : '—') },
    {
      title: '明细',
      render: (r: AuditEntry) => (
        <Typography.Text type="secondary" ellipsis style={{ maxWidth: 320 }}>
          {Object.keys(r.detail || {}).length ? JSON.stringify(r.detail) : '—'}
        </Typography.Text>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/scenarios/${scenarioId}`)} />
          <span>版本与审计 · {scenario?.name ?? `方案 #${scenarioId}`}</span>
        </Space>
      }
      extra={
        <Button icon={<AuditOutlined />} onClick={openAudit}>
          审计日志
        </Button>
      }
    >
      <Typography.Paragraph type="secondary">
        每次参数保存/计算均自动留痕（版本快照）。点击「查看参数变更」对比相邻版本字段级前后值差异。
      </Typography.Paragraph>
      {isLoading ? <Card loading /> : <Timeline items={timelineItems} />}

      <Drawer title={`参数变更 · v${diffSnap?.version ?? ''}`} open={diffSnap !== null} onClose={() => setDiffSnap(null)} size={560}>
        {diffSnap ? <DiffTable diff={diffSnap.diff as Record<string, unknown>} /> : null}
      </Drawer>

      <Drawer title="审计日志" open={auditOpen} onClose={() => setAuditOpen(false)} size={680}>
        <Table
          size="small"
          rowKey="id"
          pagination={{ pageSize: 12 }}
          columns={auditCols}
          dataSource={audit ?? []}
        />
      </Drawer>
    </Card>
  );
}
