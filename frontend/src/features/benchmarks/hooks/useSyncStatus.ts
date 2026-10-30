/** 基准库数据源采集状态 hook。 */
import { useQuery } from '@tanstack/react-query';
import { getSyncStatus } from '@/features/benchmarks/api/benchmarksApi';

/**
 * 读取 InferenceX 采集状态（上次结果 / 下次计划 / 数据源地址）。
 * 只读接口，普通管理员也能看到「数据是哪天采的」。
 */
export function useSyncStatus() {
  return useQuery({
    queryKey: ['benchmarks', 'sync-status'],
    queryFn: getSyncStatus,
    // 采集是每周级低频动作，1 分钟内不必重复拉
    staleTime: 60_000,
  });
}
