# Karkinos Implementation Log

[中文](IMPLEMENTATION_LOG.zh.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md) | [Goal](KARKINOS_GOAL.md)

This file records release-level outcomes and validation evidence. It is not a
commit diary. Detailed code history, intermediate slices, and exact diffs live
in Git commits and pull requests.

## Current Baseline

As of 2026-07-16, v0.2 through v1.7 are complete. The v1.8 control-plane
foundation and AI-native research foundation through Phase 1.18 are
implemented. The active product milestone is the broker-connected controlled
per-order pilot described in [ROADMAP.md](ROADMAP.md).

The latest completed cross-cutting work includes:

- persisted observations as the authoritative read source;
- immutable valuation snapshots and ledger identity;
- evidence-bound strategy contribution v2, assuming the controlled posting
  contract's immutable `ledger_entries.source_ref = fill_id` identity; linked
  fills expose P/L only after exact production-ledger and valuation-snapshot
  replay, while the read path remains provider-free, write-free, and without
  trading or capital authority;
- canonical daily performance across Holdings, Equity Curve, Overview, and
  explainability surfaces;
- provider-neutral evidence-bound AI research, review, and memory lineage;
- human-gated allowlisted Formula DSL research over exact saved datasets,
  executed by the canonical backtest engine with next-bar semantics and no
  production-strategy or trading-authority side effects;
- fail-fast grouped runtime configuration, environment-only TuShare/AI and
  notification credentials, validated Settings write contracts, and one
  dotenv-selection path shared by server and legacy CLI entrypoints;
- signed bounded execution policy, atomic budgets, runtime sessions, live
  gates, pause/replacement, submission interlock, lifecycle evidence, operator
  projection, and capital-scaling review.
- a canonical persisted-only controlled-order journey from submission through
  reconciliation, terminal clearance, ledger posting, and append-only
  correction, with one safe human next step and no read-side authority; v3
  checks every bounded persisted intent so an older critical unfinished
  journey cannot be masked by a newer lower-risk or closed journey;
- an explicitly opened ledger-posting operator review that binds the canonical
  delta preview to a matching trusted public identity, short-lived offline
  Ed25519 proof, final acknowledgement, and exactly-once apply, while keeping
  private keys, broker actions, and authority changes outside the Web path;
- a separately signed unknown-submission recovery review that binds the
  persisted intent, exact client order id, prior gateway-result fingerprint,
  operator identity, and a short-lived offline proof before atomically
  admitting one query-only gateway call; duplicate clicks and immediate
  restart retries cannot repeat the query, and submit, cancel, ledger, risk,
  kill-switch, and authority paths remain unavailable; only the existing
  controlled-intent/OMS result status may be resolved from definitive query
  evidence;
- provider-neutral operator packages for exact open/partial lifecycle
  cancellation handoff and terminal rejection review; both recheck fingerprint
  drift and perform no broker call, while rejection review can append one exact,
  reviewer-bound no-retry audit fact without changing execution authority;
- provider-neutral adapter release manifests with append-only human
  accept/reject/revoke evidence and exact live collector prepare/commit
  binding, without selecting or registering a real provider.
- provider-neutral deterministic conformance fixtures with append-only reports,
  exact manifest/review binding, latest-result precedence, and prepare/commit
  revalidation; this does not claim a real adapter is supported.
- connector-scoped soak recovery evidence where unscoped, unrelated, or mixed
  drills cannot satisfy promotion, and the newest scoped failure invalidates an
  older pass and its signed dossier acceptance.

Exact historical test totals are intentionally not maintained here because
they become stale after every change. CI artifacts and the acceptance-audit
export own current counts and evidence.

## Release History

### v1.8 — Capital-Bounded Controlled Execution

Status: foundation implemented; broker-connected pilot active.

Implemented foundation:

- versioned capital policy and append-only evaluation evidence;
- distinct read-only evidence connector and execution gateway identities;
- signed per-order and session attestations;
- gateway verification and exact evidence binding;
- session-start Account Truth, atomic account/symbol budgets, and rate limits;
- signed expiring runtime sessions, live gates, pause, revocation, and
  equal-or-narrower replacement;
- default-closed one-shot submission, unknown recovery, and cross-order
  interlock;
- signed exact-terminal clearance for full fill, no-fill cancel, and
  partial-fill-then-cancel, plus broker-neutral lifecycle ingestion; open
  partial fills remain blocked and clearance itself cannot post the ledger;
- separately signed, provider-neutral reconciled-ledger posting with
  transaction-time OMS, intent, lifecycle, broker-evidence, Account Truth,
  valuation, and ledger-identity rechecks; exact fills commit once in one
  transaction, partial-cancel posts only actual fills, and no-fill cancel is an
  explicit zero-entry posting;
- separately signed append-only correction derived only by canonical replay;
  the write transaction re-derives the plan, preserves original trades and
  fees, rejects zero-fill/dependent/drifted/tampered cases, and deterministic
  acceptance binds Ledger, Holdings, Allocation, Equity, Overview, Cockpit,
  Account State, realized P/L, valuation identity, and Account Truth staleness;
- versioned adapter capability/boundary manifests and revocable release review
  gates for live collector ingestion;
- deterministic local adapter conformance evidence bound to release review and
  rechecked before live collector prepare/commit;
- connector-scoped, latest-result-wins recovery-drill gates for soak promotion;
- persisted operator projection and evidence-based scale review;
- cross-order operator attention prioritization over the full bounded intent
  set, while retaining the chronological latest journey separately for audit;
- a no-database-edit operator path for the terminal-clearance-to-ledger-posting
  step, with deterministic UI tests for canonical action eligibility, blockers,
  missing identities, exact request bodies, and absence of broker calls; the
  local signer refuses key overwrite, enforces private-file permissions, and
  signs only the supplied challenge payload without network I/O.
- a separate no-database-edit terminal-clearance review that appears only for
  the canonical `preview_terminal_clearance` action, binds the exact persisted
  reconciliation run, Account Truth import, lifecycle and broker-evidence
  fingerprints, terminal quantities, and fills, and requires its own offline
  signature before recording the terminal outcome and releasing the interlock.
- a no-database-edit unknown-outcome recovery review for the canonical
  query-only journey action. The old unsigned naked POST is no longer a route;
  preview is provider-free, apply requires an exact recovery fingerprint,
  matching offline Ed25519 proof and acknowledgement, and the database records
  the atomic query claim before any external call.
- no-database-edit packages for the canonical open-order and rejected-order
  journey actions. They export only fingerprinted persisted-evidence handoffs;
  the rejected journey can separately append one exactly-once reviewer/time/
  fingerprint acknowledgement and then closes as no-retry. Neither path can
  query/retry/submit/cancel, change OMS/ledger/authority, release the interlock,
  or prove a later broker outcome.

M4 non-authorizing operator-package assumptions and risk record:

- The canonical source list remains newest-first, but operator attention is
  severity-first and oldest-first within the same severity. Unknown, prepared,
  and open-order evidence precedes reconciliation, clearance, posting, and
  Account Truth follow-up; closed rejection reviews are excluded. Tests cover a
  newer rejected journey coexisting with an older unknown outcome and prove
  that the query-only, no-resubmit action remains primary.
- Risk impact is medium because this changes which existing human review is
  shown first across Automation Cockpit and Decision/Operations. It remains a
  read-only projection: no provider query, submission, cancellation, OMS or
  ledger mutation, risk decision, kill-switch change, or authority change is
  introduced.

- The latest exact-identity persisted lifecycle observation is assumed to be
  the only broker-order evidence available to the preview. The operator must
  independently verify broker/client ids and remaining quantity. Rejection
  review assumes only sanitized persisted results are reviewable; its audit
  record binds the exact fingerprint and never becomes permission to retry.
- Deterministic validation covers open/partial and local/definitive rejection,
  blocked or ambiguous evidence, restart-stable fingerprints, duplicate export,
  exactly-once concurrent/restart replay, conflicting reviewer, transaction-time drift,
  strict routes, UI acknowledgement, and no query/submit/cancel/ledger calls.
- Risk impact is low: only the dedicated append-only review audit store is
  written. OMS, ledger, Account Truth, risk, kill switch, capital authority,
  and the unresolved-submission interlock remain unchanged.

M4 query-only recovery assumptions and risk record:

- Broker order query by the persisted idempotent client order id is assumed to
  be read-only and bounded by the registered edge gateway. A failed or unknown
  query remains `submission_unknown`; it never authorizes resubmission. A
  persisted 30-second claim window prevents duplicate clicks and immediate
  restart retries while allowing a later explicitly signed query after a lost
  process or disconnected gateway.
- Deterministic validation covers early preview blocking, exact signature
  domain, duplicate apply, restart, query failure, definitive not-found,
  successful recovery, audit claims, route schemas, Web request bodies, and
  absence of submit/cancel/ledger paths.
- Risk impact is medium: this adds one explicit external read to a previously
  unknown execution state, but cannot alter the production ledger, capital or
  execution authority and never calls broker submit or cancel. The query result
  is sanitized and persisted through the existing controlled-intent/OMS result
  transition; ambiguity continues to fail closed.

M4 terminal-clearance UI assumptions and risk record:

- The operator journey owns the actionable submission and reconciliation
  identities; the Web client neither chooses arbitrary financial facts nor
  recalculates quantities, fees, terminal state, or clearance eligibility.
  Full fill, no-fill cancel, and partial-fill-then-cancel are the only
  clearable outcomes; open or conflicting evidence remains blocked by the
  canonical service.
- Validation uses deterministic component fixtures for the exact preview,
  challenge, proof, and apply sequence plus the full Node 24 Web suite,
  formatting, production build, backend safety suite, and CI.
- Risk impact is high at the execution-evidence layer because clearance records
  real fills, transitions the OMS to the reviewed terminal state, and releases
  the cross-order interlock. The existing write transaction rechecks the latest
  reconciliation, lifecycle, Account Truth, order, intent, signature, and
  fingerprint; the UI cannot supply financial values, post the ledger, contact
  a provider, submit/cancel an order, or change authority.

M3 correction assumptions and risk record:

- A non-empty controlled posting represents actual fills for one instrument;
  the applied zero-entry cancel is an auditable no-op and has no financial fact
  to reverse. A correction is local ledger recovery, not replacement broker
  truth, so a newer Account Truth import is mandatory afterward.
- Validation commands are `uv run python -m pytest`,
  `uv run python -m pytest -m trading_safety`, CI-equivalent coverage, and the
  Node 24 `npm run test`, `npm run format:check`, and `npm run build` commands
  under `web/`.
- Risk impact is high because the canonical ledger projector feeds cash,
  positions, costs, realized P/L, equity, Overview, Cockpit, Account State, and
  risk inputs. The boundary mitigates this by rejecting operator-supplied
  financial values, deriving both buy and sell reversal state from canonical
  replay, binding valuation/ledger/Account Truth identities, re-deriving under
  the write lock, verifying before-state on every replay, preserving history,
  and granting no OMS, broker, risk, kill-switch, AI/strategy, or capital
  capability.

M3/M4 correction operator-journey assumptions and risk record:

- Correction is optional recovery after an applied non-empty posting, never the
  routine next action. The operator must select one server-allowlisted reason;
  the Web client cannot submit cash, quantity, price, cost, fee, or ledger-entry
  deltas. Preview and apply continue to use the canonical replay service.
- The operator flow is preview -> three-minute offline Ed25519 challenge ->
  detached-proof verification -> explicit append-only acknowledgement ->
  exactly-once apply. Missing trusted keys, canonical blockers, changed
  fingerprint, duplicate correction, or stale Account Truth keep apply disabled
  or rejected. Success invalidates all affected persisted projection queries and
  makes the required Account Truth re-import visible.
- Risk impact is high because the final signed action mutates the production
  ledger. Mitigations remain server-owned: transaction-time replay and identity
  rechecks, append-only history, exact posting scope, no arbitrary financial
  input, no provider contact, and no OMS, broker submit/cancel, risk, kill
  switch, strategy/AI, or capital-authority capability.

Market-review remediation assumptions and risk record:

- The configured default data source is not assumed to support every asset
  class. TuShare latest quotes remain limited to stocks and open-end funds;
  index refreshes route directly to the already registered AKShare edge source.
  AKShare's documented Sina index feed is preferred when the Eastmoney feed is
  unavailable, but a persisted close is published only after the same adapter's
  daily feed supplies a completed trading date. Intraday rows without a
  trustworthy as-of remain provisional/stale.
- Deterministic validation covers capability-aware source selection, bounded
  timeouts, Shanghai 15:00 completion, previous-close/change derivation, Sina
  code prefixes, Eastmoney fallback, and explicit quote-source provenance.
  Local acceptance additionally used auditable manual refresh runs for 399001
  and 399006 and verified persisted `2026-07-16T15:00:00+08:00` closes.
- Risk impact is medium at the market-evidence boundary: the change can publish
  valuation inputs, but it never changes ledger, OMS, risk, kill switch,
  capital, or broker permissions. Missing timestamps, incomplete sessions, and
  provider failures continue to fail closed. Intraday fund estimates remain
  explicitly provisional; post-close confirmation accepts only a confirmed NAV
  published for the target trading date, so an older NAV cannot overwrite the
  current estimate or clear the review gate.
- The Overview review queue and Operations tower now consume the same canonical
  daily-operations projection. The older Overview projection remains only as a
  rolling-upgrade fallback and cannot override a current Operations response.

Remaining release work is owned by the roadmap: one real adapter, read-only
soak, real cancel/unknown recovery, signed submission UI,
broader fault injection and real-evidence acceptance, the rest of the operator
journey, and the controlled per-order pilot.

### v1.7 — Controlled Broker Bridge Foundation

- Added manual ticket preview, export, dry run, and operator evidence.
- Added read-only connector capability and health contracts.
- Added execution reconciliation and broker-evidence handoff.
- Kept production broker submission, cancellation, and automatic ledger
  mutation disabled.

### v1.6 — Operations Center and Paper/Shadow Runbook

- Added persisted scheduled and operator-triggered runs.
- Added deterministic paper/shadow orders, fills, costs, divergence, review,
  retry, and limitations.
- Added Operations, Decision, Overview, and Trading visibility plus alerts and
  recovery tasks.

### v1.5 — Daily Trading Plan and Portfolio Construction

- Added candidate pools, target weights, order intents, costs, batch risk, and
  Today's to-dos.
- Preserved no-action, review-required, and manual-confirmation outcomes.

### v1.4 — Attribution and Cost-Basis Fidelity

- Added strategy contribution evidence across orders, fills, fees, taxes,
  realized/unrealized P/L, and unattributed effects.
- Replaced latest-quote contribution estimates with
  `karkinos.account_strategy_contribution.v2`: only production-ledger-posted
  fills bound to one persisted valuation snapshot can expose P/L; missing,
  stale, drifted, or incomplete inventory evidence fails closed with an
  explicit manual next action.
- Aligned broker fees, cost basis, proceeds, and public ledger formatting.

### v1.3 — Professional Decision Workflow

- Unified portfolio, market, signal, research, risk, Account Truth, and
  operations evidence into daily and intraday decisions.
- Exposed explicit action, blocker, explanation, and next-step states.

### v1.2 — Broker Evidence Connector

- Added broker evidence import, staged facts, capability/health status, and
  reconciliation inputs without broker-write authority.

### v1.1 — Paper Broker and OMS

- Added canonical order identity, transitions, idempotency, paper fills, and
  paper/shadow/manual-ticket modes.

### v1.0 — Strategy Runtime Foundation

- Added registered strategy execution, assignments, evidence binding, and
  production-safe extension boundaries.

### v0.9 — Data Plane and Market Reliability

- Added quote-fetch runs, source/cache metadata, stale reasons, manual refresh,
  and deterministic data-health evidence.

### v0.8 — Strategy Assignment and Attribution

- Added account/symbol strategy assignment, lifecycle state, downstream
  references, and attribution without pretending manual trades are strategic.

### v0.7 — Account Truth Review Center

- Added import/reconciliation listing, item review, score explanations, and
  Decision/promotion degradation or blocking.

### v0.6 — Account Truth and Reconciliation

- Added canonical broker statement import preview, staged evidence, duplicate
  detection, reconciliation, review states, and Account Truth scoring.

### v0.5 — Research Evidence Hardening

- Added versioned evidence bundles, data-quality gates, stronger OOS analysis,
  parameter stability, China-market assumptions, and promotion readiness.

### v0.4 — Strategy Lab

- Added typed strategy registry and extensions, generic parameters, Web
  backtests, frozen datasets, sweeps, comparisons, and after-cost/OOS reports.

### v0.3 — Daily and Intraday Decision Platform

- Added daily/intraday decision APIs and Web surfaces with explicit action and
  evidence bundles.

### v0.2 — Profit Discipline MVP

- Completed the first deterministic data-to-backtest-to-signal-to-risk-to-
  dashboard/journal operating loop.

## Validation Ownership

- Current automated evidence: CI artifacts and
  `scripts/export_acceptance_audit.py`.
- Machine-readable completion source: acceptance-audit registry under
  `analytics/`.
- Detailed change history: Git commits and pull requests.
- Current priorities and release gates: `ROADMAP.md`.

When a milestone completes, add a short release-level outcome here. Do not copy
full test output, implementation diffs, per-phase safety disclaimers, or every
intermediate commit into this file.
