# 后端镜像（FastAPI + asyncpg + Alembic）· Python 3.14 基线，不可降级
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# src 布局：可编辑安装使 ai_roi 主包可导入（六边形架构唯一包，无兼容层）
RUN pip install --no-cache-dir -e . --no-deps

# 默认不自动迁移；启动前请执行 `alembic upgrade head` 与 `python -m scripts.seed`
EXPOSE 8000

CMD ["uvicorn", "ai_roi.main:app", "--host", "0.0.0.0", "--port", "8000"]
