import { describe, it, expect } from 'vitest';
import { D, ZERO, Decimal } from '../decimalConfig';
import { defaultPricing } from '../parameters';
import { compute } from '../revenue';

// 极简 DerivedParams（revenue.compute 仅用 D_in/D_out/Q_eq）
function mkDerived() {
  return { D_in: D(1262), D_out: D(3786), Q_eq: D(3888) } as any;
}

// 极简 ScenarioParams（revenue.compute 仅用 pricing + demand.h）
function mkParams(pricing: any) {
  return { pricing, demand: { h: D('0.2') } } as any;
}

describe('C-1 revenue dual-basis (mirror)', () => {
  it('no benchmark => null dual basis, no loss', () => {
    const p = defaultPricing();
    const rev = compute(mkParams(p), mkDerived(), D(100000));
    expect(rev.G_benchmark).toBeNull();
    expect(rev.cost_benchmark_total).toBeNull();
    expect(rev.GM_pct_benchmark).toBeNull();
    expect(rev.loss_vs_benchmark).toBe(false);
  });

  it('benchmark computes G_benchmark and no loss', () => {
    const p = { ...defaultPricing(), cost_benchmark: D('0.08') };
    const rev = compute(mkParams(p), mkDerived(), D(100000));
    expect(rev.cost_benchmark_total?.toString()).toBe(D(3888).times(D('0.08')).toString());
    expect(rev.loss_vs_benchmark).toBe(false);
    expect(rev.G_benchmark).not.toBeNull();
    expect((rev.G_benchmark as Decimal).gt(ZERO)).toBe(true);
  });

  it('benchmark above price => loss', () => {
    const p = { ...defaultPricing(), cost_benchmark: D('40') };
    const rev = compute(mkParams(p), mkDerived(), D(100000));
    expect(rev.loss_vs_benchmark).toBe(true);
    expect((rev.G_benchmark as Decimal).lt(ZERO)).toBe(true);
  });
});
