# ---- Stage 1: Build Vue frontend ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KARKINOS_CONFIG_PATH=/app/config.json \
    KARKINOS_DATA_DIR=/app/data/store \
    KARKINOS_HOST=0.0.0.0 \
    KARKINOS_PORT=8000

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY . .
COPY --from=frontend-build /app/web/dist /app/web/dist

RUN uv pip install --system ".[server]" && \
    useradd --create-home --shell /bin/bash karkinos && \
    mkdir -p /app/data/store && \
    chown -R karkinos:karkinos /app

USER karkinos

VOLUME ["/app/data/store"]

EXPOSE 8000

CMD ["python", "-m", "server"]
