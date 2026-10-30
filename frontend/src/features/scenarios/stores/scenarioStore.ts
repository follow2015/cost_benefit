/**
 * 编辑中的方案草稿状态（Zustand）。承载向导的实时参数，供 Web Worker 实时重算。
 * 参数为字典形态（与后端 `params_to_dict` / `params_from_dict` 同构，Decimal 以字符串存储）。
 */
import { create } from 'zustand';
import type { ScenarioParams } from '@/features/calc/engine/parameters';
import { defaultParams } from '@/features/calc/engine/parameters';
import { paramsToDict } from '@/features/calc/engine/codec';

export interface ScenarioDraftState {
  id: number | null;
  name: string;
  description: string;
  version: number;
  params: ScenarioParams;
  dirty: boolean;
  setField: (group: keyof ScenarioParams, field: string, value: unknown) => void;
  setParams: (params: ScenarioParams) => void;
  setName: (name: string) => void;
  setDescription: (description: string) => void;
  load: (payload: { id: number | null; name: string; description: string; version: number; params: ScenarioParams }) => void;
  reset: () => void;
}

export const useScenarioDraft = create<ScenarioDraftState>((set) => ({
  id: null,
  name: '',
  description: '',
  version: 1,
  params: defaultParams(),
  dirty: false,
  setField: (group, field, value) =>
    set((state) => {
      const groupObj = state.params[group] as unknown as Record<string, unknown>;
      const nextGroup = { ...groupObj, [field]: value };
      return {
        params: { ...state.params, [group]: nextGroup },
        dirty: true,
      };
    }),
  setParams: (params) => set({ params, dirty: true }),
  setName: (name) => set({ name, dirty: true }),
  setDescription: (description) => set({ description, dirty: true }),
  load: (payload) =>
    set({
      id: payload.id,
      name: payload.name,
      description: payload.description,
      version: payload.version,
      params: payload.params,
      dirty: false,
    }),
  reset: () =>
    set({ id: null, name: '', description: '', version: 1, params: defaultParams(), dirty: false }),
}));

/** 取当前草稿参数的字典形态（Decimal → 字符串），用于 worker 与后端。 */
export function draftParamsDict(): Record<string, unknown> {
  return paramsToDict(useScenarioDraft.getState().params);
}
