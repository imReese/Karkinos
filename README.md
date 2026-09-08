# Karkinos

> Investing is a chronic condition. Here is your scalpel.
>
> 投资是一种慢性病。这是你的手术刀。

Karkinos is a local-first quantitative research and investing platform for the
China market. It connects reproducible research, persisted portfolio evidence,
risk controls, daily decisions, paper/shadow validation, and human-supervised
execution in one auditable workflow.

## What Karkinos does

- Reproducible backtests with frozen datasets, modeled costs, OOS validation,
  parameter sweeps, and strategy comparison.
- Persisted market, portfolio, ledger, valuation, fee, Account Truth, and
  reconciliation evidence with explicit provenance and freshness.
- Daily account actions including buy, sell, hold, rebalance, no-action, and
  review-required outcomes.
- Mandatory data, account, fee, risk, and operator gates before live-like
  actions.
- Paper Broker, OMS, paper/shadow workflows, signal journals, and post-decision
  review.
- Evidence-bound AI research whose output remains non-authoritative and cannot
  grant trading or capital authority.
- Verified immutable native releases with explicit candidate testing, update,
  rollback, and recovery paths.

## Safety boundary

Karkinos is research and operating software, not investment advice or a return
guarantee.

- Real-money submission is disabled by default.
- Strategy and AI code cannot call a broker directly.
- Live-like actions require explicit, bounded, revocable human authority.
- Read endpoints do not silently contact providers or mutate financial facts.
- Broker credentials, private account exports, runtime databases, logs, and
  screenshots must never enter source control.

## Quick start: run main without a tag

Requirements: Python 3.12+, Node.js 24.x, `uv`, and Git.
For an existing account, use its original runtime directory. The default is
`~/Library/Application Support/Karkinos`, with databases under `data/` and
configuration in `config/config.json` and `config/.env`.

```bash
git switch main
./scripts/stop_server.sh main
git pull --ff-only origin main
./scripts/start_server.sh main
```

Open `http://127.0.0.1:8000` after startup succeeds. The command builds the
frontend, checks the persisted state, and starts the service in the background.
It returns after the API, databases, research worker, and data worker are ready;
this confirms service startup, not financial readiness. You can then close the
terminal. Stop the service with `./scripts/stop_server.sh main`; Ctrl+C while
startup is still pending cancels that attempt and cleans up its processes.

Logs are written automatically to `$KARKINOS_HOME/logs/main.log`, with a default
location of `~/Library/Application Support/Karkinos/logs/main.log`. The log
rotates at 20 MiB and retains three archives. To follow it:

```bash
tail -F "$HOME/Library/Application Support/Karkinos/logs/main.log"
```

Use `./scripts/start_server.sh main --foreground` for terminal debugging;
Ctrl+C stops that foreground service, and logs stay in the terminal. Ordinary
startup needs no `nohup`, redirection, or trailing `&`. It does not install
automatic startup at login or restart the service after a crash.

No tag, native release, GitHub credentials, or Docker is required for startup.
A clean main checkout
matching the fetched origin/main is required. Startup never pulls, switches,
resets branches, or stops an unknown listener automatically.

Startup requires existing `data/app.db`, `data/meta.db`, and both configuration
files; missing files fail explicitly instead of opening an empty account.
`KARKINOS_HOME`, `KARKINOS_DATA_DIR`, `KARKINOS_CONFIG_PATH`, and
`KARKINOS_ENV_FILE` accept explicit absolute paths. Changing `KARKINOS_HOME`
changes the other defaults. Files stay in place; no private data is copied.
The frontend always uses this checkout's freshly built `web/dist`.

For a genuinely new account, prepare configuration without overwriting files:

```bash
export KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
mkdir -p "$KARKINOS_HOME/config"
test -e "$KARKINOS_HOME/config/config.json" || cp config.example.json "$KARKINOS_HOME/config/config.json"
test -e "$KARKINOS_HOME/config/.env" || cp .env.example "$KARKINOS_HOME/config/.env"
./scripts/start_server.sh main --init
```

Review the configuration before `--init`; it explicitly creates a new empty
account and requires an empty data directory. It is never an existing-account
upgrade command. Subsequent starts use `./scripts/start_server.sh main`.
Stop managed services with `./scripts/stop_server.sh prod` before starting main;
loaded managed services and pending release recovery block startup. Set
`KARKINOS_MAIN_PORT` when 8000 is already occupied. Stop main before editing or
pulling its checkout, then start it again.

For development with hot reload, use `./scripts/start_server.sh dev` and open
`http://127.0.0.1:5173`; stop it with `./scripts/stop_server.sh dev`.
The optional legacy `prod` mode still controls an already installed immutable
release. See [scripts/README.md](scripts/README.md) for these separate modes.

## Verification

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

## Documentation

Start at [docs/README.md](docs/README.md). The active engineering documentation
is intentionally small:

- [Goal](docs/GOAL.md) — why Karkinos exists and its hard boundaries.
- [Architecture](docs/ARCHITECTURE.md) — durable ownership, data flow, and
  failure semantics.
- [Plan](docs/PLAN.md) — the single current implementation plan.
- [Codebase](docs/CODEBASE.md) — source layout and dependency rules.

Historical implementation detail belongs in Git history and Releases rather
than a second roadmap or implementation diary.

## Technology

Python · FastAPI · SQLite · React · TypeScript · Vite · Docker

## License

MIT
