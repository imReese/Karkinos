#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${REPO_ROOT}/.run/server.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "MyQuant Web service is not running."
  exit 0
fi

PID="$(cat "${PID_FILE}")"

if [[ -z "${PID}" ]]; then
  echo "Error: PID file is empty." >&2
  rm -f "${PID_FILE}"
  exit 1
fi

if ! kill -0 "${PID}" >/dev/null 2>&1; then
  echo "MyQuant Web service is not running, cleaning stale PID file."
  rm -f "${PID_FILE}"
  exit 0
fi

kill "${PID}"

for _ in {1..20}; do
  if ! kill -0 "${PID}" >/dev/null 2>&1; then
    rm -f "${PID_FILE}"
    echo "Stopped MyQuant Web service (${PID})."
    exit 0
  fi
  sleep 0.5
done

echo "MyQuant Web service did not stop gracefully, sending SIGKILL."
kill -9 "${PID}"
rm -f "${PID_FILE}"
echo "Stopped MyQuant Web service (${PID})."
