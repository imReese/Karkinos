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

MODE="${MODE:-${1:-dev}}"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
NATIVE_ENTRYPOINT="${KARKINOS_HOME_PATH}/current/bin/karkinos"
NATIVE_RELEASE_DIR=""
USE_NATIVE_RELEASE=false
if [[ "${MODE}" == "prod" && (-L "${KARKINOS_HOME_PATH}/current" || -e "${KARKINOS_HOME_PATH}/current") ]]; then
	if [[ "${KARKINOS_HOME_PATH}" != /* || ! -L "${KARKINOS_HOME_PATH}/current" || ! -x "${NATIVE_ENTRYPOINT}" ]]; then
		echo "Error: current native release must be an executable release symlink." >&2
		exit 1
	fi
	NATIVE_RELEASE_DIR="$(CDPATH='' cd -- "${KARKINOS_HOME_PATH}/current" && pwd -P)"
	NATIVE_RELEASE_NAME="${NATIVE_RELEASE_DIR##*/}"
	if [[ "${NATIVE_RELEASE_DIR}" != "${KARKINOS_HOME_PATH}/releases/${NATIVE_RELEASE_NAME}" ||
		! "${NATIVE_RELEASE_NAME}" =~ ^sha-[0-9a-f]{40}$ ||
		! -f "${NATIVE_RELEASE_DIR}/release.json" ]]; then
		echo "Error: current native release pointer is invalid." >&2
		exit 1
	fi
	USE_NATIVE_RELEASE=true
	export KARKINOS_HOME="${KARKINOS_HOME_PATH}"
	export KARKINOS_DATA_DIR="${KARKINOS_HOME_PATH}/data"
	export KARKINOS_CONFIG_PATH="${KARKINOS_HOME_PATH}/config/config.json"
	export KARKINOS_ENV_FILE="${KARKINOS_HOME_PATH}/config/.env"
fi

if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
	RUN_DIR="${KARKINOS_HOME_PATH}/.run"
	LOG_DIR="${KARKINOS_HOME_PATH}/logs"
else
	RUN_DIR="${REPO_ROOT}/.run"
	LOG_DIR="${REPO_ROOT}/logs"
fi
PID_FILE="${RUN_DIR}/server.pid"
LOG_FILE="${LOG_DIR}/server.log"
WEB_PID_FILE="${REPO_ROOT}/.run/web.pid"
WEB_LOG_FILE="${REPO_ROOT}/logs/web.log"
LOG_MAX_BYTES="${KARKINOS_LOG_MAX_BYTES:-20971520}"
STARTUP_HEALTH_TIMEOUT_SECONDS="${KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS:-60}"
FRONTEND_STARTUP_TIMEOUT_SECONDS="${KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS:-30}"
FRONTEND_HOST="${KARKINOS_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${KARKINOS_FRONTEND_PORT:-5173}"
LAUNCH_AGENT_LABEL="com.karkinos.daily-candidate"
LAUNCH_AGENT_TARGET="gui/$(id -u)/${LAUNCH_AGENT_LABEL}"
REUSE_RESIDENT_BACKEND=false

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
  - The live scheduler starts with the backend and cannot be disabled independently.
  - Scheduler liveness does not grant broker, execution, or capital authority.
  - \`dev\` defaults to \`--reload\`.
  - \`dev\` also starts the Vite frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}.
  - If the supervised LaunchAgent is healthy, \`dev\` reuses that resident backend and starts only Vite.
  - \`prod\` treats a healthy supervised LaunchAgent as an already-running success.
  - \`prod\` starts without hot reload.
  - Output is redirected to \`logs/server.log\` and \`logs/web.log\`.
  - Logs larger than KARKINOS_LOG_MAX_BYTES (default 20 MiB) are archived before startup.
  - Startup succeeds only after process liveness and the always-on scheduler are both ready.
  - Vite startup succeeds only after its HTTP endpoint responds within the bounded frontend timeout.
  - PIDs are written to \`.run/server.pid\` and \`.run/web.pid\` in \`dev\` mode.
  - It installs missing frontend dependencies before building.
  - Run \`uv run python scripts/data/configure_data_source.py\` to configure local market data.
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
  uv run python scripts/data/configure_data_source.py
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

if [[ "${USE_NATIVE_RELEASE}" != "true" ]] && ! command -v uv >/dev/null 2>&1; then
	echo "Error: 'uv' was not found in PATH." >&2
	echo "Install uv first, or make sure \$HOME/.local/bin/env exists and is loadable." >&2
	exit 1
fi

if [[ "${MODE}" == "dev" ]] && ! command -v npm >/dev/null 2>&1; then
	echo "Error: npm was not found in PATH." >&2
	exit 1
fi

if [[ "${USE_NATIVE_RELEASE}" != "true" && ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
	echo "Error: pyproject.toml was not found. Are you running inside the Karkinos repository?" >&2
	exit 1
fi

if [[ "${USE_NATIVE_RELEASE}" != "true" ]] && ! UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" uv run python -c "import fastapi, uvicorn, aiosqlite, websockets" >/dev/null 2>&1; then
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

frontend_probe_host() {
	case "${FRONTEND_HOST}" in
	0.0.0.0 | :: | \[::\])
		printf '%s' "127.0.0.1"
		;;
	*)
		printf '%s' "${FRONTEND_HOST}"
		;;
	esac
}

backend_listener_pids() {
	if ! command -v lsof >/dev/null 2>&1; then
		return
	fi
	lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

resident_service_is_loaded() {
	[[ "$(uname -s)" == "Darwin" ]] || return 1
	command -v launchctl >/dev/null 2>&1 || return 1
	launchctl print "${LAUNCH_AGENT_TARGET}" >/dev/null 2>&1
}

karkinos_backend_is_ready() {
	if ! command -v curl >/dev/null 2>&1; then
		return 1
	fi
	local health_response
	health_response="$(
		env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
			--max-time 2 "http://$(backend_probe_host):${BACKEND_PORT}/api/health" \
			2>/dev/null
	)" || return 1
	[[ "${health_response}" == *'"schema_version":"karkinos.service_health.v1"'* &&
		"${health_response}" == *'"status":"alive"'* ]] || return 1
	local live_response
	live_response="$(
		env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
			--max-time 2 "http://$(backend_probe_host):${BACKEND_PORT}/api/settings/live/status" \
			2>/dev/null
	)" || return 1
	[[ "${live_response}" == *'"running":true'* ]]
}

vite_frontend_is_ready() {
	command -v curl >/dev/null 2>&1 || return 1
	env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
		--max-time 2 --output /dev/null \
		"http://$(frontend_probe_host):${FRONTEND_PORT}/" 2>/dev/null
}

validate_startup_health_timeout() {
	if [[ -z "${STARTUP_HEALTH_TIMEOUT_SECONDS}" ||
		"${STARTUP_HEALTH_TIMEOUT_SECONDS}" == *[!0-9]* ||
		"${STARTUP_HEALTH_TIMEOUT_SECONDS}" == "0" ||
		"${STARTUP_HEALTH_TIMEOUT_SECONDS}" -gt 300 ]]; then
		echo "Error: KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS must be an integer within [1, 300]." >&2
		exit 1
	fi
	if ! command -v curl >/dev/null 2>&1; then
		echo "Error: curl is required to verify Karkinos service readiness." >&2
		exit 1
	fi
	if [[ "${MODE}" == "dev" ]] && [[ -z "${FRONTEND_STARTUP_TIMEOUT_SECONDS}" ||
		"${FRONTEND_STARTUP_TIMEOUT_SECONDS}" == *[!0-9]* ||
		"${FRONTEND_STARTUP_TIMEOUT_SECONDS}" == "0" ||
		"${FRONTEND_STARTUP_TIMEOUT_SECONDS}" -gt 300 ]]; then
		echo "Error: KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS must be an integer within [1, 300]." >&2
		exit 1
	fi
}

cleanup_failed_backend_launch() {
	if [[ "${TRACKED_PID}" != "${LAUNCH_PID}" ]] && kill -0 "${TRACKED_PID}" >/dev/null 2>&1; then
		kill "${TRACKED_PID}" >/dev/null 2>&1 || true
	fi
	if kill -0 "${LAUNCH_PID}" >/dev/null 2>&1; then
		kill "${LAUNCH_PID}" >/dev/null 2>&1 || true
	fi
	wait "${LAUNCH_PID}" >/dev/null 2>&1 || true
	rm -f "${PID_FILE}"
}

wait_for_backend_readiness() {
	local deadline=$((SECONDS + STARTUP_HEALTH_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! kill -0 "${TRACKED_PID}" >/dev/null 2>&1; then
			echo "Error: Karkinos Web service exited before service readiness was established. Check ${LOG_FILE}" >&2
			cleanup_failed_backend_launch
			return 1
		fi
		if karkinos_backend_is_ready; then
			return 0
		fi
		if ((SECONDS < deadline)); then
			sleep 1
		fi
	done

	echo "Error: Karkinos service readiness did not become ready within ${STARTUP_HEALTH_TIMEOUT_SECONDS}s. Check ${LOG_FILE}" >&2
	cleanup_failed_backend_launch
	return 1
}

cleanup_failed_frontend_launch() {
	if [[ "${TRACKED_WEB_PID}" != "${WEB_LAUNCH_PID}" ]] && kill -0 "${TRACKED_WEB_PID}" >/dev/null 2>&1; then
		kill "${TRACKED_WEB_PID}" >/dev/null 2>&1 || true
	fi
	if kill -0 "${WEB_LAUNCH_PID}" >/dev/null 2>&1; then
		kill "${WEB_LAUNCH_PID}" >/dev/null 2>&1 || true
	fi
	wait "${WEB_LAUNCH_PID}" >/dev/null 2>&1 || true
	rm -f "${WEB_PID_FILE}"
}

wait_for_frontend_readiness() {
	local deadline=$((SECONDS + FRONTEND_STARTUP_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! kill -0 "${TRACKED_WEB_PID}" >/dev/null 2>&1; then
			echo "Error: Karkinos Web frontend exited before readiness. Check ${WEB_LOG_FILE}" >&2
			cleanup_failed_frontend_launch
			return 1
		fi
		if vite_frontend_is_ready; then
			return 0
		fi
		if ((SECONDS < deadline)); then
			sleep 1
		fi
	done

	echo "Error: Karkinos Web frontend did not become ready within ${FRONTEND_STARTUP_TIMEOUT_SECONDS}s. Check ${WEB_LOG_FILE}" >&2
	cleanup_failed_frontend_launch
	return 1
}

preflight_backend_port() {
	if resident_service_is_loaded; then
		if karkinos_backend_is_ready; then
			REUSE_RESIDENT_BACKEND=true
			return
		fi
		echo "Error: the resident Karkinos LaunchAgent is loaded, but service readiness is unavailable at ${PRODUCT_ENTRY_URL}." >&2
		echo "No fallback backend was launched. Inspect it with:" >&2
		echo "  ./scripts/service/manage_launch_agent.sh status" >&2
		exit 1
	fi

	local listener_pids
	listener_pids="$(backend_listener_pids)"
	if [[ -z "${listener_pids}" ]]; then
		return
	fi

	if karkinos_backend_is_ready; then
		echo "Error: a Karkinos service is already responding at ${PRODUCT_ENTRY_URL}." >&2
	else
		echo "Error: backend port ${BACKEND_PORT} is occupied, but Karkinos service readiness did not respond." >&2
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

validate_startup_health_timeout
mkdir -p "${RUN_DIR}" "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
	EXISTING_PID="$(cat "${PID_FILE}")"
	if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" >/dev/null 2>&1; then
		echo "Error: Karkinos Web service is already running with PID ${EXISTING_PID}." >&2
		if karkinos_backend_is_ready; then
			echo "Process liveness and the live scheduler are ready at ${PRODUCT_ENTRY_URL}." >&2
		else
			echo "The tracked process exists, but service readiness is unavailable." >&2
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
elif [[ "${USE_NATIVE_RELEASE}" != "true" && ! -f "${REPO_ROOT}/web/dist/index.html" ]]; then
	cat >&2 <<EOF
Warning: web/dist/index.html was not found.
The backend API will start, but ${PRODUCT_ENTRY_URL} cannot serve the product UI until the frontend is built.
Build it with:
  cd web && npm run build
EOF
fi

guide_data_source_configuration

echo "Mode: ${MODE}"
if [[ "${REUSE_RESIDENT_BACKEND}" == "true" ]]; then
	echo "Reusing resident Karkinos Web service managed by ${LAUNCH_AGENT_TARGET}."
	echo "Product entry: ${PRODUCT_ENTRY_URL}"
	if [[ "${MODE}" == "prod" ]]; then
		echo "Resident service is already running; no process was replaced."
		exit 0
	fi
else
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		echo "Starting Karkinos Web service from ${NATIVE_RELEASE_DIR}"
		echo "Log file: ${LOG_FILE}"
		echo "Command: ${NATIVE_ENTRYPOINT} ${SERVER_ARGS[*]-}"
		pushd "${NATIVE_RELEASE_DIR}/app" >/dev/null
		if command -v setsid >/dev/null 2>&1; then
			setsid nohup env "${NO_PROXY_ENV[@]}" \
				KARKINOS_HOME="${KARKINOS_HOME_PATH}" \
				KARKINOS_DATA_DIR="${KARKINOS_HOME_PATH}/data" \
				KARKINOS_CONFIG_PATH="${KARKINOS_HOME_PATH}/config/config.json" \
				KARKINOS_ENV_FILE="${KARKINOS_HOME_PATH}/config/.env" \
				"${NATIVE_ENTRYPOINT}" ${SERVER_ARGS[@]+"${SERVER_ARGS[@]}"} >>"${LOG_FILE}" 2>&1 &
		else
			nohup env "${NO_PROXY_ENV[@]}" \
				KARKINOS_HOME="${KARKINOS_HOME_PATH}" \
				KARKINOS_DATA_DIR="${KARKINOS_HOME_PATH}/data" \
				KARKINOS_CONFIG_PATH="${KARKINOS_HOME_PATH}/config/config.json" \
				KARKINOS_ENV_FILE="${KARKINOS_HOME_PATH}/config/.env" \
				"${NATIVE_ENTRYPOINT}" ${SERVER_ARGS[@]+"${SERVER_ARGS[@]}"} >>"${LOG_FILE}" 2>&1 &
		fi
		popd >/dev/null
	else
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
	fi

	LAUNCH_PID=$!
	TRACKED_PID="${LAUNCH_PID}"

	sleep 1
	CHILD_PID="$(pgrep -P "${LAUNCH_PID}" | tail -n 1 || true)"
	if [[ -n "${CHILD_PID}" ]]; then
		TRACKED_PID="${CHILD_PID}"
	fi

	echo "${TRACKED_PID}" >"${PID_FILE}"

	if ! wait_for_backend_readiness; then
		exit 1
	fi

	echo "Karkinos Web service started with PID ${TRACKED_PID}"
	if [[ "${USE_NATIVE_RELEASE}" == "true" || -f "${REPO_ROOT}/web/dist/index.html" ]]; then
		echo "Product entry: ${PRODUCT_ENTRY_URL}"
		echo "Page refresh and direct links are served from web/dist via FastAPI."
	fi
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

if ! wait_for_frontend_readiness; then
	exit 1
fi

cat <<EOF
Karkinos dev environment started.
Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}
Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}

Use ./scripts/stop_server.sh to stop Vite and any manually started backend.
The resident LaunchAgent remains running until ./scripts/stop_server.sh is called.
EOF
