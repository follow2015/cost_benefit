/** 路由表。鉴权保护由 RequireAuth 守卫；公开仅 /login。
 *
 * 代码分割：除应用骨架（AppLayout / RequireAuth）外，16 个页面全部改为
 * `React.lazy` 按需加载，使首屏只下载骨架与当前页，而非一次性拉入
 * antd + echarts + xlsx 全量依赖（改前主 chunk 约 3.0 MB / gzip 984 KB）。
 */
import React, { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '@/app/layouts/AppLayout';
import { RequireAuth } from '@/app/guards/RequireAuth';
import { PageLoading } from '@/shared/ui/PageLoading';

/** 把动态 import 包装为带 Suspense 兜底的路由元素。
 *  须在模块顶层调用：`lazy()` 若在渲染期重复执行会生成新组件类型，导致子树反复卸载重建。
 */
function page(loader: () => Promise<{ default: React.ComponentType }>): React.ReactElement {
  const Component = lazy(loader as () => Promise<{ default: React.ComponentType<object> }>);
  return (
    <Suspense fallback={<PageLoading />}>
      <Component />
    </Suspense>
  );
}

const Login = page(() => import('@/features/auth/pages/LoginPage'));
const Workbench = page(() => import('@/features/workbench/pages/WorkbenchPage'));
const Wizard = page(() => import('@/features/scenario-wizard/pages/WizardPage'));
const Result = page(() => import('@/features/result/pages/ResultPage'));
const ComparePage = page(() => import('@/features/compare/pages/ComparePage'));
const Benchmarks = page(() => import('@/features/benchmarks/pages/BenchmarksPage'));
const Reports = page(() => import('@/features/reports/pages/ReportsPage'));
const Versions = page(() => import('@/features/versions/pages/VersionsPage'));
const Tenant = page(() => import('@/features/tenant/pages/TenantPage'));
const ThroughputCalc = page(() => import('@/features/throughput/pages/ThroughputPage'));
const HardwareRecommend = page(() => import('@/features/hardware-recommend/pages/HardwareRecommendPage'));
const Builder = page(() => import('@/features/builder/pages/BuilderPage'));
const ImportParams = page(() => import('@/features/import-params/pages/ImportParamsPage'));
const NetworkCatalog = page(() => import('@/features/network-catalog/pages/NetworkCatalogPage'));
const NetworkBomEstimator = page(() => import('@/features/network-bom/pages/NetworkBomPage'));

export const router = createBrowserRouter([
  { path: '/login', element: Login },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: Workbench },
      { path: 'scenarios/new', element: Wizard },
      { path: 'scenarios/:id/edit', element: Wizard },
      { path: 'scenarios/:id', element: Result },
      { path: 'scenarios/:id/compare', element: ComparePage },
      { path: 'scenarios/:id/versions', element: Versions },
      { path: 'reports/:id', element: Reports },
      { path: 'benchmarks', element: Benchmarks },
      { path: 'network-catalog', element: NetworkCatalog },
      { path: 'network-bom', element: NetworkBomEstimator },
      { path: 'throughput', element: ThroughputCalc },
      { path: 'builder', element: Builder },
      { path: 'recommend', element: HardwareRecommend },
      { path: 'import', element: ImportParams },
      { path: 'tenant', element: Tenant },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
