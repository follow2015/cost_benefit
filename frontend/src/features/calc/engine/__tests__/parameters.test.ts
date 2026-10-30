import { describe, expect, it } from 'vitest';
import { D } from '../decimalConfig';
import { defaultParams, defaultPricing } from '../parameters';
import { paramsFromDict, paramsToDict } from '../codec';

// S-3 汇率层：前端镜像 PricingParams.fx_usd_cny，与后端默认 7.2 一致。
describe('S-3 fx_usd_cny mirror', () => {
  it('default fx_usd_cny = 7.2', () => {
    expect(defaultPricing().fx_usd_cny.eq(D('7.2'))).toBe(true);
  });
  it('cost_benchmark stays null by default (golden-vector safe)', () => {
    expect(defaultPricing().cost_benchmark).toBeNull();
  });
});

// C-1/S-3：cost_benchmark 与 fx_usd_cny 必须能随方案保存→加载往返（codec 已纳入对应分组）。
describe('C-1/S-3 codec round-trip', () => {
  it('cost_benchmark + fx_usd_cny survive save→load', () => {
    const params = defaultParams();
    params.pricing.cost_benchmark = D('0.0504'); // qwen/GB300/AgentX 校准值
    params.pricing.fx_usd_cny = D('7.2');
    const dict = paramsToDict(params);
    expect((dict.pricing as Record<string, unknown>).cost_benchmark).toBe('0.0504');
    const back = paramsFromDict(dict);
    expect(back.pricing.cost_benchmark?.toString()).toBe('0.0504');
    expect(back.pricing.fx_usd_cny.toString()).toBe('7.2');
  });
  it('null cost_benchmark round-trips to null', () => {
    const dict = paramsToDict(defaultParams());
    const back = paramsFromDict(dict);
    expect(back.pricing.cost_benchmark).toBeNull();
    expect(back.pricing.fx_usd_cny.toString()).toBe('7.2');
  });
});

