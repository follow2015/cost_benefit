# AI 算力投资经济性测算平台 · 一键开发入口（redesign 基线）
# 环境硬约束：Python 3.14 / Node 26.7 / PostgreSQL 16 / Redis —— 不准降级
#
# 用法：make <target>

# 虚拟环境自适应：优先 .venv（当前基线），兼容历史的 .venv314。
# 之前写死 .venv314，重建环境时若命名不同，`make` 的每个目标都会指向不存在的
# 解释器，报错是「no such file」而不是「venv 没建」——排查成本不必要地高。
VENV    ?= $(firstword $(wildcard .venv .venv314))
PY      ?= $(VENV)/bin/python
PIP     ?= $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.DEFAULT_GOAL := help
.PHONY: help env-check venv install be-test be-dev fe-install fe-test fe-verify \
        docker-up docker-down docker-logs seed migrate lint contract arch smoke

help: ## 显示本帮助
	@# 两个 BSD grep 坑必须避开：① 字符类里的 `-` 放最前；② 不能写 `.*?## `，
	@# `*?` 是 PCRE 的非贪婪语法，BSD ERE 会报 "repetition-operator operand invalid"，
	@# 整个 help 目标就哑了（而它通常是新人敲的第一条 make）。
	@grep -E '^[-a-zA-Z_]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------- 环境 ----------
env-check: ## 运行环境自检脚本（若存在；该脚本属开发仓内部件，公开仓不含）
	@if [ -x .codebuddy/skills/ipip-env-bootstrap/scripts/env_check.sh ]; then \
		bash .codebuddy/skills/ipip-env-bootstrap/scripts/env_check.sh; \
	else \
		echo "⏭  跳过：env_check.sh 不在本仓（公开交付仓按白名单排除了 .codebuddy/）"; \
	fi

venv: ## 创建 .venv（Python 3.14）
	python3.14 -m venv .venv

install: ## 安装后端依赖，并以 editable 方式注册 ai_roi 包
	$(PIP) install -r backend/requirements.txt
	@# 依赖与「包安装」是两件事：src 布局下不装项目本身，alembic/lint-imports
	@# 这类独立进程 import 不到 ai_roi（CI 首次跑就死在这里）。--no-deps：版本
	@# 由 requirements.txt 钉死，此处只做注册。与 backend/Dockerfile 同口径。
	cd backend && ../$(PY) -m pip install -e . --no-deps

# ---------- 后端 ----------
be-test: ## 后端全量测试（含计算引擎黄金向量）
	cd backend && ../$(PY) -m pytest -q

be-dev: ## 后端开发服务器（热重载）
	cd backend && ../$(UVICORN) ai_roi.main:app --reload --port 8000

migrate: ## 执行 Alembic 迁移
	cd backend && ../$(PY) -m alembic upgrade head

seed: ## 灌入种子数据
	cd backend && ../$(PY) -m scripts.seed

sync-benchmarks: ## 手动采集一次 InferenceX 基准（后台任务每 7 天也会自动跑）
	cd backend && ../$(PY) -m scripts.sync_inferencex

lint: ## 后端静态检查（ruff，若已安装）
	-$(PY) -m ruff check backend/src

contract: ## 黄金向量契约门（Python 侧：15 案例 × 111 断言路径）
	cd backend && ../$(PY) -m pytest src/ai_roi/domain/calc/__tests__/test_consistency.py -q

arch: ## 六边形架构契约门（import-linter L1–L5）
	cd backend && ../$(PY) -c "from importlinter.cli import lint_imports_command; lint_imports_command()"

be-gate: ## 后端质量门禁全联（契约 + 架构 + 全量测试）
	$(MAKE) contract arch be-test

# ---------- 前端 ----------
fe-install: ## 安装前端依赖
	cd frontend && npm install

fe-test: ## 前端单元测试
	cd frontend && npm test

fe-verify: ## 前后端黄金向量一致性校验
	cd frontend && node scripts/verify-consistency.mjs

# ---------- 容器 ----------
docker-up: ## 启动 v2 三容器（偏移端口 5433/8001/5174，与旧栈共存）
	docker compose -f docker-compose.v2.yml up -d --build

docker-down: ## 停止 v2 三容器
	docker compose -f docker-compose.v2.yml down

docker-logs: ## 跟踪 v2 容器日志
	docker compose -f docker-compose.v2.yml logs -f

smoke: ## v2 栈健康检查（curl /api/v1/healthz，偏移端口 8001）
	curl -fsS http://localhost:8001/api/v1/healthz && echo " <- v2 后端健康"
