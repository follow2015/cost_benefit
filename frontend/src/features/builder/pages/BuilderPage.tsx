/** 方案构建向导（/builder）：选模型 → 量化对比 → 算力/配套 → 完整 BOM + 估算对比 → 生成方案。
 *
 * - 「选模型」走基准库 model_code（后端查表填充 M_param / 显存快照，全尺寸）；
 * - 「量化对比」对选中的量化档并行跑硬件反选，输出各档 BOM + KPI 横向对比；
 * - 「生成方案」把选中候选回填 ScenarioParams 并自动生成名称/摘要，跳转新建向导。
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App, Alert, Button, Card, Checkbox, Col, Descriptions, Divider, Input, InputNumber,
  Radio, Row, Select, Space, Spin, Statistic, Table, Tag, Typography,
} from 'antd';
import { ThunderboltOutlined, ImportOutlined, ExperimentOutlined } from '@ant-design/icons';
import { useBenchmarks } from '@/features/benchmarks/hooks/useBenchmarks';
import { recommendHardware } from '@/features/calc/api/calcApi';
import { useScenarioDraft } from '@/features/scenarios/stores/scenarioStore';
import { paramsFromDict } from '@/features/calc/engine/codec';
import { HardwareBomCard } from '@/shared/ui/HardwareBomCard';
import type {
  HardwareCandidateDto, HardwareRecommendIn, HardwareRecommendResult, ModelBench,
} from '@/shared/types';

const QUANT_OPTIONS = [
  { value: 'BF16', label: '全尺寸（BF16）', hint: '2 字节/参数，显存最大、吞吐基准' },
  { value: 'FP8', label: 'FP8', hint: '1 字节/参数，显存减半，吞吐 ×1.0' },
  { value: 'INT8', label: 'INT8', hint: '显存更小，吞吐 ×1.3' },
  { value: 'INT4', label: 'INT4', hint: '显存最小，吞吐 ×1.8（精度有损）' },
];
const PORT_OPTIONS = [
  { value: '', label: '自动（按卡型）' },
  { value: 200, label: '200G' },
  { value: 400, label: '400G' },
  { value: 800, label: '800G' },
];
const CN_OPTIONS = [
  { value: 'none', label: '无合规要求' },
  { value: 'partial', label: '部分国产化' },
  { value: 'full', label: '全栈国产化' },
];

interface QuantRow {
  quant: string;
  cand: HardwareCandidateDto;
}

export default function BuilderPage(): React.ReactElement {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { data: bundle, isLoading: loadingBundle } = useBenchmarks();

  const models: ModelBench[] = bundle?.models ?? [];
  const [modelCode, setModelCode] = React.useState<string>();
  const [model, setModel] = React.useState<ModelBench | null>(null);
  const [reqMode, setReqMode] = React.useState<'T' | 'D'>('T');
  const [tEff, setTEff] = React.useState<number | null>(10000);
  const [dEq, setDEq] = React.useState<number | null>(300);
  const [uTarget, setUTarget] = React.useState<number | null>(0.7);
  const [quants, setQuants] = React.useState<string[]>(['BF16', 'FP8']);
  const [portSpeed, setPortSpeed] = React.useState<number | ''>('');
  const [spinePortSpeed, setSpinePortSpeed] = React.useState<number | ''>('');
  const [extraNodes, setExtraNodes] = React.useState<number>(0);
  const [cnCfg, setCnCfg] = React.useState<string>('none');
  const [capexBudget, setCapexBudget] = React.useState<number | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [rows, setRows] = React.useState<QuantRow[]>([]);
  const [targetInfo, setTargetInfo] = React.useState<{ tok: string; mem: string } | null>(null);

  const num = (v: string | null | undefined, fallback = 0): number => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };
  const fmt = (v: string | null | undefined, digits = 0): string => {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(digits || 1)}万`;
    return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
  };

  const onModelChange = (code: string) => {
    setModelCode(code);
    setModel(models.find((m) => m.code === code) ?? null);
  };

  const run = async () => {
    if (!modelCode) {
      message.warning('请先选择模型');
      return;
    }
    if (reqMode === 'T' && !tEff) {
      message.warning('请填写目标吞吐（tok/s）');
      return;
    }
    if (reqMode === 'D' && !dEq) {
      message.warning('请填写月需求量（Mtok/月）');
      return;
    }
    if (!quants.length) {
      message.warning('请至少勾选一个量化档');
      return;
    }
    setLoading(true);
    try {
      const out: QuantRow[] = [];
      let lastTok = '';
      let lastMem = '';
      for (const quant of quants) {
        const req: HardwareRecommendIn = {
          T_eff_target: reqMode === 'T' ? String(tEff ?? '') : null,
          D_eq_target: reqMode === 'D' ? String(dEq ?? '') : null,
          U_target: String(uTarget ?? 0.7),
          model_code: modelCode,
          quant,
          CN_cfg: cnCfg,
          port_speed: portSpeed === '' ? null : Number(portSpeed),
          spine_port_speed: spinePortSpeed === '' ? null : Number(spinePortSpeed),
          extra_nodes: extraNodes,
          capex_budget: capexBudget != null ? String(capexBudget) : null,
          top_n: 4,
        };
        const res: HardwareRecommendResult = await recommendHardware(req);
        lastTok = res.target_tok_s;
        lastMem = res.mem_required_gb;
        for (const cand of res.recommended) out.push({ quant, cand });
      }
      setRows(out);
      setTargetInfo({ tok: lastTok, mem: lastMem });
      const gpuCount = new Set(out.map((r) => r.cand.gpu.id)).size;
      if (!out.length) message.warning('无可行候选，请放宽约束');
      else message.success(`评估完成：${quants.length} 个量化档 × ${gpuCount} 种卡型，共 ${out.length} 条候选`);
    } catch (e) {
      message.error((e as Error).message || '评估失败');
    } finally {
      setLoading(false);
    }
  };

  /** 生成方案：选中候选 → 回填 ScenarioParams + 自动名称/摘要 → 跳转新建向导。 */
  const apply = (quant: string, cand: HardwareCandidateDto) => {
    if (!cand.params) return;
    const params = paramsFromDict(cand.params as Record<string, unknown>);
    const draft = useScenarioDraft.getState();
    draft.setParams(params);
    const gpuName = cand.gpu.name ?? '';
    draft.setName(`方案构建向导：${model?.name ?? modelCode} ${quant}（${gpuName} ×${cand.N_gpu}卡）`);
    draft.setDescription(
      `模型=${model?.name ?? modelCode}；量化=${quant}；N_gpu=${cand.N_gpu}；节点=${cand.node_count}；` +
      `组网=${cand.network?.port_speed_gbps ?? '—'}G ${cand.network?.fabric ?? '—'}；` +
      `总CAPEX=${fmt(String(num(cand.capex) + num(cand.supporting_capex)))}元；NPV=${fmt(cand.kpis.npv)}元`,
    );
    message.success('方案已生成并回填测算向导（含名称/摘要），请确认后计算');
    navigate('/scenarios/new');
  };

  const columns = [
    {
      title: '量化', key: 'quant', width: 92, fixed: 'left' as const,
      render: (_: unknown, r: QuantRow) => (
        <Tag color={r.quant === 'BF16' ? 'gold' : r.quant === 'FP8' ? 'blue' : 'purple'}>{r.quant}</Tag>
      ),
    },
    {
      title: 'GPU 配置', key: 'gpu', width: 180,
      render: (_: unknown, r: QuantRow) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>{r.cand.gpu.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.cand.N_gpu} 卡 / {r.cand.node_count} 节点
            {r.cand.gpu.domestic ? ' · 国产' : ''}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '组网', key: 'net', width: 110,
      render: (_: unknown, r: QuantRow) => (
        r.cand.network
          ? <Tag>{r.cand.network.port_speed_gbps}G {r.cand.network.fabric}</Tag>
          : <Typography.Text type="secondary">—</Typography.Text>
      ),
    },
    {
      title: 'GPU CAPEX', key: 'capex', width: 100, align: 'right' as const,
      render: (_: unknown, r: QuantRow) => fmt(r.cand.capex, 1),
    },
    {
      title: '配套', key: 'sup', width: 90, align: 'right' as const,
      render: (_: unknown, r: QuantRow) => (
        <Typography.Text type="secondary">{fmt(r.cand.supporting_capex, 1)}</Typography.Text>
      ),
    },
    {
      title: '总 CAPEX', key: 'total', width: 110, align: 'right' as const,
      render: (_: unknown, r: QuantRow) => (
        <Typography.Text strong>{fmt(String(num(r.cand.capex) + num(r.cand.supporting_capex)), 1)}</Typography.Text>
      ),
    },
    {
      title: '单位成本', key: 'cost', width: 100, align: 'right' as const,
      render: (_: unknown, r: QuantRow) => fmt(r.cand.kpis.cost_per_m, 2),
    },
    {
      title: 'NPV', key: 'npv', width: 110, align: 'right' as const,
      render: (_: unknown, r: QuantRow) => (
        <Typography.Text type={num(r.cand.kpis.npv) < 0 ? 'danger' : 'success'}>
          {fmt(r.cand.kpis.npv, 0)}
        </Typography.Text>
      ),
    },
    {
      title: '回本', key: 'payback', width: 80, align: 'right' as const,
      render: (_: unknown, r: QuantRow) =>
        r.cand.kpis.payback_static ? `${num(r.cand.kpis.payback_static, 1)} 月` : '—',
    },
    {
      title: '操作', key: 'apply', width: 110, fixed: 'right' as const,
      render: (_: unknown, r: QuantRow) => (
        <Button
          size="small" type="primary" icon={<ImportOutlined />}
          disabled={!r.cand.params}
          onClick={() => apply(r.quant, r.cand)}
        >
          生成方案
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            <ThunderboltOutlined />
            <span>方案构建向导</span>
          </Space>
        }
        extra={<Typography.Text type="secondary">选模型 → 量化对比 → 算力/配套 → 完整 BOM 估算</Typography.Text>}
      >
        {/* ① 模型 */}
        <Typography.Title level={5}>① 选择模型（默认全尺寸）</Typography.Title>
        <Row gutter={[16, 8]}>
          <Col span={12}>
            <Select
              showSearch style={{ width: '100%' }} placeholder="选择模型（如 Kimi K3 / DeepSeek V4 / Qwen3.8…）"
              value={modelCode} onChange={onModelChange}
              optionFilterProp="label" loading={loadingBundle}
              options={models.map((m) => ({
                value: m.code,
                label: `${m.name}（${m.params_b}B / 显存≈${m.vram_required_gb}GB）`,
              }))}
            />
          </Col>
          {model ? (
            <Col span={12}>
              <Descriptions size="small" column={3} colon={false}>
                <Descriptions.Item label="参数量">{model.params_b}B</Descriptions.Item>
                <Descriptions.Item label="推荐显存">{model.vram_required_gb}GB</Descriptions.Item>
                <Descriptions.Item label="全尺寸显存（BF16）">
                  {fmt(String(Number(model.params_b) * 2 * 1.15), 0)}GB
                </Descriptions.Item>
              </Descriptions>
            </Col>
          ) : null}
        </Row>

        <Divider />

        {/* ② 需求与量化 */}
        <Typography.Title level={5}>② 需求与量化对比</Typography.Title>
        <Row gutter={[16, 8]}>
          <Col span={8}>
            <Typography.Text>需求口径</Typography.Text>
            <Radio.Group
              style={{ display: 'block', marginTop: 4 }} value={reqMode} onChange={(e) => setReqMode(e.target.value)}
              options={[
                { value: 'T', label: '目标吞吐' },
                { value: 'D', label: '月需求量' },
              ]}
            />
            {reqMode === 'T' ? (
              <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                <InputNumber style={{ width: '100%' }} min={100} value={tEff} onChange={setTEff} />
                <Input style={{ width: 78 }} value="tok/s" disabled />
              </Space.Compact>
            ) : (
              <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                <InputNumber style={{ width: '100%' }} min={1} value={dEq} onChange={setDEq} />
                <Input style={{ width: 92 }} value="Mtok/月" disabled />
              </Space.Compact>
            )}
          </Col>
          <Col span={6}>
            <Typography.Text>设计利用率</Typography.Text>
            <Space.Compact style={{ width: '100%', marginTop: 4 }}>
              <InputNumber style={{ width: '100%' }} min={0.1} max={0.99} step={0.05} value={uTarget} onChange={setUTarget} />
              <Input style={{ width: 46 }} value="U" disabled />
            </Space.Compact>
          </Col>
          <Col span={10}>
            <Typography.Text>量化对比（各档分别出 BOM）</Typography.Text>
            <Checkbox.Group
              style={{ display: 'block', marginTop: 4 }} value={quants} onChange={(v) => setQuants(v as string[])}
              options={QUANT_OPTIONS.map((q) => ({ value: q.value, label: `${q.label}（${q.hint}）` }))}
            />
          </Col>
        </Row>

        <Divider />

        {/* ③ 算力与配套 */}
        <Typography.Title level={5}>③ 算力与配套（影响价格参数可改）</Typography.Title>
        <Row gutter={[16, 8]}>
          <Col span={6}>
            <Typography.Text>组网端口速率（Leaf）</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={portSpeed} onChange={setPortSpeed} options={PORT_OPTIONS} />
          </Col>
          <Col span={6}>
            <Typography.Text>Spine 端口速率</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={spinePortSpeed} onChange={setSpinePortSpeed} options={[{ value: '', label: '复用 Leaf' }, ...PORT_OPTIONS.filter((o) => o.value !== '')]} />
          </Col>
          <Col span={6}>
            <Typography.Text>通用计算节点数</Typography.Text>
            <InputNumber
              style={{ width: '100%', marginTop: 4 }} min={0} value={extraNodes} onChange={(v) => setExtraNodes(v ?? 0)}
              placeholder="无 GPU 的通用节点"
            />
          </Col>
          <Col span={6}>
            <Typography.Text>信创合规</Typography.Text>
            <Select style={{ width: '100%', marginTop: 4 }} value={cnCfg} onChange={setCnCfg} options={CN_OPTIONS} />
          </Col>
          <Col span={6}>
            <Typography.Text>CAPEX 预算（元，超出降权）</Typography.Text>
            <InputNumber
              style={{ width: '100%', marginTop: 4 }} min={0} value={capexBudget} onChange={setCapexBudget}
              placeholder="可选"
            />
          </Col>
          <Col span={24} style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" icon={<ExperimentOutlined />} loading={loading} onClick={run}>
              生成方案对比
            </Button>
          </Col>
        </Row>

        {targetInfo ? (
          <Alert
            type="info" showIcon style={{ marginTop: 16 }}
            title={`目标吞吐 ${num(targetInfo.tok, 0).toLocaleString()} tok/s · 权重显存需求 ${num(targetInfo.mem, 0).toLocaleString()} GB（按所选量化档）`}
          />
        ) : null}

        {rows.length > 0 ? (
          <Table<QuantRow>
            style={{ marginTop: 16 }}
            size="small" rowKey={(r) => `${r.quant}-${r.cand.gpu.id}-${r.cand.N_gpu}`}
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1100 }}
            pagination={false}
            expandable={{
              expandedRowRender: (r) => (
                <div>
                  <Alert
                    type="warning" showIcon style={{ marginBottom: 8 }}
                    title="候选假设与告警"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {r.cand.assumptions.map((a) => <li key={a}>{a}</li>)}
                        {r.cand.warnings.map((w) => <li key={w}><Typography.Text type="danger">{w}</Typography.Text></li>)}
                      </ul>
                    }
                  />
                  {r.cand.params ? <HardwareBomCard params={paramsFromDict(r.cand.params as Record<string, unknown>)} /> : null}
                </div>
              ),
            }}
          />
        ) : loading ? (
          <div style={{ textAlign: 'center', marginTop: 32 }}>
            <Spin description="正在并行评估各量化档…" />
          </div>
        ) : null}
      </Card>
    </div>
  );
}
