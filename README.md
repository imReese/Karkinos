# Karkinos

> Investing is a chronic condition. Here is your scalpel.  
> 投资是一种慢性病。这是你的手术刀。

Karkinos is a China-market personal quant research and trading platform. It
connects reproducible research, portfolio evidence, risk control, daily plans,
paper/shadow execution, reconciliation, and human-supervised controlled
execution in one local-first application.

Karkinos 是面向中国市场的个人量化投研与交易平台，将可复现研究、组合证据、风控、每日计划、
paper/shadow 执行、对账与人工监督的受控执行连接成一个本地优先的金融应用。

[中文文档](docs/README.zh.md) | [English documentation](docs/README.en.md) |
[Roadmap](docs/ROADMAP.md) | [Architecture](docs/ARCHITECTURE.md)

## What Karkinos provides

- Deterministic backtests with frozen datasets, after-cost metrics, OOS
  evidence, parameter sweeps, comparisons, and strategy extensions.
- A daily decision and trading-plan workflow with explicit buy, sell, hold,
  rebalance, no-action, and review-required outcomes.
- Portfolio, ledger, valuation, Account Truth, broker evidence, and
  reconciliation views built from persisted facts.
- Mandatory risk, data-quality, paper/shadow, reconciliation, and operator
  gates before live-like actions.
- Paper Broker, OMS, manual order tickets, execution reconciliation, and a
  default-closed controlled-execution foundation.
- Evidence-bound AI research workflows, including human-gated allowlisted
  Formula DSL experiments and explicitly selected canonical strategy-outcome
  evidence. Their output remains non-authoritative research and never becomes
  trading authority by itself.
- React/Vite product UI, FastAPI backend, SQLite persistence, Docker runtime,
  deterministic tests, and acceptance-audit evidence.

## Safety boundary

Karkinos is a personal research and trading platform, not investment advice.
Historical results and AI-generated research do not guarantee future returns.

- Strategy code and AI output cannot call a broker directly.
- Real-money submission is disabled by default.
- Controlled execution requires explicit, bounded, expiring human authority
  plus fresh risk, account, market, gateway, and reconciliation evidence.
- Missing, stale, partial, ambiguous, or conflicting financial evidence fails
  closed.
- Broker passwords, API keys, private account exports, runtime databases,
  logs, and screenshots containing private data must not enter source control.

## Current status

Research, daily planning, paper/shadow operations, OMS, Account Truth,
reconciliation, and the non-submitting controlled-execution foundation are
implemented. The active milestone is v1.8. Provider-neutral release and local
read-only conformance foundations and their persisted-only Operations readiness
view are in place. A separate default-closed execution-edge fixture suite now
proves the M2 dry-run/submit/query/cancel/idempotency contract without loading or
registering an adapter. Signed exact-terminal reconciliation now covers full fill, no-fill
cancel, and partial-fill-then-cancel from persisted evidence. A separate final
operator signature can now post the exact cleared fills to the production
ledger once, in one transaction, while zero-fill cancel remains a recorded
no-op. The posting boundary rechecks OMS, lifecycle, broker evidence, Account
Truth, and ledger identity; it cannot submit, cancel, contact a provider, or
change capital authority. A separately signed append-only correction can now
reverse one posting only from canonical replay, preserving the original trades
and requiring a newer Account Truth import afterward. That optional correction
is available from the existing order journey as a reason-selected deterministic
preview, offline-signature verification, and final exactly-once apply; the UI
cannot supply financial deltas. Selecting or implementing one real broker edge
still requires explicit owner confirmation before any read-only soak or
human-confirmed per-order pilot.

Account-strategy contribution is now a persisted-facts-only projection: a fill
must be posted to the production ledger and bound to one exact valuation
snapshot and ledger cutoff before P/L is visible. Missing or drifted evidence
produces an explicit manual review step, while a strategy with no fills creates
no artificial blocker. This projection cannot contact a provider, write the
ledger, or grant execution or capital authority.

From Strategy Lab, a human can optionally bind the exact current strategy id
and this canonical contribution report into a frozen AI research context. The
capture rejects strategy or valuation/ledger drift; incomplete contribution
evidence stays blocked and cannot start authoritative analysis. It neither
recalculates P/L nor invokes a model by itself.

Decision's signal journal now supports an explicit post-decision review. It
first previews the persisted signal/action/risk/order/fill chain and the same
canonical contribution report, then records a human conclusion only against
that exact fingerprint. Acted outcomes require bound fill, valuation-snapshot,
and ledger-cutoff evidence; unexecuted or risk-blocked signals retain their own
non-financial outcomes. Reviews are idempotent, append-only, replayable, and
become visibly stale after evidence drift. This path does not invoke AI, contact
a provider, change financial facts, or grant trading or capital authority.

Decision also exposes the evidence-bound North Star Decision Quality Score.
The current projection checks data and Account Truth completeness,
deterministic risk, benchmark awareness, journaling, and later reviewability.
An operator may explicitly freeze the exact daily fingerprint into an
append-only, replayable capture; longitudinal coverage includes captured days
only. The score measures process evidence, not return, advice, or authority.

On Overview, the market/NAV review count is scoped to canonical current
non-zero holdings. Watchlist instruments, market indices, and closed-position
quotes remain visible in Market or history but cannot inflate the current
holding review queue. The queue is now projected by
`/api/portfolio/market-evidence-review` from one persisted Portfolio snapshot,
with the exact valuation snapshot, quote-set fingerprint, ledger cutoff, and
ledger fingerprint attached. Market exposes the affected symbols, reasons, and
safe manual next step. The GET path is read-only and provider-free; an explicit
targeted refresh is a separately audited ingestion command and clears nothing
unless newer confirmed persisted evidence produces a new canonical snapshot.

Trading now provides a default-collapsed, non-submitting per-order evidence
review. It lists only canonical `manually_confirmed` OMS candidates and resolves
the newest exact capital evaluation, prior-batch reconciliation, and gateway
verification from persisted facts, so the operator does not copy those
fingerprints by hand. A three-minute offline signature can append one exact
review fact; it cannot submit/cancel, contact a provider, or change OMS, ledger,
risk, kill switch, or capital authority. Missing, ambiguous, newer blocked, or
bounded-scan-incomplete evidence remains blocked.
Automation Cockpit and Decision project the same persisted-only candidates as a
ready/blocked summary and provide only a non-submitting handoff to Trading.
Only an explicit alert scan records idempotent warnings for source or candidate
blockers; review-ready candidates remain normal tasks rather than incidents.

For a reconciled controlled order, the Operations/Decision journey can now
complete both signed terminal clearance and the following reconciled-ledger
posting without database edits. Each step has its own canonical preview,
three-minute offline Ed25519 challenge, detached-proof verification, and final
acknowledgement. Clearance records only exact terminal fills and releases the
cross-order interlock without posting the ledger; posting remains a separate
exactly-once transaction. The private key never enters Karkinos, and neither
path can submit or cancel broker orders or change capital authority.

Operations now keeps chronological history separate from operator priority.
Every bounded persisted controlled-order journey is evaluated, and an older
unknown, prepared, or open-order outcome remains ahead of a newer lower-risk or
closed journey. The compact attention queue shows the exact safe next action
for each item. Its final Account Truth stage now closes only from the canonical
fresh, complete, current-ledger-covered reconciliation; partial, degraded,
stale, or pre-correction evidence stays open for review. It is a read-only
projection and cannot contact a provider or perform any trading, ledger, risk,
kill-switch, or authority mutation.

For a controlled order whose latest exact persisted lifecycle is still open or
partially filled, the same journey can prepare a provider-neutral manual
cancellation evidence package. It binds both broker/client order ids and the
latest lifecycle fingerprint, rechecks evidence at export, and remains a
copy-only human handoff. Karkinos does not contact the broker or expose a cancel
action; a newer ingested lifecycle observation is required before cancellation
can be treated as fact.

For a rejected controlled submission, the journey can also prepare a sanitized,
fingerprinted rejection-review package. It distinguishes a local pre-gateway
block from a definitive gateway rejection and explicitly forbids retrying the
same intent or client order id. The package remains copy-only; a separate
append-only review records exactly who acknowledged which fingerprint and when,
then closes the journey as no-retry. Duplicate/restart replay is idempotent and
conflicting reviewers or evidence drift fail closed. Only that audit store is
written: no query, retry, submit, cancel, OMS, ledger, risk, Account Truth,
interlock, or authority side effect occurs.

See [the roadmap](docs/ROADMAP.md) for priorities and release gates. Completed
implementation evidence lives in
[the implementation log](docs/IMPLEMENTATION_LOG.md), not in this README.

## Quick start

Requirements:

- Python 3.12+
- Node.js 24.x
- `uv`
- Docker, optionally

Install backend and frontend dependencies:

```bash
uv sync --extra server --extra dev --frozen
npm ci --prefix web
```

Build the product frontend and start the local server without the live
scheduler:

```bash
npm --prefix web run build
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
uv run python -m server --no-live
```

The product entry point is `http://127.0.0.1:8000` unless configured
otherwise.

Run the primary checks:

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

Docker:

```bash
docker compose up --build
```

Use fake or sanitized data for development. Do not commit `config.json` or
`.env`; credentials are rejected from JSON and belong only in the selected
runtime environment file or process environment.

## Documentation

Choose one documentation index:

- [中文文档](docs/README.zh.md) — 安装、工作流、产品边界和专题参考
- [English documentation](docs/README.en.md) — setup, workflows, product
  boundaries, and topic references

Each index organizes the same material into core documents, operational
guides, and references. Individual pages link directly to their translation.

## Repository layout

```text
analytics/       reports, attribution, evidence, and acceptance audit
backtest/        deterministic backtesting and experiment services
core/            events, portfolio primitives, and shared contracts
data/            market-data providers, cache, and reliability evidence
execution/       paper broker, OMS, gateway, and controlled execution
risk/            pre-trade and runtime risk controls
server/          FastAPI application and routes
strategy/        built-in strategies, registry, and runtime
tests/           deterministic backend and safety tests
web/             React/Vite product UI
docs/            durable product, architecture, reference, and runbook docs
```

## License

MIT
