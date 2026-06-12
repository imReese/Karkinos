#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${REPO_ROOT}/.run/server.pid"
WEB_PID_FILE="${REPO_ROOT}/.run/web.pid"
BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${KARKINOS_FRONTEND_PORT:-5173}"

is_number() {
	[[ "${1:-}" =~ ^[0-9]+$ ]]
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

	local pgid
	pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
	if [[ -n "${pgid}" ]] && is_number "${pgid}" && [[ "${pgid}" != "1" ]]; then
		kill -- "-${pgid}" >/dev/null 2>&1 || true
	else
		pkill -TERM -P "${pid}" >/dev/null 2>&1 || true
		kill "${pid}" >/dev/null 2>&1 || true
	fi

	for _ in {1..20}; do
		if ! kill -0 "${pid}" >/dev/null 2>&1; then
			return 0
		fi
		sleep 0.25
	done

	if [[ -n "${pgid}" ]] && is_number "${pgid}" && [[ "${pgid}" != "1" ]]; then
		kill -9 -- "-${pgid}" >/dev/null 2>&1 || true
	else
		pkill -KILL -P "${pid}" >/dev/null 2>&1 || true
		kill -9 "${pid}" >/dev/null 2>&1 || true
	fi
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

stop_pid_file "${WEB_PID_FILE}" "Karkinos Web frontend"
stop_pid_file "${PID_FILE}" "Karkinos Web service"

cleanup_orphans_by_command "${REPO_ROOT}/web/node_modules/.bin/vite --host .* --port ${FRONTEND_PORT}" "Karkinos Web frontend"
cleanup_orphans_by_command "${REPO_ROOT}/.venv/bin/python.* -m server" "Karkinos Web service"
cleanup_orphans_by_command "uv run python -m server" "Karkinos Web service"
cleanup_orphans_by_port "${FRONTEND_PORT}" "Karkinos Web frontend"
cleanup_orphans_by_port "${BACKEND_PORT}" "Karkinos Web service"

echo "Karkinos Web processes stopped."
