# Karkinos Scripts

Run repository commands from the repository root.

## Source runtime

The source launcher selects code by Git branch while keeping one shared local state directory.

```bash
./scripts/start_server.sh              # main
./scripts/start_server.sh dev          # dev
./scripts/start_server.sh feature/x    # another development branch
```

`main` is the default. `--branch <name>` is equivalent to passing the branch name positionally.

The normal local layout is:

```text
Karkinos/
├── config.json
├── .env
├── data/store/
├── logs/
├── exports/
└── .run/
    ├── source.lock
    ├── main/
    └── dev/
```

`config.json`, `.env`, `data/store`, `logs`, and `exports` are shared by `main`, `dev`, and other source branches. `.run/<branch>` contains only branch-specific PID/control state.

The launcher switches the Git checkout only when it is safe. It refuses to switch while the checkout contains uncommitted/untracked source changes or while a Karkinos source runtime is still using the checkout. It never runs `git reset`, `git clean`, or automatic `git stash`.

Only one source backend may use the shared local workspace at a time. `.run/source.lock` enforces this for the backend processes.

### First local initialization

```bash
cp config.example.json config.json
cp .env.example .env
./scripts/start_server.sh --init
```

`--init` is only for a genuinely new empty `main` data store. It is not an upgrade or repair command.

Later stable starts use:

```bash
./scripts/start_server.sh
```

Run stable `main` in the terminal for debugging:

```bash
./scripts/start_server.sh --foreground
```

Stop it with:

```bash
./scripts/stop_server.sh
```

### Development branches

```bash
./scripts/start_server.sh dev
```

For non-`main` branches the launcher starts:

```text
Web     http://127.0.0.1:5173
API     http://127.0.0.1:8001
Health  http://127.0.0.1:8001/api/health
```

Stop the selected development branch with:

```bash
./scripts/stop_server.sh dev
```

The development runtime uses the same `config.json`, `.env`, and `data/store` as `main`. This is intentional. Schema-changing development must therefore use explicit migrations and preserve persisted-data compatibility.

### Branch switching

Examples:

```bash
./scripts/start_server.sh main
./scripts/start_server.sh dev
./scripts/start_server.sh --branch feature/research-ui
```

If the selected branch is not currently checked out, the launcher switches to an existing local branch or an existing `origin/<branch>` remote-tracking branch. It does not fetch automatically; fetch explicitly when a branch is not available locally.

## Local paths

Source defaults are repository-local and platform-independent:

| Path | Purpose |
| --- | --- |
| `config.json` | local application configuration |
| `.env` | local credentials and environment overrides |
| `data/store/` | persistent databases and local data |
| `logs/` | runtime logs |
| `exports/` | user exports |
| `.run/<branch>/` | disposable branch process/control state |
| `.run/source.lock` | prevents concurrent source backends on the shared state |

`KARKINOS_WORKSPACE` remains an advanced override for running source code against an explicit absolute local workspace. When unset, the repository root is used. `KARKINOS_DATA_DIR`, `KARKINOS_CONFIG_PATH`, and `KARKINOS_ENV_FILE` remain advanced path overrides.

## Installed native runtime

`prod` is retained for existing immutable native installations and maintenance:

```bash
KARKINOS_HOME=/absolute/installed/runtime ./scripts/start_server.sh prod
KARKINOS_HOME=/absolute/installed/runtime ./scripts/stop_server.sh prod
```

This installed-release path is separate from the normal source branch workflow and does not define where source users keep local state.

## Specialized scripts

Subdirectories under `scripts/` contain focused tools for data ingestion, configuration, CI, maintenance, migration, and release verification. A script is not automatically a stable user interface merely because it exists.

## Safety

- Stop the current source runtime before switching branches.
- Do not commit runtime databases, `.env`, credentials, private logs, account exports, or screenshots containing financial information.
- Schema-changing development must use explicit migrations because source branches share the same local databases.
- Do not repair financial state by manually editing SQLite unless a documented migration or recovery procedure explicitly requires it.
- Process readiness does not imply market-data, portfolio, risk, or capital readiness.
