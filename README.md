# Karkinos

> Investing is a chronic condition. Here is your scalpel.
>
> 投资是一种慢性病。这是你的手术刀。

Karkinos is a local-first quantitative investing platform. It connects
reproducible research, persisted portfolio evidence, risk controls, daily
decisions, paper/shadow validation, reconciliation, and human-supervised
execution in one auditable workflow.

[中文文档](docs/README.zh.md) · [English docs](docs/README.en.md) ·
[Roadmap](docs/ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Latest release](https://github.com/imReese/Karkinos/releases/latest)

## Investment operating loop

![Karkinos evidence-bound investment operating loop](docs/assets/investment-operating-loop.svg)

Every transition preserves its inputs, identity, limitations, and blockers.
Missing, stale, partial, ambiguous, or conflicting financial evidence remains
visible and fails closed.

## Architecture

![Karkinos local-first system architecture](docs/assets/system-architecture.svg)

Provider, model, and broker responses enter through explicit boundaries.
Authoritative reads consume persisted facts; they do not silently refresh data
or grant execution authority. See the [Architecture](docs/ARCHITECTURE.md) for
canonical ownership, invariants, and failure semantics.

## Core capabilities

- Reproducible backtests with frozen datasets, modeled costs, OOS evidence,
  comparisons, parameter sweeps, and strategy review.
- Persisted portfolio, ledger, valuation, market-data, Account Truth, and
  reconciliation evidence with explicit freshness and provenance.
- Daily decisions and trading plans that include buy, sell, hold, rebalance,
  no-action, and review-required outcomes.
- Paper Broker, OMS, paper/shadow validation, signal journals, and
  post-decision review.
- Mandatory data, account, risk, fee, strategy, reconciliation, and operator
  gates before live-like actions.
- Evidence-bound AI research whose output remains non-authoritative and cannot
  grant trading or capital authority.
- Immutable full-market stock-universe snapshots, receipt-bound daily history,
  full-directory hard-filtered 40-stock research panels, and full-pool scans by
  human-promoted strategies, with a separate current-holding exit lane and
  local constraints.

## Safety by design

Karkinos is research and operating software, not investment advice or a return
guarantee.

- Real-money submission is disabled by default.
- Strategy and AI code cannot call a broker directly.
- Live-like actions require explicit, bounded, revocable human authority.
- Read endpoints do not silently contact providers or mutate financial facts.
- Broker credentials, account exports, runtime databases, logs, and private
  screenshots must never enter source control.

## Project status

The current software version is `0.3.7`. v0.3.7 separates authoritative stock,
ETF, and open-end-fund market identities and keeps confirmed fund NAV evidence
independent from intraday stock research. Persisted valuation, ledger, action,
and exact typed quote identities are revalidated atomically before a pre-trade
risk batch can be recorded. The release also adds a durable, independently
supervised AI research worker, provider-free account qualification and replay,
explicit human-only promotion to paper/shadow, and separate research-preview
and account-action projections in Decision and Overview. The live scheduler is
unconditional; automatic trading remains a separate default-off runtime gate
that does not enable broker submission. Native releases now use a two-process
protocol with exact API and worker identity, verified immutable artifacts,
journaled `current`/`previous` activation, automatic rollback, and only one
local rollback version. The release does not select, register, contact, or
require a real broker adapter and does not claim real-money readiness.

The exact tag commit must already have passed the complete `main` Code CI gate
and repository acceptance audit; the tag release workflow verifies and reuses
that exact-SHA evidence instead of rerunning it. These establish software-
release evidence only. Real-adapter
selection/deployment, the 20-trading-day soak, recovery drills, and the
`manual_each_order` pilot remain unchanged v1.8 product-milestone gates.
Each official SemVer tag publishes a multi-architecture image at
`ghcr.io/imreese/karkinos:<tag>` plus its workflow-protected `sha-<commit>`
identity tag. The OCI manifest digest remains the immutable image identity;
repository code cannot enforce GHCR-wide tag immutability against another
credential with package write access.
Only the newest stable tag advances the mutable `latest`, `v<major>`, and
`v<major>.<minor>` aliases, so queued out-of-order releases cannot roll them
backward.
Roadmap labels such as `v1.8` remain separate from SemVer software tags.

See the [Roadmap](docs/ROADMAP.md) for active priorities and the
[Implementation Log](docs/IMPLEMENTATION_LOG.md) for completed evidence. Those
details intentionally do not live in this README.

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

Open `http://127.0.0.1:5173` for the development UI. Stop both frontend and
backend services with:

```bash
./scripts/stop_server.sh
```

With no mode argument, `start_server.sh` runs only the source development stack:
a reloadable backend on `127.0.0.1:8001` and Vite on `127.0.0.1:5173`.
It does not reuse, replace, or stop the stable production service on its
persisted port (8000 by default).
The live scheduler is part of every backend lifecycle and has no off switch.
Automatic trading is a separate, default-off runtime gate on the Trading page;
it can be changed without restarting the service and never grants capital
authority by itself. Automatic broker submission is not implemented yet.

## Native macOS production releases

Native production runs only from a verified, immutable CI artifact selected by
`~/Library/Application Support/Karkinos/current`. It is never built from the
local checkout or a local Docker image. `./scripts/start_server.sh prod` starts
that selected release; it never copies the checkout into production and never
changes `current`.

The managed runtime keeps mutable state outside release directories:

```text
~/Library/Application Support/Karkinos/
  current  -> releases/sha-<40-hex-commit>
  previous -> releases/sha-<40-hex-commit>
  releases/
  data/
  config/
  logs/
  .service-config.json
```

After bootstrap, source-checkout-free lifecycle commands are available at
`current/bin/karkinosctl status`, `service-start`, and `service-stop`. The
repository wrappers remain convenience adapters; production stop is explicit:
`./scripts/stop_server.sh prod`.

An exact 40-hex commit can be tested without a tag. The candidate command
downloads the CI artifact, verifies its checksum, identity, architecture, and
GitHub build-provenance attestation, runs it against disposable state on an
isolated port, and always discards it without changing `current` or `previous`.
A stable update instead requires a published `v<major>.<minor>.<patch>` Release
and its verified immutable artifact. Activation is locked and journaled: it
stops the service, snapshots mutable state, checks the new runtime against that
snapshot, switches the pointers atomically, and requires the exact release SHA,
artifact fingerprint, version, health, and scheduler identity after restart.
Before the journal is committed, unsafe HTTP and other background work remain
blocked while the scheduler alone enters an explicit readiness phase and
completes at least one loop iteration or initialized-idle pass.
A conclusive activation failure restores the prior state and pointers; an
inconclusive recovery retains its journal and blocks later mutations. Successful
activation retains only `current` and `previous`; older history stays on GitHub.

See [scripts/README.md](scripts/README.md) for candidate, stable update,
rollback, and one-time legacy-bootstrap commands. Direct LaunchAgent management
and low-level release subcommands are internal implementation details.

Use fake or sanitized development data. Keep `config.json`, `.env`, runtime
databases, and private account evidence local.

## Verification

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

Optional Docker development/runtime verification:

```bash
docker compose up --build
```

Docker Compose also starts the live market-data scheduler. It is independent of
the native production update path: native production does not require a local
Docker service or build. Provider failures remain fail-closed, and scheduler
liveness grants no broker, execution, or capital authority.

## Documentation map

- [Product goal](docs/KARKINOS_GOAL.md) — North Star and durable boundaries.
- [Roadmap](docs/ROADMAP.md) — milestones, priorities, and release gates.
- [Architecture](docs/ARCHITECTURE.md) — canonical ownership and failure
  semantics.
- [AI 策略研究详细设计](docs/AI_STRATEGY_RESEARCH_DESIGN.zh.md) — DeepSeek
  研究协议、锁定式验证与生产隔离。
- [Codebase guide](docs/CODEBASE.md) — source layout and dependency rules.
- [Account Truth broker-statement import](docs/account-truth-import.zh.md) —
  start from the tracked [CSV template](broker_statement.template.csv); keep
  real broker exports in the ignored local `broker_statement.csv`.
- [English documentation](docs/README.en.md) / [中文文档](docs/README.zh.md) —
  setup, workflows, configuration, and operator guides.
- [AI collaboration policy](AI_COLLABORATION.md) — integrity, authority, and
  validation rules for assisted work.

## Technology

Python · FastAPI · SQLite · React · TypeScript · Vite · Docker

## License

MIT
