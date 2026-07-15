# Karkinos Implementation Log

[中文](IMPLEMENTATION_LOG.zh.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md) | [Goal](KARKINOS_GOAL.md)

This file records release-level outcomes and validation evidence. It is not a
commit diary. Detailed code history, intermediate slices, and exact diffs live
in Git commits and pull requests.

## Current Baseline

As of 2026-07-15, v0.2 through v1.7 are complete. The v1.8 control-plane
foundation and AI-native research foundation through Phase 1.18 are
implemented. The active product milestone is the broker-connected controlled
per-order pilot described in [ROADMAP.md](ROADMAP.md).

The latest completed cross-cutting work includes:

- persisted observations as the authoritative read source;
- immutable valuation snapshots and ledger identity;
- canonical daily performance across Holdings, Equity Curve, Overview, and
  explainability surfaces;
- provider-neutral evidence-bound AI research, review, and memory lineage;
- human-gated allowlisted Formula DSL research over exact saved datasets,
  executed by the canonical backtest engine with next-bar semantics and no
  production-strategy or trading-authority side effects;
- fail-fast grouped runtime configuration, environment-only TuShare/AI
  credentials, and one dotenv-selection path shared by server and legacy CLI
  entrypoints;
- signed bounded execution policy, atomic budgets, runtime sessions, live
  gates, pause/replacement, submission interlock, lifecycle evidence, operator
  projection, and capital-scaling review.

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
- signed exact-full-fill clearance and broker-neutral lifecycle ingestion;
- persisted operator projection and evidence-based scale review.

Remaining release work is owned by the roadmap: one real adapter, read-only
soak, full partial/cancel/unknown recovery, reconciled ledger posting, operator
journey, and controlled per-order pilot.

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
