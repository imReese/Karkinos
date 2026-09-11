#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_WORKSPACE="${KARKINOS_WORKSPACE:-${REPO_ROOT}}"
INSTALLED_HOME="${KARKINOS_HOME:-${KARKINOS_WORKSPACE:-${REPO_ROOT}}}"
PRODUCTION_CONTROL="${INSTALLED_HOME}/current/bin/karkinosctl"
PRODUCTION_SERVICE_PORT="${KARKINOS_BACKEND_PORT:-}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/start_server.sh [branch] [extra args...]
  ./scripts/start_server.sh --branch <branch> [extra args...]
  ./scripts/start_server.sh prod

Source branches:
  main is the default. The launcher never switches the current Git checkout.

  main        Run a cached code snapshot of the locally fetched main branch.
              Serves the Web app and API on port 8000. Supports --init and
              --foreground.
  dev         Run the current dev working tree with backend reload on port 8001
              and Vite on port 5173. Local uncommitted development edits are used.
  <branch>    Run a cached code snapshot of that branch without touching the
              current checkout.

All source branches share the repository-local config.json, .env, data/store,
logs, and exports. Only code, dependencies, and process state are branch-specific
under .run/<branch>. Only one source backend may use the shared workspace at a
time.

Snapshot branches use the latest ref already available locally. Run `git fetch
origin` when you want to refresh origin/main or another remote branch.

prod controls an already installed immutable release and is retained only for
legacy/native release maintenance.
EOF
}

production_service_port_is_valid() {
	if [[ -z "${PRODUCTION_SERVICE_PORT}" ]]; then
		return 0
	fi
	[[ "${PRODUCTION_SERVICE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] &&
		((10#${PRODUCTION_SERVICE_PORT} <= 65535))
}

require_packaged_release_control() {
	local release_dir release_name release_control
	if [[ "${INSTALLED_HOME}" != /* || ! -L "${INSTALLED_HOME}/current" ]]; then
		return 1
	fi
	release_dir="$(CDPATH='' cd -- "${INSTALLED_HOME}/current" 2>/dev/null && pwd -P)" || return 1
	release_name="${release_dir##*/}"
	release_control="${release_dir}/bin/karkinosctl"
	[[ "${release_dir}" == "${INSTALLED_HOME}/releases/${release_name}" &&
		"${release_name}" =~ ^sha-[0-9a-f]{40}$ &&
		-f "${release_dir}/release.json" && ! -L "${release_dir}/release.json" &&
		-d "${release_dir}/bin" && ! -L "${release_dir}/bin" &&
		-f "${release_control}" && ! -L "${release_control}" &&
		-x "${release_control}" ]] || return 1
	PRODUCTION_CONTROL="${release_control}"
}

source_runtime_is_running() {
	local command
	while IFS= read -r command; do
		[[ "${command}" == *"${REPO_ROOT}/scripts/service/run_main.py"* ||
			"${command}" == *"${REPO_ROOT}/scripts/service/run_dev.py"* ]] && return 0
	done < <(ps -axo command= 2>/dev/null || true)
	return 1
}

require_source_workspace() {
	if [[ "${SOURCE_WORKSPACE}" != /* ]]; then
		echo "Error: KARKINOS_WORKSPACE must be an absolute path when set." >&2
		exit 2
	fi
	if [[ ! -f "${SOURCE_WORKSPACE}/config.json" ]]; then
		echo "Error: missing ${SOURCE_WORKSPACE}/config.json" >&2
		echo "Create it with: cp config.example.json config.json" >&2
		exit 1
	fi
	if [[ ! -f "${SOURCE_WORKSPACE}/.env" ]]; then
		echo "Error: missing ${SOURCE_WORKSPACE}/.env" >&2
		echo "Create it with: cp .env.example .env" >&2
		exit 1
	fi
}

validate_branch_name() {
	git check-ref-format --branch "$1" >/dev/null 2>&1 || {
		echo "Error: invalid Git branch '$1'." >&2
		exit 2
	}
}

resolve_branch_ref() {
	local branch="$1"
	if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/remotes/origin/${branch}"; then
		printf '%s\n' "refs/remotes/origin/${branch}"
		return 0
	fi
	if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/heads/${branch}"; then
		printf '%s\n' "refs/heads/${branch}"
		return 0
	fi
	echo "Error: branch '${branch}' is not available locally or under origin/." >&2
	echo "Fetch it explicitly, then retry." >&2
	return 1
}

prepare_branch_snapshot() {
	local branch="$1"
	local ref sha runtime_dir code_dir marker temporary previous
	ref="$(resolve_branch_ref "${branch}")" || exit 1
	sha="$(git -C "${REPO_ROOT}" rev-parse "${ref}^{commit}")"
	runtime_dir="${SOURCE_WORKSPACE}/.run/${branch}"
	code_dir="${runtime_dir}/code"
	marker="${code_dir}/.karkinos-source-sha"

	if [[ -f "${marker}" && -f "${code_dir}/pyproject.toml" &&
		"$(cat "${marker}")" == "${sha}" ]]; then
		SNAPSHOT_ROOT="${code_dir}"
		SNAPSHOT_SHA="${sha}"
		return 0
	fi

	if source_runtime_is_running; then
		echo "Error: a Karkinos source runtime is running; snapshot refresh was refused." >&2
		echo "Stop it before refreshing branch '${branch}'." >&2
		exit 1
	fi
	if ! command -v tar >/dev/null 2>&1; then
		echo "Error: tar is required to materialize a branch snapshot." >&2
		exit 1
	fi

	mkdir -p "${runtime_dir}"
	temporary="${runtime_dir}/code.tmp.$$"
	previous="${runtime_dir}/code.old.$$"
	rm -rf "${temporary}" "${previous}"
	mkdir -p "${temporary}"
	if ! git -C "${REPO_ROOT}" archive "${sha}" | tar -xf - -C "${temporary}"; then
		rm -rf "${temporary}"
		echo "Error: failed to materialize branch '${branch}' at ${sha}." >&2
		exit 1
	fi
	printf '%s\n' "${sha}" >"${temporary}/.karkinos-source-sha"
	printf '%s\n' "${branch}" >"${temporary}/.karkinos-source-branch"

	if [[ -e "${code_dir}" ]]; then
		mv "${code_dir}" "${previous}"
	fi
	mv "${temporary}" "${code_dir}"
	rm -rf "${previous}"

	SNAPSHOT_ROOT="${code_dir}"
	SNAPSHOT_SHA="${sha}"
}

export_source_workspace() {
	local source_root="$1"
	local branch="$2"
	export KARKINOS_WORKSPACE="${SOURCE_WORKSPACE}"
	# Temporary compatibility for runtime code still reading the older name.
	export KARKINOS_HOME="${SOURCE_WORKSPACE}"
	export KARKINOS_DATA_DIR="${SOURCE_WORKSPACE}/data/store"
	export KARKINOS_CONFIG_PATH="${SOURCE_WORKSPACE}/config.json"
	export KARKINOS_ENV_FILE="${SOURCE_WORKSPACE}/.env"
	export KARKINOS_STATIC_DIR="${source_root}/web/dist"
	export KARKINOS_RELEASE_ROOT="${source_root}"
	export KARKINOS_SOURCE_ROOT="${source_root}"
	export KARKINOS_SOURCE_BRANCH="${branch}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

if [[ "${1:-}" == "prod" ]]; then
	shift
	if (($# != 0)); then
		echo "Error: prod does not accept ad-hoc server arguments." >&2
		exit 2
	fi
	if ! production_service_port_is_valid; then
		echo "Error: KARKINOS_BACKEND_PORT must be an integer from 1 through 65535." >&2
		exit 2
	fi
	if ! require_packaged_release_control; then
		echo "Error: production requires an installed immutable release controller." >&2
		echo "Set KARKINOS_HOME to that installed runtime when necessary." >&2
		exit 1
	fi
	service_args=(service-start)
	if [[ -n "${PRODUCTION_SERVICE_PORT}" ]]; then
		service_args+=(--service-port "${PRODUCTION_SERVICE_PORT}")
	fi
	exec "${PRODUCTION_CONTROL}" "${service_args[@]}"
fi

TARGET_BRANCH="main"
if [[ "${1:-}" == "--branch" ]]; then
	(($# >= 2)) || {
		echo "Error: --branch requires a branch name." >&2
		exit 2
	}
	TARGET_BRANCH="$2"
	shift 2
elif [[ -n "${1:-}" && "${1}" != -* ]]; then
	TARGET_BRANCH="$1"
	shift
fi
validate_branch_name "${TARGET_BRANCH}"
require_source_workspace

mkdir -p "${SOURCE_WORKSPACE}/data/store" "${SOURCE_WORKSPACE}/logs" \
	"${SOURCE_WORKSPACE}/exports" "${SOURCE_WORKSPACE}/.run"

if [[ "${TARGET_BRANCH}" != "dev" ]]; then
	prepare_branch_snapshot "${TARGET_BRANCH}"
	export_source_workspace "${SNAPSHOT_ROOT}" "${TARGET_BRANCH}"
	export KARKINOS_SOURCE_SHA="${SNAPSHOT_SHA}"
	export KARKINOS_SOURCE_SNAPSHOT=1
	exec python3 "${SCRIPT_DIR}/service/run_main.py" "$@"
fi

CURRENT_BRANCH="$(git -C "${REPO_ROOT}" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "${CURRENT_BRANCH}" != "dev" ]]; then
	echo "Error: the dev runtime uses the current working tree, but this checkout is '${CURRENT_BRANCH:-detached HEAD}'." >&2
	echo "Switch to dev yourself before starting the development runtime." >&2
	exit 1
fi

unset KARKINOS_SOURCE_SNAPSHOT KARKINOS_SOURCE_SHA
export_source_workspace "${REPO_ROOT}" "dev"
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
if ! UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" uv run --locked --extra server python -c \
	"import fastapi, uvicorn, aiosqlite, websockets" >/dev/null 2>&1; then
	cat >&2 <<'EOF'
Error: server dependencies could not be loaded from the committed lockfile.

Install them with:
  UV_CACHE_DIR=.uv-cache uv sync --locked --extra server --extra dev
EOF
	exit 1
fi

RUNTIME_DIR="${SOURCE_WORKSPACE}/.run/dev"
LOG_DIR="${SOURCE_WORKSPACE}/logs"
PID_FILE="${RUNTIME_DIR}/backend.pid"
WEB_PID_FILE="${RUNTIME_DIR}/frontend.pid"
LOG_FILE="${LOG_DIR}/dev-backend.log"
WEB_LOG_FILE="${LOG_DIR}/dev-frontend.log"
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
	--host=*) BACKEND_HOST="${SERVER_ARGS[$i]#--host=}" ;;
	--port=*) BACKEND_PORT="${SERVER_ARGS[$i]#--port=}" ;;
	esac
done
SERVER_ARGS=(--host "${BACKEND_HOST}" --port "${BACKEND_PORT}" "${SERVER_ARGS[@]}")

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
	if [[ ! -f "${web_dir}/package.json" || ! -f "${web_dir}/package-lock.json" ]]; then
		echo "Error: web/package.json and web/package-lock.json are required." >&2
		exit 1
	fi
	local stamp_file="${web_dir}/node_modules/.karkinos-dependencies"
	local dependency_stamp
	local -a dependency_files=("${web_dir}/package.json" "${web_dir}/package-lock.json")
	[[ ! -f "${web_dir}/.npmrc" ]] || dependency_files+=("${web_dir}/.npmrc")
	dependency_stamp="$(cksum "${dependency_files[@]}")"
	if [[ -x "${web_dir}/node_modules/.bin/vite" && -f "${web_dir}/node_modules/vitest/globals.d.ts" &&
		-f "${stamp_file}" && "$(cat "${stamp_file}")" == "${dependency_stamp}" ]]; then
		return
	fi
	echo "Frontend dependency inputs changed or installation is incomplete; running npm ci"
	pushd "${web_dir}" >/dev/null
	npm ci
	popd >/dev/null
	printf '%s\n' "${dependency_stamp}" >"${stamp_file}"
}

guide_data_source_configuration() {
	if [[ -n "${KARKINOS_TUSHARE_TOKEN:-}" ]]; then
		return
	fi
	cat <<'EOF'
Data source: AKShare works without a token.
To select AKShare or configure TuShare interactively:
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

launch_tree_pids() {
	local pid="$1" child_pid
	while IFS= read -r child_pid; do
		[[ -z "${child_pid}" ]] || launch_tree_pids "${child_pid}"
	done < <(pgrep -P "${pid}" 2>/dev/null || true)
	printf '%s\n' "${pid}"
}

cleanup_launch() {
	local launch_pid="$1"
	local tracked_pid="$2"
	local pid_file="$3"
	local pid any_alive
	local -a launch_pids=()
	while IFS= read -r pid; do
		launch_pids+=("${pid}")
	done < <(launch_tree_pids "${launch_pid}")
	if [[ "${tracked_pid}" != "${launch_pid}" ]]; then
		while IFS= read -r pid; do
			launch_pids+=("${pid}")
		done < <(launch_tree_pids "${tracked_pid}")
	fi
	for pid in "${launch_pids[@]}"; do
		kill -TERM "${pid}" >/dev/null 2>&1 || true
	done
	for _ in {1..20}; do
		any_alive=false
		for pid in "${launch_pids[@]}"; do
			kill -0 "${pid}" >/dev/null 2>&1 && any_alive=true
		done
		[[ "${any_alive}" == true ]] || break
		sleep 0.1
	done
	for pid in "${launch_pids[@]}"; do
		kill -0 "${pid}" >/dev/null 2>&1 && kill -KILL "${pid}" >/dev/null 2>&1 || true
	done
	wait "${launch_pid}" >/dev/null 2>&1 || true
	rm -f "${pid_file}"
}

cleanup_failed_startup() {
	local status=$?
	trap - EXIT INT TERM
	if [[ -n "${WEB_LAUNCH_PID:-}" ]]; then
		cleanup_launch "${WEB_LAUNCH_PID}" "${TRACKED_WEB_PID:-${WEB_LAUNCH_PID}}" "${WEB_PID_FILE}"
	fi
	if [[ -n "${LAUNCH_PID:-}" ]]; then
		cleanup_launch "${LAUNCH_PID}" "${TRACKED_PID:-${LAUNCH_PID}}" "${PID_FILE}"
	fi
	exit "${status}"
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
			return 1
		fi
		backend_is_ready && return 0
		sleep 1
	done
	echo "Error: backend readiness timed out after ${STARTUP_HEALTH_TIMEOUT_SECONDS}s. Check ${LOG_FILE}." >&2
	return 1
}

wait_for_frontend() {
	local deadline=$((SECONDS + FRONTEND_STARTUP_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! kill -0 "${TRACKED_WEB_PID}" >/dev/null 2>&1; then
			echo "Error: development frontend exited before readiness. Check ${WEB_LOG_FILE}." >&2
			return 1
		fi
		frontend_is_ready && return 0
		sleep 1
	done
	echo "Error: frontend readiness timed out after ${FRONTEND_STARTUP_TIMEOUT_SECONDS}s. Check ${WEB_LOG_FILE}." >&2
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

mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"
chmod 700 "${RUNTIME_DIR}" "${LOG_DIR}" "${SOURCE_WORKSPACE}/data/store"

for pid_file in "${PID_FILE}" "${WEB_PID_FILE}"; do
	if [[ ! -f "${pid_file}" ]]; then
		continue
	fi
	existing_record="$(cat "${pid_file}")"
	IFS=$'\t' read -r existing_pid _ <<<"${existing_record}"
	if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
		echo "Error: dev already has a tracked process with PID ${existing_pid}." >&2
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

LAUNCH_PID=""
WEB_LAUNCH_PID=""
trap cleanup_failed_startup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo "Starting current dev backend on ${PRODUCT_ENTRY_URL}"
if command -v setsid >/dev/null 2>&1; then
	setsid nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run --locked --extra server "${REPO_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/service/run_dev.py" "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
else
	nohup env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}" \
		uv run --locked --extra server "${REPO_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/service/run_dev.py" "${SERVER_ARGS[@]}" >>"${LOG_FILE}" 2>&1 &
fi
LAUNCH_PID=$!
TRACKED_PID="${LAUNCH_PID}"
sleep 1
child_pid="$(pgrep -P "${LAUNCH_PID}" | tail -n 1 || true)"
[[ -z "${child_pid}" ]] || TRACKED_PID="${child_pid}"
if ! write_pid_record "${PID_FILE}" "${TRACKED_PID}"; then
	exit 1
fi
wait_for_backend

echo "Starting Vite frontend on ${HOT_RELOAD_URL}"
pushd "${REPO_ROOT}/web" >/dev/null
if command -v setsid >/dev/null 2>&1; then
	setsid nohup env KARKINOS_DEV_BACKEND_URL="http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}" \
		npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort >>"${WEB_LOG_FILE}" 2>&1 &
else
	nohup env KARKINOS_DEV_BACKEND_URL="http://$(probe_host "${BACKEND_HOST}"):${BACKEND_PORT}" \
		npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort >>"${WEB_LOG_FILE}" 2>&1 &
fi
WEB_LAUNCH_PID=$!
popd >/dev/null
TRACKED_WEB_PID="${WEB_LAUNCH_PID}"
sleep 1
web_child_pid="$(pgrep -P "${WEB_LAUNCH_PID}" | tail -n 1 || true)"
[[ -z "${web_child_pid}" ]] || TRACKED_WEB_PID="${web_child_pid}"
if ! write_pid_record "${WEB_PID_FILE}" "${TRACKED_WEB_PID}"; then
	exit 1
fi
wait_for_frontend
trap - EXIT INT TERM

cat <<EOF
Karkinos dev runtime started from the current working tree.
Workspace: ${SOURCE_WORKSPACE}
Backend:   ${PRODUCT_ENTRY_URL}
Frontend:  ${HOT_RELOAD_URL}

config.json, .env, data/store, logs, and exports are shared with snapshot branches.
Use ./scripts/stop_server.sh dev to stop the development runtime.
EOF
