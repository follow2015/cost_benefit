/** 基准库管理页（P1 REQ-13）：四类基准的表格展示 + 行内编辑 + 新增 + 删除。
 * 仅具备 `benchmark:write` 权限（owner / 超管）可见可改；平台内置条目对普通管理员只读。
 * P1 延伸：版本发布 / 回滚——发布冻结全量快照，回滚只还原与快照不同的字段（行版本自增）。
 */
import React from 'react';
import { Alert, App, Button, Card, Drawer, Form, Input, Modal, Popconfirm, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import {
  BankOutlined,
  CloudUploadOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useBenchmarks } from '@/features/benchmarks/hooks/useBenchmarks';
import { useSyncStatus } from '@/features/benchmarks/hooks/useSyncStatus';
import { useAuthorityStatus } from '@/features/benchmarks/hooks/useAuthorityStatus';
import AuthoritySyncDrawer from '@/features/benchmarks/components/AuthoritySyncDrawer';
import MarketSyncDrawer from '@/features/benchmarks/components/MarketSyncDrawer';
import { useAuthStore } from '@/features/auth/stores/authStore';
import {
  createBenchmark,
  deleteBenchmark,
  getModelCoverage,
  getSyncOverview,
  listPublishes,
  publishBenchmarks,
  rollbackPublish,
  syncInferencex,
  updateBenchmark,
  type AuthorityStatus,
  type CoverageStatus,
  type MarketKind,
  type ModelCoverage,
  type ModelCoverageRow,
  type PublishSummary,
  type RollbackResult,
  type SyncOutcome,
  type SyncOverview,
  type SyncStatus,
} from '@/features/benchmarks/api/benchmarksApi';
import type { BenchKind } from '@/shared/types';

interface ColDef {
  key: string;
  title: string;
  editable?: boolean;
  required?: boolean;
  inputType?: 'text' | 'number' | 'bool' | 'date';
  width?: number;
  render?: (row: Record<string, unknown>) => React.ReactNode;
}

const TYPE_TAG = (builtin: boolean) => (
  <Tag color={builtin ? 'gold' : 'blue'}>{builtin ? '平台内置' : '租户'}</Tag>
);

/** 成本标杆的展示优先级：先这些硬件，再退回键序第一个。
 *  不直接用 Object.keys(cny)[0]，否则同一行数据的展示硬件会随 JSON 键序漂移。 */
const HARDWARE_PREF = ['B200', 'GB200_NVL72', 'B300', 'H100', 'MI355X'];
/** 场景优先级：推理场景优先 AgentX（与需求口径一致）。 */
const SCENARIO_PREF = 'AgentX';

/** 自动写入来源的前缀 → 中文标签与配色（与后端 SOURCE_ROW_PREFIX 一一对应）。 */
const AUTO_SOURCE: Array<{ prefix: string; color: string; label: (v: string) => string; tip: string }> = [
  {
    prefix: 'inferencex:',
    color: 'green',
    label: (v) => `InferenceX ${v}`,
    tip: '成本标杆由 InferenceX（SemiAnalysis）自动采集写入',
  },
  {
    prefix: 'authority:',
    color: 'purple',
    label: (v) => `权威同步 ${v}`,
    tip: 'API 价由 LiteLLM / models.dev / OpenRouter 三源投票后写入',
  },
  {
    prefix: 'gpu-rental:',
    color: 'orange',
    label: (v) => `行情采集 ${v}`,
    tip: 'GPU 租赁单价来自 GetDeploying 数据集（各云公开挂牌按需价中位数）',
  },
  {
    prefix: 'cloud-sync:',
    color: 'cyan',
    label: (v) => `官方价 ${v}`,
    tip: '云租赁单价来自云厂商官网按需挂牌价',
  },
];

/**
 * 「来源」列：自动采集写入的用标签标出，人工录入的保持原文。
 *
 * 采集接管 `source` 后，原人工依据被后端转存到 `meta.manual_source`，
 * 悬停即可追溯「这条数据最早是从哪抄来的」。
 */
function sourceCol(): ColDef {
  return {
    key: 'source',
    title: '来源',
    editable: true,
    render: (r) => {
      const raw = String(r.source ?? '');
      const manual = (r.meta as Record<string, unknown> | undefined)?.manual_source;
      const hit = AUTO_SOURCE.find((a) => raw.startsWith(a.prefix));
      const node = hit ? (
        <Tooltip title={hit.tip}>
          <Tag color={hit.color}>{hit.label(raw.slice(hit.prefix.length))}</Tag>
        </Tooltip>
      ) : raw ? (
        <span>{raw}</span>
      ) : (
        <Typography.Text type="secondary">—</Typography.Text>
      );
      return manual ? (
        <Tooltip title={`人工录入依据：${String(manual)}`}>
          <span>{node}</span>
        </Tooltip>
      ) : (
        node
      );
    },
  };
}

/** 超过这个天数没更新就标「过期」。季度复核是价格类数据的行业惯例。 */
const STALE_DAYS = 90;

/** 距今多少天；`as_of` 为空、格式不对或落在未来时返回 null（视为「未核实」）。 */
function daysSince(raw: unknown): number | null {
  const s = String(raw ?? '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  const t = Date.parse(`${s}T00:00:00`);
  if (Number.isNaN(t)) return null;
  const diff = Math.floor((Date.now() - t) / 86_400_000);
  return diff < 0 ? null : diff;
}

/**
 * 「生效日期」列。
 *
 * 后端把 `as_of` 按 `source` 文本还原过：只写到月的取月末，`source=seed` 这类
 * 没有任何日期依据的置空。所以这里必须把「未核实」和「过期」分开表达——
 * 早前所有行都是同一个占位日期 2026-08-01，看着像精确到日，其实一天也不对应，
 * 也就没法判断数据到底有多老。
 */
function asOfCol(): ColDef {
  return {
    key: 'as_of',
    title: '生效日期',
    editable: true,
    inputType: 'date',
    width: 150,
    render: (r) => {
      const days = daysSince(r.as_of);
      if (days === null) {
        return (
          <Tooltip title="来源未给出可核实的日期（常识值或只注明到月且无法回填）">
            <Typography.Text type="secondary" data-testid="asof-unknown">
              未核实
            </Typography.Text>
          </Tooltip>
        );
      }
      const stale = days > STALE_DAYS;
      return (
        <Tooltip title={stale ? `已 ${days} 天未更新，建议复核` : `${days} 天前更新`}>
          <span style={{ whiteSpace: 'nowrap' }}>
            {String(r.as_of).slice(0, 10)}
            {stale ? (
              <Tag color="orange" style={{ marginInlineStart: 4 }} data-testid="asof-stale">
                过期
              </Tag>
            ) : null}
          </span>
        </Tooltip>
      );
    },
  };
}

const GPU_COLS: ColDef[] = [
  { key: 'code', title: '代号', editable: true, required: true },
  { key: 'name', title: '名称', editable: true, required: true },
  { key: 'vendor', title: '厂商', editable: true },
  { key: 'price_cny', title: '价格(元)', editable: true, inputType: 'number', width: 100 },
  { key: 'tdp_w', title: '功耗(W)', editable: true, inputType: 'number', width: 90 },
  { key: 'vram_gb', title: '显存(GB)', editable: true, inputType: 'number', width: 90 },
  { key: 'rent_cny_per_hour', title: '租金(元/时)', editable: true, inputType: 'number', width: 110 },
  sourceCol(),
  asOfCol(),
  { key: 'version', title: '版本', width: 70, render: (r) => String(r.version ?? 1) },
  { key: 'is_builtin', title: '归属', width: 90, render: (r) => TYPE_TAG(Boolean(r.is_builtin)) },
];

const MODEL_COLS: ColDef[] = [
  { key: 'code', title: '代号', editable: true, required: true },
  { key: 'name', title: '名称', editable: true, required: true },
  { key: 'params_b', title: '参数量(B)', editable: true, inputType: 'number', width: 100 },
  { key: 'throughput_effective', title: '有效吞吐', editable: true, inputType: 'number', width: 100 },
  { key: 'k_ratio', title: 'k 比值', editable: true, inputType: 'number', width: 80 },
  { key: 'vram_required_gb', title: '显存(GB)', editable: true, inputType: 'number', width: 90 },
  {
    key: 'inferencex_cost',
    title: '成本标杆(¥/Mtok)',
    width: 190,
    render: (r) => {
      const cny = (r.meta as Record<string, unknown> | undefined)?.cost_benchmark_cny_per_mtok as
        | Record<string, Record<string, number | string>>
        | undefined;
      if (!cny) return <Typography.Text type="secondary">—</Typography.Text>;
      // 成本标杆里每个硬件/场景都是一个值，取「首选硬件 × 首选场景」做代表展示。
      // 用固定优先级而非 Object.keys 顺序：JSON 键序在库里不可控，今天 B200、明天 MI355X，
      // 同一行数据每次刷新都会跳，看上去像数据在变。
      const hw = HARDWARE_PREF.find((h) => cny[h]) ?? Object.keys(cny)[0];
      if (!hw) return <Typography.Text type="secondary">—</Typography.Text>;
      const scenMap = cny[hw] ?? {};
      const scen = scenMap[SCENARIO_PREF] != null ? SCENARIO_PREF : Object.keys(scenMap)[0];
      // 后端把 Decimal 序列化成字符串（避免 JS 浮点丢精度），这里必须显式转数字：
      // 直接 `.toFixed` 会抛 `o.toFixed is not a function`，整页被 ErrorBoundary 接走。
      const num = Number(scenMap?.[scen]);
      if (!Number.isFinite(num)) return <Typography.Text type="secondary">—</Typography.Text>;
      const combos = Object.entries(cny)
        .map(([h, m]) => `${h}/${scen}: ¥${Number(m?.[scen]).toFixed(3)}`)
        .join('\n');
      return (
        <Tooltip title={<span style={{ whiteSpace: 'pre-line' }}>{combos}</span>}>
          <Typography.Text>
            {hw}/{scen}: ¥{num.toFixed(3)}
          </Typography.Text>
        </Tooltip>
      );
    },
  },
  sourceCol(),
  asOfCol(),
  { key: 'version', title: '版本', width: 70, render: (r) => String(r.version ?? 1) },
  { key: 'is_builtin', title: '归属', width: 90, render: (r) => TYPE_TAG(Boolean(r.is_builtin)) },
];

/** 采集覆盖四种判决的配色。
 *
 * `no_value`（上游在测、本次没给值）用橙色而不是灰色：它是「等下一轮就好」的
 * 临时状态，灰掉会让人误以为是永久的「上游不测」。反过来 `untested` 用灰色——
 * 那是终局，换任何数据源都一样。
 */
const COVERAGE_STYLE: Record<CoverageStatus, { color?: string; hint: string }> = {
  covered: { color: 'green', hint: '上游已采到成本值，本行为自动数据' },
  no_value: { color: 'orange', hint: '上游在测这个模型，只是本次没有可用成本值' },
  untested: { hint: '上游本轮模型清单里没有它：换数据源也采不到，只能人工维护' },
  unknown: { hint: '没有可用的上游清单，无法判断（重新采集一次即可）' },
};

/** 「采集覆盖」列：解释这条模型基准为什么有值 / 为什么空着。 */
function coverageCol(coverage?: Map<string, ModelCoverageRow>): ColDef {
  return {
    key: 'coverage',
    title: '采集覆盖',
    width: 130,
    render: (r) => {
      const hit = coverage?.get(String(r.code ?? ''));
      if (!hit) return <Typography.Text type="secondary">—</Typography.Text>;
      const style = COVERAGE_STYLE[hit.status] ?? COVERAGE_STYLE.unknown;
      return (
        <Tooltip title={`${style.hint}${hit.detail ? `（${hit.detail}）` : ''}`}>
          <Tag color={style.color} data-testid={`coverage-${hit.status}`}>
            {hit.label}
          </Tag>
        </Tooltip>
      );
    },
  };
}

/** 模型表列：把「采集覆盖」插在成本标杆后面，值与它的解释紧挨着看。 */
function modelCols(coverage?: Map<string, ModelCoverageRow>): ColDef[] {
  const cols = [...MODEL_COLS];
  const anchor = cols.findIndex((c) => c.key === 'inferencex_cost');
  cols.splice(anchor >= 0 ? anchor + 1 : cols.length, 0, coverageCol(coverage));
  return cols;
}

const CLOUD_COLS: ColDef[] = [
  { key: 'provider', title: '云厂商', editable: true, required: true },
  { key: 'gpu_code', title: 'GPU 型号', editable: true, required: true },
  { key: 'region', title: '区域', editable: true, width: 80 },
  { key: 'price_cny_per_hour', title: '单价(元/时)', editable: true, inputType: 'number', width: 120 },
  { key: 'include_power', title: '含电费', editable: true, inputType: 'bool', width: 80 },
  { key: 'include_hosting', title: '含托管', editable: true, inputType: 'bool', width: 80 },
  { key: 'billing_mode', title: '计费模式', editable: true, width: 90 },
  sourceCol(),
  asOfCol(),
  { key: 'version', title: '版本', width: 70, render: (r) => String(r.version ?? 1) },
  { key: 'is_builtin', title: '归属', width: 90, render: (r) => TYPE_TAG(Boolean(r.is_builtin)) },
];

const API_COLS: ColDef[] = [
  { key: 'provider', title: '服务商', editable: true, required: true },
  { key: 'model_code', title: '模型代号', editable: true, required: true },
  { key: 'price_in_cny_per_m', title: '输入价(元/M)', editable: true, inputType: 'number', width: 120, required: true },
  { key: 'price_out_cny_per_m', title: '输出价(元/M)', editable: true, inputType: 'number', width: 120, required: true },
  { key: 'price_cache_cny_per_m', title: '缓存价(元/M)', editable: true, inputType: 'number', width: 120 },
  sourceCol(),
  asOfCol(),
  { key: 'version', title: '版本', width: 70, render: (r) => String(r.version ?? 1) },
  { key: 'is_builtin', title: '归属', width: 90, render: (r) => TYPE_TAG(Boolean(r.is_builtin)) },
];

/** 空字符串 → null，但**只针对数值/日期列**。
 *
 * 原因：数值列提交 '' 会被后端判为非法值（422「字段 xxx 不是合法数值」），
 * 而行内编辑与新增表单里这类空值很常见（如租金、缓存价、生效日期留空）；
 * 但文本列（source / vendor 等）在库里是 NOT NULL DEFAULT ''，
 * 置成 null 反而会触发 NOT NULL 违约——所以文本列保持空串不动。
 */
function normalizePayload(
  values: Record<string, unknown>,
  nullableKeys: ReadonlySet<string>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [
      key,
      value === '' && nullableKeys.has(key) ? null : value,
    ]),
  );
}

function BenchTable(props: {
  kind: BenchKind;
  title: string;
  columns: ColDef[];
  rows: Record<string, unknown>[];
  canWrite: boolean;
}): React.ReactElement {
  const { kind, title, columns, rows, canWrite } = props;
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [form, setForm] = React.useState<Record<string, unknown>>({});
  const [saving, setSaving] = React.useState(false);
  const [modalOpen, setModalOpen] = React.useState(false);
  const [modalForm] = Form.useForm();

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['benchmarks'] });

  /** 允许「清空」的列：只有数值/日期列。文本列在库中是 NOT NULL DEFAULT ''。 */
  const nullableKeys = React.useMemo(
    () =>
      new Set(
        columns
          .filter((c) => c.inputType === 'number' || c.inputType === 'date')
          .map((c) => c.key),
      ),
    [columns],
  );

  const startEdit = (row: Record<string, unknown>) => {
    const init: Record<string, unknown> = {};
    columns.forEach((c) => {
      if (c.editable) init[c.key] = row[c.key] ?? (c.inputType === 'bool' ? false : '');
    });
    setForm(init);
    setEditingId(Number(row.id));
  };
  const cancelEdit = () => {
    setEditingId(null);
    setForm({});
  };

  const saveEdit = async (row: Record<string, unknown>) => {
    setSaving(true);
    try {
      await updateBenchmark(kind, Number(row.id), normalizePayload(form, nullableKeys));
      message.success('已保存（版本自增）');
      cancelEdit();
      void refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row: Record<string, unknown>) => {
    try {
      await deleteBenchmark(kind, Number(row.id));
      message.success('已删除');
      void refresh();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const add = async () => {
    try {
      const values = await modalForm.validateFields();
      await createBenchmark(kind, normalizePayload(values as Record<string, unknown>, nullableKeys));
      message.success('已新增基准');
      setModalOpen(false);
      modalForm.resetFields();
      void refresh();
    } catch (e) {
      if ((e as { errorFields?: unknown }).errorFields) return;
      message.error((e as Error).message);
    }
  };

  const tableCols = columns.map((c) => ({
    title: c.title,
    dataIndex: c.key,
    width: c.width,
    render: (val: unknown, row: Record<string, unknown>) => {
      if (editingId === Number(row.id) && c.editable) {
        if (c.inputType === 'bool')
          return <Switch checked={Boolean(form[c.key])} onChange={(v) => setForm({ ...form, [c.key]: v })} />;
        if (c.inputType === 'date')
          return (
            <Input
              type="date"
              value={(form[c.key] as string) ?? ''}
              onChange={(e) => setForm({ ...form, [c.key]: e.target.value || null })}
            />
          );
        return (
          <Input
            value={(form[c.key] as string) ?? ''}
            onChange={(e) => setForm({ ...form, [c.key]: e.target.value })}
          />
        );
      }
      if (c.render) return c.render(row);
      if (c.inputType === 'bool')
        return <Tag color={val ? 'green' : 'default'}>{val ? '是' : '否'}</Tag>;
      return val === null || val === undefined ? (
        <Typography.Text type="secondary">—</Typography.Text>
      ) : (
        String(val)
      );
    },
  }));

  if (canWrite) {
    tableCols.push({
      title: '操作',
      dataIndex: '__op',
      width: 150,
      render: (_: unknown, row: Record<string, unknown>) => {
        if (editingId === Number(row.id))
          return (
            <Space>
              <Button type="link" loading={saving} onClick={() => saveEdit(row)}>
                保存
              </Button>
              <Button type="link" onClick={cancelEdit}>
                取消
              </Button>
            </Space>
          );
        return (
          <Space>
            <Button type="link" onClick={() => startEdit(row)}>
              编辑
            </Button>
            <Popconfirm title="确认删除该基准？" onConfirm={() => remove(row)}>
              <Button type="link" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    });
  }

  return (
    <Card
      title={title}
      extra={
        canWrite ? (
          <Button type="primary" onClick={() => setModalOpen(true)}>
            新增
          </Button>
        ) : null
      }
      style={{ marginBottom: 16 }}
    >
      <Table
        rowKey="id"
        size="small"
        pagination={{ pageSize: 8 }}
        columns={tableCols}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
      />
      <Modal
        title={`新增${title}`}
        open={modalOpen}
        onOk={add}
        onCancel={() => {
          setModalOpen(false);
          modalForm.resetFields();
        }}
        destroyOnHidden
      >
        <Form form={modalForm} layout="vertical">
          {columns
            .filter((c) => c.editable)
            .map((c) => (
              <Form.Item
                key={c.key}
                name={c.key}
                label={c.title}
                rules={c.required ? [{ required: true, message: `请填写${c.title}` }] : []}
              >
                {c.inputType === 'bool' ? (
                  <Switch />
                ) : c.inputType === 'date' ? (
                  <Input type="date" />
                ) : (
                  <Input />
                )}
              </Form.Item>
            ))}
        </Form>
      </Modal>
    </Card>
  );
}

/** 采集状态 → 中文标签与配色（与后端 STATUS_* 一一对应）。 */
const SYNC_STATUS: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  partial: { color: 'orange', text: '部分成功' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
  running: { color: 'blue', text: '采集中' },
};

/** 时间戳（UTC ISO）→ 本地可读，缺值显示占位符。 */
function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false });
}

interface SyncPanelProps {
  syncStatus?: SyncStatus;
  syncLoading: boolean;
  authorityStatus?: AuthorityStatus;
  authorityLoading: boolean;
  overview?: SyncOverview;
  modelCoverage?: ModelCoverage;
  syncing: boolean;
  canWrite: boolean;
  onSync: () => void;
  onAuthority: () => void;
  onMarket: (kind: MarketKind) => void;
}

/** 权威源清单的前端兜底（后端 `/authority-status` 不可用时也能显示来源）。 */
const DEFAULT_AUTHORITY_SOURCES = [
  { source: 'litellm', label: 'LiteLLM 价格表', url: 'https://github.com/BerriAI/litellm' },
  { source: 'modelsdev', label: 'models.dev', url: 'https://models.dev' },
  { source: 'openrouter', label: 'OpenRouter', url: 'https://openrouter.ai/api/v1/models' },
];

/** 一栏的骨架：标题 + 说明行 + 按钮。两栏共用同一套排布。 */
function SyncColumn(props: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
  testId: string;
  action: React.ReactNode;
}): React.ReactElement {
  const { icon, title, children, testId, action } = props;
  return (
    <div
      data-testid={testId}
      style={{ flex: '1 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
        {icon}
        <span>{title}</span>
      </div>
      <div style={{ lineHeight: 1.9, fontSize: 13 }}>{children}</div>
      <div style={{ marginTop: 2 }}>{action}</div>
    </div>
  );
}

/**
 * 数据更新面板：四条采集链路各自独立，各一个按钮。
 *
 * 合成一个按钮会让人以为「点一次就全刷新了」，实际上四条链路的数据源、
 * 节奏、失败后果完全不同：
 *
 * | 链路 | 源 | 节奏 | 写库方式 |
 * |---|---|---|---|
 * | 成本标杆 | InferenceX（SemiAnalysis） | 每 7 天自动 | 采集即写 |
 * | API 价 | LiteLLM / models.dev / OpenRouter | 手动 | 勾选后写 |
 * | GPU 租赁价 | GetDeploying 行情数据集 | 手动 | 勾选后写 |
 * | 云租赁价 | 云厂商官网挂牌价 | 手动 | 勾选后写 |
 *
 * 后三条都要求人工确认，因为它们是测算输入，自动漂移会静默改掉所有结论。
 */
function DataSyncPanel({
  syncStatus,
  syncLoading,
  authorityStatus,
  authorityLoading,
  overview,
  modelCoverage,
  syncing,
  canWrite,
  onSync,
  onAuthority,
  onMarket,
}: SyncPanelProps): React.ReactElement {
  const sourceUrl = syncStatus?.source_url ?? 'https://inferencex.semianalysis.com';
  const intervalDays = syncStatus?.interval_days ?? 7;
  const last = syncStatus?.last;
  const tag = last ? SYNC_STATUS[last.status] : undefined;
  const failed = last?.status === 'failed';
  const gpu = overview?.gpu_rental;
  const cloud = overview?.cloud_official;

  return (
    <Card size="small" style={{ marginBottom: 12 }} data-testid="inferencex-source-bar">
      <div
        style={{
          display: 'grid',
          // 窄屏自动落成单列；宽屏两栏并排，四条链路一眼全看到
          gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
          gap: '16px 24px',
          alignItems: 'start',
        }}
      >
        <SyncColumn
          testId="cost-benchmark-sync"
          icon={<SyncOutlined spin={syncing} style={{ color: '#1677ff' }} />}
          title="成本标杆 · InferenceX"
          action={
            canWrite ? (
              <Button
                type="primary"
                ghost
                size="small"
                icon={<SyncOutlined />}
                loading={syncing}
                onClick={onSync}
                data-testid="inferencex-sync-button"
              >
                立即采集
              </Button>
            ) : null
          }
        >
          <div>
            数据源：
            <Typography.Link
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              data-testid="inferencex-source-link"
            >
              inferencex.semianalysis.com
            </Typography.Link>
            <span>（InferenceX · SemiAnalysis）· 每 {intervalDays} 天自动采集</span>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {syncLoading ? (
              <span>读取采集状态…</span>
            ) : last ? (
              <span data-testid="inferencex-last-run">
                上次 {fmtTime(last.started_at)}
                {tag ? (
                  <Tag color={tag.color} style={{ marginInlineStart: 6 }}>
                    {tag.text}
                  </Tag>
                ) : null}
                {last.point_count > 0
                  ? `（${last.point_count} 个成本点 / 命中 ${last.matched_count} 个模型）`
                  : null}
              </span>
            ) : (
              <span>尚未采集过，当前为人工录入值</span>
            )}
            {syncStatus?.due ? (
              <span>· 已到采集周期</span>
            ) : syncStatus?.next_run_at ? (
              <span>· 下次 {fmtTime(syncStatus.next_run_at)}</span>
            ) : null}
            {syncStatus?.last_success?.as_of ? (
              <span>· 数据生效日 {syncStatus.last_success.as_of}</span>
            ) : null}
          </Typography.Text>
          {modelCoverage ? (
            <Typography.Text
              type="secondary"
              // 必须成块：`SyncColumn` 的 children 容器是普通 block，
              // 行内 span 会跟上一行「数据生效日 …」粘成一句，读起来像同一个结论。
              style={{ fontSize: 13, display: 'block' }}
              data-testid="model-coverage-line"
            >
              模型覆盖 {modelCoverage.summary.covered}/{modelCoverage.summary.total} 条
              {modelCoverage.judgeable ? (
                <>
                  {` · 上游本次只测 ${modelCoverage.upstream.model_count} 个模型`}
                  {modelCoverage.summary.no_value > 0
                    ? `（其中 ${modelCoverage.summary.no_value} 条上游在测但本次无值，等下一轮）`
                    : null}
                  {modelCoverage.summary.untested > 0
                    ? ` · 其余 ${modelCoverage.summary.untested} 条上游不测，换源也采不到`
                    : null}
                </>
              ) : (
                ' · 上次采集记录未存上游清单，重新采集后可判定'
              )}
              {modelCoverage.upstream.unmatched.length > 0 ? (
                <Tooltip
                  title={`上游测了这些模型，但基准库没有同名行：${modelCoverage.upstream.unmatched.join('、')}`}
                >
                  <Tag color="gold" style={{ marginInlineStart: 6 }} data-testid="model-coverage-unmatched">
                    {modelCoverage.upstream.unmatched.length} 个上游模型未建行
                  </Tag>
                </Tooltip>
              ) : null}
            </Typography.Text>
          ) : null}
        </SyncColumn>

        <SyncColumn
          testId="authority-sync-block"          icon={<SafetyCertificateOutlined style={{ color: '#722ed1' }} />}
          title="API 价 · 三源权威比对"
          action={
            canWrite ? (
              <Button
                size="small"
                type="primary"
                ghost
                icon={<SafetyCertificateOutlined />}
                onClick={onAuthority}
                data-testid="authority-sync-button"
              >
                同步 API 价
              </Button>
            ) : null
          }
        >
          <div>
            数据源：
            {(authorityStatus?.sources?.length ? authorityStatus.sources : DEFAULT_AUTHORITY_SOURCES).map(
              (s, i) => (
                <React.Fragment key={s.source}>
                  {i > 0 ? <span> · </span> : null}
                  {s.url ? (
                    <Typography.Link href={s.url} target="_blank" rel="noreferrer">
                      {s.label}
                    </Typography.Link>
                  ) : (
                    <span>{s.label}</span>
                  )}
                </React.Fragment>
              ),
            )}
            <span>· 多源投票裁决，冲突项不自动采信</span>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {authorityLoading ? (
              <span>读取同步状态…</span>
            ) : authorityStatus ? (
              <span data-testid="authority-last-sync">
                上次同步 {fmtTime(authorityStatus.last_synced_at)} · 覆盖{' '}
                {authorityStatus.from_authority}/{authorityStatus.total} 条
                {authorityStatus.manual > 0 ? `（${authorityStatus.manual} 条仍为人工值）` : null}
                {authorityStatus.as_of ? ` · 数据生效日 ${authorityStatus.as_of}` : null}
                {` · 汇率 ${authorityStatus.fx_usd_cny}`}
              </span>
            ) : (
              <span>尚未读取到同步状态</span>
            )}
          </Typography.Text>
        </SyncColumn>

        <SyncColumn
          testId="gpu-rental-sync-block"
          icon={<ThunderboltOutlined style={{ color: '#fa8c16' }} />}
          title="GPU 租赁价 · 行情数据集"
          action={
            canWrite ? (
              <Button
                size="small"
                type="primary"
                ghost
                icon={<ThunderboltOutlined />}
                onClick={() => onMarket('gpu-rental')}
                data-testid="gpu-rental-sync-button"
              >
                采集行情价
              </Button>
            ) : null
          }
        >
          <div>
            数据源：
            <Typography.Link
              href="https://getdeploying.com/dataset/gpu-prices"
              target="_blank"
              rel="noreferrer"
            >
              GetDeploying GPU 价格数据集
            </Typography.Link>
            <span>（CC BY 4.0 · 103 型号 × 88 家云 · 每日更新）· 手动触发</span>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {gpu ? (
              <span data-testid="gpu-rental-coverage">
                已采集 {gpu.from_source}/{gpu.auto_capable} 个可采集型号
                {gpu.no_market.length > 0
                  ? ` · ${gpu.no_market.length} 个型号国际市场无此 SKU（人工维护）`
                  : null}
              </span>
            ) : (
              <span>读取覆盖情况…</span>
            )}
            <span>· 采集后需人工确认才写库</span>
          </Typography.Text>
        </SyncColumn>

        <SyncColumn
          testId="cloud-official-sync-block"
          icon={<BankOutlined style={{ color: '#13c2c2' }} />}
          title="云租赁价 · 云厂商官网"
          action={
            canWrite ? (
              <Button
                size="small"
                type="primary"
                ghost
                icon={<BankOutlined />}
                onClick={() => onMarket('cloud-official')}
                data-testid="cloud-official-sync-button"
              >
                采集官方价
              </Button>
            ) : null
          }
        >
          <div>
            数据源：
            <Typography.Link
              href="https://prices.azure.com/api/retail/prices"
              target="_blank"
              rel="noreferrer"
            >
              Azure 零售价
            </Typography.Link>
            <span> · </span>
            <Typography.Link
              href="https://aws.amazon.com/ec2/pricing/on-demand/"
              target="_blank"
              rel="noreferrer"
            >
              AWS 按需价目表
            </Typography.Link>
            <span>（官方公开）· 手动触发</span>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {cloud ? (
              <span data-testid="cloud-official-coverage">
                已采集 {cloud.from_source}/{cloud.auto_capable} 条可采集厂商行
                {cloud.total - cloud.auto_capable > 0
                  ? ` · 其余 ${cloud.total - cloud.auto_capable} 条无公开接口（人工维护）`
                  : null}
              </span>
            ) : (
              <span>读取覆盖情况…</span>
            )}
            <span>· 国内云与 GCP 无公开价格接口</span>
          </Typography.Text>
        </SyncColumn>
      </div>
      {failed ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 10 }}
          title={`成本标杆上次采集失败：${last?.error || '未知原因'}`}
          description="失败不会清空已有数据，当前仍沿用上一次成功采集（或人工录入）的标杆值。"
        />
      ) : null}
    </Card>
  );
}

export default function BenchmarksPage(): React.ReactElement {
  const { data, isLoading } = useBenchmarks();
  const { data: syncStatus, isLoading: syncLoading } = useSyncStatus();
  const { data: authorityStatus, isLoading: authorityLoading } = useAuthorityStatus();
  // 覆盖率只读本库，跟随页面加载即可；它是「哪些行能自动更新」的即时答案
  const { data: overview } = useQuery<SyncOverview>({
    queryKey: ['benchmarks', 'sync-overview'],
    queryFn: getSyncOverview,
    staleTime: 30_000,
  });
  // 模型逐行覆盖（判「上游不测」还是「本次缺数据」）：纯读库，跟随页面加载
  const { data: modelCoverage } = useQuery<ModelCoverage>({
    queryKey: ['benchmarks', 'model-coverage'],
    queryFn: getModelCoverage,
    staleTime: 30_000,
  });
  /** code → 判决，供模型表渲染「采集覆盖」列 */
  const coverageByCode = React.useMemo(() => {
    const map = new Map<string, ModelCoverageRow>();
    for (const row of modelCoverage?.rows ?? []) map.set(row.code, row);
    return map;
  }, [modelCoverage]);
  const modelsColumns = React.useMemo(() => modelCols(coverageByCode), [coverageByCode]);
  const user = useAuthStore((s) => s.user);
  const canWrite = Boolean(user?.permissions?.includes('benchmark:write') || user?.is_super);
  const queryClient = useQueryClient();
  const { message } = App.useApp();

  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [authorityOpen, setAuthorityOpen] = React.useState(false);
  /** 租赁价采集抽屉：null 表示关闭；记录当前采哪条链路 */
  const [marketKind, setMarketKind] = React.useState<MarketKind | null>(null);
  const [publishes, setPublishes] = React.useState<PublishSummary[]>([]);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [publishing, setPublishing] = React.useState(false);
  const [syncing, setSyncing] = React.useState(false);
  const [rollingBack, setRollingBack] = React.useState<number | null>(null);
  const [lastRollback, setLastRollback] = React.useState<RollbackResult | null>(null);

  /**
   * 刷新基准库与其两条状态查询。
   *
   * 用 `refetchType: 'all'` 而非默认的 `'active'`：权威同步刚把数据写进库，
   * 此刻哪怕某个查询暂时不在活跃观察者上（如抽屉覆盖/表格切页），
   * 也必须作废重取——否则「生效日期 / 来源」会停在旧值上，看着像没生效。
   */
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['benchmarks'], refetchType: 'all' });
  };

  /** 手动采集成本标杆：忽略 7 天周期，立即向 InferenceX 拉一次并写回平台内置基准。 */
  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await syncInferencex();
      if (res.status === 'failed') {
        message.error(`采集失败：${res.error || '未知原因'}（已保留现有数据）`);
      } else if (res.status === 'skipped') {
        message.info(res.error || '已跳过本次采集');
      } else {
        const gap = res.unmatched.length ? `，${res.unmatched.length} 个上游模型未匹配` : '';
        message.success(
          `采集完成：${res.point_count} 个成本点 / 命中 ${res.matched_count} 个模型` +
            `（新增 ${res.added}、更新 ${res.updated}${gap}）`,
        );
      }
      // 前缀匹配会同时失效 sync-status 与基准库列表
      await refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const loadPublishes = React.useCallback(async () => {
    setHistoryLoading(true);
    try {
      setPublishes(await listPublishes(20));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setHistoryLoading(false);
    }
  }, [message]);

  const handlePublish = async () => {
    setPublishing(true);
    try {
      const res = await publishBenchmarks();
      const total = Object.values(res.counts).reduce((a, b) => a + b, 0);
      message.success(`已发布基准库版本 #${res.publish_id}（${total} 条快照）`);
      if (historyOpen) await loadPublishes();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  const handleRollback = async (publishId: number) => {
    setRollingBack(publishId);
    try {
      const res = await rollbackPublish(publishId);
      setLastRollback(res);
      const tail = res.skipped.length ? `，跳过 ${res.skipped.length} 条` : '';
      message.success(`已回滚 ${res.updated.length} 条，无差异 ${res.unchanged} 条${tail}`);
      void refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setRollingBack(null);
    }
  };

  const openHistory = () => {
    setHistoryOpen(true);
    setLastRollback(null);
    void loadPublishes();
  };

  if (isLoading || !data) {
    return <Card loading />;
  }

  const kindsTotal = (counts: Record<string, number>) =>
    Object.values(counts ?? {}).reduce((a, b) => a + b, 0);

  /**
   * 数据新鲜度汇总：过期条数 / 未核实条数 / 最老一条。
   *
   * 为什么要在页面上明说：四张表里只有一部分能被自动采集 ——
   * 模型的成本标杆有 InferenceX，GPU 租赁价只有 6 个型号有国际市场行情，
   * 云租赁价只有 Azure 与 AWS 有官方接口，国产卡与国内云只能人工维护。
   * 不把「有多老」摆出来，那些人工行就永远没人去更新。
   */
  const freshness = (() => {
    const buckets: Array<[string, Record<string, unknown>[]]> = [
      ['GPU', data.gpus as unknown as Record<string, unknown>[]],
      ['模型', data.models as unknown as Record<string, unknown>[]],
      ['云价', data.cloud_prices as unknown as Record<string, unknown>[]],
      ['API 价', data.api_prices as unknown as Record<string, unknown>[]],
    ];
    let stale = 0;
    let unknown = 0;
    let oldest: { label: string; date: string; days: number } | null = null;
    const detail: string[] = [];
    for (const [label, rows] of buckets) {
      let n = 0;
      for (const row of rows) {
        const days = daysSince(row.as_of);
        if (days === null) {
          unknown += 1;
          continue;
        }
        if (days > STALE_DAYS) {
          n += 1;
          stale += 1;
        }
        if (!oldest || days > oldest.days) {
          oldest = { label, date: String(row.as_of).slice(0, 10), days };
        }
      }
      if (n > 0) detail.push(`${label} ${n} 条`);
    }
    return { stale, unknown, oldest, detail };
  })();

  return (
    <div>
      <Typography.Paragraph type="secondary">
        基准库为全局测算提供硬件/模型/云价/API 价输入。平台内置条目对所有租户只读；具备「基准维护」权限可新增本租户基准并编辑/删除自有条目。
        发布即冻结一份全量快照，之后可随时回滚到该版本。
      </Typography.Paragraph>
      <DataSyncPanel
        syncStatus={syncStatus}
        syncLoading={syncLoading}
        authorityStatus={authorityStatus}
        authorityLoading={authorityLoading}
        overview={overview}
        modelCoverage={modelCoverage}
        syncing={syncing}
        canWrite={canWrite}
        onSync={() => void handleSync()}
        onAuthority={() => setAuthorityOpen(true)}
        onMarket={(kind) => setMarketKind(kind)}
      />
      {freshness.stale > 0 || freshness.unknown > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="staleness-alert"
          title={
            `${freshness.stale} 条基准超过 ${STALE_DAYS} 天未更新` +
            (freshness.unknown > 0 ? `，${freshness.unknown} 条来源未标注日期（未核实）` : '')
          }
          description={
            <span>
              {freshness.oldest
                ? `最老一条：${freshness.oldest.label} · ${freshness.oldest.date}（${freshness.oldest.days} 天前）`
                : null}
              {freshness.detail.length ? `；按类型：${freshness.detail.join(' · ')}` : null}
              。能自动采集的链路见上方「数据更新」面板；没有公开数据源的行
              需人工复核后修改「来源」与「生效日期」。
            </span>
          }
        />
      ) : null}
      {canWrite ? (
        <Space style={{ marginBottom: 12 }} wrap>
          <Button type="primary" icon={<CloudUploadOutlined />} loading={publishing} onClick={handlePublish}>
            发布版本
          </Button>
          <Button icon={<HistoryOutlined />} onClick={openHistory}>
            发布历史
          </Button>
        </Space>
      ) : null}
      <BenchTable kind="gpus" title="GPU 基准" columns={GPU_COLS} rows={data.gpus as unknown as Record<string, unknown>[]} canWrite={canWrite} />
      <BenchTable kind="models" title="模型基准" columns={modelsColumns} rows={data.models as unknown as Record<string, unknown>[]} canWrite={canWrite} />
      <BenchTable kind="cloud-prices" title="云租赁价基准" columns={CLOUD_COLS} rows={data.cloud_prices as unknown as Record<string, unknown>[]} canWrite={canWrite} />
      <BenchTable kind="api-prices" title="第三方 API 价基准" columns={API_COLS} rows={data.api_prices as unknown as Record<string, unknown>[]} canWrite={canWrite} />

      <AuthoritySyncDrawer
        open={authorityOpen}
        onClose={() => setAuthorityOpen(false)}
        canWrite={canWrite}
        onApplied={() => {
          void refresh();
        }}
      />

      {marketKind ? (
        <MarketSyncDrawer
          open
          kind={marketKind}
          onClose={() => setMarketKind(null)}
          canWrite={canWrite}
          onApplied={() => {
            void refresh();
          }}
        />
      ) : null}

      <Drawer
        title="基准库发布历史"
        size="large"
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="回滚只还原与快照不同的字段，被回滚的行版本号会继续自增；平台内置条目仅平台超管可回滚。"
        />
        {lastRollback ? (
          <Alert
            type={lastRollback.updated.length ? 'success' : 'warning'}
            showIcon
            style={{ marginBottom: 12 }}
            title={`上次回滚：还原 ${lastRollback.updated.length} 条 / 无差异 ${lastRollback.unchanged} 条 / 跳过 ${lastRollback.skipped.length} 条`}
            description={
              lastRollback.updated.length
                ? lastRollback.updated
                    .slice(0, 5)
                    .map((r) => `${r.code || r.id}：${r.fields.join('、')}（v${r.from_version}→v${r.to_version}）`)
                    .join('；')
                : lastRollback.skipped.length
                  ? Array.from(new Set(lastRollback.skipped.map((s) => s.reason))).join('；')
                  : '当前基准库已与该版本一致'
            }
          />
        ) : null}
        <Table
          rowKey="publish_id"
          size="small"
          loading={historyLoading}
          dataSource={publishes}
          pagination={false}
          locale={{ emptyText: '还没有发布过版本' }}
          columns={[
            { title: '版本', dataIndex: 'publish_id', width: 90, render: (v: number) => `#${v}` },
            {
              title: '发布时间',
              dataIndex: 'published_at',
              width: 190,
              render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN') : '—'),
            },
            { title: '操作人', dataIndex: 'actor_email', ellipsis: true },
            {
              title: '条目数',
              dataIndex: 'counts',
              width: 90,
              render: (counts: Record<string, number>) => kindsTotal(counts),
            },
            {
              title: '操作',
              width: 110,
              render: (_: unknown, row: PublishSummary) => (
                <Popconfirm
                  title={`回滚到版本 #${row.publish_id}？`}
                  description="仅还原有差异的字段，版本号继续自增"
                  onConfirm={() => handleRollback(row.publish_id)}
                >
                  <Button type="link" loading={rollingBack === row.publish_id}>
                    回滚到此版
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
