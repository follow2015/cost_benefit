/**
 * P1/P2 引擎增强前端镜像单测（Phase 6）：C-4 / E-5 / E-6 / E-9 / E-10。
 * 与后端 `app/calc/__tests__/test_p1p2_enhancements.py` 口径一致，保证双端零漂移。
 * 黄金向量（默认参数）须零回归：所有增强在默认（短链 / kv=0 / spec=none / 无标杆）下数值不变。
 */

import { describe, it, expect } from 'vitest';
import { D, Decimal } from '../decimalConfig';
import {
  agentxParams,
  defaultParams,
  derive,
  AGENTX_PRESET_RHO,
  AGENTX_PRESET_H,
  AGENTX_PRESET_CTX,
  SHORT_CTX_PRESET_CTX,
} from '../parameters';
import {
  kvCacheBatchLimit,
  effectiveBMax,
  availableBatchLimit,
  deriveThroughputCalc,
} from '../throughput';
import { compute, contextUpliftFactor } from '../unitCost';
import { computeCore } from '../engine';

function withPerf(overrides: Record<string, unknown>) {
  const params = defaultParams();
  const perf = { ...params.perf, ...overrides };
  return { ...params, perf };
}

describe('C-4 长上下文成本曲线', () => {
  it('短链（Ctx≤8192）uplift=1（黄金向量零回归）', () => {
    expect(contextUpliftFactor(defaultParams()).toString()).toBe('1');
  });

  it('AgentX uplift 严格按公式 = 1 + K·(Ctx/8192−1)·(1−h)', () => {
    const uplift = contextUpliftFactor(agentxParams());
    // (128000/8192 − 1)·(1−0.96) = 14.625·0.04 = 0.585 ⇒ 1.585
    expect(uplift.toString()).toBe('1.585');
  });

  it('AgentX 成本高于短链（仅经 uplift 上浮，同产出假设）', () => {
    const dDefault = derive(defaultParams());
    const dAgentx = derive(agentxParams());
    const ucDefault = compute(defaultParams(), dDefault);
    const ucAgentx = compute(agentxParams(), dAgentx);
    expect(ucAgentx.context_uplift.gt(new Decimal('1'))).toBe(true);
    expect(ucAgentx.cost_per_m_capacity.gt(ucDefault.cost_per_m_capacity)).toBe(true);
    const ratio = ucAgentx.cost_per_m_capacity.div(ucDefault.cost_per_m_capacity);
    expect(ratio.toString()).toBe(ucAgentx.context_uplift.toString());
  });
});

describe('E-5 KV cache 容量约束', () => {
  it('默认 kv/vram=0 ⇒ 回退 B_max（黄金向量零回归）', () => {
    const base = defaultParams();
    expect(kvCacheBatchLimit(base.perf)).toBeNull();
    expect(effectiveBMax(base.perf).toString()).toBe(base.perf.B_max.toString());
  });

  it('充足显存：vram=400, Mem_w=140, kv=0.001/token, Ctx=8192 ⇒ floor(260/8.192)=31', () => {
    const roomy = withPerf({ vram_total_gb: D(400), kv_cache_per_token_gb: D('0.001'), B_max: D(64) });
    const kv = kvCacheBatchLimit(roomy.perf as any);
    expect(kv?.toString()).toBe('31');
    expect(effectiveBMax(roomy.perf as any).toString()).toBe('31');
  });

  it('权重占满显存（vram<Mem_w）⇒ 仅能承载极小 batch（floor→1）', () => {
    const tight = withPerf({ vram_total_gb: D(80), kv_cache_per_token_gb: D('0.001') });
    expect(effectiveBMax(tight.perf as any).toString()).toBe('1');
  });

  it('KV 约束经 deriveThroughputCalc 主入口生效（B_max 收紧）', () => {
    const roomy = withPerf({ vram_total_gb: D(400), kv_cache_per_token_gb: D('0.001'), B_max: D(64) });
    const result = deriveThroughputCalc(roomy as any);
    expect(result.B_max.toString()).toBe('31');
    expect(result.B_limit.lte(new Decimal('31'))).toBe(true);
  });
});

describe('E-6 投机解码 SLA 放松', () => {
  it('spec=none（默认）数值与修订前一致（spec_mult=1.0，黄金向量零回归）', () => {
    const none = withPerf({ B_max: D(64), SLA_ttft: D(500), SLA_tpot: D(50) });
    const limit = availableBatchLimit(none.perf.B_max as Decimal, none.perf.SLA_ttft as Decimal, none.perf.SLA_tpot as Decimal, 'none');
    expect(limit.toString()).toBe('32');
  });

  it('TTFT 宽松使 TPOT 绑定时，EAGLE 的 batch 上限 > none（放松）', () => {
    const none = availableBatchLimit(D(64), D(1000), D(50), 'none');
    const eagle = availableBatchLimit(D(64), D(1000), D(50), 'EAGLE');
    expect(eagle.gte(none)).toBe(true);
    expect(eagle.gt(none)).toBe(true);
    const noneCalc = deriveThroughputCalc(withPerf({ B_max: D(64), SLA_ttft: D(1000), SLA_tpot: D(50), spec_method: 'none' }) as any);
    const eagleCalc = deriveThroughputCalc(withPerf({ B_max: D(64), SLA_ttft: D(1000), SLA_tpot: D(50), spec_method: 'EAGLE' }) as any);
    expect(eagleCalc.B_limit.gte(noneCalc.B_limit)).toBe(true);
  });
});

describe('E-9 AgentX 场景预设', () => {
  it('agentxParams 预设 rho≈200 / h≈0.96 / Ctx≈128k，且不污染默认', () => {
    const p = agentxParams();
    expect(p.demand.rho.toString()).toBe(AGENTX_PRESET_RHO.toString());
    expect(p.demand.h.toString()).toBe(AGENTX_PRESET_H.toString());
    expect(p.perf.Ctx.toString()).toBe(AGENTX_PRESET_CTX.toString());
    const d = defaultParams();
    expect(d.demand.rho.toString()).not.toBe(AGENTX_PRESET_RHO.toString());
    expect(d.perf.Ctx.toString()).toBe(SHORT_CTX_PRESET_CTX.toString());
  });
});

describe('E-10 标杆告警环（前端镜像）', () => {
  it('自建设本偏离 cost_benchmark > ±50% 触发「标杆告警」', () => {
    const params = defaultParams();
    const cpm = compute(params, derive(params)).cost_per_m_capacity;
    const low = { ...params, pricing: { ...params.pricing, cost_benchmark: cpm.div(D(3)) } };
    const r = computeCore(low);
    expect(r.warnings.some((w) => w.includes('标杆告警'))).toBe(true);
  });

  it('自建设本与 cost_benchmark 一致（偏离 0%）不触发「标杆告警」', () => {
    const params = defaultParams();
    const cpm = compute(params, derive(params)).cost_per_m_capacity;
    const ok = { ...params, pricing: { ...params.pricing, cost_benchmark: cpm } };
    const r = computeCore(ok);
    expect(r.warnings.some((w) => w.includes('标杆告警'))).toBe(false);
  });

  it('cost_benchmark=null（默认）不触发「标杆告警」', () => {
    const r = computeCore(defaultParams());
    expect(r.warnings.some((w) => w.includes('标杆告警'))).toBe(false);
  });

  it('C-1 口径告警：售价低于市场成本标杆时触发', () => {
    const params = defaultParams();
    const pEq = computeCore(params).revenue.p_eq;
    const loss = { ...params, pricing: { ...params.pricing, cost_benchmark: pEq.times(D(5)) } };
    const r = computeCore(loss);
    expect(r.warnings.some((w) => w.includes('口径告警'))).toBe(true);
  });
});
