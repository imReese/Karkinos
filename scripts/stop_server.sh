#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUNTIME_DIR="${REPO_ROOT}/.run"
PID_FILE="${RUNTIME_DIR}/server.pid"
START_FILE="${RUNTIME_DIR}/server.start"
OWNER_FILE="${RUNTIME_DIR}/server.owner"
META_FILE="${RUNTIME_DIR}/server.meta"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/stop_server.sh

Stops the currently managed Karkinos source runtime. Takes no arguments;
branch selection belongs to start_server.sh.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -gt 0 ]]; then
    echo "Error: stop_server.sh takes no arguments (got: ${1})." >&2
    echo "It stops the currently managed runtime; branch selection belongs to start_server.sh." >&2
    exit 1
fi

process_start_identity() {
    ps -p "$1" -o lstart= 2>/dev/null |
        sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

process_command() {
    ps -p "$1" -o command= 2>/dev/null || true
}

clear_runtime_state() {
    rm -f \
        "${PID_FILE}" \
        "${START_FILE}" \
        "${OWNER_FILE}" \
        "${META_FILE}"
}

signal_tree() {
    local pid="$1"
    local signal="$2"
    local child

    while IFS= read -r child; do
        [[ -n "${child}" ]] || continue
        signal_tree "${child}" "${signal}"
    done < <(pgrep -P "${pid}" 2>/dev/null || true)

    kill "-${signal}" "${pid}" >/dev/null 2>&1 || true
}

if [[ ! -f "${PID_FILE}" ]]; then
    echo "Karkinos is not running."
    clear_runtime_state
    exit 0
fi

pid="$(cat "${PID_FILE}" 2>/dev/null || true)"

if [[ ! "${pid}" =~ ^[0-9]+$ ]]; then
    echo "Invalid Karkinos PID record; removing stale runtime state." >&2
    clear_runtime_state
    exit 1
fi

if ! kill -0 "${pid}" >/dev/null 2>&1; then
    echo "Karkinos is already stopped."
    clear_runtime_state
    exit 0
fi

owner="$(cat "${OWNER_FILE}" 2>/dev/null || true)"
recorded_start="$(cat "${START_FILE}" 2>/dev/null || true)"
current_start="$(process_start_identity "${pid}")"
command="$(process_command "${pid}")"

if [[ -n "${recorded_start}" &&
    "${recorded_start}" != "${current_start}" ]]; then

    echo "Refusing to stop PID ${pid}: process identity changed." >&2
    echo "No process was signaled." >&2
    exit 1
fi

case "${owner}" in
    dev:*)
        expected="${owner#dev:}"

        if [[ "${command}" != *"${expected}"* ]]; then
            echo "Refusing to stop PID ${pid}: it no longer looks like the Karkinos dev runtime." >&2
            exit 1
        fi
        ;;

    server:*)
        expected="${owner#server:}"

        if [[ "${command}" != *"${expected}"* ||
            "${command}" != *"-m server"* ]]; then
            echo "Refusing to stop PID ${pid}: it no longer looks like the Karkinos server." >&2
            exit 1
        fi
        ;;

    *)
        echo "Refusing to stop PID ${pid}: unknown runtime owner." >&2
        exit 1
        ;;
esac

echo "Stopping Karkinos (PID ${pid})..."

signal_tree "${pid}" TERM

for _ in {1..32}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
        clear_runtime_state
        echo "Karkinos stopped."
        exit 0
    fi

    sleep 0.25
done

echo "Karkinos did not stop gracefully; forcing shutdown..."

signal_tree "${pid}" KILL

for _ in {1..8}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
        clear_runtime_state
        echo "Karkinos stopped."
        exit 0
    fi

    sleep 0.25
done

echo "Error: Karkinos PID ${pid} is still running." >&2
exit 1
