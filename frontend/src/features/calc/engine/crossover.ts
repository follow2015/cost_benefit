/** 三方案临界规模与下包络。对齐后端 `app/calc/crossover.py`。 */

import { D, ZERO, Decimal, safeDiv, decStr } from './decimalConfig';
import { CostModel, CostModelLike } from './costModel';
import type { CrossoverPayload } from '@/shared/types';

const CURVE_SAMPLES = 41;

export interface CostCurve {
  plan: string;
  label: string;
  a: Decimal;
  b: Decimal;
  points: Array<{ Q: Decimal; total_cost: Decimal; unit_cost: Decimal }>;
}

export interface Crossover {
  plans: string[];
  Q: Decimal | null;
  active: boolean;
  status: string;
  note: string;
}

export interface Segment {
  from_Q: Decimal;
  to_Q: Decimal | null;
  best_plan: string;
  best_label: string;
}

export interface CrossoverResult {
  curves: CostCurve[];
  crossovers: Crossover[];
  recommended: Segment[];
  q_max: Decimal;
  capacity_wall: Decimal;
  notes: string[];
}

type Models = CostModelLike[];

function pairCrossover(left: CostModelLike, right: CostModelLike): [Decimal | null, string, string] {
  const denominator = right.b.minus(left.b);
  if (denominator.eq(ZERO)) {
    const cheaper = left.a.lte(right.a) ? left : right;
    return [null, 'parallel', `两方案单位变动成本相同（平行线），全程 ${cheaper.name()} 恒不劣，无临界点。`];
  }
  const q = left.a.minus(right.a).div(denominator);
  if (q.lt(ZERO)) {
    const cheaper = left.cost(D(1)).lte(right.cost(D(1))) ? left : right;
    return [q, 'negative', `交点位于负需求区间，在任何正需求下 ${cheaper.name()} 恒优。`];
  }
  return [q, 'ok', '存在有效交点。'];
}

function lowerEnvelope(models: Models, qMax: Decimal): [Segment[], Decimal[]] {
  if (models.length === 0) return [[], []];
  let current = models.reduce((best, m) => (m.a.lt(best.a) || (m.a.eq(best.a) && m.b.lt(best.b)) ? m : best), models[0]);
  const segments: Segment[] = [];
  const switchPoints: Decimal[] = [];
  let start = ZERO;
  let guard = 0;

  while (guard <= models.length + 2) {
    guard++;
    let nextQ: Decimal | null = null;
    let nextModel: CostModelLike | null = null;
    for (const candidate of models) {
      if (candidate.plan === current.plan) continue;
      const [q, status] = pairCrossover(current, candidate);
      if (status !== 'ok' || q === null) continue;
      if (q.lte(start) || q.gt(qMax)) continue;
      if (candidate.b.lt(current.b) && (nextQ === null || q.lt(nextQ))) {
        nextQ = q;
        nextModel = candidate;
      }
    }
    if (nextQ === null || nextModel === null) {
      segments.push({ from_Q: start, to_Q: null, best_plan: current.plan, best_label: current.name() });
      break;
    }
    segments.push({
      from_Q: start,
      to_Q: nextQ,
      best_plan: current.plan,
      best_label: current.name(),
    });
    switchPoints.push(nextQ);
    start = nextQ;
    current = nextModel;
  }
  return [segments, switchPoints];
}

export function compute(
  models: Models,
  demandQ: Decimal,
  capacityWall: Decimal,
  dominatedNote = '交点存在但被第三方案支配（非活跃转折点），仅作信息展示，不作为推荐分界。',
  noActiveNote = '三方案成本线在可行域内无活跃交点：推荐方案在全区间不变。',
): CrossoverResult {
  const notes: string[] = [];
  const candidates = [demandQ.times(D(2)), capacityWall.times(D('1.2'))].filter((v) => v.gt(ZERO));
  const qMax = candidates.length ? Decimal.max(...candidates) : D(1000);

  const curves: CostCurve[] = [];
  for (const model of models) {
    const points: Array<{ Q: Decimal; total_cost: Decimal; unit_cost: Decimal }> = [];
    for (let i = 0; i < CURVE_SAMPLES; i++) {
      const q = qMax.times(new Decimal(i)).div(new Decimal(CURVE_SAMPLES - 1));
      points.push({
        Q: q,
        total_cost: model.cost(q),
        unit_cost: safeDiv(model.cost(q), q),
      });
    }
    curves.push({ plan: model.plan, label: model.name(), a: model.a, b: model.b, points });
  }

  const [segments, switchPoints] = lowerEnvelope(models, qMax);

  const crossovers: Crossover[] = [];
  for (let i = 0; i < models.length; i++) {
    for (const right of models.slice(i + 1)) {
      const [q, status, note] = pairCrossover(models[i], right);
      const active = q !== null && switchPoints.some((s) => q.minus(s).abs().lte(new Decimal('1e-12')));
      let st = status;
      let nt = note;
      if (status === 'ok' && q !== null && q.gt(capacityWall) && capacityWall.gt(ZERO)) {
        st = 'beyond_capacity';
        nt = '交点超出当前满负荷产能（容量墙），需扩容才会发生成本反转。';
      } else if (status === 'ok' && !active) {
        st = 'dominated';
        nt = dominatedNote; // P1-1 文案参数化：三方案/四方案措辞由调用方注入，消除漂移
      }
      crossovers.push({ plans: [models[i].plan, right.plan], Q: q, active, status: st, note: nt });
    }
  }

  if (switchPoints.length === 0) notes.push(noActiveNote);
  if (capacityWall.gt(ZERO) && demandQ.gt(capacityWall)) {
    notes.push('当前需求已超自建/租用容量墙，A/B 方案需扩容，成本线仅供参考。');
  }

  return { curves, crossovers, recommended: segments, q_max: qMax, capacity_wall: capacityWall, notes };
}

// ===========================================================================
// P2-3 混合部署：在 A/B/C 基础上叠加混合方案 H，求四方案下包络（复用 compute）。
// ===========================================================================
export function computeHybrid(
  threeModels: Models,
  hybridModel: CostModelLike,
  demandQ: Decimal,
  capacityWall: Decimal,
): CrossoverResult {
  return compute(
    [...threeModels, hybridModel],
    demandQ,
    capacityWall,
    '交点存在但被其他方案支配（非活跃转折点），仅作信息展示，不作为推荐分界。',
    '混合部署四方案成本线在可行域内无活跃交点：推荐方案在全区间不变。',
  );
}

/** 把 CrossoverResult（Decimal）转为图表所需字符串载荷（供 CrossoverChart 渲染）。 */
export function toChartPayload(result: CrossoverResult): CrossoverPayload {
  return {
    curves: result.curves.map((curve) => ({
      plan: curve.plan,
      label: curve.label,
      a: decStr(curve.a),
      b: decStr(curve.b),
      points: curve.points.map((p) => ({
        Q: decStr(p.Q),
        total_cost: decStr(p.total_cost),
        unit_cost: decStr(p.unit_cost),
      })),
    })),
    crossovers: result.crossovers.map((item) => ({
      plans: item.plans,
      Q: item.Q === null ? null : decStr(item.Q),
      active: item.active,
      status: item.status,
      note: item.note,
    })),
    recommended: result.recommended.map((segment) => ({
      from_Q: decStr(segment.from_Q),
      to_Q: segment.to_Q === null ? null : decStr(segment.to_Q),
      best_plan: segment.best_plan,
      best_label: segment.best_label,
    })),
    q_max: decStr(result.q_max),
    capacity_wall: decStr(result.capacity_wall),
    notes: result.notes,
  };
}
