/** 租赁价采集抽屉：外部价格 → 与库内逐条比对 → 人工勾选 → 写回。
 *
 * 为什么不让它自动写库：价格基准是测算输入，一动就换一批结论。
 * 实测 Azure H100 官方价 ¥46.63，库内人工值 ¥23.7 —— 差一倍。
 * 这种量级的差异要么是人工值抄错，要么当初填的是折扣价，
 * 机器分不清，只能摆出来让人判断。
 *
 * 所以本抽屉只做三件事：拉数、摆差异、按勾选写回。
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
  Spin,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import {
  applyMarket,
  previewMarket,
  type MarketApplyItem,
  type MarketItem,
  type MarketKind,
  type MarketPreview,
} from '@/features/benchmarks/api/benchmarksApi';

/** 超过这个幅度的变动值得单独提示：调价和口径错误的可能性都存在。 */
const BIG_CHANGE = 0.2;

const KIND_META: Record<MarketKind, { title: string; hint: string; sourceTip: string }> = {
  'gpu-rental': {
    title: 'GPU 租赁行情',
    hint: '各云厂商公开挂牌按需价的中位数（USD/GPU/小时），折算后写入「GPU 基准」的租赁单价',
    sourceTip: '覆盖 H100/A100/A800/L40S/RTX4090/RTX5090 六个型号',
  },
  'cloud-official': {
    title: '云厂商官方价',
    hint: '云厂商官网按需挂牌价，按整机 GPU 数折算成单卡价后写入「云租赁价基准」',
    sourceTip: 'Azure 零售价格接口与 AWS 批量价目表均已接入；国内云与 GCP 没有公开接口',
  },
};

export default function MarketSyncDrawer(props: {
  open: boolean;
  kind: MarketKind;
  onClose: () => void;
  canWrite: boolean;
  onApplied: () => void;
}): React.ReactElement {
  const { open, kind, onClose, canWrite, onApplied } = props;
  const { message } = App.useApp();
  const [preview, setPreview] = React.useState<MarketPreview | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  const [picked, setPicked] = React.useState<Record<number, boolean>>({});

  const meta = KIND_META[kind];

  const load = React.useCallback(async () => {
    setLoading(true);
    setPicked({});
    try {
      const data = await previewMarket(kind);
      setPreview(data);
      // 默认全选：用户点「应用」就是要同步；分项确认放在取消勾选上，
      // 否则每次都要手动点 6 次才能完成一次例行同步。
      const all: Record<number, boolean> = {};
      for (const it of data.items) all[it.id] = true;
      setPicked(all);
    } catch (err) {
      setPreview(null);
      message.error(err instanceof Error ? err.message : '采集失败');
    } finally {
      setLoading(false);
    }
  }, [kind, message]);

  React.useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const pickedItems = preview?.items.filter((it) => picked[it.id]) ?? [];
  const pickedIds = pickedItems.map((it) => it.id);
  const bigChanges = pickedItems.filter((it) => {
    const n = Number.parseFloat(String(it.change ?? '').replace('%', ''));
    return Number.isFinite(n) && Math.abs(n) / 100 > BIG_CHANGE;
  }).length;

  const onApply = async () => {
    if (!preview || pickedItems.length === 0) return;
    setApplying(true);
    try {
      const items: MarketApplyItem[] = pickedItems.map((it) => ({
        id: it.id,
        proposed_cny: String(it.proposed_cny),
        as_of: it.as_of,
        meta: {},
      }));
      const result = await applyMarket(kind, items);
      message.success(
        `已应用 ${result.applied.length} 条` +
          (result.skipped.length ? `，跳过 ${result.skipped.length} 条` : ''),
      );
      onApplied();
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '应用失败');
    } finally {
      setApplying(false);
    }
  };

  const columns = [
    {
      title: '条目',
      key: 'label',
      width: 168,
      render: (_: unknown, it: MarketItem) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{it.label}</span>
          {it.note ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {it.note}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '现网值',
      key: 'current',
      width: 116,
      align: 'right' as const,
      render: (_: unknown, it: MarketItem) => (
        <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>
            {it.current_cny ? `¥${Number(it.current_cny).toFixed(2)}` : '—'}
          </span>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {it.current_source || '无来源'}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '采集值',
      key: 'proposed',
      width: 108,
      align: 'right' as const,
      render: (_: unknown, it: MarketItem) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
          {it.proposed_cny ? `¥${Number(it.proposed_cny).toFixed(2)}` : '—'}
        </span>
      ),
    },
    {
      title: '变动',
      key: 'change',
      width: 104,
      align: 'right' as const,
      render: (_: unknown, it: MarketItem) => {
        if (!it.change) {
          return <Tag color="blue">新增</Tag>;
        }
        const num = Number.parseFloat(it.change.replace('%', ''));
        const big = Number.isFinite(num) && Math.abs(num) / 100 > BIG_CHANGE;
        // 涨红跌绿：与国内行情看板一致
        const color = num > 0 ? '#cf1322' : num < 0 ? '#3f8600' : 'rgba(0,0,0,0.45)';
        return (
          <Space size={4}>
            <span style={{ color, fontVariantNumeric: 'tabular-nums' }}>{it.change}</span>
            {big ? (
              <Tooltip title="变动超过 20%：可能是真实调价，也可能是口径不同（国内云价 vs 全球行情价）">
                <Tag color="volcano" style={{ marginInlineEnd: 0 }}>
                  大
                </Tag>
              </Tooltip>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: () => <span data-testid="market-pick-all">应用</span>,
      key: 'pick',
      width: 64,
      align: 'center' as const,
      render: (_: unknown, it: MarketItem) => (
        <Checkbox
          checked={Boolean(picked[it.id])}
          onChange={(e) => setPicked((prev) => ({ ...prev, [it.id]: e.target.checked }))}
          aria-label={`应用 ${it.label}`}
        />
      ),
    },
  ];

  const allChecked =
    Boolean(preview?.items.length) && pickedItems.length === preview?.items.length;
  const someChecked = pickedItems.length > 0 && !allChecked;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={760}
      destroyOnHidden
      title={
        <Space size={8}>
          <ThunderboltOutlined style={{ color: '#fa8c16' }} />
          <span>{meta.title}</span>
          <Tag color="default" data-testid="market-kind-tag">
            {kind}
          </Tag>
        </Space>
      }
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void load()}
          data-testid="market-reload"
        >
          重新采集
        </Button>
      }
      footer={
        canWrite ? (
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button onClick={onClose}>取消</Button>
            <Button
              type="primary"
              loading={applying}
              disabled={pickedItems.length === 0}
              onClick={() => void onApply()}
              data-testid="market-apply"
            >
              应用 {pickedItems.length} 条
              {bigChanges > 0 ? `（含 ${bigChanges} 条大幅变动）` : ''}
            </Button>
          </Space>
        ) : null
      }
    >
      {loading ? (
        <div style={{ padding: '64px 0', textAlign: 'center' }}>
          <Spin />
          <div style={{ marginTop: 12 }}>
            <Typography.Text type="secondary">正在拉取外部价格…</Typography.Text>
          </div>
        </div>
      ) : !preview ? (
        <Empty description="未取到数据" />
      ) : (
        <>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 10 }}>
            {meta.hint}。数据源：
            <Tooltip title={meta.sourceTip}>
              <Typography.Link href={preview.source_url} target="_blank" rel="noreferrer">
                {preview.source_name}
              </Typography.Link>
            </Tooltip>
            {preview.as_of ? ` · 数据日期 ${preview.as_of}` : null}
            {` · 汇率 ${preview.fx_usd_cny}`}
          </Typography.Paragraph>

          <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="可采集">
              <b data-testid="market-total">{preview.summary.total}</b>
            </Descriptions.Item>
            <Descriptions.Item label="上调">
              <b style={{ color: '#cf1322' }}>{preview.summary.up}</b>
            </Descriptions.Item>
            <Descriptions.Item label="下调">
              <b style={{ color: '#3f8600' }}>{preview.summary.down}</b>
            </Descriptions.Item>
            <Descriptions.Item label="仅汇率口径">
              {preview.summary.settled}
            </Descriptions.Item>
          </Descriptions>

          {preview.warnings?.length ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              data-testid="market-warnings"
              title="部分数据源本次没有采到"
              description={
                <Space direction="vertical" size={2}>
                  {preview.warnings.map((w) => (
                    <Typography.Text key={w} type="secondary" style={{ fontSize: 12 }}>
                      {w}
                    </Typography.Text>
                  ))}
                </Space>
              }
            />
          ) : null}

          {preview.items.length === 0 ? (
            <Empty description="本次采集没有可写入的条目" />
          ) : (
            <Table<MarketItem>
              rowKey="id"
              size="small"
              dataSource={preview.items}
              columns={columns as never}
              pagination={false}
              scroll={{ y: 380 }}
              rowClassName={(it) =>
                it.direction === 'settled' ? 'market-row-settled' : ''
              }
            />
          )}

          {preview.items.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              <Checkbox
                indeterminate={someChecked}
                checked={allChecked}
                onChange={(e) => {
                  const next: Record<number, boolean> = {};
                  for (const it of preview.items) next[it.id] = e.target.checked;
                  setPicked(next);
                }}
              >
                全选 / 全不选
              </Checkbox>
            </div>
          ) : null}

          {preview.manual_only.length > 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              data-testid="market-manual-only"
              title={`${preview.manual_only.length} 条没有公开数据源，只能人工维护`}
              description={
                <>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {kind === 'gpu-rental'
                      ? '国产卡与中国特供型号（H800/H20/L20）在国际市场没有对应 SKU，不是采集失败，是根本没有这个市场。'
                      : '国内云与 GCP 不提供可匿名调用的价格接口，这些行继续由人工维护。'}
                  </Typography.Text>
                  <div style={{ marginTop: 6 }}>
                    <Space size={4} wrap>
                      {preview.manual_only.map((code) => (
                        <Tag key={code}>{code}</Tag>
                      ))}
                    </Space>
                  </div>
                </>
              }
            />
          ) : null}

          {preview.missing.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 10 }}
              title={`${preview.missing.length} 条本次上游没有数据`}
              description={
                <Space size={4} wrap>
                  {preview.missing.map((code) => (
                    <Tag key={code}>{code}</Tag>
                  ))}
                </Space>
              }
            />
          ) : null}
        </>
      )}
    </Drawer>
  );
}
