# ---- Stage 1: Build React frontend ----
FROM node:24.20.0-alpine3.24@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src/ ./src/
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12.13-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

ARG UV_VERSION=0.11.28
ARG VERSION=dev

LABEL org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.source="https://github.com/imReese/Karkinos" \
    org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:${PATH} \
    KARKINOS_WORKSPACE=/app \
    KARKINOS_CONFIG_PATH=/app/config.json \
    KARKINOS_DATA_DIR=/app/data/store \
    KARKINOS_HOST=0.0.0.0 \
    KARKINOS_PORT=8000

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# Keep the runtime image limited to locked packaging metadata and production
# Python packages. README and LICENSE are required by the package build;
# private configuration and local runtime evidence are never build inputs.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY account_truth/ ./account_truth/
COPY analytics/ ./analytics/
COPY backtest/ ./backtest/
COPY core/ ./core/
COPY data/ ./data/
COPY domain/ ./domain/
COPY execution/ ./execution/
COPY notification/ ./notification/
COPY risk/ ./risk/
COPY server/ ./server/
COPY strategy/ ./strategy/
COPY --from=frontend-build /app/web/dist /app/web/dist

RUN uv sync --locked --extra server --no-dev && \
    useradd --create-home --shell /bin/bash karkinos && \
    mkdir -p /app/data/store && \
    chown -R karkinos:karkinos /app

USER karkinos

VOLUME ["/app/data/store"]

EXPOSE 8000

CMD ["python", "-m", "server"]
