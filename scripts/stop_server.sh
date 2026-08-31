#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
LAUNCH_AGENT_LABEL="com.karkinos.daily-candidate"
LAUNCH_AGENT_TARGET="gui/$(id -u)/${LAUNCH_AGENT_LABEL}"
LAUNCH_AGENT_PLIST="${HOME}/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
PACKAGED_RELEASE_CONTROL="${KARKINOS_HOME_PATH}/current/bin/karkinosctl"
PRODUCTION_SERVICE_PORT="${KARKINOS_BACKEND_PORT:-}"

production_service_port_is_valid() {
	if [[ -z "${PRODUCTION_SERVICE_PORT}" ]]; then
		return 0
	fi
	[[ "${PRODUCTION_SERVICE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] &&
		((10#${PRODUCTION_SERVICE_PORT} <= 65535))
}

usage() {
	cat <<'EOF'
Usage:
  ./scripts/stop_server.sh [dev|prod|all]

Modes:
  dev   Stop only exact PID-tracked source development processes (default).
  prod  Stop only the supervised immutable production service.
  all   Stop both development and production services.

Unknown listeners are never signaled. Production is stopped only through the
packaged release controller selected by the managed current pointer.
EOF
}

packaged_release_control_is_valid() {
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
	# Stop through the physical release that was validated above. Re-reading
	# current here would reopen a pointer-switch race before the exec boundary.
	PACKAGED_RELEASE_CONTROL="${release_control}"
}

is_number() {
	[[ "${1:-}" =~ ^[0-9]+$ ]]
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
		echo "Migrate a legacy source LaunchAgent with the explicit release bootstrap workflow before stopping it here." >&2
		return 1
	fi
	local -a service_args=(service-stop)
	if [[ -n "${PRODUCTION_SERVICE_PORT}" ]]; then
		service_args+=(--service-port "${PRODUCTION_SERVICE_PORT}")
	fi
	"${PACKAGED_RELEASE_CONTROL}" "${service_args[@]}"
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
		[[ "${command}" == *"${REPO_ROOT}"* && "${command}" == *" -m server"* ]]
		;;
	dev-frontend)
		[[ "${command}" == *"${REPO_ROOT}/web"* && "${command}" == *"vite"* ]]
		;;
	legacy-native)
		[[ "${command}" == *"${KARKINOS_HOME_PATH}/"* && "${command}" == *"/bin/karkinos"* ]]
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
		echo "${label} is not running."
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
		echo "${label} is not running; cleaning its stale PID file."
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

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	(($# == 1)) || {
		usage >&2
		exit 2
	}
	usage
	exit 0
fi
if (($# > 1)); then
	usage >&2
	exit 2
fi

MODE="${1:-dev}"
case "${MODE}" in
dev)
	STOP_DEVELOPMENT=true
	STOP_PRODUCTION=false
	;;
prod)
	STOP_DEVELOPMENT=false
	STOP_PRODUCTION=true
	;;
all)
	STOP_DEVELOPMENT=true
	STOP_PRODUCTION=true
	;;
*)
	echo "Error: unknown mode '${MODE}'." >&2
	usage >&2
	exit 2
	;;
esac

EXIT_STATUS=0
if [[ "${STOP_DEVELOPMENT}" == true ]]; then
	stop_tracked_process "${REPO_ROOT}/.run/web.pid" "Karkinos development frontend" "dev-frontend" || EXIT_STATUS=1
	stop_tracked_process "${REPO_ROOT}/.run/dev-server.pid" "Karkinos development backend" "dev-backend" || EXIT_STATUS=1

	# Clean up only old PID-file based source processes from transitional scripts.
	if [[ -f "${REPO_ROOT}/.run/server.pid" ]]; then
		stop_tracked_process "${REPO_ROOT}/.run/server.pid" "legacy Karkinos source backend" "dev-backend" || EXIT_STATUS=1
	fi
fi

if [[ "${STOP_PRODUCTION}" == true ]]; then
	# Clean up only the exact old native PID record. No port sweep is performed.
	if [[ -f "${KARKINOS_HOME_PATH}/.run/server.pid" ]]; then
		stop_tracked_process "${KARKINOS_HOME_PATH}/.run/server.pid" "legacy Karkinos native backend" "legacy-native" || EXIT_STATUS=1
	fi

	if packaged_release_control_is_valid ||
		resident_service_is_loaded ||
		[[ -f "${LAUNCH_AGENT_PLIST}" ]]; then
		if stop_resident_service; then
			echo "Karkinos production service stopped."
		else
			echo "Error: failed to stop ${LAUNCH_AGENT_TARGET}." >&2
			EXIT_STATUS=1
		fi
	else
		echo "Karkinos production service is not running."
	fi
fi

if ((EXIT_STATUS != 0)); then
	echo "Error: one or more tracked Karkinos processes could not be stopped safely." >&2
	exit "${EXIT_STATUS}"
fi

echo "Karkinos ${MODE} services stopped. Unknown listeners were not touched."
