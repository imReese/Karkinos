#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
PRODUCTION_CONTROL="${KARKINOS_HOME_PATH}/current/bin/karkinosctl"
PRODUCTION_SERVICE_PORT="${KARKINOS_BACKEND_PORT:-}"

production_service_port_is_valid() {
	if [[ -z "${PRODUCTION_SERVICE_PORT}" ]]; then
		return 0
	fi
	[[ "${PRODUCTION_SERVICE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] &&
		((10#${PRODUCTION_SERVICE_PORT} <= 65535))
}

require_packaged_release_control() {
	local release_dir release_name release_control
	if [[ "${KARKINOS_HOME_PATH}" != /* || ! -L "${KARKINOS_HOME_PATH}/current" ]]; then
		return 1
	fi
	release_dir="$(CDPATH='' cd -- "${KARKINOS_HOME_PATH}/current" 2>/dev/null && pwd -P)" || return 1
	release_name="${release_dir##*/}"
	release_control="${release_dir}/bin/karkinosctl"
	[[ "${release_dir}" == "${KARKINOS_HOME_PATH}/releases/${release_name}" &&
		"${release_name}" =~ ^sha-[0-9a-f]{40}$ &&
		-f "${release_dir}/release.json" && ! -L "${release_dir}/release.json" &&
		-d "${release_dir}/bin" && ! -L "${release_dir}/bin" &&
		-f "${release_control}" && ! -L "${release_control}" &&
		-x "${release_control}" ]] || return 1
	# Execute the physical path that was just validated, so a concurrent current
	# pointer switch cannot redirect this invocation to an unvalidated tree.
	PRODUCTION_CONTROL="${release_control}"
}

usage() {
	cat <<'EOF'
Usage:
  ./scripts/start_server.sh [dev] [extra server args...]
  ./scripts/start_server.sh prod

Modes:
  dev   Run the current source tree with reload plus the Vite frontend.
        It defaults to backend port 8001; production uses its persisted port.
  prod  Start the supervised immutable release selected by
        ~/Library/Application Support/Karkinos/current.

The live scheduler always starts with the backend. It has no independent off
switch. Automatic trading remains a separate default-off runtime control and
does not gain broker, execution, or capital authority from this command.

Production never runs from the source checkout and never changes current.
Use candidate for tag-free isolation, update for a published stable tag, and
bootstrap for the one-time legacy handoff.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

MODE="${MODE:-${1:-dev}}"
case "${MODE}" in
dev)
	if [[ "${1:-}" == "dev" ]]; then
		shift
	fi
	if [[ -f "${HOME}/.local/bin/env" ]]; then
		# shellcheck disable=SC1091
		source "${HOME}/.local/bin/env"
	fi
	;;
prod)
	if [[ "${1:-}" == "prod" ]]; then
		shift
	fi
	if (($# != 0)); then
		echo "Error: prod does not accept ad-hoc server arguments." >&2
		echo "Set KARKINOS_BACKEND_PORT explicitly when a non-default port is required." >&2
		exit 2
	fi
	if ! production_service_port_is_valid; then
		echo "Error: KARKINOS_BACKEND_PORT must be an integer from 1 through 65535." >&2
		exit 2
	fi
	if ! require_packaged_release_control; then
		echo "Error: production requires the packaged immutable release controller." >&2
		echo "Stage and bootstrap or update a verified CI release before starting production." >&2
		exit 1
	fi
	service_args=(service-start)
	if [[ -n "${PRODUCTION_SERVICE_PORT}" ]]; then
		service_args+=(--service-port "${PRODUCTION_SERVICE_PORT}")
	fi
	exec "${PRODUCTION_CONTROL}" "${service_args[@]}"
	;;
*)
	echo "Error: unknown mode '${MODE}'." >&2
	usage >&2
	exit 2
	;;
esac

cd "${REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
	echo "Error: 'uv' was not found in PATH." >&2
	exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
	echo "Error: npm was not found in PATH." >&2
	exit 1
fi
if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
	echo "Error: pyproject.toml was not found under ${REPO_ROOT}." >&2
	exit 1
fi
if ! UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" uv run python -c \
	"import fastapi, uvicorn, aiosqlite, websockets" >/dev/null 2>&1; then
	cat >&2 <<'EOF'
Error: server dependencies are not installed.

Install them with:
  UV_CACHE_DIR=.uv-cache uv sync --extra server --extra dev
EOF
	exit 1
fi

RUN_DIR="${REPO_ROOT}/.run"
LOG_DIR="${REPO_ROOT}/logs"
PID_FILE="${RUN_DIR}/dev-server.pid"
WEB_PID_FILE="${RUN_DIR}/web.pid"
LOG_FILE="${LOG_DIR}/dev-server.log"
WEB_LOG_FILE="${LOG_DIR}/web.log"
LOG_MAX_BYTES="${KARKINOS_LOG_MAX_BYTES:-20971520}"
STARTUP_HEALTH_TIMEOUT_SECONDS="${KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS:-60}"
FRONTEND_STARTUP_TIMEOUT_SECONDS="${KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS:-30}"
FRONTEND_HOST="${KARKINOS_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${KARKINOS_FRONTEND_PORT:-5173}"

SERVER_ARGS=(--reload --reload-exclude 'tests/**' --reload-exclude 'web/**' "$@")
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${KARKINOS_DEV_BACKEND_PORT:-8001}"
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

require_positive_integer() {
	local value="$1"
	local label="$2"
	local maximum="$3"
	if [[ -z "${value}" || "${value}" == *[!0-9]* || "${value}" == "0" || "${value}" -gt "${maximum}" ]]; then
		echo "Error: ${label} must be an integer within [1, ${maximum}]." >&2
		exit 1
	fi
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
	if [[ -f "${KARKINOS_CONFIG_PATH:-config.json}" || -n "${KARKINOS_TUSHARE_TOKEN:-}" ]]; then
		return
	fi
	cat <<'EOF'
Data source: defaulting to AKShare.
Configure local development data with:
  uv run python scripts/data/configure_data_source.py
EOF
}

rotate_log_if_needed() {
	local log_file="$1"
	[[ -f "${log_file}" ]] || return 0
	require_positive_integer "${LOG_MAX_BYTES}" "KARKINOS_LOG_MAX_BYTES" 9223372036854775807
	local current_size
	current_size="$(wc -c <"${log_file}")"
	if ((current_size < LOG_MAX_BYTES)); then
		return
	fi
	local archived_log="${log_file}.$(date '+%Y%m%d-%H%M%S').$$"
	mv -- "${log_file}" "${archived_log}"
	echo "Archived oversized log: ${archived_log}"
}

probe_host() {
	case "$1" in
	0.0.0.0 | :: | \[::\]) printf '%s' "127.0.0.1" ;;
	*) printf '%s' "$1" ;;
	esac
}

listener_pids() {
	command -v lsof >/dev/null 2>&1 || return 0
	lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

backend_is_ready() {
	local health_response live_response
	health_response="$(
		env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
			--max-time 2 "http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}/api/health" 2>/dev/null
	)" || return 1
	[[ "${health_response}" == *'"schema_version":"karkinos.service_health.v1"'* &&
		"${health_response}" == *'"service":"karkinos"'* &&
		"${health_response}" == *'"status":"alive"'* ]] || return 1
	live_response="$(
		env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
			--max-time 2 "http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}/api/settings/live/status" 2>/dev/null
	)" || return 1
	[[ "${live_response}" == *'"running":true'* ]]
}

frontend_is_ready() {
	env "${NO_PROXY_ENV[@]}" curl --noproxy '*' --fail --silent --show-error \
		--max-time 2 --output /dev/null \
		"http://$(probe_host "${FRONTEND_HOST}"):${FRONTEND_PORT}/" 2>/dev/null
}

cleanup_launch() {
	local launch_pid="$1"
	local tracked_pid="$2"
	local pid_file="$3"
	if [[ "${tracked_pid}" != "${launch_pid}" ]] && kill -0 "${tracked_pid}" >/dev/null 2>&1; then
		kill "${tracked_pid}" >/dev/null 2>&1 || true
	fi
	if kill -0 "${launch_pid}" >/dev/null 2>&1; then
		kill "${launch_pid}" >/dev/null 2>&1 || true
	fi
	wait "${launch_pid}" >/dev/null 2>&1 || true
	rm -f "${pid_file}"
}

write_pid_record() {
	local pid_file="$1"
	local pid="$2"
	local started_at
	started_at="$(ps -p "${pid}" -o lstart= 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
	if [[ -z "${started_at}" ]]; then
		echo "Error: could not bind PID ${pid} to a process start identity." >&2
		return 1
	fi
	printf '%s\t%s\n' "${pid}" "${started_at}" >"${pid_file}"
}

wait_for_backend() {
	local deadline=$((SECONDS + STARTUP_HEALTH_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! kill -0 "${TRACKED_PID}" >/dev/null 2>&1; then
			echo "Error: development backend exited before readiness. Check ${LOG_FILE}." >&2
			cleanup_launch "${LAUNCH_PID}" "${TRACKED_PID}" "${PID_FILE}"
			return 1
		fi
		backend_is_ready && return 0
		sleep 1
	done
	echo "Error: backend readiness timed out after ${STARTUP_HEALTH_TIMEOUT_SECONDS}s. Check ${LOG_FILE}." >&2
	cleanup_launch "${LAUNCH_PID}" "${TRACKED_PID}" "${PID_FILE}"
	return 1
}

wait_for_frontend() {
	local deadline=$((SECONDS + FRONTEND_STARTUP_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! kill -0 "${TRACKED_WEB_PID}" >/dev/null 2>&1; then
			echo "Error: development frontend exited before readiness. Check ${WEB_LOG_FILE}." >&2
			cleanup_launch "${WEB_LAUNCH_PID}" "${TRACKED_WEB_PID}" "${WEB_PID_FILE}"
			return 1
		fi
		frontend_is_ready && return 0
		sleep 1
	done
	echo "Error: frontend readiness timed out after ${FRONTEND_STARTUP_TIMEOUT_SECONDS}s. Check ${WEB_LOG_FILE}." >&2
	cleanup_launch "${WEB_LAUNCH_PID}" "${TRACKED_WEB_PID}" "${WEB_PID_FILE}"
	return 1
}

require_positive_integer "${BACKEND_PORT}" "development backend port" 65535
require_positive_integer "${FRONTEND_PORT}" "frontend port" 65535
require_positive_integer "${STARTUP_HEALTH_TIMEOUT_SECONDS}" "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS" 300
require_positive_integer "${FRONTEND_STARTUP_TIMEOUT_SECONDS}" "KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS" 300
if ! command -v curl >/dev/null 2>&1; then
	echo "Error: curl is required for bounded readiness checks." >&2
	exit 1
fi

mkdir -p "${RUN_DIR}" "${LOG_DIR}"
chmod 700 "${RUN_DIR}" "${LOG_DIR}"

for pid_file in "${PID_FILE}" "${WEB_PID_FILE}"; do
	if [[ ! -f "${pid_file}" ]]; then
		continue
	fi
	existing_record="$(cat "${pid_file}")"
	IFS=$'\t' read -r existing_pid _ <<<"${existing_record}"
	if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
		echo "Error: a tracked development process is already running with PID ${existing_pid}." >&2
		echo "Stop it explicitly with ./scripts/stop_server.sh." >&2
		exit 1
	fi
	rm -f "${pid_file}"
done

backend_pids="$(listener_pids "${BACKEND_PORT}")"
frontend_pids="$(listener_pids "${FRONTEND_PORT}")"
if [[ -n "${backend_pids}" || -n "${frontend_pids}" ]]; then
	echo "Error: a development port is already occupied; no process was terminated." >&2
	[[ -z "${backend_pids}" ]] || echo "Backend listener PID(s): ${backend_pids//$'\n'/ }" >&2
	[[ -z "${frontend_pids}" ]] || echo "Frontend listener PID(s): ${frontend_pids//$'\n'/ }" >&2
	exit 1
fi

rotate_log_if_needed "${LOG_FILE}"
rotate_log_if_needed "${WEB_LOG_FILE}"
ensure_frontend_dependencies
echo "Building product frontend bundle for ${PRODUCT_ENTRY_URL}"
npm --prefix web run build
guide_data_source_configuration

echo "Starting source development backend on ${PRODUCT_ENTRY_URL}"
if command -v setsid >/dev/null 2>&1; then
	setsid nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run python -m server "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
else
	nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run python -m server "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
fi
LAUNCH_PID=$!
TRACKED_PID="${LAUNCH_PID}"
sleep 1
child_pid="$(pgrep -P "${LAUNCH_PID}" | tail -n 1 || true)"
[[ -z "${child_pid}" ]] || TRACKED_PID="${child_pid}"
if ! write_pid_record "${PID_FILE}" "${TRACKED_PID}"; then
	cleanup_launch "${LAUNCH_PID}" "${TRACKED_PID}" "${PID_FILE}"
	exit 1
fi
wait_for_backend

echo "Starting Vite frontend on ${HOT_RELOAD_URL}"
pushd "${REPO_ROOT}/web" >/dev/null
if command -v setsid >/dev/null 2>&1; then
	setsid nohup env KARKINOS_DEV_BACKEND_URL="http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}" \
		npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >>"${WEB_LOG_FILE}" 2>&1 &
else
	nohup env KARKINOS_DEV_BACKEND_URL="http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}" \
		npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >>"${WEB_LOG_FILE}" 2>&1 &
fi
WEB_LAUNCH_PID=$!
popd >/dev/null
TRACKED_WEB_PID="${WEB_LAUNCH_PID}"
sleep 1
web_child_pid="$(pgrep -P "${WEB_LAUNCH_PID}" | tail -n 1 || true)"
[[ -z "${web_child_pid}" ]] || TRACKED_WEB_PID="${web_child_pid}"
if ! write_pid_record "${WEB_PID_FILE}" "${TRACKED_WEB_PID}"; then
	cleanup_launch "${WEB_LAUNCH_PID}" "${TRACKED_WEB_PID}" "${WEB_PID_FILE}"
	exit 1
fi
wait_for_frontend

cat <<EOF
Karkinos development environment started.
Backend:  ${PRODUCT_ENTRY_URL}
Frontend: ${HOT_RELOAD_URL}

Stable production, if loaded, remains isolated on its own port and release.
Use ./scripts/stop_server.sh to stop Karkinos development and production services.
EOF
