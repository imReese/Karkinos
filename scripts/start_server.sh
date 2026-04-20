#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${HOME}/.local/bin/env" ]]; then
  # Load user-local PATH updates so `uv` is discoverable when installed via official script.
  # shellcheck disable=SC1091
  source "${HOME}/.local/bin/env"
fi

cd "${REPO_ROOT}"

RUN_DIR="${REPO_ROOT}/.run"
LOG_DIR="${REPO_ROOT}/logs"
PID_FILE="${RUN_DIR}/server.pid"
LOG_FILE="${LOG_DIR}/server.log"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/start_server.sh [dev|prod] [extra server args...]

Examples:
  ./scripts/start_server.sh
  ./scripts/start_server.sh dev
  ./scripts/start_server.sh prod
  ./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
  ./scripts/start_server.sh prod --no-live
  ./scripts/start_server.sh prod --host 0.0.0.0 --port 9000

Notes:
  - This script starts the Web service via `python -m server` in the background.
  - `dev` defaults to `--reload --no-live`.
  - `prod` starts without hot reload and preserves server defaults unless extra args are passed.
  - Output is redirected to `logs/server.log`.
  - PID is written to `.run/server.pid`.
  - It does not install dependencies automatically.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' was not found in PATH." >&2
  echo "Install uv first, or make sure \$HOME/.local/bin/env exists and is loadable." >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
  echo "Error: pyproject.toml was not found. Are you running inside the MyQuant repository?" >&2
  exit 1
fi

if ! UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" uv run python -c "import fastapi, uvicorn, aiosqlite, websockets" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Error: server dependencies are not installed.

Install them with:
  source $HOME/.local/bin/env
  UV_CACHE_DIR=.uv-cache uv sync --extra server --extra dev

If you do not need dev dependencies, this is enough:
  source $HOME/.local/bin/env
  UV_CACHE_DIR=.uv-cache uv sync --extra server
EOF
  exit 1
fi

MODE="${1:-dev}"
case "${MODE}" in
  dev)
    shift || true
    SERVER_ARGS=(--reload --no-live "$@")
    ;;
  prod)
    shift || true
    SERVER_ARGS=("$@")
    ;;
  -*)
    MODE="dev"
    SERVER_ARGS=(--reload --no-live "$@")
    ;;
  *)
    echo "Error: unknown mode '${MODE}'." >&2
    echo >&2
    usage >&2
    exit 1
    ;;
esac

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}")"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" >/dev/null 2>&1; then
    echo "Error: MyQuant Web service is already running with PID ${EXISTING_PID}." >&2
    echo "Stop it first with ./scripts/stop_server.sh" >&2
    exit 1
  fi
  rm -f "${PID_FILE}"
fi

echo "Mode: ${MODE}"
echo "Starting MyQuant Web service from ${REPO_ROOT}"
echo "Log file: ${LOG_FILE}"
echo "Command: UV_CACHE_DIR=${UV_CACHE_DIR:-.uv-cache} uv run python -m server ${SERVER_ARGS[*]}"

if command -v setsid >/dev/null 2>&1; then
  setsid nohup env UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
    uv run python -m server "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
else
  nohup env UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
    uv run python -m server "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
fi

LAUNCH_PID=$!
TRACKED_PID="${LAUNCH_PID}"

sleep 1
CHILD_PID="$(pgrep -P "${LAUNCH_PID}" | tail -n 1 || true)"
if [[ -n "${CHILD_PID}" ]]; then
  TRACKED_PID="${CHILD_PID}"
fi

echo "${TRACKED_PID}" > "${PID_FILE}"

if ! kill -0 "${TRACKED_PID}" >/dev/null 2>&1; then
  echo "Error: MyQuant Web service failed to start. Check ${LOG_FILE}" >&2
  rm -f "${PID_FILE}"
  exit 1
fi

echo "MyQuant Web service started with PID ${TRACKED_PID}"
