/** 方案相关的 TanStack Query hooks。 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from '@/features/scenarios/api/scenariosApi';
import type { ScenarioCreate, ScenarioUpdate } from '@/shared/types';

export function useScenarioList(params: { page?: number; page_size?: number; keyword?: string; status?: string }) {
  return useQuery({
    queryKey: ['scenarios', params],
    queryFn: () => api.listScenarios(params),
  });
}

export function useScenario(id: number | null) {
  return useQuery({
    queryKey: ['scenario', id],
    queryFn: () => api.getScenario(id as number),
    enabled: id != null,
  });
}

export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ScenarioCreate) => api.createScenario(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scenarios'] }),
  });
}

export function useUpdateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: ScenarioUpdate }) => api.updateScenario(id, payload),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['scenarios'] });
      qc.invalidateQueries({ queryKey: ['scenario', vars.id] });
    },
  });
}

export function useDeleteScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteScenario(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scenarios'] }),
  });
}

export function useDuplicateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: number; name?: string }) => api.duplicateScenario(id, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scenarios'] }),
  });
}
