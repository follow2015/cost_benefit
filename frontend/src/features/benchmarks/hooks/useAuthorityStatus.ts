/** 权威同步现状 hook。
 *
 * 与 `useSyncStatus` 并列：一个管成本标杆（InferenceX），一个管 API 价
 * （三源投票），两者是**互相独立的两条数据链路**，界面与刷新也各自独立。
 */
import { useQuery } from '@tanstack/react-query';
import { getAuthorityStatus } from '@/features/benchmarks/api/benchmarksApi';

export function useAuthorityStatus() {
  return useQuery({
    queryKey: ['benchmarks', 'authority-status'],
    queryFn: getAuthorityStatus,
    // 纯读本库，代价很低；但同步动作本身低频，30 秒内不必重复拉
    staleTime: 30_000,
  });
}
