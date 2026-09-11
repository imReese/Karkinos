# Karkinos Scripts

Run repository commands from the repository root.

```bash
./scripts/start_server.sh main
./scripts/start_server.sh dev
./scripts/start_server.sh prod
./scripts/stop_server.sh main
./scripts/stop_server.sh dev
./scripts/stop_server.sh prod
./scripts/stop_server.sh all
```

## Source user runtime

`main` runs the current clean `main` checkout. It does not fetch another copy of
the repository or create a nested source checkout.

For the normal clone-based workflow, the repository root is the workspace:

```text
Karkinos/
├── config.json
├── .env
├── data/store/
├── logs/
├── exports/
└── .run/main/
```

Create a new empty workspace once:

```bash
git switch main
cp config.example.json config.json
cp .env.example .env
./scripts/start_server.sh main --init
```

Later starts use:

```bash
./scripts/start_server.sh main
```

Run in the current terminal for debugging:

```bash
./scripts/start_server.sh main --foreground
```

Stop only the source user runtime:

```bash
./scripts/stop_server.sh main
```

`main` requires a clean local `main` at the same commit as `origin/main`. It
installs locked backend dependencies, builds the frontend, runs the persistent
state preflight, then starts the API and research worker.

### Workspace override

`KARKINOS_WORKSPACE` selects a different absolute workspace without changing the
source checkout:

```bash
export KARKINOS_WORKSPACE=/absolute/path/to/workspace
```

The selected workspace contains `config.json`, `.env`, `data/store`, `logs`,
`exports`, and `.run/main`. `KARKINOS_HOME` remains only as a compatibility alias
for older managed installations; new source usage should use
`KARKINOS_WORKSPACE`.

`KARKINOS_DATA_DIR`, `KARKINOS_CONFIG_PATH`, and `KARKINOS_ENV_FILE` remain
advanced explicit overrides and must be absolute in the managed source runtime.

`--init` is only for a genuinely new empty data store. It is not an upgrade or
repair operation.

## Development runtime

Development is separate from the user workspace:

```bash
git switch dev
./scripts/start_server.sh dev
```

The default development workspace is:

```text
.run/dev/
├── config/
├── data/
├── logs/
└── run/
```

It starts:

```text
Web     http://127.0.0.1:5173
API     http://127.0.0.1:8001
Health  http://127.0.0.1:8001/api/health
```

Stop it with:

```bash
./scripts/stop_server.sh dev
```

Use an absolute `KARKINOS_DEV_WORKSPACE` only when a different disposable
workspace is needed. Development strips user runtime paths and credentials before
launching. Never point it at real portfolio/account data.

## Installed native runtime

`prod` controls an already installed immutable release under the selected
workspace:

```bash
KARKINOS_WORKSPACE=/absolute/installed/workspace ./scripts/start_server.sh prod
KARKINOS_WORKSPACE=/absolute/installed/workspace ./scripts/stop_server.sh prod
```

Native release/bootstrap tooling is currently macOS-specific maintenance
infrastructure. It is not the normal source-development path and should not shape
the source workspace model.

## Specialized scripts

Subdirectories under `scripts/` contain focused tools for data ingestion,
configuration, CI, maintenance, migration, and release verification. A script is
not automatically a stable user interface merely because it exists.

## Safety

- User and development workspaces are separate.
- Do not commit runtime databases, `.env`, credentials, private logs, account
  exports, or screenshots containing financial information.
- Do not repair financial state by manually editing SQLite unless a documented
  migration or recovery procedure explicitly requires it.
- Process readiness does not imply market-data, portfolio, risk, or capital
  readiness.
