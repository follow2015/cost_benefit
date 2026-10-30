/** 向导页：参数录入（7 组）+ 基准库预填 + 实时预览 + 保存/保存并计算。 */
import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Tabs, Button, Input, Space, Select, Typography, App as AntApp, Divider, Row, Col, Slider, Switch, Alert, Tag } from 'antd';
import { SaveOutlined, CalculatorOutlined, ExperimentOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useScenarioDraft, draftParamsDict } from '@/features/scenarios/stores/scenarioStore';
import { useScenario, useCreateScenario, useUpdateScenario } from '@/features/scenarios/hooks/useScenarios';
import { useBenchmarks } from '@/features/benchmarks/hooks/useBenchmarks';
import { getCostBenchmark } from '@/features/benchmarks/api/benchmarksApi';
import { GROUPS, readFieldValue } from '@/features/scenario-wizard/components/paramMeta';
import { ParamField } from '@/features/scenario-wizard/components/ParamField';
import { LivePreview } from '@/features/scenario-wizard/components/LivePreview';
import { paramsFromDict } from '@/features/calc/engine/codec';
import { compute as computeClient } from '@/features/calc/api/calcClient';
import { defaultParams } from '@/features/calc/engine/parameters';
import { recomputeSupportingCapex } from '@/features/calc/engine/supportingCost';
import { D, Decimal } from '@/features/calc/engine/decimalConfig';
import * as calcApi from '@/features/calc/api/calcApi';
import type { CalcPayload } from '@/shared/types';

export default function WizardPage(): React.ReactElement {
  const { id } = useParams();
  const scenarioId = id ? Number(id) : null;
  const navigate = useNavigate();
  const { message } = AntApp.useApp();

  const draft = useScenarioDraft();
  const { data: existing, isLoading: loadingScenario } = useScenario(scenarioId);
  const { data: bundle } = useBenchmarks();
  const createMut = useCreateScenario();
  const updateMut = useUpdateScenario();

  const [name, setName] = React.useState('');
  // 以 scenarioId 为键的加载守卫：同一方案只载入一次；切到「新建」(id=null) 时重置为默认。
  // 不能依赖整个 store（useScenarioDraft() 返回全量状态），否则 load 触发的 store 更新会
  // 改变 draft 引用并让 effect 无限重跑（Maximum update depth exceeded）。
  const loadedIdRef = React.useRef<number | null | undefined>(undefined);

  // 载入现有方案或默认参数
  React.useEffect(() => {
    if (scenarioId != null && existing) {
      if (loadedIdRef.current === scenarioId) return;
      loadedIdRef.current = scenarioId;
      useScenarioDraft.getState().load({
        id: scenarioId,
        name: existing.name,
        description: existing.description,
        version: existing.version,
        params: paramsFromDict(existing.params),
      });
      setName(existing.name);
    } else if (scenarioId == null) {
      if (loadedIdRef.current === null) return;
      loadedIdRef.current = null;
      const state = useScenarioDraft.getState();
      if (state.dirty) {
        // 外部回填（硬件反选「一键应用」/ 配置清单「应用此估算方案」等）已写入草稿：
        // 跳过默认参数覆盖，并把回填的方案名/摘要同步到表单。
        setName(state.name);
        return;
      }
      useScenarioDraft.getState().load({
        id: null,
        name: '',
        description: '',
        version: 1,
        params: defaultParams(),
      });
    }
  }, [scenarioId, existing]);

  const tabItems = GROUPS.map((group) => ({
    key: String(group.key),
    label: group.label,
    children: (
      <Row gutter={[16, 8]}>
        {group.key === 'bench' ? (
          <BenchPrefill />
        ) : null}
        {group.key === 'hw' ? (
          <Col span={24}>
            <HardwareInvestmentSummary />
          </Col>
        ) : null}
        {group.key === 'pricing' ? (
          <Col span={24}>
            <CostBenchmarkCalibration />
            <ScenarioPresetE9 />
          </Col>
        ) : null}
        {group.fields.map((meta) => (
          <Col span={12} key={meta.path}>
            <ParamField
              meta={meta}
              value={readFieldValue(draft.params, meta.path)}
              onChange={(v) => {
                draft.setField(group.key, meta.path.split('.')[1], v);
                // 硬件反选来源联动：改卡数 ⇒ 按同一口径重算配套 CAPEX（存储+组网）
                if (group.key === 'hw' && meta.path === 'hw.N_gpu' && typeof v === 'number') {
                  const fabric = draft.params.hw.supporting_fabric;
                  if (fabric) {
                    const newAux = recomputeSupportingCapex(draft.params, D(v));
                    if (newAux !== null && !newAux.eq(draft.params.hw.P_aux)) {
                      draft.setField('hw', 'P_aux', newAux);
                      message.info(
                        `配套 CAPEX 已随卡数联动重算：${newAux.toNumber().toLocaleString()} 元（fabric=${fabric}，存储+组网）`,
                      );
                    }
                  }
                }
              }}
            />
          </Col>
        ))}
      </Row>
    ),
  }));

  const handleSave = async (withCalc: boolean) => {
    const paramsDict = draftParamsDict();
    if (!name.trim()) {
      message.warning('请填写方案名称');
      return;
    }
    let newId: number | undefined;
    try {
      if (scenarioId) {
        await updateMut.mutateAsync({ id: scenarioId, payload: { name, description: draft.description, params: paramsDict } });
        message.success('已保存');
      } else {
        const created = await createMut.mutateAsync({ name, description: draft.description, params: paramsDict });
        newId = created.id;
        message.success('已创建');
      }
      if (withCalc) {
        // 前端估算 KPI 作为 client_kpis，交由后端权威重算并比对偏差
        const clientRes = await computeClient(paramsDict);
        const clientKpis = (clientRes.payload as unknown as CalcPayload).kpis ?? [];
        const clientKpiMap: Record<string, string> = {};
        for (const k of clientKpis) {
          if (k.value !== null && k.value !== undefined && k.kind !== 'text') clientKpiMap[k.key] = String(k.value);
        }
        // 新建场景时用 createMut 返回的 id 作为 scenario_id，确保后端落库并回传正确导航目标
        const targetId = scenarioId ?? newId;
        const calc = await calcApi.calculate({ scenario_id: targetId, params: targetId ? undefined : paramsDict, persist: true, client_kpis: clientKpiMap });
        const dev = calc.client_deviation;
        if (dev !== null && dev !== undefined) {
          const devNum = Number(dev);
          if (devNum <= 0.001) message.success(`双端一致，最大偏差 ${(devNum * 100).toFixed(3)}%`);
          else message.warning(`双端偏差 ${(devNum * 100).toFixed(3)}%，请关注`);
        }
        navigate(`/scenarios/${targetId ?? calc.scenario_id}`);
      } else {
        navigate(scenarioId ? `/scenarios/${scenarioId}` : '/');
      }
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    }
  };

  return (
    <div>
      <Card
        title={scenarioId ? '编辑测算方案' : '新建测算方案'}
        extra={
          <Space>
            <Button
              icon={<ExperimentOutlined />}
              onClick={() => navigate('/builder')}
              title="选模型 → 量化对比 → 自动生成完整 BOM 与方案"
            >
              方案构建向导
            </Button>
            <Button icon={<SaveOutlined />} onClick={() => handleSave(false)} loading={createMut.isPending || updateMut.isPending}>
              保存
            </Button>
            <Button type="primary" icon={<CalculatorOutlined />} onClick={() => handleSave(true)} loading={createMut.isPending || updateMut.isPending}>
              保存并计算
            </Button>
          </Space>
        }
      >
        <Space orientation="vertical" style={{ width: '100%' }} size={12}>
          <Space.Compact style={{ maxWidth: 520 }}>
            <Input style={{ width: 96 }} value="方案名称" disabled />
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：H100×8 自建 vs 租赁对比"
            />
          </Space.Compact>
          <Input.TextArea
            value={draft.description}
            onChange={(e) => draft.setDescription(e.target.value)}
            rows={2}
            placeholder="可选：业务背景、假设说明"
            style={{ maxWidth: 720 }}
          />
          {loadingScenario && scenarioId ? <Typography.Text>加载中…</Typography.Text> : null}
        </Space>
      </Card>

      <HybridPanel />


      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} lg={15}>
          <Card>
            <Tabs items={tabItems} />
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <LivePreview />
        </Col>
      </Row>
    </div>
  );
}

/** 基准库预填：选中后写入 bench.* 并补全相关数值字段。 */
function BenchPrefill(): React.ReactElement {
  const { data: bundle } = useBenchmarks();
  const draft = useScenarioDraft();
  if (!bundle) return <Col span={24}><Typography.Text type="secondary">加载基准库中…</Typography.Text></Col>;

  const applyGpu = (gpuId: number) => {
    const gpu = bundle.gpus.find((g) => g.id === gpuId);
    if (!gpu) return;
    draft.setField('bench', 'gpu_id', gpuId);
    if (Number(gpu.price_cny)) draft.setField('hw', 'P_gpu', D(gpu.price_cny));
    if (Number(gpu.tdp_w)) draft.setField('power', 'TDP', D(gpu.tdp_w));
  };
  const applyModel = (modelId: number) => {
    const m = bundle.models.find((x) => x.id === modelId);
    if (!m) return;
    draft.setField('bench', 'model_id', modelId);
    if (m.throughput_effective) draft.setField('perf', 'T_eff', D(m.throughput_effective));
    if (m.throughput_prefill) draft.setField('perf', 'T_pf', D(m.throughput_prefill));
    if (m.throughput_decode) draft.setField('perf', 'T_dc', D(m.throughput_decode));
    if (m.k_ratio) draft.setField('perf', 'k_benchmark', D(m.k_ratio));
  };
  const applyCloud = (cloudId: number) => {
    const c = bundle.cloud_prices.find((x) => x.id === cloudId);
    if (!c) return;
    draft.setField('bench', 'cloud_id', cloudId);
    if (Number(c.price_cny_per_hour)) draft.setField('pricing', 'Rent_gpu', D(c.price_cny_per_hour));
  };
  const applyApi = (apiId: number) => {
    const a = bundle.api_prices.find((x) => x.id === apiId);
    if (!a) return;
    draft.setField('bench', 'api_id', apiId);
    if (Number(a.price_in_cny_per_m)) draft.setField('pricing', 'API_in', D(a.price_in_cny_per_m));
    if (Number(a.price_out_cny_per_m)) draft.setField('pricing', 'API_out', D(a.price_out_cny_per_m));
  };

  return (
    <Col span={24}>
      <Card size="small" title="基准库预填（可选）" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            style={{ width: 220 }}
            placeholder="选择 GPU"
            allowClear
            value={draft.params.bench.gpu_id ?? undefined}
            options={bundle.gpus.map((g) => ({ value: g.id, label: `${g.name}（${g.vendor || '—'}）` }))}
            onChange={applyGpu}
          />
          <Select
            style={{ width: 220 }}
            placeholder="选择模型"
            allowClear
            value={draft.params.bench.model_id ?? undefined}
            options={bundle.models.map((m) => ({ value: m.id, label: `${m.name}（${m.params_b}B）` }))}
            onChange={applyModel}
          />
          <Select
            style={{ width: 220 }}
            placeholder="选择云租赁价"
            allowClear
            value={draft.params.bench.cloud_id ?? undefined}
            options={bundle.cloud_prices.map((c) => ({ value: c.id, label: `${c.provider} ${c.gpu_code}` }))}
            onChange={applyCloud}
          />
          <Select
            style={{ width: 220 }}
            placeholder="选择 API 价"
            allowClear
            value={draft.params.bench.api_id ?? undefined}
            options={bundle.api_prices.map((a) => ({ value: a.id, label: `${a.provider} ${a.model_code}` }))}
            onChange={applyApi}
          />
        </Space>
      </Card>
      <Divider style={{ margin: '8px 0' }} />
    </Col>
  );
}

/** 硬件投资汇总：GPU 卡投资 + 辅助设备 CAPEX（存储/组网配套）= 总硬件投资（derive CAPEX 口径）。 */
function HardwareInvestmentSummary(): React.ReactElement {
  const draft = useScenarioDraft();
  const toNum = (v: unknown): number => {
    if (v === null || v === undefined || v === '') return 0;
    return v instanceof Decimal ? v.toNumber() : Number(v);
  };
  const gpuInv =
    toNum(readFieldValue(draft.params, 'hw.N_gpu')) *
    toNum(readFieldValue(draft.params, 'hw.P_gpu'));
  const aux = toNum(readFieldValue(draft.params, 'hw.P_aux'));
  const total = gpuInv + aux;
  const fmt = (n: number): string => n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 12 }}
      title={`硬件投资汇总：GPU 卡投资 ${fmt(gpuInv)} 元 + 辅助设备 CAPEX ${fmt(aux)} 元 = 总硬件投资 ${fmt(total)} 元`}
    />
  );
}

/** S-3/C-1 一键校准：选项与 scripts/seed_inferencex.py 的 InferenceX 数据保持一致。 */
const INFERENCEX_MODELS = [
  { value: 'deepseek-v4-pro', label: 'DeepSeek-V4-Pro（1.6T MoE/49B 激活）' },
  { value: 'kimi-k3', label: 'Kimi-K3（2.8T MoE/104B 激活）' },
  { value: 'minimax-m3', label: 'MiniMax-M3 428B' },
  { value: 'glm-5.3', label: 'GLM-5.3 743B MoE' },
  { value: 'qwen-3.5-397b-a17b', label: 'Qwen-3.5 397B-A17B（激活 17B）' },
];
const INFERENCEX_HARDWARE = [
  { value: 'B200', label: 'NVIDIA B200' },
  { value: 'B300', label: 'NVIDIA B300' },
  { value: 'GB200_NVL72', label: 'NVIDIA GB200 NVL72' },
  { value: 'GB300_NVL72', label: 'NVIDIA GB300 NVL72' },
  { value: 'MI355X', label: 'AMD MI355X' },
];
const INFERENCEX_SCENARIOS = [
  { value: 'AgentX', label: 'AgentX（长上下文 Agent）' },
  { value: '8K/1K', label: '8K/1K（短上下文）' },
];

/** 从 InferenceX 校准市场成本标杆：解析 → 填入 pricing.cost_benchmark（触发 C-1 双口径对标）。 */
function CostBenchmarkCalibration(): React.ReactElement {
  const draft = useScenarioDraft();
  const { message } = AntApp.useApp();
  const [modelCode, setModelCode] = React.useState<string | undefined>(undefined);
  const [hardwareCode, setHardwareCode] = React.useState<string | undefined>(undefined);
  const [scenario, setScenario] = React.useState<string>('AgentX');
  const [loading, setLoading] = React.useState(false);

  const fxVal = draft.params.pricing.fx_usd_cny;
  const currentCb = draft.params.pricing.cost_benchmark;

  const handleCalibrate = async () => {
    if (!modelCode || !hardwareCode) {
      message.warning('请先选择模型与硬件');
      return;
    }
    setLoading(true);
    try {
      const res = await getCostBenchmark({
        model_code: modelCode,
        hardware_code: hardwareCode,
        scenario,
        fx: fxVal != null ? fxVal.toString() : '7.2',
      });
      if (res.found && res.cost_benchmark_cny_per_mtok != null) {
        draft.setField('pricing', 'cost_benchmark', D(res.cost_benchmark_cny_per_mtok));
        message.success(
          `已校准市场成本标杆：${res.cost_benchmark_cny_per_mtok} 元/Mtok（${modelCode} / ${hardwareCode} / ${scenario}；汇率 ${res.fx_usd_cny ?? '7.2'}）`,
        );
      } else {
        message.warning(res.message ?? '基准库中无该组合的成本数据（请先运行 python -m scripts.seed_inferencex）');
      }
    } catch (e) {
      message.error((e as Error).message || '校准失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card size="small" title="从 InferenceX 校准市场成本标杆（C-1 双口径对标）" style={{ marginBottom: 12 }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="用途"
        description="按「模型×硬件×场景」从 InferenceX（SemiAnalysis）公开基准解析市场公允成本（元/Mtok），一键填入「市场成本标杆」，触发 ROI 双口径（售价−自建 vs 售价−市场）对标与亏损告警。该标杆为成本侧口径，非对外售价。"
      />
      <Space wrap>
        <Select style={{ width: 260 }} placeholder="选择模型" allowClear value={modelCode} options={INFERENCEX_MODELS} onChange={setModelCode} />
        <Select style={{ width: 200 }} placeholder="选择硬件" allowClear value={hardwareCode} options={INFERENCEX_HARDWARE} onChange={setHardwareCode} />
        <Select style={{ width: 200 }} value={scenario} options={INFERENCEX_SCENARIOS} onChange={setScenario} />
        <Button type="primary" icon={<ExperimentOutlined />} loading={loading} onClick={handleCalibrate}>
          一键校准
        </Button>
      </Space>
      {currentCb != null ? (
        <Alert
          type="success"
          showIcon
          style={{ marginTop: 12 }}
          title={`当前市场成本标杆：${currentCb.toString()} 元/Mtok（已填入，结果页将展示双口径毛利与亏损告警）`}
        />
      ) : (
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          尚未设置成本标杆：默认不启用双口径对标。
        </Typography.Text>
      )}
    </Card>
  );
}

/** E-9 AgentX 长上下文场景预设：一键套用 InferenceX 真实负载画像（rho≈200 / h≈0.96 / Ctx≈128k）。
 *  与 C-4 长上下文成本曲线、E-10 标杆告警环联动；与 M-17 来源徽标共用图例。 */
function ScenarioPresetE9(): React.ReactElement {
  const draft = useScenarioDraft();
  const { message } = AntApp.useApp();
  const applyAgentX = () => {
    draft.setField('demand', 'rho', D(200));
    draft.setField('demand', 'h', D('0.96'));
    draft.setField('perf', 'Ctx', D(128000));
    message.success('已套用 AgentX 长上下文预设（rho=200, h=0.96, Ctx=128k）');
  };
  const applyShortCtx = () => {
    draft.setField('demand', 'rho', D(1).div(D(3)));
    draft.setField('demand', 'h', D('0.20'));
    draft.setField('perf', 'Ctx', D(8192));
    message.success('已套用 8K/1K 短上下文预设');
  };
  return (
    <Card size="small" title="场景预设（E-9 AgentX 长上下文画像）" style={{ marginBottom: 12 }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="用途"
        description="按 InferenceX v1.0 数据集（393 会话）真实负载一键套用场景画像：AgentX 输入中位 142k、缓存命中 95–98%、输入:输出≈200:1。套用后 C-4 长上下文成本曲线上浮、E-10 标杆告警环与 C-1 双口径对标自动联动。"
      />
      <Space wrap>
        <Button icon={<ThunderboltOutlined />} onClick={applyAgentX}>AgentX 长上下文预设</Button>
        <Button onClick={applyShortCtx}>8K/1K 短上下文预设</Button>
      </Space>
      <div style={{ marginTop: 10, fontSize: 12 }}>
        <Tag color="green">基准库</Tag> 来自 InferenceX 基准库的取值
        <Tag color="default" style={{ marginLeft: 8 }}>估算</Tag> 默认待核实的估算值（建议用实测/基准库覆盖）
      </div>
    </Card>
  );
}

/** P2-3 混合部署面板：开关 + 三权重滑块（归一化，权重和=1）。 */
function HybridPanel(): React.ReactElement {
  const draft = useScenarioDraft();
  const hybrid = draft.params.hybrid;

  const setEnabled = (v: boolean) => draft.setField('hybrid', 'enabled', v);

  const handleWeight = (idx: 0 | 1 | 2, pct: number): void => {
    const others = [0, 1, 2].filter((i) => i !== idx);
    const wThis = D(Math.max(0, Math.min(100, pct))).div(100);
    const otherVals = others.map((i) => (i === 0 ? hybrid.w_A : i === 1 ? hybrid.w_B : hybrid.w_C));
    const othersSum = otherVals[0].plus(otherVals[1]);
    const remain = new Decimal(1).minus(wThis);
    let newOthers: [Decimal, Decimal];
    if (othersSum.lte(new Decimal(0))) {
      newOthers = [remain.div(2), remain.div(2)];
    } else {
      newOthers = [
        remain.times(otherVals[0].div(othersSum)),
        remain.times(otherVals[1].div(othersSum)),
      ];
    }
    const next: [Decimal, Decimal, Decimal] = [wThis, wThis, wThis];
    others.forEach((i, k) => {
      next[i] = newOthers[k];
    });
    draft.setField('hybrid', 'w_A', next[0]);
    draft.setField('hybrid', 'w_B', next[1]);
    draft.setField('hybrid', 'w_C', next[2]);
  };

  const toPct = (d: Decimal): number => Math.round(Number(d.times(100)));

  return (
    <Card style={{ marginTop: 16 }} size="small" title="混合部署（P2-3 第四方案）">
      <Space orientation="vertical" style={{ width: '100%' }} size={8}>
        <Space>
          <Switch checked={hybrid.enabled} onChange={setEnabled} />
          <Typography.Text>启用混合部署（按权重组合 自建/租用/API 为方案D）</Typography.Text>
        </Space>
        {hybrid.enabled ? (
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Typography.Text>方案A 自建 权重：{toPct(hybrid.w_A)}%</Typography.Text>
              <Slider min={0} max={100} value={toPct(hybrid.w_A)} onChange={(v) => handleWeight(0, v)} />
            </Col>
            <Col xs={24} md={8}>
              <Typography.Text>方案B 租用 权重：{toPct(hybrid.w_B)}%</Typography.Text>
              <Slider min={0} max={100} value={toPct(hybrid.w_B)} onChange={(v) => handleWeight(1, v)} />
            </Col>
            <Col xs={24} md={8}>
              <Typography.Text>方案C API 权重：{toPct(hybrid.w_C)}%</Typography.Text>
              <Slider min={0} max={100} value={toPct(hybrid.w_C)} onChange={(v) => handleWeight(2, v)} />
            </Col>
          </Row>
        ) : null}
        <Alert
          type="info"
          showIcon
          title="混合方案满足统一线性化 C_hybrid(Q)=a_h+b_h·Q，结果页将叠加第四方案成本线与临界规模结论。"
        />
      </Space>
    </Card>
  );
}
