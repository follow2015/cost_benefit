/**
 * 硬件反选推荐（§3.13）：输入需求（吞吐/需求量/SLA/模型/合规/预算），
 * 调后端 /calc/recommend 反推 GPU 候选并生成完整测算方案；
 * 「一键应用」把候选 params 回填 Wizard 草稿后跳转，与手工配置同源同口径。
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Row, Col, InputNumber, Select, Button, Statistic, Alert, Tag, Space, Typography,
  Table, Descriptions, Tooltip, Empty, Spin, message,
} from 'antd';
import { RobotOutlined, ImportOutlined, ThunderboltOutlined, WarningOutlined } from '@ant-design/icons';
import { recommendHardware } from '@/features/calc/api/calcApi';
import { paramsFromDict } from '@/features/calc/engine/codec';
import { HardwareBomCard } from '@/shared/ui/HardwareBomCard';
import { useScenarioDraft } from '@/features/scenarios/stores/scenarioStore';
import type { HardwareCandidateDto, HardwareRecommendResult } from '@/shared/types';

const QUANT_OPTIONS = ['FP8', 'FP16', 'BF16', 'INT8', 'INT4'].map((q) => ({ value: q, label: q }));
const OBJECTIVE_OPTIONS = [
  { value: 'balanced', label: '综合平衡（单位成本70% + CAPEX 30%）' },
  { value: 'min_capex', label: '期初投资最小' },
  { value: 'min_tco', label: '全周期 TCO 最小' },
  { value: 'min_cost_per_m', label: '每百万 token 成本最小' },
];
const CN_OPTIONS = [
  { value: 'none', label: '无合规要求' },
  { value: 'partial', label: '部分国产化' },
  { value: 'full', label: '全栈国产化' },
];
const FABRIC_OPTIONS = [
  { value: '', label: '自动适配（H 系→IB / 消费级·国产→RoCE）' },
  { value: 'ib', label: 'IB（InfiniBand，H 系列）' },
  { value: 'roce', label: 'RoCE（以太网，消费级/国产）' },
  { value: 'rdma', label: 'RDMA（兼容旧值）' },
  { value: 'ethernet', label: '以太网（兼容旧值）' },
];
const SPINE_PORT_OPTIONS = [
  { value: '', label: '复用 Leaf' },
  { value: 200, label: '200G' },
  { value: 400, label: '400G' },
  { value: 800, label: '800G' },
];

function fmt(v: string | null | undefined, digits = 0): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(digits || 2)}万`;
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

function opt(v: string | undefined, fallback: string): string {
  return v === undefined || v === '' ? fallback : v;
}

export default function HardwareRecommendPage(): React.ReactElement {
  const navigate = useNavigate();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string>('');
  const [result, setResult] = React.useState<HardwareRecommendResult | null>(null);

  // ---- 表单状态（字符串，与 ThroughputCalc 风格一致）----
  const [tEffTarget, setTEffTarget] = React.useState<string>('');
  const [dEqTarget, setDEqTarget] = React.useState<string>('300');
  const [uTarget, setUTarget] = React.useState<string>('0.7');
  const [growth, setGrowth] = React.useState<string>('0.2');
  const [mParam, setMParam] = React.useState<string>('70');
  const [quant, setQuant] = React.useState<string>('FP8');
  const [slaTtft, setSlaTtft] = React.useState<string>('');
  const [slaTpot, setSlaTpot] = React.useState<string>('');
  const [cnCfg, setCnCfg] = React.useState<string>('none');
  const [fabric, setFabric] = React.useState<string>('');
  const [spinePortSpeed, setSpinePortSpeed] = React.useState<string>('');
  const [extraNodes, setExtraNodes] = React.useState<number>(0);
  const [capexBudget, setCapexBudget] = React.useState<string>('');
  const [powerBudget, setPowerBudget] = React.useState<string>('');
  const [objective, setObjective] = React.useState<string>('balanced');
  const [topN, setTopN] = React.useState<number>(3);

  const handleRun = async () => {
    if (!tEffTarget.trim() && !dEqTarget.trim()) {
      setError('请至少填写「目标吞吐 T_eff」或「月需求量 D_eq」之一。');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await recommendHardware({
        T_eff_target: tEffTarget.trim() || null,
        D_eq_target: dEqTarget.trim() || null,
        U_target: opt(uTarget, '0.7'),
        growth_headroom: opt(growth, '0.2'),
        M_param: opt(mParam, '70'),
        quant,
        SLA_ttft: slaTtft.trim() || null,
        SLA_tpot: slaTpot.trim() || null,
        CN_cfg: cnCfg,
        fabric,
        extra_nodes: extraNodes,
        spine_port_speed: spinePortSpeed === '' ? null : Number(spinePortSpeed),
        capex_budget: capexBudget.trim() || null,
        power_budget_kw: powerBudget.trim() || null,
        objective,
        top_n: topN,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : '推荐请求失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  /** 一键应用：候选 params（字符串 dict）→ ScenarioParams → 写入草稿（含名称/摘要）→ 跳转 Wizard。 */
  const handleApply = (candidate: HardwareCandidateDto) => {
    if (!candidate.params) return;
    const params = paramsFromDict(candidate.params as Record<string, unknown>);
    const draft = useScenarioDraft.getState();
    draft.setParams(params);
    draft.setName(`硬件反选推荐（${candidate.gpu.name} ×${candidate.N_gpu}卡）`);
    draft.setDescription(
      `源自硬件反选推荐：N_gpu=${candidate.N_gpu}、节点=${candidate.node_count}、CAPEX=${fmt(candidate.capex, 0)}元、配套=${fmt(candidate.supporting_capex, 0)}元、NPV=${fmt(candidate.kpis.npv, 0)}元`,
    );
    const hasSupporting = Number(candidate.supporting_capex) > 0;
    void message.success(
      hasSupporting
        ? `方案已应用：配套 CAPEX ${fmt(candidate.supporting_capex, 0)} 元（存储+组网）已并入「整机配套价」，财务测算与推荐口径一致`
        : '方案已应用：参数已回填至测算向导',
    );
    navigate('/scenarios/new');
  };

  const num = (v: string | null | undefined, fallback: number): number => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };

  const candidatesTableData = (result?.candidates ?? []).map((c) => ({
    key: c.gpu.id,
    ...c,
  }));

  return (
    <div>
      <Card
        title={
          <Space>
            <RobotOutlined />
            <span>硬件反选推荐（§3.13）</span>
            <Tag color="blue">需求 → GPU 候选 → 完整测算方案</Tag>
          </Space>
        }
        extra={<Typography.Text type="secondary">与手工配置同源同口径，结果可一键回填 Wizard</Typography.Text>}
      >
        <Row gutter={16}>
          {/* ---------------- 输入侧 ---------------- */}
          <Col xs={24} md={9}>
            <Card type="inner" title="需求与约束输入">
              <Row gutter={[12, 8]}>
                <Col span={12}>
                  <Typography.Text>目标吞吐 T_eff (tok/s)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="如 6000"
                    value={tEffTarget ? Number(tEffTarget) : null}
                    onChange={(v) => setTEffTarget(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>月需求量 D_eq (Mtok)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="如 300"
                    value={dEqTarget ? Number(dEqTarget) : null}
                    onChange={(v) => setDEqTarget(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>设计利用率 U_target</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0.01} max={1} step={0.05}
                    value={uTarget ? Number(uTarget) : null}
                    onChange={(v) => setUTarget(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>增长裕量</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} max={2} step={0.1}
                    value={growth ? Number(growth) : null}
                    onChange={(v) => setGrowth(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>模型规模 (B)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1}
                    value={mParam ? Number(mParam) : null}
                    onChange={(v) => setMParam(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>量化精度</Typography.Text>
                  <Select style={{ width: '100%' }} value={quant} options={QUANT_OPTIONS} onChange={setQuant} />
                </Col>
                <Col span={12}>
                  <Typography.Text>SLA TTFT (ms，可选)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} placeholder="500"
                    value={slaTtft ? Number(slaTtft) : null}
                    onChange={(v) => setSlaTtft(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>SLA TPOT (ms，可选)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} placeholder="50"
                    value={slaTpot ? Number(slaTpot) : null}
                    onChange={(v) => setSlaTpot(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>信创合规</Typography.Text>
                  <Select style={{ width: '100%' }} value={cnCfg} options={CN_OPTIONS} onChange={setCnCfg} />
                </Col>
                <Col span={12}>
                  <Typography.Text>跨机组网形态</Typography.Text>
                  <Select style={{ width: '100%' }} value={fabric} options={FABRIC_OPTIONS} onChange={setFabric} />
                </Col>
                <Col span={12}>
                  <Typography.Text>Spine 端口速率</Typography.Text>
                  <Select style={{ width: '100%' }} value={spinePortSpeed} options={SPINE_PORT_OPTIONS} onChange={setSpinePortSpeed} />
                </Col>
                <Col span={12}>
                  <Typography.Text>CAPEX 预算 (元，可选)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="超出降权不剔除"
                    value={capexBudget ? Number(capexBudget) : null}
                    onChange={(v) => setCapexBudget(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>功耗预算 (kW，可选)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="超出降权不剔除"
                    value={powerBudget ? Number(powerBudget) : null}
                    onChange={(v) => setPowerBudget(v === null ? '' : String(v))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>打分目标</Typography.Text>
                  <Select style={{ width: '100%' }} value={objective} options={OBJECTIVE_OPTIONS} onChange={setObjective} />
                </Col>
                <Col span={12}>
                  <Typography.Text>通用计算节点数</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} placeholder="无 GPU 但需上联，如 4"
                    value={extraNodes}
                    onChange={(v) => setExtraNodes(Math.max(0, Math.floor(Number(v ?? 0))))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>Top-N 推荐数</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} max={6}
                    value={topN}
                    onChange={(v) => setTopN(Math.max(1, Math.min(6, Number(v ?? 3))))} />
                </Col>
              </Row>
              <DividerSmall />
              <Button type="primary" icon={<ThunderboltOutlined />} block loading={loading} onClick={handleRun}>
                反选推荐
              </Button>
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                吞吐/需求量至少填一项；两项都填时以吞吐为准（更严格约束）。
              </Typography.Text>
            </Card>
          </Col>

          {/* ---------------- 结果侧 ---------------- */}
          <Col xs={24} md={15}>
            {error && <Alert style={{ marginBottom: 12 }} type="error" showIcon title="推荐失败" description={error} />}
            {!result && !loading && (
              <Empty description="填写左侧需求后点击「反选推荐」" style={{ padding: '48px 0' }} />
            )}
            {loading && <div style={{ textAlign: 'center', padding: 48 }}><Spin description="正在评估候选卡并测算方案…" /></div>}

            {result && !loading && (
              <>
                <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
                  <Col span={8}>
                    <Statistic title="目标吞吐" value={num(result.target_tok_s, 0)} suffix="tok/s" />
                  </Col>
                  <Col span={8}>
                    <Statistic title="权重显存需求" value={num(result.mem_required_gb, 0)} suffix="GB" />
                  </Col>
                  <Col span={8}>
                    <Statistic title="可行候选" value={result.candidates.filter((c) => c.feasible).length}
                      suffix={`/ ${result.candidates.length}`} />
                  </Col>
                </Row>

                {result.notes.length > 0 && (
                  <Alert style={{ marginBottom: 12 }} type="warning" showIcon title="提示"
                    description={<ul style={{ margin: 0, paddingLeft: 18 }}>{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>} />
                )}

                <Typography.Title level={5} style={{ marginTop: 8 }}>推荐配置（Top-N）</Typography.Title>
                <Row gutter={[12, 12]}>
                  {result.recommended.map((c, idx) => (
                    <Col xs={24} sm={12} lg={8} key={c.gpu.id}>
                      <Card size="small" title={
                        <Space>
                          <Tag color={c.gpu.domestic ? 'gold' : 'blue'}>{idx + 1}</Tag>
                          <span>{c.gpu.name}</span>
                          {c.gpu.domestic && <Tag color="gold">国产</Tag>}
                        </Space>
                      }>
                        <Descriptions size="small" column={2} colon={false}>
                          <Descriptions.Item label="卡数">{c.N_gpu} 卡</Descriptions.Item>
                          <Descriptions.Item label="节点数">{c.node_count} 台机</Descriptions.Item>
                          <Descriptions.Item label="吞吐">{num(c.T_eff_achieved, 0).toLocaleString()} tok/s</Descriptions.Item>
                          <Descriptions.Item label="总 CAPEX">{fmt(
                            String(num(c.capex, 0) + num(c.supporting_capex, 0)), 0)} 元</Descriptions.Item>
                          <Descriptions.Item label="整机功耗">{num(c.power_kw, 0)} kW</Descriptions.Item>
                          <Descriptions.Item label="存储容量">
                            {c.storage ? `${num(c.storage.capacity_gb, 0).toLocaleString()} GB` : '—'}
                          </Descriptions.Item>
                          <Descriptions.Item label="配套 CAPEX">{fmt(c.supporting_capex, 0)} 元</Descriptions.Item>
                          <Descriptions.Item label="配套月费">
                            {c.storage || c.network
                              ? fmt(String(num(String(c.storage?.monthly ?? 0), 2) + num(String(c.network?.monthly ?? 0), 2)), 0)
                              : '—'} 元/月
                          </Descriptions.Item>
                          <Descriptions.Item label="单位成本">{fmt(c.kpis.cost_per_m, 2)} 元/Mtok</Descriptions.Item>
                          <Descriptions.Item label="NPV">{fmt(c.kpis.npv, 0)} 元</Descriptions.Item>
                          <Descriptions.Item label="TCO">{fmt(c.kpis.tco, 0)} 元</Descriptions.Item>
                          <Descriptions.Item label="回本">{c.kpis.payback_static ? `${num(c.kpis.payback_static, 1)} 月` : '—'}</Descriptions.Item>
                        </Descriptions>
                        {c.over_budget && <Tag color="orange" icon={<WarningOutlined />}>超预算/功耗</Tag>}
                        <Tooltip title={c.params ? '把此候选的完整参数写入新建方案草稿并跳转向导' : '该候选不可行，无法应用'}>
                          <Button
                            size="small" type="primary" icon={<ImportOutlined />} block
                            style={{ marginTop: 8 }} disabled={!c.params}
                            onClick={() => handleApply(c)}
                          >
                            一键应用此方案
                          </Button>
                        </Tooltip>
                        {c.params && (
                          <div style={{ marginTop: 8 }}>
                            <HardwareBomCard params={paramsFromDict(c.params as Record<string, unknown>)} />
                          </div>
                        )}
                        {c.warnings.length > 0 && (
                          <Typography.Text type="warning" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
                            {c.warnings.join('；')}
                          </Typography.Text>
                        )}
                      </Card>
                    </Col>
                  ))}
                </Row>

                <Typography.Title level={5} style={{ marginTop: 20 }}>全部候选评估</Typography.Title>
                <Table
                  size="small" dataSource={candidatesTableData} pagination={false}
                  columns={[
                    { title: '型号', dataIndex: ['gpu', 'name'], key: 'name',
                      render: (_: unknown, c: HardwareCandidateDto) => (
                        <Space size={4}>
                          <span>{c.gpu.name}</span>
                          {c.gpu.domestic && <Tag color="gold">国产</Tag>}
                        </Space>
                      ) },
                    { title: '卡数', dataIndex: 'N_gpu', key: 'N_gpu', width: 60 },
                    { title: '节点', dataIndex: 'node_count', key: 'node_count', width: 60,
                      render: (v: number) => (v > 1 ? `${v} 台` : '单机') },
                    { title: '总CAPEX(万)', key: 'capex', width: 100,
                      render: (_: unknown, c: HardwareCandidateDto) =>
                        ((num(c.capex, 0) + num(c.supporting_capex, 0)) / 1e4).toFixed(1) },
                    { title: '功耗(kW)', key: 'power', width: 90,
                      render: (_: unknown, c: HardwareCandidateDto) =>
                        num(c.power_kw, 0) + num(c.supporting_power_kw, 0) },
                    { title: '单位成本', key: 'cost', width: 100,
                      render: (_: unknown, c: HardwareCandidateDto) => (c.kpis.cost_per_m ? `${num(c.kpis.cost_per_m, 2)} 元/Mtok` : '—') },
                    { title: '可行性', dataIndex: 'feasible', key: 'feasible', width: 90,
                      render: (v: boolean) => (v ? <Tag color="green">可行</Tag> : <Tag color="red">不可行</Tag>) },
                    { title: '说明', key: 'warnings', render: (_: unknown, c: HardwareCandidateDto) => (
                        <Typography.Text type={c.feasible ? 'secondary' : 'danger'} style={{ fontSize: 12 }}>
                          {c.warnings.join('；') || (c.feasible ? '—' : '—')}
                        </Typography.Text>
                      ) },
                  ]}
                />

                <Alert style={{ marginTop: 12 }} type="info" showIcon title="推导假设"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                      {(result.recommended[0]?.assumptions ?? []).map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                  } />
              </>
            )}
          </Col>
        </Row>
      </Card>
    </div>
  );
}

function DividerSmall(): React.ReactElement {
  return <div style={{ height: 12 }} />;
}
