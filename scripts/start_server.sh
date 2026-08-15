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
WEB_PID_FILE="${RUN_DIR}/web.pid"
WEB_LOG_FILE="${LOG_DIR}/web.log"
LOG_MAX_BYTES="${KARKINOS_LOG_MAX_BYTES:-20971520}"
FRONTEND_HOST="${KARKINOS_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${KARKINOS_FRONTEND_PORT:-5173}"

usage() {
	cat <<EOF
Usage:
  ./scripts/start_server.sh [dev|prod] [extra server args...]

Examples:
  ./scripts/start_server.sh
  ./scripts/start_server.sh dev
  ./scripts/start_server.sh prod
  ./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
  ./scripts/start_server.sh prod --host 0.0.0.0 --port 9000

Notes:
  - This script starts the Web service via \`python -m server\` in the background.
  - \`dev\` defaults to \`--reload\`; it does not enable live monitoring.
  - \`dev\` also starts the Vite frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}.
  - \`prod\` starts without hot reload and does not enable live monitoring.
  - Enable live monitoring explicitly with server.live_auto_start=true or KARKINOS_LIVE_AUTO_START=true.
  - Output is redirected to \`logs/server.log\` and \`logs/web.log\`.
  - Logs larger than KARKINOS_LOG_MAX_BYTES (default 20 MiB) are archived before startup.
  - PIDs are written to \`.run/server.pid\` and \`.run/web.pid\` in \`dev\` mode.
  - It installs missing frontend dependencies before building.
  - Run \`uv run python scripts/configure_data_source.py\` to configure local market data.
EOF
}

ensure_frontend_dependencies() {
	local web_dir="${REPO_ROOT}/web"

	if [[ ! -f "${web_dir}/package.json" ]]; then
		echo "Error: web/package.json was not found." >&2
		exit 1
	fi

	if [[ -x "${web_dir}/node_modules/.bin/vite" && -f "${web_dir}/node_modules/vitest/globals.d.ts" ]]; then
		return
	fi

	echo "Frontend dependencies are missing or incomplete; running npm install"
	pushd "${web_dir}" >/dev/null
	npm install
	popd >/dev/null
}

guide_data_source_configuration() {
	local config_path="${KARKINOS_CONFIG_PATH:-config.json}"

	if [[ -f "${config_path}" || -n "${KARKINOS_TUSHARE_TOKEN:-}" ]]; then
		return
	fi

	cat <<EOF
Data source: defaulting to AKShare.
Configure local market data with:
  uv run python scripts/configure_data_source.py
EOF
}

rotate_log_if_needed() {
	local log_file="$1"
	if [[ ! -f "${log_file}" ]]; then
		return
	fi
	if [[ -z "${LOG_MAX_BYTES}" || "${LOG_MAX_BYTES}" == *[!0-9]* || "${LOG_MAX_BYTES}" == "0" ]]; then
		echo "Error: KARKINOS_LOG_MAX_BYTES must be a positive integer." >&2
		exit 1
	fi

	local current_size
	current_size="$(wc -c <"${log_file}")"
	if ((current_size < LOG_MAX_BYTES)); then
		return
	fi

	local archived_log
	archived_log="${log_file}.$(date '+%Y%m%d-%H%M%S').$$"
	mv -- "${log_file}" "${archived_log}"
	echo "Archived oversized log: ${archived_log}"
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

if [[ "${MODE:-${1:-dev}}" == "dev" ]] && ! command -v npm >/dev/null 2>&1; then
	echo "Error: npm was not found in PATH." >&2
	exit 1
fi

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
	echo "Error: pyproject.toml was not found. Are you running inside the Karkinos repository?" >&2
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
NO_PROXY_ENV=(
	-u http_proxy
	-u https_proxy
	-u HTTP_PROXY
	-u HTTPS_PROXY
	-u all_proxy
	-u ALL_PROXY
	-u DEFAULT_PROXY_URL
	NO_PROXY=127.0.0.1,localhost
	no_proxy=127.0.0.1,localhost
)

backend_probe_host() {
	case "${BACKEND_HOST}" in
	0.0.0.0 | :: | \[::\])
		printf '%s' "127.0.0.1"
		;;
	*)
		printf '%s' "${BACKEND_HOST}"
		;;
	esac
}

backend_listener_pids() {
	if ! command -v lsof >/dev/null 2>&1; then
		return
	fi
	lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

karkinos_backend_is_alive() {
	if ! command -v curl >/dev/null 2>&1; then
		return 1
	fi
	local health_response
	health_response="$(
		env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
			--max-time 2 "http://$(backend_probe_host):${BACKEND_PORT}/api/health" \
			2>/dev/null
	)" || return 1
	[[ "${health_response}" == *'"schema_version":"karkinos.service_health.v1"'* && \
		"${health_response}" == *'"status":"alive"'* ]]
}

preflight_backend_port() {
	local listener_pids
	listener_pids="$(backend_listener_pids)"
	if [[ -z "${listener_pids}" ]]; then
		return
	fi

	if karkinos_backend_is_alive; then
		echo "Error: a Karkinos service is already responding at ${PRODUCT_ENTRY_URL}." >&2
	else
		echo "Error: backend port ${BACKEND_PORT} is occupied, but Karkinos liveness did not respond." >&2
	fi
	echo "Listener PID(s): ${listener_pids//$'\n'/ }" >&2
	echo "No process was terminated." >&2
	echo "Inspect the listener, then stop the tracked Karkinos instance with:" >&2
	echo "  ./scripts/stop_server.sh" >&2
	echo "Or choose another explicit port:" >&2
	echo "  ./scripts/start_server.sh ${MODE} --host ${BACKEND_HOST} --port <port>" >&2
	exit 1
}

case "${MODE}" in
	dev)
		shift || true
		SERVER_ARGS=(--reload --reload-exclude 'tests/**' --reload-exclude 'web/**' "$@")
		;;
	prod)
		shift || true
		SERVER_ARGS=("$@")
		;;
	-*)
		MODE="dev"
		SERVER_ARGS=(--reload --reload-exclude 'tests/**' --reload-exclude 'web/**' "$@")
		;;
	*)
		echo "Error: unknown mode '${MODE}'." >&2
		echo >&2
		usage >&2
		exit 1
		;;
esac

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
for ((i = 0; i < ${#SERVER_ARGS[@]}; i++)); do
	case "${SERVER_ARGS[$i]}" in
		--host)
			if ((i + 1 < ${#SERVER_ARGS[@]})); then
				BACKEND_HOST="${SERVER_ARGS[$((i + 1))]}"
			fi
			;;
		--port)
			if ((i + 1 < ${#SERVER_ARGS[@]})); then
				BACKEND_PORT="${SERVER_ARGS[$((i + 1))]}"
			fi
			;;
	esac
done
PRODUCT_ENTRY_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
HOT_RELOAD_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
	EXISTING_PID="$(cat "${PID_FILE}")"
	if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" >/dev/null 2>&1; then
		echo "Error: Karkinos Web service is already running with PID ${EXISTING_PID}." >&2
		if karkinos_backend_is_alive; then
			echo "The process-liveness endpoint is responding at ${PRODUCT_ENTRY_URL}." >&2
		else
			echo "The tracked process exists, but its process-liveness endpoint is unavailable." >&2
		fi
		echo "No process was terminated. Stop it explicitly with ./scripts/stop_server.sh" >&2
		exit 1
	fi
	rm -f "${PID_FILE}"
fi

if [[ "${MODE}" == "dev" && -f "${WEB_PID_FILE}" ]]; then
	EXISTING_WEB_PID="$(cat "${WEB_PID_FILE}")"
	if [[ -n "${EXISTING_WEB_PID}" ]] && kill -0 "${EXISTING_WEB_PID}" >/dev/null 2>&1; then
		echo "Error: Karkinos Web frontend is already running with PID ${EXISTING_WEB_PID}." >&2
		echo "No process was terminated. Stop it explicitly with ./scripts/stop_server.sh" >&2
		exit 1
	fi
	rm -f "${WEB_PID_FILE}"
fi

preflight_backend_port
rotate_log_if_needed "${LOG_FILE}"
if [[ "${MODE}" == "dev" ]]; then
	rotate_log_if_needed "${WEB_LOG_FILE}"
fi

if [[ "${MODE}" == "dev" ]]; then
	echo "Building product frontend bundle for ${PRODUCT_ENTRY_URL}"
	echo "Frontend build command: npm run build"
	ensure_frontend_dependencies
	pushd "${REPO_ROOT}/web" >/dev/null
	npm run build
	popd >/dev/null
elif [[ ! -f "${REPO_ROOT}/web/dist/index.html" ]]; then
	cat >&2 <<EOF
Warning: web/dist/index.html was not found.
The backend API will start, but ${PRODUCT_ENTRY_URL} cannot serve the product UI until the frontend is built.
Build it with:
  cd web && npm run build
EOF
fi

guide_data_source_configuration

echo "Mode: ${MODE}"
echo "Starting Karkinos Web service from ${REPO_ROOT}"
echo "Log file: ${LOG_FILE}"
echo "Command: UV_CACHE_DIR=${UV_CACHE_DIR:-.uv-cache} uv run python -m server ${SERVER_ARGS[*]-}"

if command -v setsid >/dev/null 2>&1; then
	setsid nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run python -m server ${SERVER_ARGS[@]+"${SERVER_ARGS[@]}"} >>"${LOG_FILE}" 2>&1 &
else
	nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run python -m server ${SERVER_ARGS[@]+"${SERVER_ARGS[@]}"} >>"${LOG_FILE}" 2>&1 &
fi

LAUNCH_PID=$!
TRACKED_PID="${LAUNCH_PID}"

sleep 1
CHILD_PID="$(pgrep -P "${LAUNCH_PID}" | tail -n 1 || true)"
if [[ -n "${CHILD_PID}" ]]; then
	TRACKED_PID="${CHILD_PID}"
fi

echo "${TRACKED_PID}" >"${PID_FILE}"

if ! kill -0 "${TRACKED_PID}" >/dev/null 2>&1; then
	echo "Error: Karkinos Web service failed to start. Check ${LOG_FILE}" >&2
	rm -f "${PID_FILE}"
	exit 1
fi

echo "Karkinos Web service started with PID ${TRACKED_PID}"
if [[ -f "${REPO_ROOT}/web/dist/index.html" ]]; then
	echo "Product entry: ${PRODUCT_ENTRY_URL}"
	echo "Page refresh and direct links are served from web/dist via FastAPI."
fi

if [[ "${MODE}" != "dev" ]]; then
	exit 0
fi

echo "Starting Karkinos Web frontend from ${REPO_ROOT}/web"
echo "Frontend log file: ${WEB_LOG_FILE}"
echo "Frontend command: npm run dev -- --host ${FRONTEND_HOST} --port ${FRONTEND_PORT}"
echo "Hot-reload frontend: ${HOT_RELOAD_URL}"
echo "Use ${PRODUCT_ENTRY_URL} for product-like customer flow; use ${HOT_RELOAD_URL} only while editing frontend code."

pushd "${REPO_ROOT}/web" >/dev/null
if command -v setsid >/dev/null 2>&1; then
	setsid nohup npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >>"${WEB_LOG_FILE}" 2>&1 &
else
	nohup npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >>"${WEB_LOG_FILE}" 2>&1 &
fi
WEB_LAUNCH_PID=$!
popd >/dev/null

TRACKED_WEB_PID="${WEB_LAUNCH_PID}"
sleep 1
WEB_CHILD_PID="$(pgrep -P "${WEB_LAUNCH_PID}" | tail -n 1 || true)"
if [[ -n "${WEB_CHILD_PID}" ]]; then
	TRACKED_WEB_PID="${WEB_CHILD_PID}"
fi

echo "${TRACKED_WEB_PID}" >"${WEB_PID_FILE}"

if ! kill -0 "${TRACKED_WEB_PID}" >/dev/null 2>&1; then
	echo "Error: Karkinos Web frontend failed to start. Check ${WEB_LOG_FILE}" >&2
	rm -f "${WEB_PID_FILE}"
	exit 1
fi

cat <<EOF
Karkinos dev environment started.
Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}
Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}

Use ./scripts/stop_server.sh to stop both processes.
EOF
