#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${REPO_ROOT}/.run/server.pid"
WEB_PID_FILE="${REPO_ROOT}/.run/web.pid"

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

  kill "${pid}"
  for _ in {1..20}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      rm -f "${pid_file}"
      echo "Stopped ${label} (${pid})."
      return 0
    fi
    sleep 0.5
  done

  echo "${label} did not stop gracefully, sending SIGKILL."
  kill -9 "${pid}"
  rm -f "${pid_file}"
  echo "Stopped ${label} (${pid})."
}

stop_pid_file "${WEB_PID_FILE}" "MyQuant Web frontend"
stop_pid_file "${PID_FILE}" "MyQuant Web service"
