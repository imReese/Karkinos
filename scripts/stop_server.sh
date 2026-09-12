#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_WORKSPACE="${KARKINOS_WORKSPACE:-${REPO_ROOT}}"
DEFAULT_INSTALLED_HOME="${HOME}/Library/Application Support/Karkinos"
INSTALLED_HOME="${KARKINOS_HOME:-${DEFAULT_INSTALLED_HOME}}"
LAUNCH_AGENT_LABEL="com.karkinos.daily-candidate"
WORKER_LAUNCH_AGENT_LABEL="com.karkinos.research-worker"
LAUNCH_AGENT_TARGET="gui/$(id -u)/${LAUNCH_AGENT_LABEL}"
WORKER_LAUNCH_AGENT_TARGET="gui/$(id -u)/${WORKER_LAUNCH_AGENT_LABEL}"
LAUNCH_AGENT_PLIST="${HOME}/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
WORKER_LAUNCH_AGENT_PLIST="${HOME}/Library/LaunchAgents/${WORKER_LAUNCH_AGENT_LABEL}.plist"
PACKAGED_RELEASE_CONTROL="${INSTALLED_HOME}/current/bin/karkinosctl"
PRODUCTION_SERVICE_PORT="${KARKINOS_BACKEND_PORT:-}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/stop_server.sh
  ./scripts/stop_server.sh <branch>
  ./scripts/stop_server.sh --branch <branch>
  ./scripts/stop_server.sh prod

With no arguments, stop every known Karkinos runtime: the dev working tree,
all tracked stable source snapshots, and the legacy/native resident service when
present. Branch/prod arguments remain available for targeted shutdown.

Unknown listeners and unrelated processes are never signaled.
EOF
}

production_service_port_is_valid() {
	if [[ -z "${PRODUCTION_SERVICE_PORT}" ]]; then
		return 0
	fi
	[[ "${PRODUCTION_SERVICE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] &&
		((10#${PRODUCTION_SERVICE_PORT} <= 65535))
}

packaged_release_control_is_valid() {
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
	PACKAGED_RELEASE_CONTROL="${release_control}"
}

launch_agent_is_loaded() {
	local target="$1"
	[[ "$(uname -s)" == "Darwin" ]] || return 1
	command -v launchctl >/dev/null 2>&1 || return 1
	launchctl print "${target}" >/dev/null 2>&1
}

resident_service_is_loaded() {
	launch_agent_is_loaded "${LAUNCH_AGENT_TARGET}" ||
		launch_agent_is_loaded "${WORKER_LAUNCH_AGENT_TARGET}"
}

resident_service_state_exists() {
	resident_service_is_loaded ||
		[[ -f "${LAUNCH_AGENT_PLIST}" || -L "${LAUNCH_AGENT_PLIST}" ||
			-f "${WORKER_LAUNCH_AGENT_PLIST}" || -L "${WORKER_LAUNCH_AGENT_PLIST}" ]]
}

wait_until_launch_agent_stops() {
	local target="$1"
	local deadline=$((SECONDS + 10))
	while ((SECONDS < deadline)); do
		if ! launch_agent_is_loaded "${target}"; then
			return 0
		fi
		sleep 0.25
	done
	return 1
}

stop_exact_launch_agent() {
	local target="$1"
	local label="$2"
	if ! launch_agent_is_loaded "${target}"; then
		return 0
	fi
	if ! launchctl bootout "${target}"; then
		echo "Error: launchctl could not stop ${label}." >&2
		return 1
	fi
	if ! wait_until_launch_agent_stops "${target}"; then
		echo "Error: ${label} remained loaded after launchctl bootout." >&2
		return 1
	fi
}

remove_stale_launch_agent_plist() {
	local path="$1"
	if [[ -L "${path}" ]]; then
		echo "Error: refusing to remove symlinked LaunchAgent plist: ${path}" >&2
		return 1
	fi
	[[ -f "${path}" ]] || return 0
	rm -f -- "${path}"
}

stop_resident_without_controller() {
	if [[ "$(uname -s)" != "Darwin" ]] || ! command -v launchctl >/dev/null 2>&1; then
		echo "Error: resident Karkinos state exists but launchctl is unavailable." >&2
		return 1
	fi

	local status=0
	# Stop the worker first so it cannot outlive the API service during cleanup.
	stop_exact_launch_agent "${WORKER_LAUNCH_AGENT_TARGET}" "${WORKER_LAUNCH_AGENT_LABEL}" || status=1
	stop_exact_launch_agent "${LAUNCH_AGENT_TARGET}" "${LAUNCH_AGENT_LABEL}" || status=1
	if ((status != 0)); then
		return "${status}"
	fi
	remove_stale_launch_agent_plist "${WORKER_LAUNCH_AGENT_PLIST}" || status=1
	remove_stale_launch_agent_plist "${LAUNCH_AGENT_PLIST}" || status=1
	return "${status}"
}

stop_resident_service() {
	if ! production_service_port_is_valid; then
		echo "Error: KARKINOS_BACKEND_PORT must be an integer from 1 through 65535." >&2
		return 1
	fi
	if packaged_release_control_is_valid; then
		local -a service_args=(service-stop)
		if [[ -n "${PRODUCTION_SERVICE_PORT}" ]]; then
			service_args+=(--service-port "${PRODUCTION_SERVICE_PORT}")
		fi
		"${PACKAGED_RELEASE_CONTROL}" "${service_args[@]}"
		return
	fi
	stop_resident_without_controller
}

stop_resident_if_present() {
	if ! resident_service_state_exists; then
		return 0
	fi
	if ! stop_resident_service; then
		return 1
	fi
	echo "Karkinos resident service stopped."
}

is_number() {
	[[ "${1:-}" =~ ^[0-9]+$ ]]
}

process_start_identity() {
	ps -p "$1" -o lstart= 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

process_command() {
	ps -p "$1" -o command= 2>/dev/null
}

command_matches_owner() {
	local command="$1"
	local owner="$2"
	case "${owner}" in
	dev-backend)
		[[ "${command}" == *"${REPO_ROOT}/scripts/service/run_dev.py"* ||
			("${command}" == *"${REPO_ROOT}"* && "${command}" == *" -m server"*) ]]
		;;
	dev-frontend)
		[[ "${command}" == *"${REPO_ROOT}/web"* && "${command}" == *"vite"* ]]
		;;
	*) return 1 ;;
	esac
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

stop_tracked_process() {
	local pid_file="$1"
	local label="$2"
	local owner="$3"
	if [[ ! -f "${pid_file}" ]]; then
		return 0
	fi

	local record pid recorded_start current_start command
	record="$(cat "${pid_file}")"
	IFS=$'\t' read -r pid recorded_start <<<"${record}"
	if ! is_number "${pid}"; then
		echo "Error: invalid ${label} PID record; no process was signaled." >&2
		return 1
	fi
	if ! kill -0 "${pid}" >/dev/null 2>&1; then
		rm -f "${pid_file}"
		return 0
	fi

	command="$(process_command "${pid}")"
	if ! command_matches_owner "${command}" "${owner}"; then
		echo "Error: PID ${pid} no longer belongs to ${label}; no process was signaled." >&2
		return 1
	fi
	if [[ -n "${recorded_start:-}" ]]; then
		current_start="$(process_start_identity "${pid}")"
		if [[ -z "${current_start}" || "${current_start}" != "${recorded_start}" ]]; then
			echo "Error: PID ${pid} start identity changed; no process was signaled." >&2
			return 1
		fi
	fi

	signal_pid_tree "${pid}" TERM
	for _ in {1..20}; do
		if ! kill -0 "${pid}" >/dev/null 2>&1; then
			rm -f "${pid_file}"
			echo "Stopped ${label} (${pid})."
			return 0
		fi
		sleep 0.25
	done
	signal_pid_tree "${pid}" KILL
	for _ in {1..8}; do
		kill -0 "${pid}" >/dev/null 2>&1 || break
		sleep 0.25
	done
	if kill -0 "${pid}" >/dev/null 2>&1; then
		echo "Error: ${label} PID ${pid} did not stop." >&2
		return 1
	fi
	rm -f "${pid_file}"
	echo "Stopped ${label} (${pid})."
}

stop_snapshot_branch() {
	local branch="$1"
	KARKINOS_WORKSPACE="${SOURCE_WORKSPACE}" \
	KARKINOS_HOME="${SOURCE_WORKSPACE}" \
	KARKINOS_SOURCE_BRANCH="${branch}" \
		python3 "${SCRIPT_DIR}/service/run_main.py" --stop
}

stop_dev() {
	local runtime="${SOURCE_WORKSPACE}/.run/dev"
	local status=0
	stop_tracked_process "${runtime}/frontend.pid" "Karkinos dev frontend" "dev-frontend" || status=1
	stop_tracked_process "${runtime}/backend.pid" "Karkinos dev backend" "dev-backend" || status=1
	return "${status}"
}

stop_other_snapshots() {
	local status=0 socket runtime branch
	if [[ ! -d "${SOURCE_WORKSPACE}/.run" ]]; then
		return 0
	fi
	while IFS= read -r socket; do
		[[ -n "${socket}" ]] || continue
		runtime="${socket%/control.sock}"
		branch="${runtime#${SOURCE_WORKSPACE}/.run/}"
		[[ "${branch}" != "dev" && "${branch}" != "main" ]] || continue
		stop_snapshot_branch "${branch}" || status=1
	done < <(find "${SOURCE_WORKSPACE}/.run" -type s -name control.sock -print 2>/dev/null || true)
	return "${status}"
}

stop_everything() {
	local status=0
	stop_dev || status=1
	# Always ask main to stop; request_stop is a safe no-op when it is not running.
	stop_snapshot_branch main || status=1
	stop_other_snapshots || status=1
	stop_resident_if_present || status=1
	if ((status != 0)); then
		return "${status}"
	fi
	echo "Karkinos runtimes stopped. Unknown listeners were not touched."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

# Backward-compatible alias; no argument is the normal stop-everything command.
if [[ "${1:-}" == "all" ]]; then
	shift
	(($# == 0)) || {
		usage >&2
		exit 2
	}
	stop_everything
	exit $?
fi

if (($# == 0)); then
	stop_everything
	exit $?
fi

if [[ "${1:-}" == "prod" ]]; then
	shift
	(($# == 0)) || {
		usage >&2
		exit 2
	}
	if resident_service_state_exists; then
		stop_resident_service
		echo "Karkinos resident service stopped."
	else
		echo "Karkinos resident service is not running."
	fi
	exit 0
fi

TARGET_BRANCH=""
if [[ "${1:-}" == "--branch" ]]; then
	(($# == 2)) || {
		usage >&2
		exit 2
	}
	TARGET_BRANCH="$2"
elif (($# == 1)); then
	TARGET_BRANCH="$1"
else
	usage >&2
	exit 2
fi

git check-ref-format --branch "${TARGET_BRANCH}" >/dev/null 2>&1 || {
	echo "Error: invalid Git branch '${TARGET_BRANCH}'." >&2
	exit 2
}

if [[ "${TARGET_BRANCH}" == "dev" ]]; then
	stop_dev
else
	stop_snapshot_branch "${TARGET_BRANCH}"
fi

echo "Karkinos ${TARGET_BRANCH} runtime stopped. Unknown listeners were not touched."
