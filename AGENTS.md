# Karkinos Agent Guide

This is the repository entry point for coding agents.

Karkinos is a local-first quantitative investing platform for reproducible
research, point-in-time evidence, portfolio decisions, risk controls,
simulation, shadow validation, and human-supervised execution. Do not treat it
as a generic CRUD app or toy backtester.

Read `AI_COLLABORATION.md` for repository-wide AI policy.

## 1. Route the task before reading broadly

Start at `docs/README.md`, then read only the canonical source needed:

| Task | Source |
| --- | --- |
| Product intent, scope, hard boundaries | `docs/GOAL.md` |
| Architecture, persistence, processes, authority | `docs/ARCHITECTURE.md` |
| Current priorities and exit gates | `docs/PLAN.md` |
| Package ownership and migration direction | `docs/CODEBASE.md` |
| UI and information architecture | `design.md` |
| Current user behavior and installation | `README.md` |
| Runtime, release, and operator commands | `scripts/README.md` |

Historical roadmaps, compatibility stubs, frozen broker docs, and old milestone
labels are not current product intent. Do not read the whole docs tree unless
the task requires it.

## 2. Follow the current engineering direction

Use `docs/PLAN.md` as the sequencing authority:

```text
Reliability
-> Architecture Seams
-> Point-in-time Data
-> Research / Alpha
-> Portfolio / Simulation
-> Shadow / Attribution
-> Controlled Capital
```

Until the relevant gate is complete, do not expand broker write authority,
legacy Strategy as the research center, bespoke AI trading automation, or
unrelated product surface. Maintenance and correctness fixes remain allowed.

## 3. Preserve the golden invariants

- Persisted, validated financial facts are authoritative; providers and caches
  are inputs.
- Read/query paths are provider-free and zero-write unless an explicit contract
  says otherwise.
- Missing, stale, estimated, partial, conflicting, or unreconciled evidence stays
  explicit and fails closed for the affected action.
- A failed candidate publication must not destroy a verified last-good read.
- Market time, information-availability time, and Karkinos capture time are
  distinct.
- Research/account-bound outputs bind the required immutable dataset, artifact,
  snapshot, and ledger identities.
- AI, research, UI, readiness, and scheduler state do not grant trading or
  capital authority.
- Strategy/research code never calls a broker directly; real-money submission is
  default-off and human-supervised.
- One financial concept has one canonical owner. Do not duplicate valuation,
  PnL, portfolio/accounting truth, risk authorization, order/fill lifecycle,
  reconciliation, dataset identity, or snapshot identity.

## 4. Put code in the owning boundary

Move new code toward the ownership in `docs/CODEBASE.md`:

```text
market -> research -> portfolio
accounting + market + portfolio + execution contracts -> risk
research + portfolio + accounting + execution + risk -> simulation
research -> ai
ports <- adapters
```

Business logic must not depend on FastAPI, React, or SQLite implementations.
Routes validate/map HTTP. Adapters translate external protocols. Durable jobs own
long-running work. Workers coordinate through durable state, not in-memory truth.

Do not expand generic facades such as `AppDatabase`, flatten more unrelated use
cases into `server/services/`, or add generic `utils.py` / `helpers.py` dumping
grounds.

Do not create new direct `Signal -> Order` paths. The target chain is:

```text
Dataset -> Alpha/Model -> Forecast -> PortfolioTarget -> RebalancePlan
-> OrderIntent -> RiskDecision -> Order -> Fill -> Accounting
```

The existing `strategy/` surface is compatibility code unless the current plan
explicitly says otherwise.

## 5. Work from evidence

Before editing, find the owner, direct callers, existing invariant tests, and any
persisted/replay-sensitive behavior. Do not infer semantics from filenames.

Prefer narrow slices: characterize/replay -> contract/port -> implementation ->
caller migration -> compatibility cleanup. Keep structural refactors separate
from financial-semantic changes when practical.

For production-state incidents, reproduce from source and persisted evidence and
add deterministic replay/characterization coverage. Never silently repair facts
on read.

Major framework, dependency, or runtime upgrades require migration review of the
declared toolchain and direct consumers; a Dependabot PR is still a code change.

## 6. Validate the affected surface

Run narrow checks first, then the repository gates required by the change.
`.github/workflows/ci.yml` is the authoritative CI definition.

Useful stable entry points include:

```bash
uv run python scripts/ci/check_python_quality.py --base origin/dev
npm ci --prefix web
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

Persistence, financial semantics, trading/risk, worker lifecycle,
release/runtime, and acceptance-evidence changes require their dedicated
replay/safety/contract gates.

Never make CI green by weakening assertions, disabling type checks, broad `any`
casts, skipping tests, or relaxing fail-closed behavior. Report only what was
actually validated; local tests do not prove a real broker/provider or managed
release.

## 7. Git, security, and documentation

Normal development uses persistent `dev`. `main` is fast-forwarded from an exact
successful `dev` CI commit by the trusted promotion workflow. Do not force-push
or reset either branch; divergence requires explicit synchronization and fresh
CI. Source startup from `main` is tag-free via `./scripts/start_server.sh main`.

Preserve unrelated workspace changes. Commit, push, merge, publish, tag, release,
or open PRs only when the owner requests that action.

Never commit credentials, tokens, private account identifiers/exports,
screenshots with private financial data, runtime databases, production state, or
secrets. Use sanitized deterministic fixtures.

Do not create parallel roadmaps, implementation logs, master architectures, AI
master designs, or profit plans. Update the canonical owner in `docs/` or
`design.md`; implementation history belongs in Git commits, PRs, and Releases.

Before declaring completion, confirm correct ownership, direct-consumer
compatibility, persisted-state semantics, authority boundaries, deterministic
coverage, relevant CI gates, documentation ownership, and absence of unrelated
or private files. If a financial or authority invariant is unclear, stop guessing
and inspect the canonical code, tests, and docs.