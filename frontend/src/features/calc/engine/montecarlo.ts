/**
 * 蒙特卡洛模拟（P2-4 / REQ-18）：前端镜像实现，对齐后端 `app/calc/montecarlo.py`。
 * 对 ≥8 个关键变量做三角分布随机抽样 N 次（默认 2000），每次复用 `engine.computeAll`
 * 的财务口径（NPV / IRR）跑一遍，收集分布并输出均值/标准差/分位数/P(NPV>0)/直方图。
 * 抽样用 float（分布估计，精度要求低），不进 Decimal 主链；NPV 计算复用既有口径。
 */

import { Decimal } from './decimalConfig';
import { ScenarioParams, withOverride, getValue } from './parameters';
import { evaluateNpvIrr } from './engine';

const SAMPLING_VARS: Array<[string, number]> = [
  ['demand.U', 0.20],
  ['power.E_price', 0.20],
  ['pricing.Rent_gpu', 0.25],
  ['pricing.API_out', 0.25],
  ['hw.P_gpu', 0.20],
  ['perf.T_eff', 0.15],
  ['finance.r_w', 0.30],
  ['pricing.p_out', 0.20],
  ['pricing.p_in', 0.20],
  ['demand.D_eq', 0.20],
  // ---- §4.1 补全：P0/P1/P2 新增成本科目纳入抽样（追加至末尾）----
  ['power.Co_eng', 0.20],
  ['power.Co_sales_admin', 0.20],
  ['power.Co_other', 0.20],
  ['perf.SLA_penalty_rate', 0.20],
  ['finance.cost_learning_rate', 0.20],
];

export interface MonteCarloResult {
  n: number;
  seed: number | null;
  mean_npv: number;
  std_npv: number;
  percentiles_npv: Record<string, number>;
  p_npv_positive: number;
  p_irr_gt_rw: number;
  histogram: Array<{ bin_start: number; bin_end: number; count: number }>;
  deterministic_npv: number;
  deterministic_irr: number;
  notes: string[];
}

/** 可复现 PRNG（mulberry32）。 */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 对称三角分布抽样（中心 0，范围 [-spread, +spread]）。 */
function sampleRelative(rng: () => number, spread: number): number {
  const low = -spread;
  const high = spread;
  const mode = 0;
  const u = rng();
  const fc = (mode - low) / (high - low);
  if (u < fc) return low + Math.sqrt(u * (high - low) * (mode - low));
  return high - Math.sqrt((1 - u) * (high - low) * (high - mode));
}

function percentile(sorted: number[], p: number): number {
  const n = sorted.length;
  if (n === 0) return 0;
  if (n === 1) return sorted[0];
  const rank = ((n - 1) * p) / 100;
  const low = Math.floor(rank);
  const high = Math.ceil(rank);
  if (low === high) return sorted[low];
  const frac = rank - low;
  return sorted[low] + (sorted[high] - sorted[low]) * frac;
}

function histogram(values: number[], nbins = 20): Array<{ bin_start: number; bin_end: number; count: number }> {
  if (values.length === 0) return [];
  const mn = Math.min(...values);
  const mx = Math.max(...values);
  if (mx <= mn) return [{ bin_start: mn, bin_end: mn + 1, count: values.length }];
  const width = (mx - mn) / nbins;
  const bins = Array.from({ length: nbins }, (_, i) => ({
    bin_start: mn + i * width,
    bin_end: mn + (i + 1) * width,
    count: 0,
  }));
  for (const v of values) {
    let idx = Math.floor((v - mn) / width);
    if (idx >= nbins) idx = nbins - 1;
    if (idx < 0) idx = 0;
    bins[idx].count += 1;
  }
  return bins;
}

export function montecarloCompute(
  params: ScenarioParams,
  n = 2000,
  seed?: number,
  spreads?: Record<string, number> | null,
): MonteCarloResult {
  const count = Math.max(1, Math.floor(n));
  const rng = seed === undefined ? Math.random : mulberry32(seed);

  // P1-2 精简求值：确定性基准与每次抽样都只跑到 financials，不构建 KPI/现金流序列等即算即弃结构
  const [detNpv, detIrr] = evaluateNpvIrr(params);
  const deterministicNpv = detNpv != null ? Number(detNpv) : 0;
  const deterministicIrr = detIrr != null ? Number(detIrr) : 0;
  const rW = Number(params.finance.r_w);

  const npvList: number[] = [];
  const irrList: number[] = [];

  for (let i = 0; i < count; i++) {
    let perturbed = params;
    for (const [path, defaultSpread] of SAMPLING_VARS) {
      const spread = spreads && path in spreads ? spreads[path] : defaultSpread;
      const baseVal = getValue(perturbed, path);
      if (baseVal == null) continue;
      const baseF = Number(baseVal as Decimal);
      const rel = sampleRelative(rng, spread);
      let newVal = baseF * (1 + rel);
      if (baseF > 0 && newVal <= 0) newVal = baseF * 1e-3;
      if (baseF === 0 && newVal <= 0) newVal = 1e-3;
      perturbed = withOverride(perturbed, path, newVal);
    }
    const [npv, irr] = evaluateNpvIrr(perturbed);
    npvList.push(npv != null ? Number(npv) : 0);
    irrList.push(irr != null ? Number(irr) : 0);
  }

  const meanNpv = npvList.reduce((a, b) => a + b, 0) / count;
  const variance = npvList.reduce((a, b) => a + (b - meanNpv) ** 2, 0) / count;
  const stdNpv = Math.sqrt(variance);

  const sorted = [...npvList].sort((a, b) => a - b);
  const percentilesNpv = {
    p5: percentile(sorted, 5),
    p10: percentile(sorted, 10),
    p25: percentile(sorted, 25),
    p50: percentile(sorted, 50),
    p75: percentile(sorted, 75),
    p90: percentile(sorted, 90),
    p95: percentile(sorted, 95),
  };

  const pNpvPositive = npvList.filter((x) => x > 0).length / count;
  const pIrrGtRw = irrList.filter((x) => x > rW).length / count;

  return {
    n: count,
    seed: seed ?? null,
    mean_npv: meanNpv,
    std_npv: stdNpv,
    percentiles_npv: percentilesNpv,
    p_npv_positive: pNpvPositive,
    p_irr_gt_rw: pIrrGtRw,
    histogram: histogram(npvList),
    deterministic_npv: deterministicNpv,
    deterministic_irr: deterministicIrr,
    notes: [`对 ${SAMPLING_VARS.length} 个变量做三角分布随机抽样（N=${count}），每次复用 financials 口径计算 NPV/IRR。`],
  };
}
