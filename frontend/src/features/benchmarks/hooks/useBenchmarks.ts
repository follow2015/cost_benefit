/** 基准库 hook（向导首屏一次性加载）。 */
import { useQuery } from '@tanstack/react-query';
import { getBundle } from '@/features/benchmarks/api/benchmarksApi';

export function useBenchmarks() {
  return useQuery({
    queryKey: ['benchmarks'],
    queryFn: getBundle,
    staleTime: 10 * 60_000,
  });
}
