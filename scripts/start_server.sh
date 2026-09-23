#!/usr/bin/env bash

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUNTIME_DIR="${REPO_ROOT}/.run"
WORKTREE_DIR="${RUNTIME_DIR}/worktrees"
PID_FILE="${RUNTIME_DIR}/server.pid"
START_FILE="${RUNTIME_DIR}/server.start"
OWNER_FILE="${RUNTIME_DIR}/server.owner"
META_FILE="${RUNTIME_DIR}/server.meta"

BACKEND_PORT="${KARKINOS_BACKEND_PORT:-8000}"
DEV_WEB_PORT="${KARKINOS_FRONTEND_PORT:-5173}"
STARTUP_TIMEOUT="${KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS:-60}"

TARGET_BRANCH="${1:-main}"
if [[ "${TARGET_BRANCH}" == "dev" ]]; then
    BACKEND_PORT="${KARKINOS_DEV_BACKEND_PORT:-${BACKEND_PORT}}"
fi

usage() {
    cat <<'EOF'
Usage:
  ./scripts/start_server.sh
  ./scripts/start_server.sh main
  ./scripts/start_server.sh dev
  ./scripts/start_server.sh <branch>

Modes:
  main       Run the locally fetched origin/main in a managed Git worktree.
             Uses the repository-local stable config/data.

  dev        Run the current dev working tree, including uncommitted changes.
             Uses ~/.karkinos/development and enables backend/Vite reload.

  <branch>   Run another locally available branch in a managed Git worktree.
             Uses development state rather than stable main data.

The launcher never switches the current checkout and never runs git fetch.
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

if [[ "${TARGET_BRANCH}" == "-h" || "${TARGET_BRANCH}" == "--help" ]]; then
    usage
    exit 0
fi

git check-ref-format --branch "${TARGET_BRANCH}" >/dev/null 2>&1 ||
    die "invalid branch name: ${TARGET_BRANCH}"

mkdir -p "${RUNTIME_DIR}" "${WORKTREE_DIR}" "${REPO_ROOT}/logs"

process_start_identity() {
    ps -p "$1" -o lstart= 2>/dev/null |
        sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

existing_runtime_is_alive() {
    [[ -f "${PID_FILE}" ]] || return 1

    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"

    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    kill -0 "${pid}" >/dev/null 2>&1
}

clear_stale_runtime_state() {
    rm -f "${PID_FILE}" "${START_FILE}" "${OWNER_FILE}" "${META_FILE}"
}

if existing_runtime_is_alive; then
    pid="$(cat "${PID_FILE}")"
    echo "Karkinos is already running (PID ${pid})." >&2
    echo "Stop it first:" >&2
    echo "  ./scripts/stop_server.sh" >&2
    exit 1
fi

clear_stale_runtime_state

wait_for_url() {
    local url="$1"
    local label="$2"
    local pid="$3"
    local deadline=$((SECONDS + STARTUP_TIMEOUT))

    while ((SECONDS < deadline)); do
        if ! kill -0 "${pid}" >/dev/null 2>&1; then
            return 1
        fi

        if curl \
            --silent \
            --show-error \
            --fail \
            --max-time 1 \
            --noproxy '*' \
            "${url}" >/dev/null 2>&1; then
            return 0
        fi

        sleep 0.25
    done

    echo "${label} did not become ready within ${STARTUP_TIMEOUT}s." >&2
    return 1
}

resolve_branch_ref() {
    local branch="$1"

    if git -C "${REPO_ROOT}" show-ref \
        --verify --quiet "refs/remotes/origin/${branch}"; then
        printf '%s\n' "refs/remotes/origin/${branch}"
        return
    fi

    if git -C "${REPO_ROOT}" show-ref \
        --verify --quiet "refs/heads/${branch}"; then
        printf '%s\n' "refs/heads/${branch}"
        return
    fi

    die "branch '${branch}' is not available locally. Run 'git fetch origin' first."
}

prepare_worktree() {
    local branch="$1"
    local ref sha worktree

    ref="$(resolve_branch_ref "${branch}")"
    sha="$(git -C "${REPO_ROOT}" rev-parse "${ref}^{commit}")"
    worktree="${WORKTREE_DIR}/${branch}"

    mkdir -p "$(dirname "${worktree}")"

    if [[ ! -e "${worktree}/.git" ]]; then
        if [[ -e "${worktree}" ]]; then
            rm -rf "${worktree}"
        fi

        git -C "${REPO_ROOT}" worktree prune
        git -C "${REPO_ROOT}" worktree add \
            --detach \
            "${worktree}" \
            "${sha}"
    else
        git -C "${worktree}" reset --hard "${sha}" >/dev/null
        git -C "${worktree}" clean -fd >/dev/null
    fi

    SOURCE_ROOT="${worktree}"
    SOURCE_SHA="${sha}"
}

ensure_stable_workspace() {
    [[ -f "${REPO_ROOT}/config.json" ]] ||
        die "missing config.json; create it from config.example.json"

    [[ -f "${REPO_ROOT}/.env" ]] ||
        die "missing .env; create it from .env.example"

    mkdir -p \
        "${REPO_ROOT}/data/store" \
        "${REPO_ROOT}/logs" \
        "${REPO_ROOT}/exports"

    export KARKINOS_WORKSPACE="${REPO_ROOT}"
    export KARKINOS_HOME="${REPO_ROOT}"
    export KARKINOS_DATA_DIR="${REPO_ROOT}/data/store"
    export KARKINOS_WORKSPACE_ROLE="stable"
    export KARKINOS_CONFIG_PATH="${REPO_ROOT}/config.json"
    export KARKINOS_ENV_FILE="${REPO_ROOT}/.env"
}

ensure_development_workspace() {
    local home="${KARKINOS_DEV_HOME:-${HOME}/.karkinos/development}"

    mkdir -p \
        "${home}/config" \
        "${home}/data" \
        "${home}/logs"

    if [[ -f "${REPO_ROOT}/config.json" ]]; then
        if [[ ! -f "${home}/config/config.json" || "${REPO_ROOT}/config.json" -nt "${home}/config/config.json" ]]; then
            cp -p "${REPO_ROOT}/config.json" "${home}/config/config.json"
        fi
    elif [[ ! -f "${home}/config/config.json" ]]; then
        cat >"${home}/config/config.json" <<'EOF'
{
  "server": {
    "market_calendar_auto_sync": false
  },
  "ai": {
    "enabled": false
  }
}
EOF
    fi

    if [[ -f "${REPO_ROOT}/.env" ]]; then
        if [[ ! -s "${home}/config/.env" || "${REPO_ROOT}/.env" -nt "${home}/config/.env" ]]; then
            cp -p "${REPO_ROOT}/.env" "${home}/config/.env"
            chmod 600 "${home}/config/.env"
        fi
    elif [[ ! -f "${home}/config/.env" ]]; then
        touch "${home}/config/.env"
        chmod 600 "${home}/config/.env"
    fi

    mkdir -p "${REPO_ROOT}/logs"
    ln -sf "${REPO_ROOT}/logs/dev-server.log" "${home}/logs/dev-server.log"

    export KARKINOS_WORKSPACE="${home}"
    export KARKINOS_HOME="${home}"
    export KARKINOS_DATA_DIR="${home}/data"
    export KARKINOS_WORKSPACE_ROLE="development"
    export KARKINOS_CONFIG_PATH="${home}/config/config.json"
    export KARKINOS_ENV_FILE="${home}/config/.env"
}

write_runtime_state() {
    local pid="$1"
    local owner="$2"
    local branch="$3"
    local sha="$4"
    local source_root="$5"
    local mode="$6"

    printf '%s\n' "${pid}" >"${PID_FILE}"
    process_start_identity "${pid}" >"${START_FILE}"

    printf '%s\n' "${owner}" >"${OWNER_FILE}"

    cat >"${META_FILE}" <<EOF
mode=${mode}
branch=${branch}
sha=${sha}
source_root=${source_root}
backend_port=${BACKEND_PORT}
EOF
}

cleanup_failed_start() {
    local pid="$1"

    if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -TERM "${pid}" >/dev/null 2>&1 || true
        sleep 1
        kill -KILL "${pid}" >/dev/null 2>&1 || true
    fi

    clear_stale_runtime_state
}

start_dev() {
    local current_branch python log pid

    current_branch="$(
        git -C "${REPO_ROOT}" symbolic-ref \
            --quiet --short HEAD 2>/dev/null || true
    )"

    [[ "${current_branch}" == "dev" ]] ||
        die "start_server.sh dev requires the current checkout to be 'dev'"

    command -v uv >/dev/null 2>&1 ||
        die "'uv' was not found in PATH"

    ensure_development_workspace

    echo "Synchronizing development dependencies..."
    (
        cd "${REPO_ROOT}" || exit 1
        UV_CACHE_DIR="${REPO_ROOT}/.uv-cache" \
            uv sync --locked --extra server --extra dev
    ) || die "dependency sync failed; development server was not started"

    python="${REPO_ROOT}/.venv/bin/python"
    [[ -x "${python}" ]] ||
        die "Python environment was not created"

    [[ -x "${REPO_ROOT}/web/node_modules/.bin/vite" ]] ||
        die "frontend dependencies missing; run: npm ci --prefix web"

    echo "Checking and preparing development database..."
    (
        cd "${REPO_ROOT}"
        "${python}" scripts/service/run_dev.py --prepare-only
    ) || die "database preparation failed; development server was not started"

    log="${REPO_ROOT}/logs/dev-server.log"

    (
        cd "${REPO_ROOT}"
        exec nohup \
            "${python}" \
            "scripts/service/run_dev.py"
    ) >>"${log}" 2>&1 </dev/null &

    pid=$!

    write_runtime_state \
        "${pid}" \
        "dev:run_dev.py" \
        "dev" \
        "working-tree" \
        "${REPO_ROOT}" \
        "development"

    if ! wait_for_url \
        "http://127.0.0.1:${BACKEND_PORT}/api/health" \
        "Karkinos API" \
        "${pid}"; then

        cleanup_failed_start "${pid}"
        echo "Startup failed. Log: ${log}" >&2
        tail -n 40 "${log}" >&2 || true
        exit 1
    fi

    if ! wait_for_url \
        "http://127.0.0.1:${DEV_WEB_PORT}" \
        "Karkinos Web" \
        "${pid}"; then

        cleanup_failed_start "${pid}"
        echo "Startup failed. Log: ${log}" >&2
        tail -n 40 "${log}" >&2 || true
        exit 1
    fi

    cat <<EOF

Karkinos started

Mode:       development
Branch:     dev
Source:     ${REPO_ROOT}
Workspace:  ${KARKINOS_DEV_HOME:-${HOME}/.karkinos/development}
Web:        http://127.0.0.1:${DEV_WEB_PORT}
API:        http://127.0.0.1:${BACKEND_PORT}
PID:        ${pid}
Log:        ${log}

Stop:
  ./scripts/stop_server.sh

EOF
}

start_worktree_branch() {
    local branch="$1"
    local python log pid mode supports_preparation

    prepare_worktree "${branch}"

    command -v uv >/dev/null 2>&1 ||
        die "'uv' was not found in PATH"

    command -v npm >/dev/null 2>&1 ||
        die "'npm' was not found in PATH"

    if [[ "${branch}" == "main" ]]; then
        mode="stable"
        ensure_stable_workspace
        log="${REPO_ROOT}/logs/main-server.log"
    else
        mode="branch"
        ensure_development_workspace
        log="${REPO_ROOT}/logs/${branch//\//-}-server.log"
    fi

    export KARKINOS_STATIC_DIR="${SOURCE_ROOT}/web/dist"
    export KARKINOS_RELEASE_ROOT="${SOURCE_ROOT}"

    echo "Synchronizing Python dependencies for ${branch}..."
    (
        cd "${SOURCE_ROOT}"
        UV_CACHE_DIR="${REPO_ROOT}/.uv-cache" \
            uv sync --locked --extra server
    )

    python="${SOURCE_ROOT}/.venv/bin/python"
    [[ -x "${python}" ]] ||
        die "Python environment was not created for ${branch}"

    # Old target branches do not necessarily implement the preparation CLI.
    # Never use the launcher's dev registry to migrate another branch's data.
    supports_preparation=false
    if (cd "${SOURCE_ROOT}" && "${python}" -m server --help) |
        grep -q -- '--prepare-database'; then
        supports_preparation=true
        (
            cd "${SOURCE_ROOT}"
            "${python}" -m server --database-status
        ) || die "database compatibility check failed; server was not started"
    fi

    echo "Building Web UI for ${branch}..."
    npm ci --prefix "${SOURCE_ROOT}/web"
    npm --prefix "${SOURCE_ROOT}/web" run build

    if [[ "${supports_preparation}" == "true" ]]; then
        echo "Checking and preparing database for ${branch}..."
        (
            cd "${SOURCE_ROOT}"
            "${python}" -m server --prepare-database
        ) || die "database preparation failed; server was not started"
    fi

    (
        cd "${SOURCE_ROOT}"
        exec nohup env \
            KARKINOS_WORKSPACE="${KARKINOS_WORKSPACE}" \
            KARKINOS_HOME="${KARKINOS_HOME}" \
            KARKINOS_DATA_DIR="${KARKINOS_DATA_DIR}" \
            KARKINOS_CONFIG_PATH="${KARKINOS_CONFIG_PATH}" \
            KARKINOS_ENV_FILE="${KARKINOS_ENV_FILE}" \
            KARKINOS_STATIC_DIR="${KARKINOS_STATIC_DIR}" \
            KARKINOS_RELEASE_ROOT="${KARKINOS_RELEASE_ROOT}" \
            "${python}" \
            -m server \
            --host 127.0.0.1 \
            --port "${BACKEND_PORT}"
    ) >>"${log}" 2>&1 </dev/null &

    pid=$!

    write_runtime_state \
        "${pid}" \
        "server:${python}" \
        "${branch}" \
        "${SOURCE_SHA}" \
        "${SOURCE_ROOT}" \
        "${mode}"

    if ! wait_for_url \
        "http://127.0.0.1:${BACKEND_PORT}/api/health" \
        "Karkinos Server" \
        "${pid}"; then

        cleanup_failed_start "${pid}"
        echo "Startup failed. Log: ${log}" >&2
        tail -n 40 "${log}" >&2 || true
        exit 1
    fi

    cat <<EOF

Karkinos started

Mode:       ${mode}
Branch:     ${branch}
Commit:     ${SOURCE_SHA}
Source:     ${SOURCE_ROOT}
Workspace:  ${KARKINOS_WORKSPACE}
Web:        http://127.0.0.1:${BACKEND_PORT}
PID:        ${pid}
Log:        ${log}

Stop:
  ./scripts/stop_server.sh

EOF
}

if [[ "${TARGET_BRANCH}" == "dev" ]]; then
    start_dev
else
    start_worktree_branch "${TARGET_BRANCH}"
fi
