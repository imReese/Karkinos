# ---- Stage 1: 构建 Vue 前端 ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build    # 输出到 web/dist/

# ---- Stage 2: Python 运行时 ----
FROM python:3.12-slim
WORKDIR /app

# 安装 uv（比 pip 快）
RUN pip install uv

# 复制依赖文件并安装
COPY pyproject.toml ./
RUN uv pip install --system -e ".[server]"

# 复制源码
COPY . .

# 从 Stage 1 复制前端构建产物
COPY --from=frontend-build /app/web/dist /app/web/dist

# 数据持久化卷
VOLUME /app/data/store

EXPOSE 8000

CMD ["python3", "-m", "server"]
