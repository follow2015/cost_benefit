/**
 * KPI 展示格式化回归：三类曾出错的口径各钉一条。
 *
 * 缺陷背景（第四轮评审遗留）：`months` 曾被并入 `ratio` 分支，
 * 「静态回本 21.79 月」在结果页 / 对比页 / 向导预览三处都被渲染成「2179.28%月」。
 */
import { describe, expect, it } from 'vitest';
import { formatKpiValue } from '../formatKpi';

const kpi = (kind: string, value: string | null) => ({ kind, value });

describe('formatKpiValue', () => {
  it('月数不再乘 100（回本周期量纲是月，不是百分比）', () => {
    expect(formatKpiValue(kpi('months', '21.792824465261087'))).toBe('21.79');
    expect(formatKpiValue(kpi('months', '23.556666576808813'))).toBe('23.56');
  });

  it('比率仍按百分比展示', () => {
    expect(formatKpiValue(kpi('ratio', '0.464588468275103'))).toBe('46.46%');
    expect(formatKpiValue(kpi('ratio', '0.751919881123527'))).toBe('75.19%');
  });

  it('倍数走原值（利息覆盖 2.5 倍不再显示成 250%）', () => {
    expect(formatKpiValue(kpi('number', '2.5'))).toBe('2.50');
    expect(formatKpiValue(kpi('number', '0.8333333'))).toBe('0.83');
  });

  it('金额按万 / 亿进位', () => {
    expect(formatKpiValue(kpi('money', '1181951.2869'))).toBe('118.20万');
    expect(formatKpiValue(kpi('money', '325000000'))).toBe('3.25亿');
    expect(formatKpiValue(kpi('money', '8600'))).toBe('8600.00');
    expect(formatKpiValue(kpi('cost', '5.42'))).toBe('5.42');
  });

  it('负值保留符号与绝对值进位', () => {
    expect(formatKpiValue(kpi('money', '-1181951.2869'))).toBe('-118.20万');
  });

  it('空值与非数值回落占位文案', () => {
    expect(formatKpiValue(kpi('money', null), '无解')).toBe('无解');
    expect(formatKpiValue(kpi('months', null))).toBe('—');
    expect(formatKpiValue(kpi('number', 'NaN'), '—')).toBe('—');
  });

  it('文本型 KPI 原样透出（推荐方案名）', () => {
    expect(formatKpiValue(kpi('text', '自建'))).toBe('自建');
  });
});
