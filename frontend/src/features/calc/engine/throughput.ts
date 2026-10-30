/** 吞吐与容量推导。对齐后端 `app/calc/throughput.py`。 */

import { D, SEC, MTOK, ZERO, Decimal, safeDiv } from './decimalConfig';
import { DerivedParams, PerfParams, ScenarioParams } from './parameters';

export const K_SOURCE_LABELS: Record<string, string> = {
  measured: '实测/用户录入',
  throughput_ratio: '吞吐比 T_dc / T_pf',
  benchmark: '基准库查表',
  default: '默认经验值 0.1（估算）',
};

export interface ThroughputInfo {
  T_eff: Decimal;
  Q_cap_M: Decimal;
  Q_out_M: Decimal;
  k: Decimal;
  k_source: string;
  k_source_label: string;
  capacity_headroom: Decimal;
  over_capacity: boolean;
  warnings: string[];
}

export function monthCapacityMtok(tEff: Decimal): Decimal {
  return D(tEff).times(SEC).div(MTOK);
}

export function monthOutputMtok(tEff: Decimal, utilization: Decimal): Decimal {
  return monthCapacityMtok(tEff).times(D(utilization));
}

export function analyze(params: ScenarioParams, derived: DerivedParams): ThroughputInfo {
  const warnings: string[] = [];
  const qOut = derived.Q_cap_M.times(derived.U);
  const headroom = derived.Q_cap_M.minus(derived.Q_eq);

  if (derived.Q_cap_M.lte(ZERO)) {
    warnings.push('满负荷产能为 0：请检查有效吞吐 T_eff 是否录入。');
  }
  if (derived.k_source === 'default') {
    warnings.push('等效折算系数 k 使用默认经验值 0.1（估算），建议提供实测吞吐或 T_pf/T_dc。');
  }
  if (headroom.lt(ZERO)) {
    warnings.push('月需求量已超过满负荷月产能（超出容量墙），自建/租用方案需扩容才可承接。');
  }
  if (derived.U.gt(ZERO)) {
    const deviation = derived.U_implied.minus(derived.U).abs().div(derived.U);
    if (deviation.gt(D('0.05'))) {
      const implied = safeDiv(derived.Q_eq, derived.Q_cap_M);
      warnings.push(
        `利用率 U 与「月需求量/满负荷产能」隐含利用率偏差超过 5%（U=${derived.U.toString()}，隐含=${implied.toString()}），请确认口径一致性。`,
      );
    }
  }

  return {
    T_eff: params.perf.T_eff,
    Q_cap_M: derived.Q_cap_M,
    Q_out_M: qOut,
    k: derived.k,
    k_source: derived.k_source,
    k_source_label: K_SOURCE_LABELS[derived.k_source] ?? derived.k_source,
    capacity_headroom: headroom,
    over_capacity: headroom.lt(ZERO),
    warnings,
  };
}

// ===========================================================================
// P2-1 吞吐计算器（REQ-17）：对齐后端 `app/calc/throughput.py` 扩展段。
// 由模型规模 / 精度 / 量化 / 并发 batch + SLA（TTFT、TPOT 阈值）推导
// 可用 batch 上限与 prefill / decode 吞吐区间，并给出折算系数 k。
// ===========================================================================

const TTFT_REF_MS = new Decimal('1000');
const TPOT_REF_MS = new Decimal('100');
const REF_T_PF = new Decimal('20000');
const REF_T_DC = new Decimal('2000');
const THROUGHPUT_BAND = new Decimal('0.15');

const QUANT_THROUGHPUT_MULT: Record<string, Decimal> = {
  FP4: new Decimal('2.0'),
  FP8: new Decimal('1.0'),
  FP16: new Decimal('0.6'),
  BF16: new Decimal('0.6'),
  INT8: new Decimal('1.3'),
  INT4: new Decimal('1.8'),
  MXFP4: new Decimal('2.2'),
  NVFP4: new Decimal('2.2'),
};

// 投机解码接受长度倍率（C-3 订正）
const SPEC_DECODE_ACCEPT_LENGTH_MULT: Record<string, Decimal> = {
  none: new Decimal('1.0'),
  MTP: new Decimal('1.3'),
  STP: new Decimal('1.5'),
  EAGLE: new Decimal('1.8'),
};

// ===========================================================================
// E-5 KV cache 容量约束（对齐后端 throughput.py effective_b_max / kv_cache_batch_limit）
// ===========================================================================
/** KV cache 容量约束下的 batch 上限（token 级）。未启用（kv=0/vram=0）返 null。 */
export function kvCacheBatchLimit(perf: PerfParams): Decimal | null {
  if (perf.kv_cache_per_token_gb.lte(ZERO) || perf.vram_total_gb.lte(ZERO)) return null;
  const kvBudget = perf.vram_total_gb.minus(perf.Mem_w);
  if (kvBudget.lte(ZERO)) return new Decimal('1'); // 权重已占满显存，仅能承载极小 batch
  const perSeq = perf.kv_cache_per_token_gb.times(perf.Ctx);
  if (perSeq.lte(ZERO)) return null;
  return kvBudget.div(perSeq).toDecimalPlaces(0, Decimal.ROUND_FLOOR);
}

/** 有效 batch 上限 = min(B_max, KV cache 容量约束)；未启用时回退 B_max（默认，黄金向量零回归）。 */
export function effectiveBMax(perf: PerfParams): Decimal {
  const kv = kvCacheBatchLimit(perf);
  if (kv === null) return perf.B_max;
  return Decimal.min(perf.B_max, kv);
}

export interface ThroughputCalcResult {
  B_max: Decimal;
  B_limit: Decimal;
  sla_constrained: boolean;
  T_pf_low: Decimal;
  T_pf_mid: Decimal;
  T_pf_high: Decimal;
  T_dc_low: Decimal;
  T_dc_mid: Decimal;
  T_dc_high: Decimal;
  k: Decimal;
  k_low: Decimal;
  k_high: Decimal;
  k_source: string;
  k_source_label: string;
  T_eff_suggestion: Decimal;
  warnings: string[];
}

/** 模型规模 / 量化 / 投机解码带来的吞吐效率因子（单调：模型越大越低；低精度越高）。 */
export function modelEfficiency(mParam: Decimal, quant: string, specMethod: string = 'none'): Decimal {
  let base = new Decimal('1').minus(mParam.minus(new Decimal('70')).div(new Decimal('400')));
  if (base.lt(new Decimal('0.3'))) base = new Decimal('0.3');
  if (base.gt(new Decimal('1.5'))) base = new Decimal('1.5');
  const mult = QUANT_THROUGHPUT_MULT[String(quant).toUpperCase()] ?? new Decimal('1.0');
  const specMult = SPEC_DECODE_ACCEPT_LENGTH_MULT[String(specMethod).toUpperCase()] ?? new Decimal('1.0');
  return base.times(mult).times(specMult);
}

/** 由 SLA 阈值推导可用 batch 上限。SLA 越严 → batch 越小（架构 §266 硬耦合）。
 *  E-6：spec_method 降低等效 TPOT 延迟要求（接受长度倍率）→ 放松 batch 约束（更大 B_limit）。 */
export function availableBatchLimit(bMax: Decimal, slaTtftMs: Decimal, slaTpotMs: Decimal, specMethod: string = 'none'): Decimal {
  // 更严格 SLA（阈值更小）→ 可用 batch 更小：relax = sla/REF（参考=1，<1 收紧，>1 夹到 B_max）
  const ttftRel = TTFT_REF_MS.gt(ZERO) ? slaTtftMs.div(TTFT_REF_MS) : new Decimal('1');
  // E-6：投机解码提升每 token 有效吞吐（accept-length 倍率）→ 等效 SLA TPOT 阈值放宽
  // → 可承受更大 batch（specMult>1 时 tpotEff 变大 → tpotRel>1 → relax 放大，夹到 B_max）。
  const specMult = SPEC_DECODE_ACCEPT_LENGTH_MULT[String(specMethod).toUpperCase()] ?? new Decimal('1.0');
  const tpotEff = specMult.gt(ZERO) ? slaTpotMs.times(specMult) : slaTpotMs;
  const tpotRel = TPOT_REF_MS.gt(ZERO) ? tpotEff.div(TPOT_REF_MS) : new Decimal('1');
  const relax = Decimal.min(ttftRel, tpotRel);
  let raw = bMax.times(relax);
  let limit = raw.toDecimalPlaces(0, Decimal.ROUND_FLOOR);
  if (limit.lt(new Decimal('1'))) limit = new Decimal('1');
  if (limit.gt(bMax)) limit = bMax;
  return limit;
}

/** 吞吐计算器主入口。 */
export function deriveThroughputCalc(params: ScenarioParams): ThroughputCalcResult {
  const { perf } = params;
  const warnings: string[] = [];
  const bMax = effectiveBMax(perf); // E-5：KV cache 容量约束后的有效 batch 上限
  const bLimit = availableBatchLimit(bMax, perf.SLA_ttft, perf.SLA_tpot, perf.spec_method); // E-6：投机解码放松 TPOT 约束
  const slaConstrained = bLimit.lt(bMax);

  const eff = modelEfficiency(
    perf.active_params_b !== null ? perf.active_params_b : perf.M_param,
    perf.quant,
    perf.spec_method,
  );
  const scale = bMax.gt(ZERO) ? bLimit.div(bMax) : ZERO;
  const tPfMid = REF_T_PF.times(eff).times(scale);
  const tDcMid = REF_T_DC.times(eff).times(scale);

  if (slaConstrained) {
    warnings.push(
      `SLA（TTFT=${perf.SLA_ttft.toString()}ms / TPOT=${perf.SLA_tpot.toString()}ms）将可用 batch 上限由 ${bMax.toString()} 收紧至 ${bLimit.toString()}，有效吞吐随之下降。`,
    );
  }
  if (tPfMid.lte(ZERO) || tDcMid.lte(ZERO)) {
    warnings.push('推导吞吐为 0：请检查模型规模 / batch / SLA 参数是否合理。');
  }

  const tPfLow = tPfMid.times(new Decimal('1').minus(THROUGHPUT_BAND));
  const tPfHigh = tPfMid.times(new Decimal('1').plus(THROUGHPUT_BAND));
  const tDcLow = tDcMid.times(new Decimal('1').minus(THROUGHPUT_BAND));
  const tDcHigh = tDcMid.times(new Decimal('1').plus(THROUGHPUT_BAND));

  let kSource: string;
  let kMid: Decimal;
  let kLow: Decimal;
  let kHigh: Decimal;
  if (perf.k_override !== null && perf.k_override.gt(ZERO)) {
    kSource = 'measured';
    kMid = perf.k_override;
    kLow = kMid;
    kHigh = kMid;
  } else {
    kSource = 'throughput_ratio';
    kMid = safeDiv(tDcMid, tPfMid, new Decimal('0.1'));
    kLow = safeDiv(tDcLow, tPfHigh, new Decimal('0.1'));
    kHigh = safeDiv(tDcHigh, tPfLow, new Decimal('0.1'));
  }

  return {
    B_max: bMax,
    B_limit: bLimit,
    sla_constrained: slaConstrained,
    T_pf_low: tPfLow,
    T_pf_mid: tPfMid,
    T_pf_high: tPfHigh,
    T_dc_low: tDcLow,
    T_dc_mid: tDcMid,
    T_dc_high: tDcHigh,
    k: kMid,
    k_low: kLow,
    k_high: kHigh,
    k_source: kSource,
    k_source_label: K_SOURCE_LABELS[kSource] ?? kSource,
    T_eff_suggestion: tDcMid,
    warnings,
  };
}
