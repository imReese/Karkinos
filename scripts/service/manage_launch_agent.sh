#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
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
USE_NATIVE_RELEASE=false
if [[ -L "${KARKINOS_HOME_PATH}/current" || -e "${KARKINOS_HOME_PATH}/current" ]]; then
	USE_NATIVE_RELEASE=true
fi
if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
	LOG_DIR="${KARKINOS_HOME_PATH}/logs"
	LOG_FILE="${LOG_DIR}/launch-agent-server.log"
else
	LOG_DIR="${REPO_ROOT}/logs"
	LOG_FILE="${LOG_DIR}/launch-agent-server.log"
fi
UV_CACHE_PATH="${REPO_ROOT}/.uv-cache"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
HEALTH_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS:-60}"
UNLOAD_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS:-10}"

usage() {
	cat <<'EOF'
Usage:
  ./scripts/service/manage_launch_agent.sh print-plist
  ./scripts/service/manage_launch_agent.sh install
  ./scripts/service/manage_launch_agent.sh status
  ./scripts/service/manage_launch_agent.sh uninstall

Commands:
  print-plist  Render the local LaunchAgent definition to stdout without writing.
  install      Install and start the current user's supervised Karkinos service.
  status       Report launchd state and service readiness.
  uninstall    Stop and remove only this exact user-level LaunchAgent.

Safety boundary:
  - This script does not edit config.json or .env.
  - When ~/Library/Application Support/Karkinos/current exists, it runs only that immutable SHA release.
  - Native release data, config, and logs remain under ~/Library/Application Support/Karkinos.
  - The live scheduler is part of the Karkinos service lifecycle and starts automatically.
  - Scheduler readiness does not establish financial readiness.
  - No command submits broker orders or changes capital authority.
EOF
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

resolve_uv() {
	local uv_bin
	uv_bin="$(command -v uv || true)"
	if [[ -z "${uv_bin}" || "${uv_bin}" != /* || ! -x "${uv_bin}" ]]; then
		echo "Error: an executable absolute uv path is required." >&2
		exit 1
	fi
	printf '%s' "${uv_bin}"
}

xml_escape() {
	sed \
		-e 's/&/\&amp;/g' \
		-e 's/</\&lt;/g' \
		-e 's/>/\&gt;/g' \
		-e 's/"/\&quot;/g'
}

render_plist() {
	local uv_bin="${1:-}"
	local escaped_workdir escaped_log escaped_cache escaped_home escaped_data escaped_config escaped_env escaped_entrypoint escaped_static
	local program_entrypoint program_arguments environment_entries
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		program_entrypoint="${NATIVE_ENTRYPOINT}"
		escaped_entrypoint="$(printf '%s' "${program_entrypoint}" | xml_escape)"
		escaped_workdir="$(printf '%s' "${KARKINOS_HOME_PATH}/current/app" | xml_escape)"
		program_arguments=$(
			cat <<EOF
    <string>${escaped_entrypoint}</string>
    <string>--host</string>
    <string>${BACKEND_HOST}</string>
    <string>--port</string>
    <string>${BACKEND_PORT}</string>
EOF
		)
	else
		program_entrypoint="${uv_bin}"
		escaped_entrypoint="$(printf '%s' "${program_entrypoint}" | xml_escape)"
		escaped_workdir="$(printf '%s' "${REPO_ROOT}" | xml_escape)"
		program_arguments=$(
			cat <<EOF
    <string>${escaped_entrypoint}</string>
    <string>run</string>
    <string>--frozen</string>
    <string>python</string>
    <string>-m</string>
    <string>server</string>
    <string>--host</string>
    <string>${BACKEND_HOST}</string>
    <string>--port</string>
    <string>${BACKEND_PORT}</string>
EOF
		)
	fi
	escaped_log="$(printf '%s' "${LOG_FILE}" | xml_escape)"
	escaped_cache="$(printf '%s' "${UV_CACHE_PATH}" | xml_escape)"
	escaped_home="$(printf '%s' "${KARKINOS_HOME_PATH}" | xml_escape)"
	escaped_static="$(printf '%s' "${KARKINOS_HOME_PATH}/current/app/web/dist" | xml_escape)"
	escaped_data="$(printf '%s' "${KARKINOS_HOME_PATH}/data" | xml_escape)"
	escaped_config="$(printf '%s' "${KARKINOS_HOME_PATH}/config/config.json" | xml_escape)"
	escaped_env="$(printf '%s' "${KARKINOS_HOME_PATH}/config/.env" | xml_escape)"
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		environment_entries=$(
			cat <<EOF
    <key>KARKINOS_HOME</key><string>${escaped_home}</string>
    <key>KARKINOS_DATA_DIR</key><string>${escaped_data}</string>
    <key>KARKINOS_CONFIG_PATH</key><string>${escaped_config}</string>
    <key>KARKINOS_ENV_FILE</key><string>${escaped_env}</string>
    <key>KARKINOS_STATIC_DIR</key><string>${escaped_static}</string>
EOF
		)
	else
		environment_entries="    <key>UV_CACHE_DIR</key><string>${escaped_cache}</string>"
	fi
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

karkinos_service_is_ready() {
	if ! command -v curl >/dev/null 2>&1; then
		return 1
	fi
	local response
	response="$(
		curl --noproxy '*' --fail --silent --show-error --max-time 2 \
			"http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" 2>/dev/null
	)" || return 1
	[[ "${response}" == *'"schema_version":"karkinos.service_health.v1"'* &&
		"${response}" == *'"status":"alive"'* &&
		"${response}" == *'"financial_readiness_claimed":false'* &&
		"${response}" == *'"broker_submission_enabled":false'* &&
		"${response}" == *'"capital_authority_changed":false'* ]] || return 1
	local live_response
	live_response="$(
		curl --noproxy '*' --fail --silent --show-error --max-time 2 \
			"http://${BACKEND_HOST}:${BACKEND_PORT}/api/settings/live/status" 2>/dev/null
	)" || return 1
	[[ "${live_response}" == *'"running":true'* ]]
}

listener_pids() {
	if ! command -v lsof >/dev/null 2>&1; then
		return
	fi
	lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

print_compact_status() {
	if ! service_is_loaded; then
		echo "LaunchAgent: not installed or not loaded (${SERVICE_TARGET})"
		return 1
	fi
	echo "LaunchAgent: loaded (${SERVICE_TARGET})"
	launchctl print "${SERVICE_TARGET}" | awk \
		'/state =|runs =|pid =|last exit code|last terminating signal/'
	if karkinos_service_is_ready; then
		echo "Service readiness: process alive, live scheduler running at http://${BACKEND_HOST}:${BACKEND_PORT}"
		echo "Financial readiness: not claimed"
		echo "Broker submission: disabled"
		return 0
	fi
	echo "Service readiness: unavailable" >&2
	echo "Financial readiness: not claimed" >&2
	return 1
}

preflight_install() {
	local uv_bin="${1:-}"
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	require_positive_integer \
		"${HEALTH_TIMEOUT_SECONDS}" \
		"KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS" \
		300
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		if [[ ! -L "${KARKINOS_HOME_PATH}/current" || ! -x "${NATIVE_ENTRYPOINT}" ]]; then
			echo "Error: current native release must be an executable release symlink." >&2
			exit 1
		fi
		local release_dir release_name
		release_dir="$(CDPATH='' cd -- "${KARKINOS_HOME_PATH}/current" && pwd -P)"
		release_name="${release_dir##*/}"
		if [[ "${release_dir}" != "${KARKINOS_HOME_PATH}/releases/${release_name}" ||
			! "${release_name}" =~ ^sha-[0-9a-f]{40}$ ||
			! -f "${release_dir}/release.json" ]]; then
			echo "Error: current native release pointer is invalid." >&2
			exit 1
		fi
		return
	fi
	if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
		echo "Error: pyproject.toml was not found under ${REPO_ROOT}." >&2
		exit 1
	fi
	if [[ ! -f "${REPO_ROOT}/web/dist/index.html" ]]; then
		echo "Error: web/dist/index.html is missing; build the product frontend first." >&2
		exit 1
	fi
	if ! UV_CACHE_DIR="${UV_CACHE_PATH}" "${uv_bin}" run --frozen python -m server --check-config >/dev/null; then
		echo "Error: Karkinos configuration validation failed." >&2
		exit 1
	fi
}

install_agent() {
	require_darwin
	local uv_bin=""
	if [[ "${USE_NATIVE_RELEASE}" != "true" ]]; then
		uv_bin="$(resolve_uv)"
	fi
	preflight_install "${uv_bin}"
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
		if karkinos_service_is_ready; then
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
	render_plist "${uv_bin}" >"${temporary_plist}"
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

uninstall_agent() {
	require_darwin
	require_positive_integer \
		"${UNLOAD_TIMEOUT_SECONDS}" \
		"KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS" \
		60
	if service_is_loaded; then
		launchctl bootout "${SERVICE_TARGET}"
		local deadline=$((SECONDS + UNLOAD_TIMEOUT_SECONDS))
		while service_is_loaded && ((SECONDS < deadline)); do
			sleep 1
		done
		if service_is_loaded; then
			echo "Error: ${SERVICE_TARGET} remained loaded after ${UNLOAD_TIMEOUT_SECONDS}s." >&2
			echo "The plist was preserved; inspect the exact job before retrying." >&2
			exit 1
		fi
	fi
	if [[ -f "${PLIST_PATH}" ]]; then
		rm -f "${PLIST_PATH}"
	fi
	echo "Uninstalled ${SERVICE_TARGET}."
	echo "Runtime data and logs were not deleted."
}

command="${1:-}"
case "${command}" in
print-plist)
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	if [[ "${USE_NATIVE_RELEASE}" == "true" ]]; then
		render_plist
	else
		render_plist "$(resolve_uv)"
	fi
	;;
install)
	install_agent
	;;
status)
	require_darwin
	require_positive_integer "${BACKEND_PORT}" "KARKINOS_BACKEND_PORT" 65535
	print_compact_status
	;;
uninstall)
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
