/** 结果页：权威重算 + KPI 卡片 + 现金流/成本/盈亏/龙卷风/三方案对比图 + 双端偏差。
 *  P3 增量：融资 KPI 卡、联合敏感性（确定性边界）、自定义情景并列。
 */
import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Row, Col, Tag, Alert, Button, Space, Typography, App as AntApp, Spin, Descriptions, Table, Input, Divider } from 'antd';
import { EditOutlined, ReloadOutlined, SwapOutlined, BookOutlined, HistoryOutlined, BarChartOutlined, FilePdfOutlined, FileExcelOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useScenario } from '@/features/scenarios/hooks/useScenarios';
import { useLatestResult, useCompare } from '@/features/calc/hooks/useCalc';
import { calculate as calculateApi, montecarlo as montecarloApi } from '@/features/calc/api/calcApi';
import { exportReport } from '@/features/reports/api/reportsApi';
import { montecarloCompute, type MonteCarloResult } from '@/features/calc/engine/montecarlo';
import { paramsFromDict } from '@/features/calc/engine/codec';
import { MonteCarloHistogram } from '@/features/result/charts/MonteCarloHistogram';
import { draftParamsDict } from '@/features/scenarios/stores/scenarioStore';
import { compute as computeClient } from '@/features/calc/api/calcClient';
import { CashflowChart } from '@/features/result/charts/CashflowChart';
import { CostStructurePie } from '@/features/result/charts/CostStructurePie';
import { BreakevenChart } from '@/features/result/charts/BreakevenChart';
import { TornadoChart } from '@/features/result/charts/TornadoChart';
import { HardwareBomCard } from '@/shared/ui/HardwareBomCard';
import { StatCard } from '@/shared/ui/StatCard';
import { formatKpiUnit, formatKpiValue, PROFIT_KPIS } from '@/shared/ui/formatKpi';
import { CrossoverChart } from '@/features/result/charts/CrossoverChart';
import { JointSensitivityChart } from '@/features/result/charts/JointSensitivityChart';
import { CustomScenarioChart } from '@/features/result/charts/CustomScenarioChart';
import { useFormulaDrawerState } from '@/shared/ui/useFormulaDrawerState';
import { D, Decimal, safeDiv } from '@/features/calc/engine/decimalConfig';
import { buildHybrid, type CostModelLike } from '@/features/calc/engine/costModel';
import { computeHybrid, toChartPayload } from '@/features/calc/engine/crossover';
import type { CalcPayload, CustomScenarioSpecDTO, Kpi } from '@/shared/types';

const KEY_ORDER = ['cost_per_m', 'gross_margin', 'gm_pct', 'gross_margin_benchmark', 'npv', 'irr', 'roi', 'tco', 'payback_static', 'payback_discounted', 'U_be', 'p_eq', 'debt_ratio', 'interest_coverage', 'roe', 'levered_npv', 'levered_irr'];

/** KPI 指标卡语义色：收益/回报类（NPV/ROI/IRR/ROE）按中国惯例 盈=红、亏=绿；其余中性。 */
function kpiTone(kpi: Kpi): 'up' | 'down' | 'neutral' {
  if (!PROFIT_KPIS.has(kpi.key)) return 'neutral';
  const num = Number(kpi.value);
  if (!Number.isFinite(num)) return 'neutral';
  return num > 0 ? 'up' : num < 0 ? 'down' : 'neutral';
}

export default function ResultPage(): React.ReactElement {
  const { id } = useParams();
  const scenarioId = Number(id);
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const { data: scenario } = useScenario(scenarioId);
  const latest = useLatestResult(scenarioId);
  const compareMut = useCompare();
  const { openDrawer } = useFormulaDrawerState();

  const [payload, setPayload] = React.useState<CalcPayload | null>(null);
  const [deviation, setDeviation] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState<'pdf' | 'excel' | null>(null);
  const [mc, setMc] = React.useState<MonteCarloResult | null>(null);
  const [mcRunning, setMcRunning] = React.useState(false);
  const [incrementalRunning, setIncrementalRunning] = React.useState(false);
  const [customSpecsText, setCustomSpecsText] = React.useState<string>(
    JSON.stringify(DEFAULT_CUSTOM_SPECS, null, 2),
  );

  const handleIncremental = async () => {
    setIncrementalRunning(true);
    try {
      let specs: CustomScenarioSpecDTO[];
      try {
        const parsed = JSON.parse(customSpecsText);
        specs = Array.isArray(parsed) ? parsed : DEFAULT_CUSTOM_SPECS;
      } catch {
        message.warning('自定义情景 JSON 解析失败，已回退为默认三组');
        specs = DEFAULT_CUSTOM_SPECS;
      }
      const paramsDict = scenario?.params ?? draftParamsDict();
      const calc = await calculateApi({
        scenario_id: scenario ? scenarioId : undefined,
        params: scenario ? null : paramsDict,
        persist: false,
        options: {
          include_sensitivity: true,
          include_scenarios: true,
          include_crossover: true,
          include_joint: true,
          joint_vars: ['U', 'E_price'],
          include_custom_scenarios: true,
          custom_scenario_specs: specs,
        },
      });
      setPayload(calc.payload);
      setDeviation(calc.client_deviation);
      message.success('联合敏感性与自定义情景已生成');
    } catch (e) {
      message.error((e as Error).message || '增量分析失败');
    } finally {
      setIncrementalRunning(false);
    }
  };

  const handleMonteCarlo = async () => {
    setMcRunning(true);
    try {
      const paramsDict = scenario?.params ?? draftParamsDict();
      try {
        const res = await montecarloApi({ scenario_id: scenarioId, params: scenario ? null : paramsDict, n: 2000 });
        setMc(res as unknown as MonteCarloResult);
      } catch {
        // 后端不可达时回退到前端镜像计算（同样复用 financials 口径）
        const p = paramsFromDict(paramsDict as Record<string, unknown>);
        setMc(montecarloCompute(p, 2000));
      }
    } finally {
      setMcRunning(false);
    }
  };

  const handleExport = async (fmt: 'pdf' | 'excel') => {
    setExporting(fmt);
    try {
      await exportReport(scenarioId, fmt);
      message.success(`已开始下载 ${fmt.toUpperCase()} 报告`);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setExporting(null);
    }
  };

  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await latest.mutateAsync();
        if (!cancelled) setPayload(res.payload as unknown as CalcPayload);
      } catch {
        // 无历史记录 → 前端估算后交由后端权威重算
        try {
          const draftDict = draftParamsDict();
          const clientRes = await computeClient(draftDict);
          const clientKpis = (clientRes.payload as unknown as CalcPayload).kpis ?? [];
          const map: Record<string, string> = {};
          for (const k of clientKpis) if (k.value !== null && k.value !== undefined && k.kind !== 'text') map[k.key] = String(k.value);
          const calc = await calculateApi({ scenario_id: scenarioId, persist: false, client_kpis: map });
          if (!cancelled) {
            setPayload(calc.payload);
            setDeviation(calc.client_deviation);
          }
        } catch (e) {
          if (!cancelled) message.error((e as Error).message);
        }
      }
    };
    void load();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  // 注意：以下 useMemo 必须在 early return（!payload 分支）之前调用——React hooks 不允许
  // 在不同渲染间数量变化（否则抛 "Rendered more hooks than during the previous render"）。
  const paramsObj = React.useMemo(
    () => (payload ? paramsFromDict(payload.params) : null),
    [payload],
  );

  const hybridBlock = React.useMemo<React.ReactElement | null>(() => {
    if (!payload) return null;
    const hy = (scenario as { params?: { hybrid?: { enabled?: boolean; w_A?: string; w_B?: string; w_C?: string } } } | undefined)?.params?.hybrid;
    if (!hy || !hy.enabled) return null;
    const models = (payload.cost_models ?? []) as Array<{ plan: string; label: string; a: string; b: string }>;
    if (models.length < 3) return null;
    const [mA, mB, mC] = models.map((m) => new CurveModel(m.plan, m.label, m.a, m.b));
    const hybrid = buildHybrid([D(hy.w_A ?? '0'), D(hy.w_B ?? '0'), D(hy.w_C ?? '0')], [mA, mB, mC]);
    const demandQ = D((payload.derived as { Q_eq?: string })?.Q_eq ?? '0');
    const capacityWall = D((payload.derived as { Q_cap_M?: string })?.Q_cap_M ?? '0');
    const result = computeHybrid([mA, mB, mC], hybrid, demandQ, capacityWall);
    const chart = toChartPayload(result);
    const seg = result.recommended.find((s) => demandQ.gte(s.from_Q) && (s.to_Q === null || demandQ.lt(s.to_Q)));
    const conclusion = seg
      ? `当前需求下混合部署临界规模结论：推荐 ${seg.best_label}`
      : '混合部署四方案下包络已生成（当前需求不在任何活跃切换区间内）。';
    return (
      <Col xs={24}>
        <Card title="混合部署四方案成本线（自建 / 租用 / API / 混合）">
          <CrossoverChart crossover={chart} />
          <Alert style={{ marginTop: 12 }} type="success" showIcon title={conclusion} />
        </Card>
      </Col>
    );
  }, [scenario, payload]);

  if (!payload) {
    return (
      <Card>
        <Spin spinning description="权威重算中…" />
      </Card>
    );
  }

  const kpis = payload.kpis ?? [];
  const ordered = KEY_ORDER.map((k) => kpis.find((x) => x.key === k)).filter(Boolean) as Kpi[];
  const recommended = kpis.find((x) => x.key === 'recommended_plan');
  const warnings = payload.warnings ?? [];

  return (
    <div>
      {paramsObj?.pricing?.cost_benchmark ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="benchmark-source-note"
          title={
            <>
              本页「市场成本标杆」口径（C-1 单 token 亏损告警 / E-10 标杆告警）对标{' '}
              <Typography.Link
                href="https://inferencex.semianalysis.com"
                target="_blank"
                rel="noreferrer"
              >
                inferencex.semianalysis.com
              </Typography.Link>
              （InferenceX · SemiAnalysis）公开成本侧数据，每 7 天自动采集；采集时间与手动刷新见基准库页。
            </>
          }
        />
      ) : null}
      <Card
        title={
          <Space>
            <span>{scenario?.name ?? `方案 #${scenarioId}`}</span>
            <Tag color="blue">CNY·税前</Tag>
            {deviation !== null && Number(deviation) <= 0.001 ? (
              <Tag color="green">双端偏差 {(Number(deviation) * 100).toFixed(3)}%</Tag>
            ) : deviation !== null ? (
              <Tag color="red">双端偏差 {(Number(deviation) * 100).toFixed(3)}%</Tag>
            ) : null}
          </Space>
        }
        extra={
          <Space>
            <Button icon={<EditOutlined />} onClick={() => navigate(`/scenarios/${scenarioId}/edit`)}>编辑</Button>
            <Button icon={<SwapOutlined />} onClick={() => navigate(`/scenarios/${scenarioId}/compare`)}>多方案对比</Button>
            <Button icon={<HistoryOutlined />} onClick={() => navigate(`/scenarios/${scenarioId}/versions`)}>版本/审计</Button>
            <Button icon={<BarChartOutlined />} onClick={() => navigate(`/reports/${scenarioId}`)}>报告</Button>
            <Button icon={<FilePdfOutlined />} loading={exporting === 'pdf'} onClick={() => handleExport('pdf')}>导出PDF</Button>
            <Button icon={<FileExcelOutlined />} loading={exporting === 'excel'} onClick={() => handleExport('excel')}>导出Excel</Button>
            <Button icon={<BookOutlined />} onClick={() => openDrawer()}>公式溯源</Button>
            <Button icon={<ReloadOutlined />} onClick={() => { window.location.reload(); }}>刷新</Button>
          </Space>
        }
      >
        {recommended &&
          (() => {
            const status = recommended.status ?? 'no_solution';
            const note = recommended.note ?? '';
            if (status === 'loss') {
              return (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginBottom: 16 }}
                  title={`当前需求下推荐方案：${recommended.value}（成本最优，但当前定价下亏损）`}
                  description={note}
                />
              );
            }
            if (status === 'no_demand' || !recommended.value) {
              return (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  title="当前需求下暂无可行推荐方案"
                  description={note || '当前月需求量 ≤ 0，无法给出推荐方案。'}
                />
              );
            }
            return (
              <Alert
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
                title={`当前需求下推荐方案：${recommended.value}`}
              />
            );
          })()}
        {/* lg 段（1024–1200）每行 4 个：实测每列仅约 105px，放「118.20万 元」
            会被撑破；xl 及以上才放开到每行 6 个（列宽约 145px，足够）。 */}
        <Row gutter={[12, 12]}>
          {ordered.map((kpi) => (
            <Col xs={12} sm={8} md={6} lg={6} xl={4} key={kpi.key}>
              <StatCard
                title={kpi.label}
                value={formatKpiValue(kpi, '无解')}
                suffix={formatKpiUnit(kpi)}
                tone={kpiTone(kpi)}
                hint={`${kpi.label}（${kpi.unit || '—'}）`}
              />
            </Col>
          ))}
        </Row>
        {paramsObj && (
          <div style={{ marginTop: 16 }}>
            <HardwareBomCard params={paramsObj} />
          </div>
        )}
        {warnings.length > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 12 }}
            title="口径提示"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {warnings.map((w, i) => <li key={i} style={{ fontSize: 12 }}>{w}</li>)}
              </ul>
            }
          />
        )}
      </Card>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="现金流曲线">
            <CashflowChart rows={payload.financials?.cashflows_yearly ?? []} />
            {payload.financials?.financing ? (
              <FinancingDetail fin={payload.financials.financing} rows={payload.financials.cashflows ?? []} />
            ) : null}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="成本结构"><CostStructurePie payload={payload} /></Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="盈亏平衡"><BreakevenChart payload={payload} /></Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="敏感性龙卷风（目标：NPV）">
            {payload.sensitivity ? <TornadoChart sensitivity={payload.sensitivity} /> : <Typography.Text type="secondary">未生成</Typography.Text>}
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="三方案成本线对比（自建 / 租用 / API）">
            {payload.crossover ? <CrossoverChart crossover={payload.crossover} /> : <Typography.Text type="secondary">未生成</Typography.Text>}
          </Card>
        </Col>
        {hybridBlock}
        <Col xs={24}>
          <Card
            title="蒙特卡洛模拟（P2-4 · NPV/IRR 分布）"
            extra={
              <Button type="primary" loading={mcRunning} onClick={() => void handleMonteCarlo()}>
                运行蒙特卡洛（N=2000）
              </Button>
            }
          >
            {mc ? (
              <MonteCarloHistogram result={mc} />
            ) : (
              <Typography.Text type="secondary">
                点击「运行蒙特卡洛」对关键变量（U / 电价 / 租金 / API 价 / CAPEX / T_eff / r_w / 单价 / 需求量等）做三角分布随机抽样，
                复用财务口径统计 NPV/IRR 分布、分位数与 P(NPV&gt;0)。
              </Typography.Text>
            )}
          </Card>
        </Col>
        <Col xs={24}>
          <Card
            title="联合敏感性与自定义情景（P3 增量 · 确定性多因素边界 + 任意 K 组情景）"
            extra={
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={incrementalRunning}
                onClick={() => void handleIncremental()}
              >
                运行增量分析
              </Button>
            }
          >
            {payload.joint ? (
              <JointSensitivityChart joint={payload.joint} variableLabels={{ U: '有效利用率 U', E_price: '电价 E_price' }} />
            ) : (
              <Typography.Paragraph type="secondary">
                点击「运行增量分析」生成：① 联合敏感性（U + E_price 全因子 2² 网格 → NPV 联合 min/max/P5/P50/P95、
                一阶主效应与二阶交互，确定性、与蒙特卡洛严格区分）；② 自定义情景（任意 K 组参数覆盖并列 KPI）。
              </Typography.Paragraph>
            )}
            <Divider style={{ margin: '16px 0' }} />
            <Typography.Text strong>自定义情景定义（JSON：key / label / overrides）</Typography.Text>
            <Input.TextArea
              value={customSpecsText}
              onChange={(e) => setCustomSpecsText(e.target.value)}
              rows={6}
              style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 12 }}
            />
            {payload.custom_scenarios ? (
              <div style={{ marginTop: 16 }}>
                <CustomScenarioChart customScenarios={payload.custom_scenarios} metric="npv" />
              </div>
            ) : null}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

/** 自定义情景预设（与后端 gen_golden GV15 对齐：保守价 / 高电价 / 高杠杆）。 */
const DEFAULT_CUSTOM_SPECS: CustomScenarioSpecDTO[] = [
  { key: 'conservative_price', label: '保守价', overrides: { 'pricing.p_out': '27', 'pricing.p_in': '6.75' } },
  { key: 'high_elec', label: '高电价', overrides: { 'power.E_price': '1.5' } },
  { key: 'high_leverage', label: '高杠杆', overrides: { 'finance.debt_ratio': '0.6', 'finance.debt_rate': '0.06' } },
];

/** 融资结构明细：杠杆概览 + 最近 12 期利息/本金（P3 增量 ① 融资）。 */
function FinancingDetail({
  fin,
  rows,
}: {
  fin: import('@/shared/types').FinancingPayload;
  rows: import('@/shared/types').CashflowRow[];
}): React.ReactElement {
  const fmtMoney = (v: string | null | undefined): string => {
    if (v === null || v === undefined) return '无解';
    const num = Number(v);
    if (!Number.isFinite(num)) return '无解';
    if (Math.abs(num) >= 1e8) return `${(num / 1e8).toFixed(2)}亿`;
    if (Math.abs(num) >= 1e4) return `${(num / 1e4).toFixed(2)}万`;
    return num.toFixed(2);
  };
  const latest = rows.slice(-12).reverse();
  const columns = [
    { title: '期', dataIndex: 'period', width: 60 },
    { title: 'EBT（元）', dataIndex: 'ebt', render: (v: string) => fmtMoney(v) },
    { title: '利息（元）', dataIndex: 'interest', render: (v: string) => fmtMoney(v) },
    { title: '本金（元）', dataIndex: 'principal', render: (v: string) => fmtMoney(v) },
    { title: '税（元）', dataIndex: 'tax', render: (v: string) => fmtMoney(v) },
    { title: '净现金流（元）', dataIndex: 'net_cf', render: (v: string) => fmtMoney(v) },
  ];
  return (
    <div style={{ marginTop: 12 }}>
      <Descriptions
        size="small"
        column={{ xs: 2, sm: 3 }}
        items={[
          { key: 'debt_ratio', label: '资产负债率', children: `${(Number(fin.debt_ratio) * 100).toFixed(2)}%` },
          { key: 'debt', label: '债务本金', children: fmtMoney(fin.debt) },
          { key: 'equity', label: '权益投入', children: fmtMoney(fin.equity) },
          { key: 'interest_total', label: '利息合计', children: fmtMoney(fin.interest_total) },
          { key: 'principal_total', label: '本金合计', children: fmtMoney(fin.principal_total) },
          { key: 'interest_coverage', label: '利息覆盖倍数', children: fin.interest_coverage === null ? '无息' : Number(fin.interest_coverage).toFixed(2) },
          { key: 'roe', label: 'ROE（回馈倍数）', children: Number(fin.roe).toFixed(4) },
          { key: 'levered_npv', label: '杠杆后 NPV', children: fmtMoney(fin.levered_npv) },
          { key: 'levered_irr', label: '杠杆后 IRR', children: fin.levered_irr === null ? '无解' : `${(Number(fin.levered_irr) * 100).toFixed(2)}%` },
        ]}
      />
      <Table
        size="small"
        rowKey="period"
        pagination={false}
        dataSource={latest}
        columns={columns}
        style={{ marginTop: 8 }}
        title={() => <Typography.Text type="secondary">最近 12 期融资现金流明细（利息/本金）</Typography.Text>}
      />
    </div>
  );
}

/** 由三条成本线（a/b）+ 权重构造线性 CostModelLike。 */
class CurveModel implements CostModelLike {
  plan: string;
  label: string;
  private _a: Decimal;
  private _b: Decimal;
  constructor(plan: string, label: string, a: string, b: string) {
    this.plan = plan;
    this.label = label;
    this._a = D(a);
    this._b = D(b);
  }
  get a(): Decimal {
    return this._a;
  }
  get b(): Decimal {
    return this._b;
  }
  cost(q: Decimal): Decimal {
    return this._a.plus(this._b.times(D(q)));
  }
  unitCost(q: Decimal): Decimal {
    return safeDiv(this.cost(q), D(q));
  }
  name(): string {
    return this.label;
  }
  toDict(): { plan: string; label: string; a: Decimal; b: Decimal } {
    return { plan: this.plan, label: this.label, a: this._a, b: this._b };
  }
}
