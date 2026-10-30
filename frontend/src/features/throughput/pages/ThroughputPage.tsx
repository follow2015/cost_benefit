/** 吞吐计算器（P2-1 / REQ-17）：输入模型规模 / 量化 / batch + SLA，推导可用 batch 上限、
 *  prefill/decode 吞吐区间与折算系数 k；提供「一键回填 Wizard」写入 T_eff/T_pf/T_dc。 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Row, Col, InputNumber, Select, Button, Statistic, Alert, Tag, Space, Typography, Divider,
} from 'antd';
import { ThunderboltOutlined, ImportOutlined } from '@ant-design/icons';
import { D, Decimal, ZERO } from '@/features/calc/engine/decimalConfig';
import { defaultParams } from '@/features/calc/engine/parameters';
import { deriveThroughputCalc } from '@/features/calc/engine/throughput';
import { useScenarioDraft } from '@/features/scenarios/stores/scenarioStore';
import type { ScenarioParams } from '@/features/calc/engine/parameters';

const QUANT_OPTIONS = ['FP8', 'FP16', 'BF16', 'INT8', 'INT4'].map((q) => ({ value: q, label: q }));

function num(v: string): Decimal {
  return D(v === '' || v === undefined ? 0 : v);
}

export default function ThroughputPage(): React.ReactElement {
  const navigate = useNavigate();
  const [mParam, setMParam] = React.useState<string>('70');
  const [quant, setQuant] = React.useState<string>('FP8');
  const [bMax, setBMax] = React.useState<string>('64');
  const [slaTtft, setSlaTtft] = React.useState<string>('500');
  const [slaTpot, setSlaTpot] = React.useState<string>('50');
  const [kOverride, setKOverride] = React.useState<string>('');

  const params: ScenarioParams = React.useMemo(() => {
    const base = defaultParams();
    return {
      ...base,
      perf: {
        ...base.perf,
        M_param: num(mParam),
        quant,
        B_max: num(bMax),
        SLA_ttft: num(slaTtft),
        SLA_tpot: num(slaTpot),
        k_override: kOverride === '' ? null : num(kOverride),
      },
    };
  }, [mParam, quant, bMax, slaTtft, slaTpot, kOverride]);

  const result = React.useMemo(() => deriveThroughputCalc(params), [params]);

  const handleFill = () => {
    const draft = useScenarioDraft.getState();
    draft.setField('perf', 'T_eff', result.T_eff_suggestion);
    draft.setField('perf', 'T_pf', result.T_pf_mid);
    draft.setField('perf', 'T_dc', result.T_dc_mid);
    draft.setField('perf', 'B_max', result.B_max);
    draft.setField('perf', 'SLA_ttft', result.B_limit.gt(ZERO) ? num(slaTtft) : result.B_limit);
    navigate('/scenarios/new');
  };

  return (
    <div>
      <Card title={
        <Space>
          <ThunderboltOutlined />
          <span>吞吐计算器（REQ-17）</span>
          <Tag color="blue">SLA 越严 → batch 越小 → 有效吞吐越低</Tag>
        </Space>
      }>
        <Row gutter={16}>
          <Col xs={24} md={10}>
            <Card type="inner" title="模型与 SLA 输入">
              <Row gutter={[12, 8]}>
                <Col span={12}>
                  <Typography.Text>模型规模 (B)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} value={mParam as never} onChange={(v: number | string | null) => setMParam(String(v ?? 0))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>量化</Typography.Text>
                  <Select style={{ width: '100%' }} value={quant} options={QUANT_OPTIONS} onChange={setQuant} />
                </Col>
                <Col span={12}>
                  <Typography.Text>并发 batch 上限</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} value={bMax as never} onChange={(v: number | string | null) => setBMax(String(v ?? 0))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>SLA TTFT (ms)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} value={slaTtft as never} onChange={(v: number | string | null) => setSlaTtft(String(v ?? 0))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>SLA TPOT (ms)</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={1} value={slaTpot as never} onChange={(v: number | string | null) => setSlaTpot(String(v ?? 0))} />
                </Col>
                <Col span={12}>
                  <Typography.Text>k 实测（可选）</Typography.Text>
                  <InputNumber style={{ width: '100%' }} min={0} value={kOverride ? Number(kOverride) : null} onChange={(v: number | string | null) => setKOverride(v === null || v === undefined ? '' : String(v))} />
                </Col>
              </Row>
              <Divider style={{ margin: '14px 0' }} />
              <Button type="primary" icon={<ImportOutlined />} block onClick={handleFill}>
                一键回填 Wizard（写入 T_eff / T_pf / T_dc）
              </Button>
            </Card>
          </Col>
          <Col xs={24} md={14}>
            <Card type="inner" title="推导结果">
              <Row gutter={[12, 12]}>
                <Col xs={12} sm={8}>
                  <Statistic title="可用 batch 上限" value={result.B_limit.toFixed(0)} suffix={`/ ${result.B_max.toFixed(0)}`} />
                </Col>
                <Col xs={12} sm={8}>
                  <Statistic title="折算系数 k" value={result.k.toFixed(4)} />
                </Col>
                <Col xs={12} sm={8}>
                  <Statistic title="k 来源" valueRender={() => <Tag>{result.k_source_label}</Tag>} />
                </Col>
                <Col xs={24} sm={12}>
                  <Statistic title="Prefill 输入吞吐 T_pf (tok/s)" value={result.T_pf_mid.toFixed(0)} />
                  <Typography.Text type="secondary">
                    [{result.T_pf_low.toFixed(0)} , {result.T_pf_high.toFixed(0)}]
                  </Typography.Text>
                </Col>
                <Col xs={24} sm={12}>
                  <Statistic title="Decode 输出吞吐 T_dc (tok/s)" value={result.T_dc_mid.toFixed(0)} />
                  <Typography.Text type="secondary">
                    [{result.T_dc_low.toFixed(0)} , {result.T_dc_high.toFixed(0)}]
                  </Typography.Text>
                </Col>
                <Col xs={24}>
                  <Statistic title="建议回填有效吞吐 T_eff (tok/s)" value={result.T_eff_suggestion.toFixed(0)} />
                </Col>
              </Row>
              {result.warnings.length > 0 && (
                <Alert style={{ marginTop: 12 }} type="warning" showIcon title="提示" description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {result.warnings.map((w, i) => <li key={i} style={{ fontSize: 12 }}>{w}</li>)}
                  </ul>
                } />
              )}
              {result.k_source === 'throughput_ratio' && (
                <Alert style={{ marginTop: 12 }} type="info" showIcon title="k = T_dc / T_pf（吞吐比来源）" />
              )}
            </Card>
          </Col>
        </Row>
      </Card>
    </div>
  );
}
