/** 计算相关 hooks：权威重算、无状态试算、多方案对比。 */
import { useMutation } from '@tanstack/react-query';
import * as api from '@/features/calc/api/calcApi';
import type { CalcRequest, CompareRequest, CalcPayload } from '@/shared/types';

export function useCalculate() {
  return useMutation({
    mutationFn: (req: CalcRequest) => api.calculate(req),
  });
}

export function usePreview() {
  return useMutation({
    mutationFn: ({ params, options }: { params: Record<string, unknown>; options?: CalcRequest['options'] }) =>
      api.preview(params, options),
  });
}

export function useCompare() {
  return useMutation({
    mutationFn: (req: CompareRequest) => api.compare(req),
  });
}

export function useLatestResult(scenarioId: number | null) {
  return useMutation({
    mutationFn: () => api.latestResult(scenarioId as number),
  });
}

export type { CalcPayload };
