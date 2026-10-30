/** 权威同步抽屉：三源比对结果 → 人工裁决 → 应用。
 *
 * 设计原则与后端一致：**冲突项绝不默认采信**。
 * - `consensus`（≥2 源一致）默认勾选，可直接应用；
 * - `single_source` 默认不勾，勾选即表示接受"仅一家之言"；
 * - `conflict` 必须点选某个源才进入待应用集合，避免盲改。
 */
import React from 'react';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import {
  applyAuthority,
  previewAuthority,
  type AuthorityApplyItem,
  type AuthorityItem,
  type AuthorityPreview,
  type AuthorityVerdict,
} from '@/features/benchmarks/api/benchmarksApi';

const VERDICT_META: Record<AuthorityVerdict, { color: string; label: string; hint: string }> = {
  consensus: {
    color: 'success',
    label: '多源一致',
    hint: '≥2 个权威源一致（相对 1% 或绝对 $0.005 内），可安全应用',
  },
  single_source: { color: 'warning', label: '单一来源', hint: '只有 1 个源有数据，可信度中等，需人工判断' },
  conflict: { color: 'error', label: '源间冲突', hint: '多个源互相矛盾且无多数，必须人工选择采信哪一方' },
  no_data: { color: 'default', label: '无权威数据', hint: '三个源都没有该模型，只能人工维护' },
};

/** 待应用的选中值。 */
interface Picked {
  usd_in: string;
  usd_out?: string | null;
  usd_cache?: string | null;
  label: string;
}

export default function AuthoritySyncDrawer(props: {
  open: boolean;
  onClose: () => void;
  canWrite: boolean;
  onApplied: () => void;
}): React.ReactElement {
  const { open, onClose, canWrite, onApplied } = props;
  const { message } = App.useApp();
  const [loading, setLoading] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  const [preview, setPreview] = React.useState<AuthorityPreview | null>(null);
  const [picked, setPicked] = React.useState<Record<number, Picked>>({});
  // 「只看需决策」开关：默认关（勾选状态必须所见即所得，不能被隐藏），
  // 但行序把真需要决策的排在前面，避免十几条汇率尾巴把 3 条真问题淹掉。
  const [onlyDiff, setOnlyDiff] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await previewAuthority();
      setPreview(data);
      // 只预选「多源一致」项；冲突与单源一律留空待人工判断
      const initial: Record<number, Picked> = {};
      for (const it of data.items) {
        if (it.verdict === 'consensus' && it.proposed.usd_in) {
          initial[it.id] = {
            usd_in: it.proposed.usd_in,
            usd_out: it.proposed.usd_out,
            usd_cache: it.proposed.usd_cache,
            label: 'multi-source',
          };
        }
      }
      setPicked(initial);
    } catch (err) {
      message.error(`拉取权威数据失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message]);

  React.useEffect(() => {
    if (open && !preview) void load();
  }, [open, preview, load]);

  const toggle = (it: AuthorityItem, on: boolean) => {
    setPicked((prev) => {
      const next = { ...prev };
      if (!on) {
        delete next[it.id];
        return next;
      }
      const usdIn = it.proposed.usd_in;
      if (!usdIn) return next;
      next[it.id] = {
        usd_in: usdIn,
        usd_out: it.proposed.usd_out,
        usd_cache: it.proposed.usd_cache,
        label: it.verdict === 'consensus' ? 'multi-source' : 'single-source',
      };
      return next;
    });
  };

  const pickSource = (it: AuthorityItem, sourceName: string) => {
    const obs = it.observations.find((o) => o.source === sourceName);
    if (!obs) return;
    setPicked((prev) => ({
      ...prev,
      [it.id]: {
        usd_in: obs.usd_in,
        usd_out: obs.usd_out,
        usd_cache: obs.usd_cache,
        label: sourceName,
      },
    }));
  };

  const submit = async () => {
    const items: AuthorityApplyItem[] = Object.entries(picked).map(([id, v]) => ({
      id: Number(id),
      usd_in: v.usd_in,
      usd_out: v.usd_out ?? undefined,
      usd_cache: v.usd_cache ?? undefined,
      source_label: v.label,
    }));
    if (!items.length) {
      message.warning('未选择任何条目');
      return;
    }
    setApplying(true);
    try {
      const res = await applyAuthority(items, preview?.fx.authoritative ?? undefined);
      message.success(
        `已应用 ${res.applied_count} 条（汇率 ${res.fx_usd_cny}）` +
          (res.skipped.length ? `，跳过 ${res.skipped.length} 条` : ''),
      );
      setPreview(null);
      setPicked({});
      onApplied();
      onClose();
    } catch (err) {
      message.error(`应用失败：${(err as Error).message}`);
    } finally {
      setApplying(false);
    }
  };

  const columns = [
    {
      title: '厂商 / 模型',
      key: 'name',
      width: 210,
      render: (_: unknown, it: AuthorityItem) => (
        <div>
          <div style={{ fontWeight: 500 }}>{it.model_code}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {it.provider} · v{it.current.version}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '库内 (¥/Mtok)',
      key: 'current',
      width: 110,
      render: (_: unknown, it: AuthorityItem) => (
        <Tooltip title={`来源：${it.current.source || '未标注'}${it.current.as_of ? ` · ${it.current.as_of}` : ''}`}>
          <span className="num-mono">{it.current.in_cny}</span>
        </Tooltip>
      ),
    },
    {
      title: '权威 (¥/Mtok)',
      key: 'proposed',
      width: 110,
      render: (_: unknown, it: AuthorityItem) => {
        const p = it.proposed.in_cny;
        if (p) return <span className="num-mono">{p}</span>;
        const choice = picked[it.id];
        if (choice) {
          return (
            <span className="num-mono">
              {choice.usd_in} <Typography.Text type="secondary" style={{ fontSize: 11 }}>USD</Typography.Text>
            </span>
          );
        }
        return <Typography.Text type="secondary">待裁决</Typography.Text>;
      },
    },
    {
      title: '变动',
      key: 'change',
      width: 96,
      render: (_: unknown, it: AuthorityItem) => {
        if (it.change === '—') return <Typography.Text type="secondary">—</Typography.Text>;
        // 「仅汇率」：价格本身没动，差异全部来自折算汇率口径不同（6.76 / 7.2 → 6.68）。
        // 不标出来的话，十几条 -0.0% 会让人以为有大面积调价。
        if (it.settled) {
          // partial 的条目（输入价一致、输出价分歧）只有输入价是「仅汇率」，
          // 直接写「仅汇率」会和旁边的「源间冲突」自相矛盾
          const label = it.partial ? '输入价仅汇率' : '仅汇率';
          return (
            <Tooltip title="价格未变，差异仅来自折算汇率口径，应用后 CNY 会按当前汇率重算">
              <Tag color="default" style={{ marginInlineEnd: 0 }}>
                {label}
              </Tag>
            </Tooltip>
          );
        }
        const up = it.change.startsWith('+');
        return (
          <span style={{ color: up ? '#cf1322' : '#3f8600', fontVariantNumeric: 'tabular-nums' }}>
            {it.change}
          </span>
        );
      },
    },
    {
      title: '判决',
      key: 'verdict',
      width: 116,
      render: (_: unknown, it: AuthorityItem) => {
        const meta = VERDICT_META[it.verdict];
        // 分维度投票后，可能出现「输入价多源一致、输出价互不相符」——
        // 只挂一个「源间冲突」会让人以为整条都没依据，必须把分歧落在哪一项说清楚。
        const split =
          it.input_verdict !== it.output_verdict &&
          it.output_verdict !== 'no_data' &&
          it.input_verdict !== 'no_data';
        return (
          <Tooltip
            title={
              split
                ? `输入价：${it.input_verdict_label}（${it.input_agreeing.join('/') || '无'}）\n输出价：${it.output_verdict_label}（${it.output_agreeing.join('/') || '无'}）`
                : meta.hint
            }
          >
            <Space size={2} direction="vertical">
              <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>
                {meta.label}
              </Tag>
              {split && (
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  输出价分歧
                </Typography.Text>
              )}
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '应用',
      key: 'pick',
      width: 168,
      render: (_: unknown, it: AuthorityItem) => {
        if (it.verdict === 'no_data') return <Typography.Text type="secondary">—</Typography.Text>;
        if (it.verdict === 'conflict') {
          // 冲突项不给勾选框：必须明确选择采信哪个源。
          // 选项里直接带上各源价格，省得用户再展开对照。
          return (
            <Select
              size="small"
              style={{ width: 150 }}
              placeholder="选择采信源"
              value={picked[it.id]?.label}
              onChange={(v: string) => pickSource(it, v)}
              options={it.observations.map((o) => ({
                value: o.source,
                label: `${o.source} $${o.usd_in}`,
              }))}
            />
          );
        }
        return (
          <Checkbox
            checked={Boolean(picked[it.id])}
            disabled={!canWrite}
            onChange={(e) => toggle(it, e.target.checked)}
          />
        );
      },
    },
  ];

  const summary = preview?.summary;
  const pickedCount = Object.keys(picked).length;

  const visibleItems = React.useMemo(() => {
    const items = preview?.items ?? [];
    const filtered = onlyDiff ? items.filter((it) => !it.settled) : items;
    // 待决策的排前面：冲突最该看，其次单源；「仅汇率」统一沉底
    const rank: Record<AuthorityVerdict, number> = {
      conflict: 0,
      single_source: 1,
      no_data: 2,
      consensus: 3,
    };
    return [...filtered].sort((a, b) => {
      if (a.settled !== b.settled) return a.settled ? 1 : -1;
      return rank[a.verdict] - rank[b.verdict];
    });
  }, [preview, onlyDiff]);

  return (
    <Drawer
      title="权威同步 · 多源比对"
      width={1000}
      open={open}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            重新拉取
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            disabled={!canWrite || pickedCount === 0}
            loading={applying}
            onClick={() => void submit()}
          >
            应用 {pickedCount} 条
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading} tip="正在拉取三个权威源并比对（首次约 20 秒，之后 10 分钟内复用缓存）">
        {!preview ? (
          <Empty
            description={
              loading
                ? '正在下载 LiteLLM / models.dev / OpenRouter 三源数据…'
                : '尚未拉取，点击右上角「重新拉取」'
            }
          />
        ) : (
          <>
            <Alert
              type={preview.fx.drifted ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 12 }}
              title={
                <Space size={16} wrap>
                  <span>
                    汇率：库内 <b>{preview.fx.current}</b> → 权威{' '}
                    <b>{preview.fx.authoritative ?? '未获取'}</b>（{preview.fx.change}）
                  </span>
                  {preview.fx.drifted && <Tag color="orange">偏离 &gt;0.5%，建议采用</Tag>}
                </Space>
              }              description={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  应用时按权威汇率折算，并把 USD 原价一并存入条目 meta，日后可区分「厂商调价」与「汇率变动」。
                </Typography.Text>
              }
            />

            <Descriptions size="small" column={5} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="待决策">
                <Tooltip title="需要人看一眼的条数：单源、源间冲突，且价格确实有变动">
                  <b style={{ color: (summary?.needs_decision ?? 0) > 0 ? '#cf1322' : '#389e0d' }}>
                    {summary?.needs_decision ?? 0}
                  </b>
                </Tooltip>
              </Descriptions.Item>
              <Descriptions.Item label="仅汇率口径">
                <Tooltip title="价格未变，只是当初按 6.76 / 7.2 折算，应用后统一到权威汇率">
                  {summary?.settled ?? 0}
                </Tooltip>
              </Descriptions.Item>
              <Descriptions.Item label="多源一致">
                <b style={{ color: '#389e0d' }}>{summary?.consensus ?? 0}</b>
              </Descriptions.Item>
              <Descriptions.Item label="单源">
                <b style={{ color: '#d48806' }}>{summary?.single_source ?? 0}</b>
              </Descriptions.Item>
              <Descriptions.Item label="冲突 / 无覆盖">
                <b style={{ color: '#cf1322' }}>{summary?.conflict ?? 0}</b>
                <Typography.Text type="secondary">/{summary?.no_data ?? 0}</Typography.Text>
              </Descriptions.Item>
            </Descriptions>

            <Space size={8} wrap style={{ marginBottom: 10 }}>
              <Checkbox checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)}>
                只看需决策（隐藏「仅汇率」）
              </Checkbox>
              {preview.sources.map((s) => (
                <Tooltip key={s.source} title={s.error ?? `${s.entries} 条记录`}>
                  <Tag color={s.ok ? 'green' : 'red'}>
                    {s.source} {s.ok ? `${s.entries}` : '失败'}
                  </Tag>
                </Tooltip>
              ))}
            </Space>

            <Table<AuthorityItem>
              rowKey="id"
              size="small"
              dataSource={visibleItems}
              columns={columns as never}
              pagination={false}
              scroll={{ y: 460 }}
              expandable={{
                rowExpandable: (it) => it.observations.length > 0,
                expandedRowRender: (it) => (
                  <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
                    {it.observations.map((o) => (
                      <span key={o.source}>
                        <Tag>{o.source}</Tag>
                        ${o.usd_in} / ${o.usd_out ?? '—'}
                        {o.context ? ` · 上下文 ${o.context}` : ''}
                      </span>
                    ))}
                  </Space>
                ),
              }}
            />
          </>
        )}
      </Spin>
    </Drawer>
  );
}
