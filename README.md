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
Stop a running source service before updating its checkout.

```bash
git switch main
git pull --ff-only origin main
test -e config.json || cp config.example.json config.json
test -e .env || cp .env.example .env
./scripts/start_server.sh main
```

Open `http://127.0.0.1:8000`. This builds the frontend and runs the API plus
research worker in the foreground; Ctrl+C stops both. No tag, native release,
GitHub credentials, or Docker is required for startup. A clean main checkout
matching the fetched origin/main is required. Startup never pulls, switches,
resets branches, or stops an unknown listener automatically.

Main-source data defaults to `.run/main/data`, separate from dev and a managed
production installation. To use existing data, stop its current owner and
explicitly select `KARKINOS_DATA_DIR`; startup does not copy or migrate your
managed production layout automatically. Set `KARKINOS_MAIN_PORT` when 8000 is
already occupied. Do not edit or pull this checkout while it is running.

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
