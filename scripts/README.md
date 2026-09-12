# Karkinos Scripts

Run repository commands from the repository root.

## Source runtime

The source launcher selects code without switching the current Git checkout.

```bash
./scripts/start_server.sh              # cached main snapshot
./scripts/start_server.sh dev          # current dev working tree
./scripts/start_server.sh feature/x    # cached snapshot of another branch
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
    │   └── code/
    └── dev/
```

`config.json`, `.env`, `data/store`, `logs`, and `exports` are shared by all source branches. Code and derived dependencies are branch-specific. `.run/source.lock` prevents concurrent source backends from writing the same local state.

### Stable branch snapshots

`main` and other non-`dev` branches are materialized with `git archive` under `.run/<branch>/code`.

```bash
./scripts/start_server.sh
./scripts/start_server.sh feature/research-ui
```

The current checkout is not changed, cleaned, reset, or stashed. The snapshot uses `origin/<branch>` when that remote-tracking ref already exists locally, otherwise the local branch ref. The launcher does not fetch automatically:

```bash
git fetch origin
./scripts/start_server.sh
```

A cached snapshot is reused while its branch ref still resolves to the same commit. When the ref changes, the disposable code snapshot is rebuilt before startup.

Stable snapshots serve the built application on port `8000`. `--foreground` keeps the supervisor in the current terminal.

### First local initialization

```bash
cp config.example.json config.json
cp .env.example .env
./scripts/start_server.sh --init
```

`--init` is only for a genuinely new empty data store. It is not an upgrade or repair command.

Later stable starts use:

```bash
./scripts/start_server.sh
```

### Development

`dev` is the only source mode that runs the current working tree directly. Switch to `dev` yourself and keep developing there:

```bash
git switch dev
./scripts/start_server.sh dev
```

Local uncommitted dev edits are intentionally included. Development starts:

```text
Web     http://127.0.0.1:5173
API     http://127.0.0.1:8001
Health  http://127.0.0.1:8001/api/health
```

The development runtime uses the same `config.json`, `.env`, and `data/store` as stable snapshots. `.run/dev` contains only PID/process state. Schema-changing development must therefore use explicit migrations and preserve persisted-data compatibility.

You can remain on `dev` and run stable `main` without switching branches:

```bash
./scripts/stop_server.sh dev
./scripts/start_server.sh
```

### Stop commands

The normal stop command takes no mode argument:

```bash
./scripts/stop_server.sh
```

It stops every Karkinos runtime the launcher can identify as its own:

```text
current dev working-tree runtime
tracked stable source snapshots
legacy/native macOS resident service, when present
```

`all` is retained only as a compatibility alias; new usage should omit it. Targeted shutdown remains available when needed:

```bash
./scripts/stop_server.sh dev
./scripts/stop_server.sh main
./scripts/stop_server.sh feature/research-ui
./scripts/stop_server.sh prod
```

Source state and installed native state are resolved separately. The source workspace defaults to the repository root. The old macOS `~/Library/Application Support/Karkinos` location is consulted only as a legacy/native installed-runtime cleanup target; it is not the source workspace model.

The resident-service stop path prefers the existing immutable release controller. If that controller is unavailable but the exact Karkinos LaunchAgent labels remain, the stop command removes only those exact `com.karkinos.daily-candidate` and `com.karkinos.research-worker` jobs. Unknown listeners and unrelated processes are never killed by a port sweep.

## Local paths

Source defaults are repository-local and platform-independent:

| Path | Purpose |
| --- | --- |
| `config.json` | local application configuration |
| `.env` | local credentials and environment overrides |
| `data/store/` | persistent databases and local data |
| `logs/` | runtime logs |
| `exports/` | user exports |
| `.run/<branch>/code/` | disposable stable-branch source snapshot |
| `.run/<branch>/` | branch process/control state and derived runtime files |
| `.run/source.lock` | prevents concurrent source backends on the shared state |

`KARKINOS_WORKSPACE` remains an advanced absolute-path override. When unset, the repository root is used. The normal local workflow does not require an OS-specific application-data directory.

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

- Only one source backend may use the shared local state at a time.
- Do not commit runtime databases, `.env`, credentials, private logs, account exports, or screenshots containing financial information.
- Schema-changing development must use explicit migrations because source branches share the same local databases.
- Do not repair financial state by manually editing SQLite unless a documented migration or recovery procedure explicitly requires it.
- Process readiness does not imply market-data, portfolio, risk, or capital readiness.
