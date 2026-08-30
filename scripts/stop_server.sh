#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
NATIVE_ENTRYPOINT="${KARKINOS_HOME_PATH}/current/bin/karkinos"
USE_NATIVE_RELEASE=false
if [[ -L "${KARKINOS_HOME_PATH}/current" || -e "${KARKINOS_HOME_PATH}/current" ]]; then
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
fi
if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
	PID_FILE="${KARKINOS_HOME_PATH}/.run/server.pid"
else
	PID_FILE="${REPO_ROOT}/.run/server.pid"
fi
WEB_PID_FILE="${REPO_ROOT}/.run/web.pid"
BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${KARKINOS_FRONTEND_PORT:-5173}"
LAUNCH_AGENT_LABEL="com.karkinos.daily-candidate"
LAUNCH_AGENT_TARGET="gui/$(id -u)/${LAUNCH_AGENT_LABEL}"
LAUNCH_AGENT_MANAGER="${REPO_ROOT}/scripts/service/manage_launch_agent.sh"

is_number() {
	[[ "${1:-}" =~ ^[0-9]+$ ]]
}

resident_service_is_loaded() {
	[[ "$(uname -s)" == "Darwin" ]] || return 1
	command -v launchctl >/dev/null 2>&1 || return 1
	launchctl print "${LAUNCH_AGENT_TARGET}" >/dev/null 2>&1
}

signal_pid_tree() {
	local pid="$1"
	local signal="$2"
	local child_pid

	while IFS= read -r child_pid; do
		[[ -z "${child_pid}" ]] && continue
		signal_pid_tree "${child_pid}" "${signal}"
	done < <(pgrep -P "${pid}" 2>/dev/null || true)

	kill "-${signal}" "${pid}" >/dev/null 2>&1 || true
}

kill_pid_tree() {
	local pid="$1"
	local label="$2"

	if ! is_number "${pid}"; then
		echo "Error: invalid ${label} PID '${pid}'." >&2
		return 1
	fi

	if ! kill -0 "${pid}" >/dev/null 2>&1; then
		return 0
	fi

	# Never signal the whole process group: on macOS, a nohup child inherits the
	# invoking terminal's group and would otherwise terminate the caller too.
	signal_pid_tree "${pid}" TERM

	for _ in {1..20}; do
		if ! kill -0 "${pid}" >/dev/null 2>&1; then
			return 0
		fi
		sleep 0.25
	done

	signal_pid_tree "${pid}" KILL
}

stop_pid_file() {
	local pid_file="$1"
	local label="$2"

	if [[ ! -f "${pid_file}" ]]; then
		echo "${label} is not running."
		return 0
	fi

	local pid
	pid="$(cat "${pid_file}")"
	if [[ -z "${pid}" ]]; then
		echo "Error: ${label} PID file is empty." >&2
		rm -f "${pid_file}"
		return 1
	fi
	if ! is_number "${pid}"; then
		echo "Error: invalid ${label} PID '${pid}'." >&2
		rm -f "${pid_file}"
		return 1
	fi

	if ! kill -0 "${pid}" >/dev/null 2>&1; then
		echo "${label} is not running, cleaning stale PID file."
		rm -f "${pid_file}"
		return 0
	fi

	kill_pid_tree "${pid}" "${label}"
	rm -f "${pid_file}"
	echo "Stopped ${label} (${pid})."
}

cleanup_orphans_by_command() {
	local pattern="$1"
	local label="$2"
	local pids

	pids="$(pgrep -f "${pattern}" || true)"
	if [[ -z "${pids}" ]]; then
		return 0
	fi

	echo "Cleaning orphan ${label} process(es): ${pids//$'\n'/ }"
	while IFS= read -r pid; do
		[[ -z "${pid}" ]] && continue
		[[ "${pid}" == "$$" ]] && continue
		kill_pid_tree "${pid}" "${label}" || true
	done <<<"${pids}"
}

cleanup_orphans_by_port() {
	local port="$1"
	local label="$2"

	if ! command -v lsof >/dev/null 2>&1; then
		return 0
	fi

	local pids
	pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
	if [[ -z "${pids}" ]]; then
		return 0
	fi

	echo "Cleaning ${label} listener(s) on port ${port}: ${pids//$'\n'/ }"
	while IFS= read -r pid; do
		[[ -z "${pid}" ]] && continue
		[[ "${pid}" == "$$" ]] && continue
		kill_pid_tree "${pid}" "${label}" || true
	done <<<"${pids}"
}

EXIT_STATUS=0
stop_pid_file "${WEB_PID_FILE}" "Karkinos Web frontend" || EXIT_STATUS=1
cleanup_orphans_by_command "${REPO_ROOT}/web/node_modules/.bin/vite --host .* --port ${FRONTEND_PORT}" "Karkinos Web frontend" || EXIT_STATUS=1
cleanup_orphans_by_port "${FRONTEND_PORT}" "Karkinos Web frontend" || EXIT_STATUS=1

if resident_service_is_loaded; then
	if [[ ! -x "${LAUNCH_AGENT_MANAGER}" ]]; then
		echo "Error: LaunchAgent manager is unavailable at ${LAUNCH_AGENT_MANAGER}." >&2
		EXIT_STATUS=1
	elif ! "${LAUNCH_AGENT_MANAGER}" uninstall; then
		echo "Error: failed to stop ${LAUNCH_AGENT_TARGET}." >&2
		EXIT_STATUS=1
	else
		echo "Karkinos resident Web service stopped."
	fi
else
	stop_pid_file "${PID_FILE}" "Karkinos Web service" || EXIT_STATUS=1
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		cleanup_orphans_by_command "${NATIVE_ENTRYPOINT}.*server" "Karkinos native Web service" || EXIT_STATUS=1
	else
		cleanup_orphans_by_command "${REPO_ROOT}/.venv/bin/python.* -m server" "Karkinos Web service" || EXIT_STATUS=1
		cleanup_orphans_by_command "uv run python -m server" "Karkinos Web service" || EXIT_STATUS=1
	fi
	cleanup_orphans_by_port "${BACKEND_PORT}" "Karkinos Web service" || EXIT_STATUS=1
fi

if ((EXIT_STATUS != 0)); then
	echo "Error: one or more Karkinos processes could not be stopped cleanly." >&2
	exit "${EXIT_STATUS}"
fi

echo "Karkinos Web processes stopped."
