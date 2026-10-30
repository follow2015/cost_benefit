/** 向导实时预览面板：基于 draft 参数走 Web Worker 重算，展示 KPI + 口径提示。 */
import React from 'react';
import { Card, Row, Col, Alert, Tag, Spin, Typography } from 'antd';
import { useScenarioDraft } from '@/features/scenarios/stores/scenarioStore';
import { compute, debounceCompute } from '@/features/calc/api/calcClient';
import { paramsToDict } from '@/features/calc/engine/codec';
import { formatKpiUnit, formatKpiValue, PROFIT_KPIS } from '@/shared/ui/formatKpi';
import { KpiStat } from '@/shared/ui/KpiStat';
import type { CalcPayload, Kpi } from '@/shared/types';

const KEY_ORDER = ['cost_per_m', 'npv', 'irr', 'roi', 'tco', 'payback_static', 'payback_discounted', 'U_be', 'gross_margin', 'gm_pct', 'rev_per_gpu_day', 'cost_per_gpu_day', 'token_per_kwh', 'sla_provision_monthly', 'idle_power_cost', 'learning_terminal_factor', 'deferred_revenue', 'rev_recognized_monthly', 'cash_prepaid'];

export function LivePreview(): React.ReactElement {
  const params = useScenarioDraft((s) => s.params);
  const [payload, setPayload] = React.useState<CalcPayload | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [duration, setDuration] = React.useState(0);

  const run = React.useCallback(
    (dict: Record<string, unknown>) => {
      setLoading(true);
      compute(dict)
        .then((res) => {
          setPayload(res.payload as unknown as CalcPayload);
          setDuration(res.duration_ms);
        })
        .catch((e) => {
          // 任何计算失败都不应让预览永久转圈。
          console.error('[LivePreview] compute failed, falling back to empty', e);
          setPayload(null);
        })
        .finally(() => {
          setLoading(false);
        });
    },
    [],
  );

  const debounced = React.useMemo(
    () => debounceCompute((dict: Record<string, unknown>) => run(dict), 500),
    [run],
  );

  React.useEffect(() => {
    debounced(paramsToDict(params));
  }, [params, debounced]);

  const kpis = payload?.kpis ?? [];
  const ordered = KEY_ORDER.map((k) => kpis.find((x) => x.key === k)).filter(Boolean) as Kpi[];
  const recommended = kpis.find((x) => x.key === 'recommended_plan');
  const warnings = payload?.warnings ?? [];

  return (
    <Card
      title="实时预览（前端引擎）"
      extra={<Tag color={duration > 0 && duration <= 500 ? 'green' : 'default'}>{duration}ms</Tag>}
      style={{ position: 'sticky', top: 16 }}
    >
      <Spin spinning={loading}>
        <Row gutter={[12, 12]}>
          {ordered.map((kpi) => (
            <Col span={12} key={kpi.key}>
              <KpiStat
                label={kpi.label}
                value={formatKpiValue(kpi, '—')}
                unit={formatKpiUnit(kpi)}
                tone={PROFIT_KPIS.has(kpi.key) ? 'up' : 'neutral'}
                hint={`${kpi.label}（${kpi.unit || '—'}）`}
              />
            </Col>
          ))}
        </Row>
        {recommended && recommended.value && (
          <Alert
            type="success"
            showIcon
            style={{ marginTop: 12 }}
            title={`当前需求下推荐方案：${recommended.value}`}
          />
        )}
        {warnings.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Typography.Text type="warning">口径提示：</Typography.Text>
            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
              {warnings.slice(0, 4).map((w, i) => (
                <li key={i} style={{ fontSize: 12 }}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </Spin>
    </Card>
  );
}
