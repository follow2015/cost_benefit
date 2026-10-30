# Changelog

本文件记录本项目所有值得注意的变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

## [0.1.1] - 2026-10-30

发布形态补齐：镜像交给 CI 构建，使用者不必再本地 build。

### Added

- **预构建镜像**：`v*` tag 与 `main` 推送时自动构建后端 / 前端镜像并推送至 GHCR，
  `amd64` + `arm64` 双架构。新增 `docker-compose.dist.yml`，`up -d` 即拉即用；
  `AIROI_TAG` 可锁定版本。
- **`LICENSE`**：Apache License 2.0。

### Changed

- `backend/`、`frontend/` 增加 `.dockerignore`：构建上下文不再携带本地虚拟环境、
  `node_modules` 与 `.env`。

### Fixed

- 前端镜像构建：宿主 `node_modules` 不再覆盖镜像内依赖（原生二进制平台不匹配
  会让 `vite build` 失败 —— 本地能过、CI 必挂）。

### Removed

- `scripts/installer/`：ipip 项目的安装器误入本仓，与本项目无关，整目录删除。

## [0.1.0] - 2026-10-30

首个公开版本：AI 算力投资 ROI 测算平台 P0 全量能力 + 六边形架构后端 + 双端
高精度计算引擎（前后端镜像，以黄金向量为单一事实来源）。

### Added

**核心测算能力（P0 四大能力）**
- 三方案对比（自建 / 租用 / 第三方 API）+ 临界规模求解。
- 每百万 token 成本推导链，公式 F001–F012（`domain/calc/`）。
- 投资财务指标：TCO / ROI / NPV / IRR / 静态与折现回本 / 逐期现金流。
- 敏感性龙卷风图 + 情景分析（单因素 ±Δ 扰动，可扩展联合网格）。

**计算引擎**
- 前后端同源镜像实现：后端 `Decimal`（精度 34 / `ROUND_HALF_UP`），前端 `decimal.js`。
- `goldenVectors.json` 作为单一事实来源：15 案例 × 111 路径 = 1665 断言，双端偏差 ≤ 0.1%。
- 前端计算在 Web Worker 中执行，避免阻塞 UI；结果随 `client_kpis` 回传后端做权威比对。

**架构（六边形 + feature-based）**
- 后端五层：`domain`（纯领域，零框架依赖）/ `application`（use_cases + ports）/ `infrastructure`（db / repositories / redis / security / reports）/ `interfaces`（HTTP）/ `shared`。
- 架构契约由 `import-linter` 的 5 份 L1–L5 契约钉住（CI 中 `lint-imports` 必须 KEPT）。
- 前端 16 个 feature 包 + `app` 外壳 + `shared` 跨特性层。

**数据与基准**
- PostgreSQL 16：JSONB + RLS 多租户隔离（UoW 进入时 `SET LOCAL app.tenant_id`）+ `cashflow_row` 哈希分区。
- Alembic 全量幂等迁移（建表 + RLS + 分区）。
- InferenceX（SemiAnalysis）基准库：模型 × 硬件 × 场景 → 市场公允成本，支持权威三源投票、差异预览、版本发布与事件化回滚、双周自动采集与手动触发。

**工程与质量**
- 后端 `pytest` 218 passed（含真 PG 集成），前端 `vitest` 115 passed，Playwright e2e 22 passed。
- 三类导出：PDF / Excel / 信创报告（e2e 校验真实文件头）。
- 交付管线：`scripts/sync-to-deploy.sh`（HEAD 快照 + 白名单 + 机密扫描 + 残留清理 + 前进性守卫）。

### Changed

- 前端依赖追平设计目标：React 19.3.1 / AntD 6.6.8 / Vite 8.3.5 / TypeScript 7.0.2 / React Router 7.18.4 / Vitest 5.0.5。
- 路由级代码分割：首屏 gzip 984 KB → 413 KB；结果页 1044 KB → 585 KB（ECharts 按需）；参数导入页 388 KB → 58 KB（`xlsx` 惰性加载）。
- AntD 6 弃用项清零（`Alert.message` → `title` 共 30 处，13 个页面的运行时告警归零）。

### Fixed

- 修复 `PUT /scenarios/{id}` 恒返回 500（`updated_at` 惰性加载触发 `MissingGreenlet`）。
- 修复基准库成本标杆列把 Decimal 字符串当数字用导致整页崩溃。
- 修复回本周期与利息覆盖倍数被当作百分比渲染。
- 修复 KPI 数值被从中间拆开、比率后缀冗余、结果页窄列溢出。
- 修复信创报告扩展名错配、基准库行内编辑空值提交必失败。
- 基准库按 SQLSTATE 区分完整性错误，不再把 NOT NULL 误报成唯一键冲突。

### Security

- 登录页不再展示演示账号密码。
- 容器编排与 CI 中的数据库口令改为变量插值 / CI 密钥读取，不再硬编码明文。
- 交付前强制机密扫描（公网 IP / 私钥 / 高熵 token / 明文口令 / 含密连接串），命中即中止同步。

[Unreleased]: https://github.com/follow2015/cost_benefit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/follow2015/cost_benefit/releases/tag/v0.1.0
