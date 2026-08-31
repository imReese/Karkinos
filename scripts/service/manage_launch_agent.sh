#!/usr/bin/env bash

set -euo pipefail
umask 077

LABEL="com.karkinos.daily-candidate"
USER_ID="$(id -u)"
DOMAIN="gui/${USER_ID}"
SERVICE_TARGET="${DOMAIN}/${LABEL}"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
DEFAULT_KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_KARKINOS_HOME}}"
if [[ "${KARKINOS_HOME_PATH}" != /* ]]; then
	echo "Error: KARKINOS_HOME must be an absolute path." >&2
	exit 1
fi
NATIVE_ENTRYPOINT="${KARKINOS_HOME_PATH}/current/bin/karkinos"
LOG_DIR="${KARKINOS_HOME_PATH}/logs"
LOG_FILE="${LOG_DIR}/launch-agent-server.log"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
HEALTH_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS:-120}"
UNLOAD_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS:-10}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/service/manage_launch_agent.sh print-plist
  ./scripts/service/manage_launch_agent.sh install
  ./scripts/service/manage_launch_agent.sh restart
  ./scripts/service/manage_launch_agent.sh status
  ./scripts/service/manage_launch_agent.sh uninstall

Commands:
  print-plist  Render the local LaunchAgent definition to stdout without writing.
  install      Install and start the current user's supervised Karkinos service.
  restart      Replace the loaded service with the exact current native release.
  status       Report launchd state and service readiness.
  uninstall    Stop and remove only this exact user-level LaunchAgent.

Safety boundary:
  - This script does not edit config.json or .env.
  - Production always runs the immutable SHA release selected by current; source fallback is forbidden.
  - Native release data, config, and logs remain under ~/Library/Application Support/Karkinos.
  - The live scheduler is part of the Karkinos service lifecycle and starts automatically.
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
	local escaped_workdir escaped_log escaped_home escaped_data escaped_config escaped_entrypoint escaped_static
	local environment_entries
	escaped_entrypoint="$(printf '%s' "${NATIVE_ENTRYPOINT}" | xml_escape)"
	escaped_workdir="$(printf '%s' "${KARKINOS_HOME_PATH}/current/app" | xml_escape)"
	local program_arguments
	program_arguments=$(
		cat <<EOF
    <string>${escaped_entrypoint}</string>
    <string>--host</string>
    <string>${BACKEND_HOST}</string>
    <string>--port</string>
    <string>${BACKEND_PORT}</string>
EOF
	)
	escaped_log="$(printf '%s' "${LOG_FILE}" | xml_escape)"
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
  <string>${LABEL}</string>
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
	launchctl print "${SERVICE_TARGET}" >/dev/null 2>&1
}

launchd_service_pid() {
	local output pid
	output="$(launchctl print "${SERVICE_TARGET}" 2>/dev/null)" || return 1
	pid="$(printf '%s\n' "${output}" | awk '$1 == "pid" && $2 == "=" && $3 ~ /^[0-9]+$/ { print $3 }')"
	[[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
	printf '%s\n' "${pid}"
}

require_current_release() {
	if [[ ! -L "${KARKINOS_HOME_PATH}/current" || ! -x "${NATIVE_ENTRYPOINT}" ]]; then
		echo "Error: production requires an executable immutable current release." >&2
		echo "Stage and promote a CI-built candidate before starting production." >&2
		exit 1
	fi
	local release_dir release_name manifest
	release_dir="$(CDPATH='' cd -- "${KARKINOS_HOME_PATH}/current" && pwd -P)"
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
	if [[ ! "${EXPECTED_RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ||
		! "${EXPECTED_ARTIFACT_FINGERPRINT}" =~ ^[0-9a-f]{64}$ ||
		-z "${EXPECTED_RELEASE_VERSION}" ||
		"${release_name}" != "sha-${EXPECTED_RELEASE_SHA}" ]]; then
		echo "Error: current native release identity is invalid." >&2
		exit 1
	fi
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
	if karkinos_service_is_ready; then
		echo "Service readiness: exact current release ${EXPECTED_RELEASE_SHA}, launchd owns the listener, live scheduler initialized at http://${BACKEND_HOST}:${BACKEND_PORT}"
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
	require_current_release
}

install_agent() {
	require_darwin
	preflight_install
	if service_is_loaded; then
		if [[ -f "${PLIST_PATH}" ]]; then
			echo "Karkinos LaunchAgent is already loaded; no process was replaced."
			print_compact_status
			return
		fi
		echo "Error: ${SERVICE_TARGET} is already loaded without ${PLIST_PATH}." >&2
		echo "No process was replaced. Inspect and remove that exact temporary job first." >&2
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
	local temporary_plist
	temporary_plist="$(mktemp "${TMPDIR:-/tmp}/karkinos-launch-agent.XXXXXX")"
	trap 'rm -f -- "${temporary_plist}"' EXIT
	render_plist >"${temporary_plist}"
	if ! plutil -lint "${temporary_plist}" >/dev/null; then
		echo "Error: generated LaunchAgent plist is invalid." >&2
		exit 1
	fi
	chmod 600 "${temporary_plist}"
	mv "${temporary_plist}" "${PLIST_PATH}"
	trap - EXIT

	if ! launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"; then
		rm -f "${PLIST_PATH}"
		echo "Error: launchctl bootstrap failed; the plist was removed." >&2
		exit 1
	fi

	local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if ! service_is_loaded; then
			break
		fi
		if karkinos_service_is_ready; then
			echo "Installed ${SERVICE_TARGET}."
			print_compact_status
			return
		fi
		sleep 1
	done

	launchctl bootout "${SERVICE_TARGET}" >/dev/null 2>&1 || true
	rm -f "${PLIST_PATH}"
	echo "Error: Karkinos service readiness did not become ready within ${HEALTH_TIMEOUT_SECONDS}s." >&2
	echo "The failed LaunchAgent was unloaded and its plist was removed." >&2
	echo "Inspect ${LOG_FILE}." >&2
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
	if ! service_is_loaded; then
		if [[ -n "${pids}" ]]; then
			echo "Error: ${SERVICE_TARGET} is not loaded, but port ${BACKEND_PORT} still has a listener." >&2
			echo "Listener PID(s): ${pids//$'\n'/ }" >&2
			echo "The plist was preserved; no process was signaled." >&2
			return 1
		fi
		if [[ -f "${PLIST_PATH}" ]]; then
			rm -f "${PLIST_PATH}"
		fi
		echo "Uninstalled ${SERVICE_TARGET}."
		echo "Runtime data and logs were not deleted."
		return 0
	fi

	if ! launchctl bootout "${SERVICE_TARGET}"; then
		echo "Error: launchctl could not unload ${SERVICE_TARGET}." >&2
		echo "The plist was preserved; no process was signaled." >&2
		return 1
	fi

	local deadline=$((SECONDS + UNLOAD_TIMEOUT_SECONDS))
	local loaded
	while :; do
		loaded=false
		if service_is_loaded; then
			loaded=true
		fi
		if ! pids="$(listener_pids)"; then
			echo "Error: could not determine whether port ${BACKEND_PORT} has a listener after bootout." >&2
			echo "The plist was preserved; no process was signaled." >&2
			return 1
		fi
		if [[ "${loaded}" == "false" && -z "${pids}" ]]; then
			if [[ -f "${PLIST_PATH}" ]]; then
				rm -f "${PLIST_PATH}"
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
	if [[ "${loaded}" == "true" ]]; then
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
