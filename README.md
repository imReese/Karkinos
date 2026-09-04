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

## Quick start

Requirements: Python 3.12+, Node.js 24.x, `uv`, and optionally Docker.

```bash
cp config.example.json config.json
cp .env.example .env
uv sync --extra server --extra dev --frozen
npm ci --prefix web
uv run python -m server --check-config
./scripts/start_server.sh
```

Open `http://127.0.0.1:5173` for the development UI. Stop development services
with:

```bash
./scripts/stop_server.sh
```

Development and production are intentionally separate. `./scripts/start_server.sh
prod` starts only the immutable release already selected under
`~/Library/Application Support/Karkinos/current`; it does not build or promote
the local checkout. See [scripts/README.md](scripts/README.md) for candidate,
update, rollback, recovery, and bootstrap commands.

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
