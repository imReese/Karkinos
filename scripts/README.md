# Karkinos Scripts

Run repository commands from the repository root.

## Development runtime

```bash
uv sync --locked --extra server --extra dev
npm ci --prefix web
./scripts/dev
```

The current checkout runs in the foreground with backend reload and Vite.
Open `http://127.0.0.1:5173`; the API is at `http://127.0.0.1:8000`.
Ctrl-C stops both processes. An occupied port fails startup without stopping
the existing listener. Application migration failures stop the development run.

Development defaults to `~/.karkinos/development/`:

| Path | Purpose |
| --- | --- |
| `config/config.json` | development configuration, created on first start |
| `config/.env` | optional development credentials |
| `data/` | development databases and local market data |
| `logs/` | development logs; process output goes to the terminal |
| `.development.lock` | prevents concurrent development writers |

New development configuration starts without account holdings or cash, with AI,
broker collectors, and automatic market-calendar synchronization disabled.
Configure optional development capabilities in this directory. The launcher
never copies financial state or reads the repository's `config.json` or `.env`.
Existing data requires its original configuration and uses the application's
normal migrations; startup never repairs or resets it automatically.

Explicit overrides:

```bash
./scripts/dev --home /absolute/development/path --port 19180 --web-port 19173
```

`KARKINOS_DEV_HOME`, `KARKINOS_DEV_BACKEND_PORT`, and `KARKINOS_FRONTEND_PORT`
provide the corresponding defaults. The runner clears inherited `KARKINOS_*` settings and binds runtime paths to the
selected development home. Put development credentials in its `config/.env`.
Do not point the development home at installed production state.

For a different branch or historical commit, create a standard Git worktree or
clone, install its dependencies, and run its `scripts/dev`. Use a separate home
when the checkouts need independent state. The retired `start_server.sh` and
`stop_server.sh` interfaces no longer create or control branch snapshots.
Existing ignored `.run` caches are not migrated or removed automatically.

## Installed runtime

Installed native releases own their configuration, data, logs, and process
lifecycle. Existing installations keep their current home, normally
`~/Library/Application Support/Karkinos`. They never use development state.

```bash
"${KARKINOS_HOME:-$HOME/Library/Application Support/Karkinos}/current/bin/karkinosctl" service-start
"${KARKINOS_HOME:-$HOME/Library/Application Support/Karkinos}/current/bin/karkinosctl" service-stop
"${KARKINOS_HOME:-$HOME/Library/Application Support/Karkinos}/current/bin/karkinosctl" status
```

The immutable installed controller owns release locks, migrations, activation,
rollback, and service supervision. Its `service-start` and `service-stop`
commands remain the installed process interface. Do not invoke the internal
LaunchAgent mutation commands directly or change branches to update an install.

## Container runtime

Docker Compose uses its own `karkinos-data` volume. Follow the root README for
container configuration; do not mount development or installed account state
into a container by default.

## Specialized scripts

Subdirectories contain focused data, configuration, CI, migration, and release
tools. A script is not automatically a stable user interface merely because it
exists. Process liveness never grants financial readiness or capital authority.
Never commit credentials, runtime databases, private logs, or account exports.
