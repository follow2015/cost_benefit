# AI 算力投资 ROI 测算平台

[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](CHANGELOG.md)

给 AI 算力投资算一笔明白账：**自建 GPU 集群、租用算力、第三方 API** 三条路线放在同一把尺子上量，
输出每百万 token 的真实成本、投资回收路径，以及「在什么规模下哪条路更便宜」的临界点。

> 当前版本 v0.1.0 · 变更见 [CHANGELOG.md](CHANGELOG.md)

贯穿全链路的四条口径约定，也是与别人对账的前提：

| 约定 | 说明 |
|---|---|
| **CNY 本位币** | 美元输入按配置汇率折算，USD 原值一并保留便于核对 |
| **税前口径** | 所有收益、成本、比率均为税前；税负作为独立参数参与现金流 |
| **利用率 U** | 统一定义为 *有效负载 / 满负荷产能*，不混用「在线率」「峰值利用率」 |
| **范围边界** | 聚焦成本与投资回收测算，不含容量规划与调度仿真 |

## 它解决什么问题

「一张 GPU 一天多少钱」很好问，「一个 token 到底该卖多少钱、这笔投资几年回本」很难答。
难点不在乘除法，而在三件事：

1. **成本是推导出来的，不是抄来的**。显存装不装得下 batch、TPOT/TTFT 满足不满足 SLA、
   上下文长度把 KV cache 撑到什么程度 —— 每一环都会改变每 token 成本。
2. **两条路线不可直接比单价**。自建有 CAPEX 和折旧，租用是 OPEX，第三方 API 按量计费；
   规模一变排序就变。
3. **结论要能复核**。每个数字都能追回它的输入参数与公式，换个人算应当得到同一个结果。

## 核心能力

| 能力 | 说明 |
|---|---|
| ① 三方案对比 + 临界规模 | 自建 / 租用 / API 成本曲线，求规模意义上的交叉点 |
| ② 每百万 token 成本推导链 | 从硬件规格、模型参数、SLA 约束一路推到单位成本 |
| ③ 投资财务指标 | TCO / ROI / NPV / IRR / 静态与折现回本 / 逐期现金流 |
| ④ 敏感性与情景分析 | 龙卷风图、单因素 ±Δ 扰动、多情景对比 |

还有几个容易被忽略、但会直接改变结论的约束：

- **KV cache 容量约束**：可用 batch 不是 `B_max`，而是取 `B_max` 与「显存余量 ÷（每 token KV × 上下文）」
  的较小者 —— 显存不够时吞吐被硬压下来。
- **长上下文成本曲线**：上下文越长，单位 token 成本按 `1 + K·max(Ctx/8192 − 1, 0)·(1 − 缓存命中率)` 抬升，
  缓存命中率是抵消它的唯一杠杆。
- **投机解码**：MTP / STP / EAGLE 提升每 token 有效吞吐，等效放宽 SLA 的 TPOT 约束，从而吃下更大 batch。
- **场景预设**：AgentX（超长输入、极高缓存命中）与 8K/1K 短上下文两类典型负载可一键套用。

## 快速开始

### 方式一：Docker Compose（最快看到界面）

```bash
docker compose up -d --build            # PG16 :5432 + 后端 :8000 + 前端 :5173
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed
```

打开 http://localhost:5173 ，账号 `demo@airoi.dev`。
**密码由 seed 在创建时随机生成并打印一次**（输出里 `====` 包起来的那段），仓库里没有明文口令。

想自己指定就先传环境变量（至少 12 位）：

```bash
SEED_DEMO_PASSWORD='<你的强密码>' docker compose exec -e SEED_DEMO_PASSWORD backend python -m scripts.seed
```

遗忘或轮换：`docker compose exec backend python -m scripts.seed --reset-password`。
（账号已存在时 seed 默认**不动密码**，重跑不会把人工改过的密码打回去。）

> 端口偏移的 v2 栈（PG 5433 / Redis 6380 / 后端 8001 / 前端 5174，可与 v1 并存）：
> `docker compose -f docker-compose.v2.yml up -d --build`。Redis 未启动时相关能力自动降级。

### 方式二：本地运行

环境要求：**Python 3.14**、**Node ^22.12 || ^24 || >=26**、PostgreSQL 16（Redis 可选）。

```bash
# 后端
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -e backend --no-deps
cp backend/.env.example backend/.env      # 改 DATABASE_URL 等
cd backend && alembic upgrade head && python -m scripts.seed
uvicorn ai_roi.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
cp .env.example .env.local
npm run dev                               # http://localhost:5173
```

也可以用 Makefile：`make venv install migrate seed be-dev`（`make help` 列出全部任务）。

## 配置

后端读 `backend/.env`（示例见 `backend/.env.example`），关键项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://airoi:airoi_dev@localhost:5433/airoi` | 异步连接串；也可用 `POSTGRESQL_*` 组合 |
| `APP_ENV` | `dev` | `prod`/`production` 下会强制校验：仍用仓库示例 `JWT_SECRET` 就**拒绝启动** |
| `JWT_SECRET` | 示例值 | 生产必须替换（HS256 的密钥就是签名凭据） |
| `ENABLE_API_DOCS` | 按 `APP_ENV` 推断 | `dev` 开，其余关；文档页等于公开全部路径与鉴权方式 |
| `INFERENCEX_SYNC_INTERVAL_DAYS` | `7` | 基准数据自动采集周期 |
| `INFERENCEX_FX_USD_CNY` | `7.2` | 基准数据折算汇率 |

前端读 `frontend/.env.local`（示例见 `frontend/.env.example`）：`VITE_API_BASE`、`VITE_API_PROXY`、
`FRONTEND_PORT`、`FRONTEND_HOST`。

> 前端变量会**编译进产物**，浏览器能读到 —— 不要放密钥或演示密码。

## 数据来源

成本标杆（用于单价亏损告警与标杆偏离告警）来自
**[inferencex.semianalysis.com](https://inferencex.semianalysis.com)**——SemiAnalysis 的推理基准平台。
采集打的是它看板的数据接口 `/api/v1/overview`，而不是抓页面（站点客户端渲染，HTML 里没有数值）。

口径：`costPerMtok` 是 **USD / 百万总 token**（prefill + decode + cache），属于 hyperscaler 最优
serving 包络的**成本侧**，不是对外售价；落库前按汇率折成 CNY，USD 原值保留。

标杆可定时自动采集（周期由 `INFERENCEX_SYNC_INTERVAL_DAYS` 控制），也可在基准库页点「立即采集」，
或命令行 `make sync-benchmarks`。**拉取失败不清空已有数据**，只记录失败原因，页面上仍是上次成功值。

## 已知限制

- **未声明开源许可证**：仓库暂无 `LICENSE`，默认保留所有权利。确定许可证后再声明可用范围。
- **演示数据是示例值**：种子数据的量级用于跑通链路，不是真实报价；生产需接入权威基准源。
- **敏感性与情景默认单因素**：±Δ 扰动为主；蒙特卡洛与联合网格已实现但默认关闭。
- **多租户隔离依赖数据库行级安全策略**：超管通道仅运维使用，无界面入口。
- **部署模板中的域名与 IP 为占位值**（如 `203.0.113.10` 属 RFC5737 文档网段），需按实际环境替换。

## 许可

本项目尚未声明开源许可证（仓库内无 `LICENSE` 文件）。在补充许可证之前，请按「保留所有权利」对待。
