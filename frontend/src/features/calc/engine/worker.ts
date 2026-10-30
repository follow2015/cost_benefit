/**
 * 计算 Web Worker：在独立线程执行权威重算，避免实时预览阻塞 UI。
 * 主线程通过 `calcClient.ts` 派发请求并接收结果，配合 ≤500ms 防抖。
 */

import { Decimal, toJsonable } from './decimalConfig';
import { computeAll, EngineOptions } from './engine';
import { paramsFromDict } from './codec';
import { ScenarioParams } from './parameters';

export interface WorkerRequest {
  id: number;
  params: Record<string, unknown>;
  options: {
    include_sensitivity: boolean;
    include_scenarios: boolean;
    include_crossover: boolean;
    sensitivity_target: string;
    sensitivity_delta: string;
    include_joint?: boolean;
    joint_target?: string;
    joint_delta?: string;
    joint_vars?: string[] | null;
    include_custom_scenarios?: boolean;
    custom_scenario_specs?: Array<{ key: string; label: string; overrides: Record<string, string> }> | null;
  };
}

export interface WorkerResponse {
  id: number;
  payload: Record<string, unknown> | null;
  error?: string;
  duration_ms: number;
}

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  const { id, params, options } = event.data;
  const started = performance.now();
  try {
    const scenarioParams: ScenarioParams = paramsFromDict(params);
    const engineOptions: EngineOptions = {
      include_sensitivity: options.include_sensitivity,
      include_scenarios: options.include_scenarios,
      include_crossover: options.include_crossover,
      sensitivity_target: options.sensitivity_target,
      sensitivity_delta: new Decimal(options.sensitivity_delta || '0.2'),
      include_joint: options.include_joint ?? false,
      joint_target: options.joint_target ?? 'npv',
      joint_delta: new Decimal(options.joint_delta || '0.2'),
      joint_vars: options.joint_vars ?? null,
      include_custom_scenarios: options.include_custom_scenarios ?? false,
      custom_scenario_specs: options.custom_scenario_specs
        ? options.custom_scenario_specs.map((s) => ({
            key: s.key,
            label: s.label,
            overrides: Object.fromEntries(
              Object.entries(s.overrides).map(([k, v]) => [k, new Decimal(v)]),
            ),
          }))
        : null,
    };
    const raw = computeAll(scenarioParams, engineOptions);
    const payload = toJsonable(raw) as Record<string, unknown>;
    const response: WorkerResponse = {
      id,
      payload,
      duration_ms: Math.round(performance.now() - started),
    };
    (self as unknown as Worker).postMessage(response);
  } catch (err) {
    const response: WorkerResponse = {
      id,
      payload: null,
      error: err instanceof Error ? err.message : String(err),
      duration_ms: Math.round(performance.now() - started),
    };
    (self as unknown as Worker).postMessage(response);
  }
};
