# 前端（AI 算力投资 ROI 测算平台）

React 18 + AntD 5 + Vite 6 + TypeScript 5 单页应用。计算核心为 `src/features/calc/engine/` 下的 **decimal.js** 镜像实现，与后端 Python 引擎逐公式对齐，并以 `goldenVectors.json` 为一致性判据（偏差 ≤ 0.1%）。

## 技术选型（就近稳定版，非 GA 预发布）

| 模块 | 版本 |
|------|------|
| React | 18.3 |
| TypeScript | 5.7 |
| Vite | 6 |
| Ant Design | 5.22 |
| Zustand | 5 |
| TanStack Query | 5.62 |
| React Router | 6.28 |
| axios | 1.7 |
| decimal.js | 10.4 |
| echarts / echarts-for-react | 5.5 / 3 |
| vitest / esbuild | 2.1 / 0.24 |

> 原始设想的 React 19 / TS 6 / Vite 8 尚未 GA，按「先可运行」原则选用上述稳定版。

## 脚本

```bash
npm install
npm run dev            # 开发服务器（默认 5173，/api 代理到 VITE_API_PROXY）
npm run build          # tsc --noEmit 类型检查 + vite 生产构建
npm run preview        # 预览构建产物
npm test               # 运行双端一致性测试（vitest）
npm run verify:golden  # esbuild 打包引擎 + 黄金向量，输出偏差统计
npm run lint           # tsc --noEmit
```

## 目录结构（feature-based）

```
src/
├── app/                     # 应用外壳：入口 / 路由 / Provider / 布局 / 守卫
│   ├── main.tsx  router.tsx  providers.tsx  errorBoundary.tsx
│   ├── layouts/AppLayout.tsx      # 侧边导航 + 公式抽屉挂载
│   ├── guards/RequireAuth.tsx     # 未登录重定向 /login
│   └── styles/index.css
├── features/                # 业务特性包（每包自含 pages/api/hooks/stores/components）
│   ├── auth/                # 登录 / 鉴权状态 / 鉴权 API
│   ├── workbench/           # 工作台首页
│   ├── scenario-wizard/     # 参数向导（录入 + 基准预填 + 实时预览）
│   ├── result/              # 结果页 + 8 类图表（现金流 / 成本结构 / 盈亏平衡 /
│   │                         # 交叉点 / 自定义情景 / 联合敏感性 / 蒙特卡洛 / 龙卷风）
│   ├── compare/  versions/  # 方案对比 / 版本历史
│   ├── reports/  scenarios/ # 报告 / 方案管理（CRUD + 草稿 store + Query hooks）
│   ├── benchmarks/          # GPU / 模型 / 云 / API 价格基准
│   ├── network-catalog/  network-bom/      # 网络设备目录 / BOM 估算
│   ├── throughput/  hardware-recommend/   # 吞吐测算 / 硬件推荐
│   ├── builder/  import-params/  tenant/   # 自建测算 / 参数导入 / 租户与成员
│   └── calc/                # 计算特性（领域引擎 + API + hooks）
│       ├── engine/          # 高精度引擎（decimalConfig / parameters / engine 编排 /
│       │                    #   worker 实时重算 / codec 编解码 / formulaSpec 公式）
│       ├── api/             # calcApi（后端权威引擎）+ calcClient（worker 编排）
│       └── hooks/useCalc.ts
└── shared/                  # 跨特性共享（禁止被 features 反向依赖的叶子）
    ├── api/client.ts        # Axios 客户端（JWT + X-Tenant-Id 拦截器、401 自动刷新、统一响应解包）
    ├── types/index.ts       # 前后端 DTO 契约（Decimal 全部以字符串出入 JSON）
    ├── ui/                  # PageHeader / StatCard / FormulaDrawer（ⓘ 口径溯源）/ HardwareBomCard / uiStore
    └── theme/               # AntD 主题令牌 + 设计令牌
```

## 环境变量（`.env.example` → `.env.local`）

- `VITE_API_BASE`：后端基地址（默认 `http://localhost:8000`）
- `VITE_API_PROXY`：开发服务器 `/api` 代理目标
- `FRONTEND_PORT`：开发端口
- `VITE_MAX_DEVIATION`：双端偏差告警阈值（默认 0.001）

## 计算一致性

前端在 **Web Worker** 中运行 `computeAll`，向导侧边「实时预览」以 ≤500ms 防抖重算；保存并计算时把前端 KPI 作为 `client_kpis` 回传后端，由权威引擎比对并回写 `client_deviation`。一致性测试：

```bash
npx vitest run src/features/calc/engine/__tests__/consistency.test.ts
```

## 启动依赖

需先启动后端（见根目录 README）并建表+种子。前端 `npm run dev` 通过 Vite 代理把 `/api` 转发到后端 8000。
