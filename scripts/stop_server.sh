#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_WORKSPACE="${KARKINOS_WORKSPACE:-${REPO_ROOT}}"
INSTALLED_HOME="${KARKINOS_HOME:-${KARKINOS_WORKSPACE:-${REPO_ROOT}}}"
LAUNCH_AGENT_LABEL="com.karkinos.daily-candidate"
LAUNCH_AGENT_TARGET="gui/$(id -u)/${LAUNCH_AGENT_LABEL}"
LAUNCH_AGENT_PLIST="${HOME}/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
PACKAGED_RELEASE_CONTROL="${INSTALLED_HOME}/current/bin/karkinosctl"
PRODUCTION_SERVICE_PORT="${KARKINOS_BACKEND_PORT:-}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/stop_server.sh [branch]
  ./scripts/stop_server.sh --branch <branch>
  ./scripts/stop_server.sh all
  ./scripts/stop_server.sh prod

main is the default source branch. Source branches share config.json, .env,
data/store, logs, and exports; only their process state differs under .run/<branch>.
Unknown listeners are never signaled.
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

resident_service_is_loaded() {
	[[ "$(uname -s)" == "Darwin" ]] || return 1
	command -v launchctl >/dev/null 2>&1 || return 1
	launchctl print "${LAUNCH_AGENT_TARGET}" >/dev/null 2>&1
}

stop_resident_service() {
	if ! production_service_port_is_valid; then
		echo "Error: KARKINOS_BACKEND_PORT must be an integer from 1 through 65535." >&2
		return 1
	fi
	if ! packaged_release_control_is_valid; then
		echo "Error: production service state has no packaged immutable release controller." >&2
		echo "Set KARKINOS_HOME to the installed runtime." >&2
		return 1
	fi
	local -a service_args=(service-stop)
	if [[ -n "${PRODUCTION_SERVICE_PORT}" ]]; then
		service_args+=(--service-port "${PRODUCTION_SERVICE_PORT}")
	fi
	"${PACKAGED_RELEASE_CONTROL}" "${service_args[@]}"
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
	source-backend)
		[[ "${command}" == *"${REPO_ROOT}/scripts/service/run_dev.py"* ||
			("${command}" == *"${REPO_ROOT}"* && "${command}" == *" -m server"*) ]]
		;;
	source-frontend)
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

stop_main() {
	KARKINOS_WORKSPACE="${SOURCE_WORKSPACE}" \
	KARKINOS_HOME="${SOURCE_WORKSPACE}" \
	KARKINOS_SOURCE_BRANCH=main \
		python3 "${SCRIPT_DIR}/service/run_main.py" --stop
}

stop_development_branch() {
	local branch="$1"
	local runtime="${SOURCE_WORKSPACE}/.run/${branch}"
	local status=0
	stop_tracked_process "${runtime}/frontend.pid" "Karkinos ${branch} frontend" "source-frontend" || status=1
	stop_tracked_process "${runtime}/backend.pid" "Karkinos ${branch} backend" "source-backend" || status=1
	return "${status}"
}

stop_all_source_development() {
	local status=0 pid_file runtime
	if [[ ! -d "${SOURCE_WORKSPACE}/.run" ]]; then
		return 0
	fi
	while IFS= read -r pid_file; do
		runtime="${pid_file%/frontend.pid}"
		stop_tracked_process "${pid_file}" "Karkinos source frontend" "source-frontend" || status=1
		stop_tracked_process "${runtime}/backend.pid" "Karkinos source backend" "source-backend" || status=1
	done < <(find "${SOURCE_WORKSPACE}/.run" -type f -name frontend.pid -print 2>/dev/null || true)
	while IFS= read -r pid_file; do
		stop_tracked_process "${pid_file}" "Karkinos source backend" "source-backend" || status=1
	done < <(find "${SOURCE_WORKSPACE}/.run" -type f -name backend.pid -print 2>/dev/null || true)
	return "${status}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

if [[ "${1:-}" == "prod" ]]; then
	shift
	(($# == 0)) || {
		usage >&2
		exit 2
	}
	if packaged_release_control_is_valid ||
		resident_service_is_loaded ||
		[[ -f "${LAUNCH_AGENT_PLIST}" ]]; then
		stop_resident_service
		echo "Karkinos production service stopped."
	else
		echo "Karkinos production service is not running."
	fi
	exit 0
fi

TARGET_BRANCH="main"
if [[ "${1:-}" == "--branch" ]]; then
	(($# == 2)) || {
		usage >&2
		exit 2
	}
	TARGET_BRANCH="$2"
elif [[ -n "${1:-}" ]]; then
	(($# == 1)) || {
		usage >&2
		exit 2
	}
	TARGET_BRANCH="$1"
fi

if [[ "${TARGET_BRANCH}" == "all" ]]; then
	EXIT_STATUS=0
	stop_main || EXIT_STATUS=1
	stop_all_source_development || EXIT_STATUS=1
	if ((EXIT_STATUS != 0)); then
		exit "${EXIT_STATUS}"
	fi
	echo "Karkinos source runtimes stopped."
	exit 0
fi

git check-ref-format --branch "${TARGET_BRANCH}" >/dev/null 2>&1 || {
	echo "Error: invalid Git branch '${TARGET_BRANCH}'." >&2
	exit 2
}

if [[ "${TARGET_BRANCH}" == "main" ]]; then
	stop_main
else
	stop_development_branch "${TARGET_BRANCH}"
fi

echo "Karkinos ${TARGET_BRANCH} runtime stopped. Unknown listeners were not touched."
