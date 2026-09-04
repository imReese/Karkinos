#!/usr/bin/env bash

set -euo pipefail
umask 077

LABEL="com.karkinos.daily-candidate"
WORKER_LABEL="com.karkinos.research-worker"
USER_ID="$(id -u)"
DOMAIN="gui/${USER_ID}"
SERVICE_TARGET="${DOMAIN}/${LABEL}"
WORKER_SERVICE_TARGET="${DOMAIN}/${WORKER_LABEL}"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
WORKER_PLIST_PATH="${PLIST_DIR}/${WORKER_LABEL}.plist"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
if [[ "${KARKINOS_HOME_PATH}" != /* ]]; then
	echo "Error: KARKINOS_HOME must be an absolute path." >&2
	exit 1
fi
NATIVE_ENTRYPOINT="${KARKINOS_HOME_PATH}/current/bin/karkinos"
LOG_DIR="${KARKINOS_HOME_PATH}/logs"
LOG_FILE="${LOG_DIR}/launch-agent-server.log"
WORKER_LOG_FILE="${LOG_DIR}/launch-agent-research-worker.log"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
HEALTH_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS:-120}"
UNLOAD_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS:-10}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/service/manage_launch_agent.sh print-plist
  ./scripts/service/manage_launch_agent.sh print-worker-plist
  ./scripts/service/manage_launch_agent.sh install
  ./scripts/service/manage_launch_agent.sh restart
  ./scripts/service/manage_launch_agent.sh status
  ./scripts/service/manage_launch_agent.sh uninstall

Commands:
  print-plist  Render the local LaunchAgent definition to stdout without writing.
  print-worker-plist  Render the isolated research-worker LaunchAgent definition.
  install      Install and start the current user's supervised Karkinos service.
  restart      Replace the loaded service with the exact current native release.
  status       Report launchd state and service readiness.
  uninstall    Stop and remove only these exact user-level LaunchAgents.

Safety boundary:
  - This script does not edit config.json or .env.
  - Production always runs the immutable SHA release selected by current; source fallback is forbidden.
  - Native release data, config, and logs remain under ~/Library/Application Support/Karkinos.
  - The live scheduler and isolated research worker start automatically.
  - Scheduler readiness does not establish financial readiness.
  - No command submits broker orders or changes capital authority.
  - Mutating commands are internal to the locked release controller. Use
    ./scripts/start_server.sh prod and ./scripts/stop_server.sh prod as the public entrypoints.
EOF
}

require_release_controller() {
	local owner_pid="${KARKINOS_RELEASE_LOCK_OWNER_PID:-}"
	local nonce="${KARKINOS_RELEASE_LOCK_NONCE:-}"
	local recorded_pid recorded_nonce extra
	if [[ ! "${owner_pid}" =~ ^[1-9][0-9]*$ ||
		! "${nonce}" =~ ^[0-9a-f]{32}$ ||
		"${PPID}" != "${owner_pid}" ||
		-L "${KARKINOS_HOME_PATH}/.release.lock" ||
		! -f "${KARKINOS_HOME_PATH}/.release.lock" ]]; then
		echo "Error: service mutation must run through the locked Karkinos release controller." >&2
		echo "Use ./scripts/start_server.sh prod or ./scripts/stop_server.sh prod." >&2
		exit 1
	fi
	IFS=' ' read -r recorded_pid recorded_nonce extra <"${KARKINOS_HOME_PATH}/.release.lock" || true
	if [[ "${recorded_pid}" != "${owner_pid}" ||
		"${recorded_nonce}" != "${nonce}" || -n "${extra:-}" ]]; then
		echo "Error: service mutation must run through the locked Karkinos release controller." >&2
		echo "Use ./scripts/start_server.sh prod or ./scripts/stop_server.sh prod." >&2
		exit 1
	fi
}

require_positive_integer() {
	local value="$1"
	local label="$2"
	local maximum="$3"
	if [[ -z "${value}" || "${value}" == *[!0-9]* || "${value}" == "0" || "${value}" -gt "${maximum}" ]]; then
		echo "Error: ${label} must be an integer within [1, ${maximum}]." >&2
		exit 1
	fi
}

require_darwin() {
	if [[ "$(uname -s)" != "Darwin" ]]; then
		echo "Error: Karkinos LaunchAgent management is available only on macOS." >&2
		exit 1
	fi
	if ! command -v launchctl >/dev/null 2>&1; then
		echo "Error: launchctl was not found." >&2
		exit 1
	fi
}

xml_escape() {
	sed \
		-e 's/&/\&amp;/g' \
		-e 's/</\&lt;/g' \
		-e 's/>/\&gt;/g' \
		-e 's/"/\&quot;/g'
}

render_plist() {
	local rendered_label="${1:-${LABEL}}"
	local rendered_log="${2:-${LOG_FILE}}"
	local process_mode="${3:-server}"
	local escaped_workdir escaped_log escaped_home escaped_data escaped_config escaped_entrypoint escaped_static
	local environment_entries
	escaped_entrypoint="$(printf '%s' "${NATIVE_ENTRYPOINT}" | xml_escape)"
	escaped_workdir="$(printf '%s' "${KARKINOS_HOME_PATH}/current/app" | xml_escape)"
	local program_arguments
	if [[ "${process_mode}" == "worker" ]]; then
		program_arguments=$(
			cat <<EOF
    <string>${escaped_entrypoint}</string>
    <string>--research-worker</string>
EOF
		)
	else
		program_arguments=$(
			cat <<EOF
    <string>${escaped_entrypoint}</string>
    <string>--host</string>
    <string>${BACKEND_HOST}</string>
    <string>--port</string>
    <string>${BACKEND_PORT}</string>
EOF
		)
	fi
	escaped_log="$(printf '%s' "${rendered_log}" | xml_escape)"
	escaped_home="$(printf '%s' "${KARKINOS_HOME_PATH}" | xml_escape)"
	escaped_static="$(printf '%s' "${KARKINOS_HOME_PATH}/current/app/web/dist" | xml_escape)"
	escaped_data="$(printf '%s' "${KARKINOS_HOME_PATH}/data" | xml_escape)"
	escaped_config="$(printf '%s' "${KARKINOS_HOME_PATH}/config/config.json" | xml_escape)"
	environment_entries=$(
		cat <<EOF
    <key>KARKINOS_HOME</key><string>${escaped_home}</string>
    <key>KARKINOS_DATA_DIR</key><string>${escaped_data}</string>
    <key>KARKINOS_CONFIG_PATH</key><string>${escaped_config}</string>
    <key>KARKINOS_STATIC_DIR</key><string>${escaped_static}</string>
    <key>PYTHONDONTWRITEBYTECODE</key><string>1</string>
EOF
	)
	cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${rendered_label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>-u</string><string>http_proxy</string>
    <string>-u</string><string>https_proxy</string>
    <string>-u</string><string>HTTP_PROXY</string>
    <string>-u</string><string>HTTPS_PROXY</string>
    <string>-u</string><string>all_proxy</string>
    <string>-u</string><string>ALL_PROXY</string>
    <string>-u</string><string>DEFAULT_PROXY_URL</string>
${program_arguments}
  </array>
  <key>WorkingDirectory</key>
  <string>${escaped_workdir}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>NO_PROXY</key><string>127.0.0.1,localhost</string>
    <key>no_proxy</key><string>127.0.0.1,localhost</string>
${environment_entries}
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${escaped_log}</string>
  <key>StandardErrorPath</key>
  <string>${escaped_log}</string>
</dict>
</plist>
EOF
}

service_is_loaded() {
	local target="${1:-${SERVICE_TARGET}}"
	launchctl print "${target}" >/dev/null 2>&1
}

launchd_service_pid() {
	local target="${1:-${SERVICE_TARGET}}"
	local output pid
	output="$(launchctl print "${target}" 2>/dev/null)" || return 1
	pid="$(printf '%s\n' "${output}" | awk '$1 == "pid" && $2 == "=" && $3 ~ /^[0-9]+$/ { print $3 }')"
	[[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
	printf '%s\n' "${pid}"
}

unload_service_and_confirm() {
	local target="$1"
	local observed_pid=""
	local deadline
	observed_pid="$(launchd_service_pid "${target}" 2>/dev/null || true)"
	if service_is_loaded "${target}" && ! launchctl bootout "${target}"; then
		echo "Error: launchctl could not unload ${target}." >&2
		return 1
	fi
	deadline=$((SECONDS + UNLOAD_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! service_is_loaded "${target}" &&
			{ [[ -z "${observed_pid}" ]] || ! /bin/kill -0 "${observed_pid}" 2>/dev/null; }; then
			return 0
		fi
		sleep 1
	done
	echo "Error: ${target} did not fully stop within ${UNLOAD_TIMEOUT_SECONDS}s." >&2
	return 1
}

cleanup_failed_install() {
	local unload_api="$1"
	local unload_worker="$2"
	local cleanup_ok=true
	local remaining_pids=""
	if [[ "${unload_worker}" == "true" ]] &&
		! unload_service_and_confirm "${WORKER_SERVICE_TARGET}"; then
		cleanup_ok=false
	fi
	if [[ "${unload_api}" == "true" ]] &&
		! unload_service_and_confirm "${SERVICE_TARGET}"; then
		cleanup_ok=false
	fi
	if [[ "${unload_api}" == "true" ]]; then
		if ! remaining_pids="$(listener_pids)" || [[ -n "${remaining_pids}" ]]; then
			cleanup_ok=false
		fi
	fi
	if [[ "${cleanup_ok}" != "true" ]]; then
		echo "The LaunchAgent plist files were preserved for recovery." >&2
		return 1
	fi
	if [[ "${unload_api}" == "true" ]]; then
		rm -f "${PLIST_PATH}"
	fi
	if [[ "${unload_worker}" == "true" ]]; then
		rm -f "${WORKER_PLIST_PATH}"
	fi
	return 0
}

research_worker_is_ready() {
	local worker_pid worker_command
	[[ -f "${WORKER_PLIST_PATH}" && ! -L "${WORKER_PLIST_PATH}" ]] &&
		grep -Fq "<string>${WORKER_LABEL}</string>" "${WORKER_PLIST_PATH}" &&
		grep -Fq "current/bin/karkinos</string>" "${WORKER_PLIST_PATH}" &&
		grep -Fq '<string>--research-worker</string>' "${WORKER_PLIST_PATH}" &&
		! grep -Fq '<string>--host</string>' "${WORKER_PLIST_PATH}" &&
		service_is_loaded "${WORKER_SERVICE_TARGET}" || return 1
	worker_pid="$(launchd_service_pid "${WORKER_SERVICE_TARGET}")" || return 1
	worker_command="$(ps -p "${worker_pid}" -o command= 2>/dev/null)" || return 1
	[[ "${worker_command}" == *"${EXPECTED_RELEASE_DIR}/runtime/bin/python3.12"* &&
		"${worker_command}" == *" -m server --research-worker"* ]]
}

research_worker_requirement_is_ready() {
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
		research_worker_is_ready
		return
	fi
	! service_is_loaded "${WORKER_SERVICE_TARGET}" &&
		[[ ! -e "${WORKER_PLIST_PATH}" && ! -L "${WORKER_PLIST_PATH}" ]]
}

require_current_release() {
	if [[ ! -L "${KARKINOS_HOME_PATH}/current" || ! -x "${NATIVE_ENTRYPOINT}" ]]; then
		echo "Error: production requires an executable immutable current release." >&2
		echo "Stage and promote a CI-built candidate before starting production." >&2
		exit 1
	fi
	local release_dir release_name manifest
	release_dir="$(CDPATH='' cd -- "${KARKINOS_HOME_PATH}/current" && pwd -P)"
	EXPECTED_RELEASE_DIR="${release_dir}"
	release_name="${release_dir##*/}"
	manifest="${release_dir}/release.json"
	if [[ "${release_dir}" != "${KARKINOS_HOME_PATH}/releases/${release_name}" ||
		! "${release_name}" =~ ^sha-[0-9a-f]{40}$ ||
		! -f "${manifest}" || -L "${manifest}" ]]; then
		echo "Error: current native release pointer is invalid." >&2
		exit 1
	fi
	EXPECTED_RELEASE_SHA="$(grep -Eo '"commit_sha":"[0-9a-f]{40}"' "${manifest}" | cut -d '"' -f 4)"
	EXPECTED_ARTIFACT_FINGERPRINT="$(grep -Eo '"payload_fingerprint":"[0-9a-f]{64}"' "${manifest}" | cut -d '"' -f 4)"
	EXPECTED_RELEASE_VERSION="$(grep -Eo '"version":"[0-9A-Za-z.-]+"' "${manifest}" | cut -d '"' -f 4)"
	EXPECTED_RELEASE_CONTROL_PROTOCOL="$(grep -Eo '"release_control_protocol":[0-9]+' "${manifest}" | cut -d ':' -f 2)"
	if [[ ! "${EXPECTED_RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ||
		! "${EXPECTED_ARTIFACT_FINGERPRINT}" =~ ^[0-9a-f]{64}$ ||
		-z "${EXPECTED_RELEASE_VERSION}" ||
		"${release_name}" != "sha-${EXPECTED_RELEASE_SHA}" ]]; then
		echo "Error: current native release identity is invalid." >&2
		exit 1
	fi
	case "${EXPECTED_RELEASE_CONTROL_PROTOCOL}" in
	1) RESEARCH_WORKER_REQUIRED=false ;;
	2) RESEARCH_WORKER_REQUIRED=true ;;
	*)
		echo "Error: current release control protocol is unsupported." >&2
		exit 1
		;;
	esac
}

karkinos_http_identity_is_ready() {
	if ! command -v curl >/dev/null 2>&1; then
		return 1
	fi
	local response
	response="$(
		curl --noproxy '*' --fail --silent --show-error --max-time 2 \
			"http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" 2>/dev/null
	)" || return 1
	[[ "${response}" == *'"schema_version":"karkinos.service_health.v1"'* &&
		"${response}" == *'"service":"karkinos"'* &&
		"${response}" == *'"status":"alive"'* &&
		"${response}" == *'"version":"'"${EXPECTED_RELEASE_VERSION}"'"'* &&
		"${response}" == *'"release_sha":"'"${EXPECTED_RELEASE_SHA}"'"'* &&
		"${response}" == *'"artifact_fingerprint":"'"${EXPECTED_ARTIFACT_FINGERPRINT}"'"'* &&
		"${response}" == *'"financial_readiness_claimed":false'* &&
		"${response}" == *'"broker_submission_enabled":false'* &&
		"${response}" == *'"production_ledger_mutated":false'* &&
		"${response}" == *'"authorizes_execution":false'* &&
		"${response}" == *'"capital_authority_changed":false'* ]] || return 1
	local live_response
	live_response="$(
		curl --noproxy '*' --fail --silent --show-error --max-time 2 \
			"http://${BACKEND_HOST}:${BACKEND_PORT}/api/settings/live/status" 2>/dev/null
	)" || return 1
	local expected_guard=false
	if [[ -e "${KARKINOS_HOME_PATH}/.release-transaction.json" ||
		-L "${KARKINOS_HOME_PATH}/.release-transaction.json" ||
		-e "${KARKINOS_HOME_PATH}/.legacy-bootstrap-transaction.json" ||
		-L "${KARKINOS_HOME_PATH}/.legacy-bootstrap-transaction.json" ]]; then
		expected_guard=true
	fi
	[[ "${live_response}" == *'"running":true'* &&
		"${live_response}" == *'"initialized":true'* &&
		"${live_response}" == *'"activation_guarded":'"${expected_guard}"* ]]
}

karkinos_service_is_ready() {
	karkinos_http_identity_is_ready || return 1
	if ! command -v lsof >/dev/null 2>&1; then
		return 1
	fi
	local launchd_pid pids
	launchd_pid="$(launchd_service_pid)" || return 1
	pids="$(listener_pids)" || return 1
	[[ "${pids}" == "${launchd_pid}" ]]
}

listener_pids() {
	if ! command -v lsof >/dev/null 2>&1; then
		return 1
	fi
	local output status pid
	if output="$(lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null)"; then
		status=0
	else
		status=$?
	fi
	# lsof uses 1 for a successful query with no matching listener. Any other
	# failure means absence was not proven and must remain fail closed.
	if ((status != 0 && status != 1)) || { ((status == 1)) && [[ -n "${output}" ]]; }; then
		return 1
	fi
	while IFS= read -r pid; do
		[[ -z "${pid}" ]] && continue
		[[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
	done <<<"${output}"
	if [[ -n "${output}" ]]; then
		printf '%s\n' "${output}" | sort -u
	fi
}

print_compact_status() {
	require_current_release
	if ! service_is_loaded; then
		echo "LaunchAgent: not installed or not loaded (${SERVICE_TARGET})"
		return 1
	fi
	echo "LaunchAgent: loaded (${SERVICE_TARGET})"
	launchctl print "${SERVICE_TARGET}" | awk \
		'/state =|runs =|pid =|last exit code|last terminating signal/'
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
		if ! research_worker_is_ready; then
			echo "Research worker: unavailable (${WORKER_SERVICE_TARGET})" >&2
			echo "Financial readiness: not claimed" >&2
			return 1
		fi
		echo "Research worker: loaded (${WORKER_SERVICE_TARGET})"
		launchctl print "${WORKER_SERVICE_TARGET}" | awk \
			'/state =|runs =|pid =|last exit code|last terminating signal/'
	else
		if ! research_worker_requirement_is_ready; then
			echo "Research worker: unexpected for legacy protocol" >&2
			return 1
		fi
		echo "Research worker: not required by legacy release protocol 1"
	fi
	if karkinos_service_is_ready; then
		echo "Service readiness: exact current release ${EXPECTED_RELEASE_SHA}, launchd owns the listener, live scheduler initialized at http://${BACKEND_HOST}:${BACKEND_PORT}"
		if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
			echo "Research isolation: supervised worker loaded"
		else
			echo "Research isolation: legacy single-process rollback compatibility"
		fi
		echo "Financial readiness: not claimed"
		echo "Broker submission: disabled"
		return 0
	fi
	echo "Service readiness: unavailable" >&2
	echo "Financial readiness: not claimed" >&2
	return 1
}

preflight_install() {
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	require_positive_integer \
		"${HEALTH_TIMEOUT_SECONDS}" \
		"KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS" \
		3600
	if ! command -v lsof >/dev/null 2>&1; then
		echo "Error: lsof is required to bind service readiness to the launchd process." >&2
		exit 1
	fi
	if ! command -v ps >/dev/null 2>&1; then
		echo "Error: ps is required to bind the research worker to the current release." >&2
		exit 1
	fi
	require_current_release
}

install_agent() {
	require_darwin
	preflight_install
	if service_is_loaded; then
		if [[ "${RESEARCH_WORKER_REQUIRED}" == "false" && -f "${PLIST_PATH}" ]] &&
			research_worker_requirement_is_ready && karkinos_service_is_ready; then
			echo "Karkinos legacy-protocol LaunchAgent is already loaded; no process was replaced."
			print_compact_status
			return
		fi
		if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" && -f "${PLIST_PATH}" && -f "${WORKER_PLIST_PATH}" ]] &&
			research_worker_is_ready; then
			echo "Karkinos LaunchAgent is already loaded; no process was replaced."
			print_compact_status
			return
		fi
		if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" && -f "${PLIST_PATH}" && ! -f "${WORKER_PLIST_PATH}" ]] &&
			! service_is_loaded "${WORKER_SERVICE_TARGET}" &&
			karkinos_service_is_ready; then
			mkdir -p "${PLIST_DIR}" "${LOG_DIR}"
			local compatibility_worker_plist
			compatibility_worker_plist="$(mktemp "${TMPDIR:-/tmp}/karkinos-research-worker.XXXXXX")"
			trap 'rm -f -- "${compatibility_worker_plist}"' EXIT
			render_plist "${WORKER_LABEL}" "${WORKER_LOG_FILE}" worker >"${compatibility_worker_plist}"
			if ! plutil -lint "${compatibility_worker_plist}" >/dev/null; then
				echo "Error: generated research-worker LaunchAgent plist is invalid." >&2
				exit 1
			fi
			chmod 600 "${compatibility_worker_plist}"
			mv "${compatibility_worker_plist}" "${WORKER_PLIST_PATH}"
			trap - EXIT
			if ! launchctl bootstrap "${DOMAIN}" "${WORKER_PLIST_PATH}"; then
				cleanup_failed_install false true || true
				echo "Error: research-worker bootstrap failed; the existing API service was preserved." >&2
				exit 1
			fi
			local compatibility_deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
			while ((SECONDS < compatibility_deadline)); do
				if research_worker_is_ready; then
					echo "Installed ${WORKER_SERVICE_TARGET} alongside the existing exact-current API service."
					print_compact_status
					return
				fi
				sleep 1
			done
			cleanup_failed_install false true || true
			echo "Error: research-worker readiness did not become ready within ${HEALTH_TIMEOUT_SECONDS}s." >&2
			echo "The existing API service was preserved." >&2
			exit 1
		fi
		echo "Error: ${SERVICE_TARGET} is already loaded without ${PLIST_PATH}." >&2
		echo "No process was replaced. Inspect and remove that exact temporary job first." >&2
		exit 1
	fi
	if service_is_loaded "${WORKER_SERVICE_TARGET}"; then
		echo "Error: ${WORKER_SERVICE_TARGET} is loaded without the API service." >&2
		echo "No process was replaced. Use the locked release controller to recover." >&2
		exit 1
	fi

	local pids
	pids="$(listener_pids)"
	if [[ -n "${pids}" ]]; then
		if karkinos_http_identity_is_ready; then
			echo "Error: another Karkinos process already owns port ${BACKEND_PORT}." >&2
		else
			echo "Error: port ${BACKEND_PORT} is occupied by a non-responsive listener." >&2
		fi
		echo "Listener PID(s): ${pids//$'\n'/ }" >&2
		echo "No process was terminated." >&2
		exit 1
	fi

	mkdir -p "${PLIST_DIR}" "${LOG_DIR}"
	local temporary_plist temporary_worker_plist=""
	temporary_plist="$(mktemp "${TMPDIR:-/tmp}/karkinos-launch-agent.XXXXXX")"
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
		temporary_worker_plist="$(mktemp "${TMPDIR:-/tmp}/karkinos-research-worker.XXXXXX")"
	fi
	trap 'rm -f -- "${temporary_plist}" "${temporary_worker_plist}"' EXIT
	render_plist >"${temporary_plist}"
	if ! plutil -lint "${temporary_plist}" >/dev/null; then
		echo "Error: generated LaunchAgent plist is invalid." >&2
		exit 1
	fi
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
		render_plist "${WORKER_LABEL}" "${WORKER_LOG_FILE}" worker >"${temporary_worker_plist}"
		if ! plutil -lint "${temporary_worker_plist}" >/dev/null; then
			echo "Error: generated research-worker LaunchAgent plist is invalid." >&2
			exit 1
		fi
	fi
	chmod 600 "${temporary_plist}"
	mv "${temporary_plist}" "${PLIST_PATH}"
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "true" ]]; then
		chmod 600 "${temporary_worker_plist}"
		mv "${temporary_worker_plist}" "${WORKER_PLIST_PATH}"
	fi
	trap - EXIT

	if ! launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"; then
		cleanup_failed_install true true || true
		echo "Error: launchctl bootstrap failed." >&2
		exit 1
	fi
	local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! service_is_loaded; then
			break
		fi
		if karkinos_service_is_ready; then
			break
		fi
		sleep 1
	done
	if ! karkinos_service_is_ready; then
		cleanup_failed_install true true || true
		echo "Error: Karkinos service readiness did not become ready within ${HEALTH_TIMEOUT_SECONDS}s." >&2
		echo "The failed API LaunchAgent cleanup was attempted fail closed." >&2
		echo "Inspect ${LOG_FILE}." >&2
		exit 1
	fi
	if [[ "${RESEARCH_WORKER_REQUIRED}" == "false" ]]; then
		echo "Installed ${SERVICE_TARGET} for legacy release protocol 1."
		print_compact_status
		return
	fi
	# Initialize/migrate shared SQLite through the API before starting the second
	# process, avoiding two release-startup migration owners racing each other.
	if ! launchctl bootstrap "${DOMAIN}" "${WORKER_PLIST_PATH}"; then
		cleanup_failed_install true true || true
		echo "Error: research-worker bootstrap failed; paired cleanup was attempted." >&2
		exit 1
	fi

	deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! service_is_loaded ||
			! service_is_loaded "${WORKER_SERVICE_TARGET}"; then
			break
		fi
		if karkinos_service_is_ready && research_worker_is_ready; then
			echo "Installed ${SERVICE_TARGET}."
			print_compact_status
			return
		fi
		sleep 1
	done

	cleanup_failed_install true true || true
	echo "Error: Karkinos service readiness did not become ready within ${HEALTH_TIMEOUT_SECONDS}s." >&2
	echo "The failed LaunchAgent pair cleanup was attempted fail closed." >&2
	echo "Inspect ${LOG_FILE} and ${WORKER_LOG_FILE}." >&2
	exit 1
}

restart_agent() {
	require_darwin
	require_current_release
	uninstall_agent
	install_agent
}

uninstall_agent() {
	require_darwin
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	require_positive_integer \
		"${UNLOAD_TIMEOUT_SECONDS}" \
		"KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS" \
		60
	if ! command -v lsof >/dev/null 2>&1; then
		echo "Error: lsof is required to confirm that port ${BACKEND_PORT} has no listener." >&2
		echo "The plist was preserved; no process was signaled." >&2
		return 1
	fi

	local pids
	if ! pids="$(listener_pids)"; then
		echo "Error: could not determine whether port ${BACKEND_PORT} has a listener." >&2
		echo "The plist was preserved; no process was signaled." >&2
		return 1
	fi
	local loaded worker_loaded
	loaded=false
	worker_loaded=false
	if service_is_loaded; then
		loaded=true
	fi
	if service_is_loaded "${WORKER_SERVICE_TARGET}"; then
		worker_loaded=true
	fi
	if [[ "${loaded}" == "false" ]]; then
		if [[ -n "${pids}" ]]; then
			echo "Error: ${SERVICE_TARGET} is not loaded, but port ${BACKEND_PORT} still has a listener." >&2
			echo "Listener PID(s): ${pids//$'\n'/ }" >&2
			echo "The plist was preserved; no process was signaled." >&2
			return 1
		fi
		if [[ "${worker_loaded}" == "false" ]]; then
			if [[ -f "${PLIST_PATH}" || -f "${WORKER_PLIST_PATH}" ]]; then
				rm -f "${PLIST_PATH}" "${WORKER_PLIST_PATH}"
			fi
			echo "Uninstalled ${SERVICE_TARGET}."
			echo "Runtime data and logs were not deleted."
			return 0
		fi
	fi

	if [[ "${worker_loaded}" == "true" ]] &&
		! launchctl bootout "${WORKER_SERVICE_TARGET}"; then
		echo "Error: launchctl could not unload ${WORKER_SERVICE_TARGET}." >&2
		echo "The plist was preserved; no process was signaled." >&2
		return 1
	fi
	if service_is_loaded && ! launchctl bootout "${SERVICE_TARGET}"; then
		echo "Error: launchctl could not unload ${SERVICE_TARGET}." >&2
		echo "The plist was preserved; no process was signaled." >&2
		return 1
	fi

	local deadline=$((SECONDS + UNLOAD_TIMEOUT_SECONDS))
	while :; do
		loaded=false
		worker_loaded=false
		if service_is_loaded; then
			loaded=true
		fi
		if service_is_loaded "${WORKER_SERVICE_TARGET}"; then
			worker_loaded=true
		fi
		if ! pids="$(listener_pids)"; then
			echo "Error: could not determine whether port ${BACKEND_PORT} has a listener after bootout." >&2
			echo "The plist was preserved; no process was signaled." >&2
			return 1
		fi
		if [[ "${loaded}" == "false" && "${worker_loaded}" == "false" && -z "${pids}" ]]; then
			if [[ -f "${PLIST_PATH}" || -f "${WORKER_PLIST_PATH}" ]]; then
				rm -f "${PLIST_PATH}" "${WORKER_PLIST_PATH}"
			fi
			echo "Uninstalled ${SERVICE_TARGET}."
			echo "Runtime data and logs were not deleted."
			return 0
		fi
		if ((SECONDS >= deadline)); then
			break
		fi
		sleep 1
	done

	echo "Error: ${SERVICE_TARGET} did not fully stop within ${UNLOAD_TIMEOUT_SECONDS}s." >&2
	if [[ "${loaded}" == "true" || "${worker_loaded}" == "true" ]]; then
		echo "The launchd label remains loaded." >&2
	fi
	if [[ -n "${pids}" ]]; then
		echo "Port ${BACKEND_PORT} listener PID(s): ${pids//$'\n'/ }" >&2
	fi
	echo "The plist was preserved; no process was signaled." >&2
	return 1
}

command="${1:-}"
case "${command}" in
print-plist)
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	require_current_release
	render_plist
	;;
print-worker-plist)
	require_current_release
	render_plist "${WORKER_LABEL}" "${WORKER_LOG_FILE}" worker
	;;
install)
	require_release_controller
	install_agent
	;;
restart)
	require_release_controller
	restart_agent
	;;
status)
	require_darwin
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	print_compact_status
	;;
uninstall)
	require_release_controller
	uninstall_agent
	;;
-h | --help | help)
	usage
	;;
*)
	usage >&2
	exit 2
	;;
esac
