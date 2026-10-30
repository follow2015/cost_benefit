/** 租户与权限页：租户信息 + 成员列表（CRUD）+ 角色权限矩阵。 */
import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  App, Button, Card, Descriptions, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { members, createMember, updateMember, deleteMember } from '@/features/auth/api/authApi';
import { useAuthStore } from '@/features/auth/stores/authStore';
import { PageHeader } from '@/shared/ui/PageHeader';
import type { MemberCreateIn, MemberUpdateIn, UserOut } from '@/shared/types';

/** 角色 → 默认权限点（与后端 `ROLE_PERMISSIONS` 对齐，仅用于 UI 展示）。 */
const ROLE_PERMISSIONS: Record<string, string[]> = {
  owner: ['scenario:read', 'scenario:write', 'scenario:delete', 'scenario:calc', 'benchmark:read', 'benchmark:write', 'member:manage', 'audit:read'],
  editor: ['scenario:read', 'scenario:write', 'scenario:calc', 'benchmark:read'],
  viewer: ['scenario:read', 'benchmark:read'],
};

const PERM_LABELS: Record<string, string> = {
  'scenario:read': '方案查看',
  'scenario:write': '方案编辑',
  'scenario:delete': '方案删除',
  'scenario:calc': '执行测算',
  'benchmark:read': '基准查看',
  'benchmark:write': '基准维护',
  'member:manage': '成员管理',
  'audit:read': '审计查看',
};

const ALL_PERMS = Object.keys(PERM_LABELS);
const ROLE_OPTIONS = [
  { value: 'owner', label: 'Owner（拥有者）' },
  { value: 'editor', label: 'Editor（编辑）' },
  { value: 'viewer', label: 'Viewer（只读）' },
];

const ROLE_COLOR: Record<string, string> = { owner: 'blue', editor: 'geekblue', viewer: 'default' };

export default function TenantPage(): React.ReactElement {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const tenant = user?.tenant;
  const canManage = Boolean(user?.permissions?.includes('member:manage') || user?.is_super);

  const { data: memberList, isLoading } = useQuery({
    queryKey: ['members'],
    queryFn: () => members(),
  });

  const [creating, setCreating] = React.useState(false);
  const [editing, setEditing] = React.useState<UserOut | null>(null);
  const [form] = Form.useForm();

  const invalidate = () => qc.invalidateQueries({ queryKey: ['members'] });

  const createMut = useMutation({
    mutationFn: (payload: MemberCreateIn) => createMember(payload),
    onSuccess: () => { invalidate(); message.success('成员已创建'); },
    onError: (e: Error) => message.error(e.message),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: MemberUpdateIn }) => updateMember(id, payload),
    onSuccess: () => { invalidate(); message.success('成员已更新'); },
    onError: (e: Error) => message.error(e.message),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteMember(id),
    onSuccess: () => { invalidate(); message.success('成员已删除'); },
    onError: (e: Error) => message.error(e.message),
  });

  const openCreate = () => {
    setCreating(true);
    form.resetFields();
    form.setFieldsValue({ role: 'viewer' });
  };

  const openEdit = (row: UserOut) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      display_name: row.display_name,
      role: row.role,
      is_active: row.is_active,
      password: '',
    });
  };

  const closeModal = () => {
    setCreating(false);
    setEditing(null);
    form.resetFields();
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (creating) {
        await createMut.mutateAsync({
          email: values.email,
          password: values.password,
          display_name: values.display_name ?? '',
          role: values.role,
        });
      } else if (editing) {
        const payload: MemberUpdateIn = {
          display_name: values.display_name ?? null,
          role: values.role ?? null,
          is_active: values.is_active,
          password: values.password ? values.password : null,
        };
        await updateMut.mutateAsync({ id: editing.id, payload });
      }
      closeModal();
    } catch (e) {
      // antd 校验或 mutation 错误已由各自处理
      if ((e as Error).message) message.error((e as Error).message);
    }
  };

  const matrixCols = [
    { title: '权限 \\ 角色', dataIndex: 'perm', render: (v: string) => PERM_LABELS[v] ?? v, width: 140 },
    ...(['owner', 'editor', 'viewer'] as const).map((role) => ({
      title: role.toUpperCase(),
      dataIndex: role,
      align: 'center' as const,
      render: (_: unknown, row: Record<string, unknown>) =>
        row[role] ? <Tag color="green">✓</Tag> : <Typography.Text type="secondary">—</Typography.Text>,
    })),
  ];
  const matrixData = ALL_PERMS.map((p) => ({
    perm: p,
    owner: ROLE_PERMISSIONS.owner.includes(p),
    editor: ROLE_PERMISSIONS.editor.includes(p),
    viewer: ROLE_PERMISSIONS.viewer.includes(p),
  }));

  const memberCols = [
    { title: '邮箱', dataIndex: 'email' },
    { title: '姓名', dataIndex: 'display_name', render: (v: string) => v || '—' },
    {
      title: '角色',
      dataIndex: 'role',
      render: (v: string) => <Tag color={ROLE_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>),
    },
    { title: '超管', dataIndex: 'is_super', render: (v: boolean) => (v ? <Tag color="gold">是</Tag> : '—') },
    {
      title: '最后登录',
      dataIndex: 'last_login_at',
      width: 160,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: unknown, row: UserOut) =>
        canManage ? (
          <Space>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
              编辑
            </Button>
            <Popconfirm
              title={row.id === user?.id ? '不能删除自己' : '确认删除该成员？'}
              disabled={row.id === user?.id}
              onConfirm={() => deleteMut.mutate(row.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} disabled={row.id === user?.id} />
            </Popconfirm>
          </Space>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="租户与权限"
        description="租户信息、成员管理与角色权限矩阵"
        extra={
          canManage ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增成员
            </Button>
          ) : null
        }
      />

      <Card title="租户信息" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="名称">{tenant?.name ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="标识">{tenant?.slug ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="当前用户">{user?.display_name || user?.email}</Descriptions.Item>
          <Descriptions.Item label="当前角色">
            <Tag color={user?.role === 'owner' ? 'blue' : 'default'}>{user?.role}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="成员列表" style={{ marginBottom: 16 }}>
        <Table
          rowKey="id"
          size="small"
          loading={isLoading}
          pagination={false}
          columns={memberCols}
          dataSource={memberList ?? []}
        />
      </Card>

      <Card title="角色权限矩阵">
        <Typography.Paragraph type="secondary">角色默认权限点；成员的实际权限 = 角色默认权限 ∪ 额外权限。</Typography.Paragraph>
        <Table rowKey="perm" size="small" pagination={false} columns={matrixCols} dataSource={matrixData} />
      </Card>

      <Modal
        open={creating || editing !== null}
        title={creating ? '新增成员' : `编辑成员：${editing?.email ?? ''}`}
        onOk={() => void handleSubmit()}
        onCancel={closeModal}
        confirmLoading={createMut.isPending || updateMut.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          {creating ? (
            <>
              <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
                <Input placeholder="user@example.com" />
              </Form.Item>
              <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}>
                <Input.Password placeholder="至少 6 位" />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="password" label="重置密码（留空不修改）" rules={[{ min: 6, message: '密码至少 6 位' }]}>
              <Input.Password placeholder="留空保持原密码" />
            </Form.Item>
          )}
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="成员姓名（可选）" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          {editing ? (
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </div>
  );
}
