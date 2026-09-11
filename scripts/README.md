# Karkinos Scripts

Run repository commands from the repository root.

The stable lifecycle entry points are:

```bash
./scripts/start_server.sh dev
./scripts/start_server.sh main
./scripts/start_server.sh prod
./scripts/stop_server.sh dev
./scripts/stop_server.sh main
./scripts/stop_server.sh prod
./scripts/stop_server.sh all
```

Commands below script subdirectories are specialized development, maintenance,
CI, data, or release tools rather than the primary user interface.

## Development runtime

Start the normal development environment:

```bash
./scripts/start_server.sh dev
```

The development runtime uses a dedicated local home, separate configuration and
account data, a reloadable backend, and the Vite frontend. The usual frontend URL
is:

```text
http://127.0.0.1:5173
```

Stop it with:

```bash
./scripts/stop_server.sh dev
```

The default development home is `.run/dev-home`. Use an absolute
`KARKINOS_DEV_HOME` when a different dedicated development directory is needed.
Do not point development at a normal user or production account directory.

## Managed `main` runtime

Start the verified source from remote `main` while keeping the normal account
state outside the source checkout:

```bash
./scripts/start_server.sh main
```

The command prepares the exact remote `main` source under `$KARKINOS_HOME/source`
and uses the existing runtime data and configuration under `$KARKINOS_HOME`.
Preparing source does not copy private account data into the checkout.

Common controls:

```bash
./scripts/start_server.sh main --status
./scripts/start_server.sh main --logs
./scripts/start_server.sh main --logs --follow
./scripts/start_server.sh main --no-update
./scripts/start_server.sh main --restart
./scripts/start_server.sh main --foreground
./scripts/stop_server.sh main
```

An existing account normally requires its expected configuration and databases
to exist. Missing account state fails explicitly rather than silently creating a
new empty account.

### New local account

Only when intentionally creating a new account, prepare configuration and use
`--init`:

```bash
export KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
mkdir -p "$KARKINOS_HOME/config"
test -e "$KARKINOS_HOME/config/config.json" || cp config.example.json "$KARKINOS_HOME/config/config.json"
test -e "$KARKINOS_HOME/config/.env" || cp .env.example "$KARKINOS_HOME/config/.env"
./scripts/start_server.sh main --init
```

Do not use `--init` as an upgrade or repair command for an existing account.

## Runtime paths

The managed `main` runtime uses these defaults:

| Variable | Default |
| --- | --- |
| `KARKINOS_HOME` | `~/Library/Application Support/Karkinos` |
| `KARKINOS_DATA_DIR` | `$KARKINOS_HOME/data` |
| `KARKINOS_CONFIG_PATH` | `$KARKINOS_HOME/config/config.json` |
| `KARKINOS_ENV_FILE` | `$KARKINOS_HOME/config/.env` |

Explicit overrides should use absolute paths for managed runtime data.

## Legacy immutable-release runtime

`prod` is the existing immutable-release runtime and is retained for supported
installations and maintenance:

```bash
./scripts/start_server.sh prod
./scripts/stop_server.sh prod
```

Do not expand release or production-orchestration machinery merely because this
mode exists. Current development scope is defined in
[docs/PLAN.md](../docs/PLAN.md).

Release-specific scripts and workflows are maintainer tooling. Use their
`--help`, tests, and workflow definitions when maintaining them rather than
copying their implementation details into this guide.

## Specialized scripts

Subdirectories under `scripts/` contain focused tools for tasks such as:

```text
data configuration / ingestion
CI and repository checks
maintenance and migration
release verification
local service control
```

Prefer the documented top-level lifecycle commands for ordinary use. A
specialized script is not automatically a stable public interface merely because
it exists in the repository.

## Safety

- Do not run development against a normal or production account directory.
- Do not commit runtime databases, private logs, `.env`, credentials, account
  exports, or screenshots with personal financial data.
- Do not repair financial state by manually editing SQLite unless a documented
  migration or recovery procedure explicitly requires it.
- Status and process readiness do not imply that market data, portfolio evidence,
  risk, or capital actions are financially ready.
