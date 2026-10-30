/** 方案相关 API。 */
import { get, post, put, del } from '@/shared/api/client';
import type {
  ScenarioListItem,
  ScenarioDetail,
  ScenarioCreate,
  ScenarioUpdate,
  SnapshotOut,
  PageResponse,
  CalcPayload,
} from '@/shared/types';

export function listScenarios(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
  status?: string;
}): Promise<PageResponse<ScenarioListItem>> {
  return get<PageResponse<ScenarioListItem>>('/scenarios', params);
}

export function getScenario(id: number): Promise<ScenarioDetail> {
  return get<ScenarioDetail>(`/scenarios/${id}`);
}

export function createScenario(payload: ScenarioCreate): Promise<ScenarioDetail> {
  return post<ScenarioDetail>('/scenarios', payload);
}

export function updateScenario(id: number, payload: ScenarioUpdate): Promise<ScenarioDetail> {
  return put<ScenarioDetail>(`/scenarios/${id}`, payload);
}

export function deleteScenario(id: number): Promise<{ ok: boolean }> {
  return del<{ ok: boolean }>(`/scenarios/${id}`);
}

export function duplicateScenario(id: number, newName?: string): Promise<ScenarioDetail> {
  return post<ScenarioDetail>(`/scenarios/${id}/duplicate`, undefined).then((r) => r);
}

export function listSnapshots(id: number, limit = 50): Promise<SnapshotOut[]> {
  return get<SnapshotOut[]>(`/scenarios/${id}/snapshots`, { limit });
}

export function getDefaultParams(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/scenarios/default-params');
}

export function latestResult(id: number): Promise<CalcPayload> {
  return get<CalcPayload>(`/calc/scenarios/${id}/latest`);
}

export function resultHistory(id: number, limit = 20): Promise<Record<string, unknown>[]> {
  return get<Record<string, unknown>[]>(`/calc/scenarios/${id}/history`, { limit });
}
