/**
 * 组网配套目录（配件库）管理页：算力/存储/管理交换机、NIC、光模块、AOC/MPO 线缆、
 * 存储单价的维护。
 *
 * 价格来源策略：计算引擎默认使用内置经验常量；本库有条目时优先用库内价格
 * （平台内置全租户可读、仅超管可写；租户可自建覆盖）。
 */
import React from 'react';
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createNetworkCatalogItem,
  deleteNetworkCatalogItem,
  listNetworkCatalog,
  updateNetworkCatalogItem,
} from '@/features/network-catalog/api/networkCatalogApi';
import type { NetworkCatalogItem } from '@/shared/types';

const CATEGORY_OPTIONS = [
  { value: 'compute_switch_ib', label: '算力交换机（IB）' },
  { value: 'compute_switch_roce', label: '算力交换机（RoCE）' },
  { value: 'storage_switch', label: '存储交换机（100G）' },
  { value: 'mgmt_switch', label: '管理交换机（1G/10G）' },
  { value: 'nic_ib', label: '跨机 NIC（IB）' },
  { value: 'nic_roce', label: '跨机 NIC（RoCE）' },
  { value: 'optics_400g', label: '400G 光模块' },
  { value: 'optics_100g', label: '100G 光模块' },
  { value: 'aoc_cable', label: 'AOC 线缆' },
  { value: 'mpo_cable', label: 'MPO 线缆' },
  { value: 'storage_per_gb', label: '存储单价（元/GB）' },
  { value: 'storage_monthly_per_gb', label: '存储月费（元/GB/月）' },
];

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_OPTIONS.map((o) => [o.value, o.label]),
);

export default function NetworkCatalogPage(): React.ReactElement {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const { data: items = [], isLoading, isError, refetch } = useQuery({
    queryKey: ['network-catalog'],
    queryFn: listNetworkCatalog,
  });
  const [editing, setEditing] = React.useState<NetworkCatalogItem | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [form] = Form.useForm();

  const invalidate = () => qc.invalidateQueries({ queryKey: ['network-catalog'] });

  const openCreate = () => {
    setCreating(true);
    form.resetFields();
    form.setFieldsValue({ unit: '台', is_builtin: false });
  };

  const openEdit = (row: NetworkCatalogItem) => {
    setEditing(row);
    form.setFieldsValue({
      category: row.category,
      code: row.code,
      name: row.name,
      price_cny: Number(row.price_cny),
      unit: row.unit,
      is_builtin: row.is_builtin,
      ports: row.spec?.ports,
      speed: row.spec?.speed,
    });
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    const spec: Record<string, unknown> = {};
    if (values.ports !== undefined && values.ports !== null && values.ports !== '') {
      spec.ports = Number(values.ports);
    }
    if (values.speed !== undefined && values.speed !== null && values.speed !== '') {
      spec.speed = Number(values.speed);
    }
    const payload = {
      category: values.category,
      code: values.code,
      name: values.name,
      price_cny: String(values.price_cny),
      unit: values.unit || '台',
      is_builtin: Boolean(values.is_builtin),
      spec,
    };
    try {
      if (editing) {
        await updateNetworkCatalogItem(editing.id, {
          price_cny: payload.price_cny,
          unit: payload.unit,
          spec: payload.spec,
        });
        message.success(`已更新至 v${editing.version + 1}`);
      } else {
        await createNetworkCatalogItem(payload);
        message.success('已新增配件条目');
      }
      setEditing(null);
      setCreating(false);
      invalidate();
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    }
  };

  const handleDelete = async (row: NetworkCatalogItem) => {
    try {
      await deleteNetworkCatalogItem(row.id);
      message.success('已删除');
      invalidate();
    } catch (e) {
      message.error((e as Error).message || '删除失败');
    }
  };

  const columns = [
    { title: '类别', dataIndex: 'category', key: 'category', width: 180, render: (v: string) => CATEGORY_LABEL[v] ?? v },
    { title: '代号', dataIndex: 'code', key: 'code', width: 140 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '单价（元）', dataIndex: 'price_cny', key: 'price_cny', width: 130, align: 'right' as const, render: (v: string) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 90 },
    {
      title: '规格',
      key: 'spec',
      width: 130,
      render: (_: unknown, row: NetworkCatalogItem) => (
        <span>
          {row.spec?.ports ? <Tag>{row.spec.ports} 口</Tag> : null}
          {row.spec?.speed ? <Tag color="blue">{row.spec.speed}G</Tag> : null}
          {!row.spec?.ports && !row.spec?.speed ? <Typography.Text type="secondary">—</Typography.Text> : null}
        </span>
      ),
    },
    { title: '归属', dataIndex: 'is_builtin', key: 'is_builtin', width: 90, render: (v: boolean) => <Tag color={v ? 'gold' : 'blue'}>{v ? '平台内置' : '租户'}</Tag> },
    { title: '版本', dataIndex: 'version', key: 'version', width: 70 },
    { title: '来源', dataIndex: 'source', key: 'source', ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, row: NetworkCatalogItem) => (
        <Space>
          <Button size="small" onClick={() => openEdit(row)}>改价</Button>
          <Popconfirm title="确认删除该配件条目？" onConfirm={() => handleDelete(row)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="组网配套目录（配件库）"
        extra={<Button type="primary" onClick={openCreate}>新增配件</Button>}
      >
        <AlertInfo />
        {isError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            title="配件目录加载失败"
            description="无法连接后端服务（组网配套目录数据为空可能是后端未启动，而非目录真的为空）。请确认服务后重试。"
            action={<Button size="small" onClick={() => refetch()}>重试</Button>}
          />
        ) : null}
        {!isError && !isLoading && items.length === 0 ? (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 12 }}
            title="暂无配件数据"
            description="目录为空，可点击右上角「新增配件」录入（平台内置条目缺失时也可先执行 seed 恢复）。"
          />
        ) : null}
        <Table
          style={{ marginTop: 12 }}
          size="small"
          rowKey="id"
          loading={isLoading}
          columns={columns}
          dataSource={isError ? [] : items}
          pagination={{ pageSize: 15 }}
        />
      </Card>

      <Modal
        open={creating || editing !== null}
        title={editing ? `编辑配件：${editing.name}` : '新增配件'}
        onOk={handleSubmit}
        onCancel={() => {
          setCreating(false);
          setEditing(null);
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="category" label="类别" rules={[{ required: true }]}>
            <Select options={CATEGORY_OPTIONS} disabled={!!editing} />
          </Form.Item>
          <Form.Item name="code" label="代号" rules={[{ required: true }]}>
            <Input disabled={!!editing} placeholder="如 ib-32x400g" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如 算力交换机 IB（32×400G）" />
          </Form.Item>
          <Form.Item name="price_cny" label="单价（元，税前）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={0} step={1000} />
          </Form.Item>
          <Form.Item name="unit" label="单位">
            <Input placeholder="台 / 卡 / 个 / 根 / 元/GB" />
          </Form.Item>
          <Form.Item name="ports" label="端口数（交换机类目，驱动拓扑）" tooltip="如 MQM9790-NS2F=64；留空则按内置 32 口推导">
            <InputNumber style={{ width: '100%' }} min={1} max={256} placeholder="留空=32" />
          </Form.Item>
          <Form.Item name="speed" label="端口速率（Gbps，交换机类目）" tooltip="如 400；留空则由请求 port_speed 决定">
            <Select
              allowClear
              options={[
                { value: 200, label: '200G' },
                { value: 400, label: '400G' },
                { value: 800, label: '800G' },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_builtin" label="归属" tooltip="平台内置需超管权限，全租户可读">
            <Select
              options={[
                { value: true, label: '平台内置（仅超管可写）' },
                { value: false, label: '本租户自建' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function AlertInfo(): React.ReactElement {
  return (
    <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
      价格来源：计算引擎默认使用内置经验常量；本库有条目时优先使用库内单价（租户自建覆盖平台内置）。
      引擎按类别匹配：算力交换机按 IB/RoCE 分型，存储/管理交换机、NIC、光模块、AOC/MPO、存储单价逐项覆盖。
    </Typography.Paragraph>
  );
}
