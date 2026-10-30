/**
 * 前端计算客户端：封装 Worker 调用 + 防抖（≤500ms）。
 * 优先走 Worker（不阻塞 UI）；Worker 不可用（如测试环境）时回退到主线程同步计算。
 */

import { Decimal } from '../engine/decimalConfig';
import { computeAll, EngineOptions } from '../engine/engine';
import { paramsFromDict } from '../engine/codec';
import { ScenarioParams } from '../engine/parameters';
import type { WorkerRequest, WorkerResponse } from '../engine/worker';

export interface CalcRequestOptions {
  include_sensitivity?: boolean;
  include_scenarios?: boolean;
  include_crossover?: boolean;
  sensitivity_target?: string;
  sensitivity_delta?: string;
  // 增量能力（默认关闭）
  include_joint?: boolean;
  joint_target?: string;
  joint_delta?: string;
  joint_vars?: string[] | null;
  include_custom_scenarios?: boolean;
  custom_scenario_specs?: Array<{ key: string; label: string; overrides: Record<string, string> }> | null;
}

export interface CalcPayload {
  [key: string]: unknown;
}

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, (res: WorkerResponse) => void>();

function ensureWorker(): Worker | null {
  if (typeof Worker === 'undefined') return null;
  if (worker) return worker;
  try {
    worker = new Worker(new URL('../engine/worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const cb = pending.get(event.data.id);
      if (cb) {
        pending.delete(event.data.id);
        cb(event.data);
      }
    };
    worker.onerror = () => {
      // worker 加载/运行失败：把挂起的请求全部以「错误」回包，让 compute 走主线程兜底，
      // 否则 pending 里的 Promise 永不 resolve → 调用方永久转圈。
      worker = null;
      for (const cb of pending.values()) cb({ id: 0, payload: null, error: 'worker unavailable', duration_ms: 0 });
      pending.clear();
    };
    return worker;
  } catch {
    return null;
  }
}

export interface CalcResult {
  payload: CalcPayload;
  duration_ms: number;
  viaWorker: boolean;
}

/** 计算（走 Worker；失败回退主线程）。 */
export function compute(
  params: Record<string, unknown>,
  options?: CalcRequestOptions,
): Promise<CalcResult> {
  const engineOptions: EngineOptions = {
    include_sensitivity: options?.include_sensitivity ?? true,
    include_scenarios: options?.include_scenarios ?? true,
    include_crossover: options?.include_crossover ?? true,
    sensitivity_target: options?.sensitivity_target ?? 'npv',
    sensitivity_delta: new Decimal(options?.sensitivity_delta ?? '0.2'),
    include_joint: options?.include_joint ?? false,
    joint_target: options?.joint_target ?? 'npv',
    joint_delta: new Decimal(options?.joint_delta ?? '0.2'),
    joint_vars: options?.joint_vars ?? null,
    include_custom_scenarios: options?.include_custom_scenarios ?? false,
    custom_scenario_specs: options?.custom_scenario_specs
      ? options.custom_scenario_specs.map((s) => ({
          key: s.key,
          label: s.label,
          overrides: Object.fromEntries(Object.entries(s.overrides).map(([k, v]) => [k, new Decimal(v)])),
        }))
      : null,
  };
  const wk = ensureWorker();
  if (wk) {
    const id = nextId++;
    const req: WorkerRequest = {
      id,
      params,
      options: {
        include_sensitivity: engineOptions.include_sensitivity,
        include_scenarios: engineOptions.include_scenarios,
        include_crossover: engineOptions.include_crossover,
        sensitivity_target: engineOptions.sensitivity_target,
        sensitivity_delta: engineOptions.sensitivity_delta.toString(),
        include_joint: engineOptions.include_joint,
        joint_target: engineOptions.joint_target,
        joint_delta: engineOptions.joint_delta!.toString(),
        joint_vars: engineOptions.joint_vars ?? null,
        include_custom_scenarios: engineOptions.include_custom_scenarios,
        custom_scenario_specs: engineOptions.custom_scenario_specs
          ? engineOptions.custom_scenario_specs.map((s) => ({
              key: s.key,
              label: s.label,
              overrides: Object.fromEntries(
                Object.entries(s.overrides).map(([k, v]) => [k, v.toString()]),
              ),
            }))
          : null,
      },
    };
    return new Promise<CalcResult>((resolve) => {
      // 安全网：worker 静默无响应（如线程卡死）时，超时回退主线程，避免永久转圈。
      const timer = setTimeout(() => {
        if (pending.has(id)) {
          pending.delete(id);
          resolve(fallback(params, engineOptions));
        }
      }, 4000);
      pending.set(id, (res) => {
        clearTimeout(timer);
        if (res.error || !res.payload) {
          resolve(fallback(params, engineOptions));
        } else {
          resolve({ payload: res.payload, duration_ms: res.duration_ms, viaWorker: true });
        }
      });
      try {
        wk.postMessage(req);
      } catch {
        // postMessage 可能同步抛错（如请求含不可结构化克隆的值），直接回退主线程。
        clearTimeout(timer);
        pending.delete(id);
        resolve(fallback(params, engineOptions));
      }
    });
  }
  return Promise.resolve(fallback(params, engineOptions));
}

function fallback(params: Record<string, unknown>, options: EngineOptions): CalcResult {
  const started = performance.now();
  const scenarioParams: ScenarioParams = paramsFromDict(params);
  const raw = computeAll(scenarioParams, options);
  return {
    payload: raw as unknown as CalcPayload,
    duration_ms: Math.round(performance.now() - started),
    viaWorker: false,
  };
}

/** 防抖：合并 500ms 内的连续调用，仅执行最后一次。 */
export function debounceCompute(
  fn: (params: Record<string, unknown>, options?: CalcRequestOptions) => void,
  delay = 500,
): (params: Record<string, unknown>, options?: CalcRequestOptions) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return (params, options) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(params, options), delay);
  };
}
