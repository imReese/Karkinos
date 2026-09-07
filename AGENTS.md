# Karkinos Agent Guide

Repository entry point for coding agents.

Karkinos is a local-first quantitative investing platform for reproducible
research, point-in-time evidence, portfolio decisions, risk controls,
simulation, shadow validation, and human-supervised execution. It is not a
generic CRUD app or toy backtester.

Read `AI_COLLABORATION.md` for the deeper repository-wide AI policy.

## 1. Route the task

Start at `docs/README.md`, then read only what the task needs:

| Task | Canonical source |
| --- | --- |
| Product intent / hard boundaries | `docs/GOAL.md` |
| Architecture / persistence / authority | `docs/ARCHITECTURE.md` |
| Priorities / sequencing / exit gates | `docs/PLAN.md` |
| Package ownership / migration | `docs/CODEBASE.md` |
| UI / information architecture | `design.md` |
| Current user behavior | `README.md` |
| Runtime / release / operator commands | `scripts/README.md` |

Historical roadmaps, compatibility stubs, frozen broker docs, and old milestone
labels are not current product intent. Do not load the whole docs tree by
default.

## 2. Follow the current direction

`docs/PLAN.md` owns sequencing:

```text
Reliability -> Architecture Seams -> Point-in-time Data -> Research / Alpha
-> Portfolio / Simulation -> Shadow / Attribution -> Controlled Capital
```

Until the relevant gate is complete, do not expand broker write authority,
legacy Strategy as the research center, bespoke AI trading automation, or
unrelated product surface. Correctness fixes remain allowed.

## 3. Preserve the golden invariants

- Persisted, validated financial facts are authoritative; providers and caches
  are inputs.
- Read/query paths are provider-free and zero-write unless explicitly specified.
- Missing, stale, partial, conflicting, or unreconciled evidence stays explicit
  and fails closed for the affected action.
- Failed candidate publication must not destroy a verified last-good read.
- Market time, information-availability time, and Karkinos capture time differ.
- Research/account-bound outputs bind required immutable dataset, artifact,
  snapshot, and ledger identities.
- AI, research, UI, readiness, and scheduler state never grant trading authority.
- Strategy/research code never calls a broker directly; real-money submission is
  default-off and human-supervised.
- One financial concept has one canonical owner. Do not duplicate valuation,
  PnL, accounting/portfolio truth, risk authorization, order/fill lifecycle,
  reconciliation, dataset identity, or snapshot identity.

## 4. Put code in the owning boundary

Use `docs/CODEBASE.md` for ownership. New code should move toward:

```text
market -> research -> portfolio
accounting + market + portfolio + execution contracts -> risk
research + portfolio + accounting + execution + risk -> simulation
research -> ai
ports <- adapters
```

Business logic must not depend on FastAPI, React, or SQLite implementations.
Routes validate/map HTTP; adapters translate protocols; durable jobs own
long-running work; workers coordinate through durable state.

Do not expand `AppDatabase`, flatten unrelated use cases into `server/services/`,
or add generic `utils.py` / `helpers.py` dumping grounds.

Do not add direct `Signal -> Order` paths. Target flow:

```text
Dataset -> Alpha/Model -> Forecast -> PortfolioTarget -> RebalancePlan
-> OrderIntent -> RiskDecision -> Order -> Fill -> Accounting
```

`strategy/` is compatibility code unless the current plan says otherwise.

## 5. Work from evidence

Before editing, find the owner, direct callers, invariant tests, and any
persisted/replay-sensitive behavior. Do not infer semantics from filenames.

Prefer narrow slices: characterization/replay -> contract/port -> implementation
-> caller migration -> cleanup. Separate structural refactors from
financial-semantic changes when practical.

Production-state incidents need deterministic replay/characterization coverage;
never silently repair financial facts on read.

Major dependency/runtime upgrades require migration review of the declared
toolchain and direct consumers. Dependabot PRs are still code changes.

## 6. Validate the affected surface

Run narrow checks first, then required repository gates.
`.github/workflows/ci.yml` is authoritative.

Stable entry points include:

```bash
uv run python scripts/ci/check_python_quality.py --base origin/dev
npm ci --prefix web
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

Persistence, financial semantics, trading/risk, worker lifecycle,
release/runtime, and acceptance-evidence changes require their dedicated gates.
Never weaken assertions, type checking, tests, or fail-closed behavior to make CI
green. Report only checks that actually ran.

## 7. Git, security, and docs

Normal development uses persistent `dev`. `main` is fast-forwarded from an exact
successful `dev` CI commit by the trusted promotion workflow. Never force-push
or reset either branch. Source startup from `main` is tag-free via
`./scripts/start_server.sh main`.

Preserve unrelated workspace changes. Commit, push, merge, publish, tag, release,
or open PRs only when the owner requests it.

Never commit secrets, credentials, private account identifiers/exports,
screenshots with private financial data, runtime databases, or production state.
Use sanitized deterministic fixtures.

Do not create parallel roadmaps, implementation logs, master architectures, AI
master designs, or profit plans. Update the canonical owner in `docs/` or
`design.md`; implementation history belongs in Git.

Before declaring completion, verify ownership, direct consumers, persisted-state
semantics, authority boundaries, deterministic coverage, relevant gates, and the
absence of unrelated/private files. If a financial or authority invariant is
unclear, inspect canonical code, tests, and docs instead of guessing.