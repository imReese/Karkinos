# Karkinos Roadmap

[中文路线图](ROADMAP.zh.md) | [Goal](KARKINOS_GOAL.md) | [Architecture](ARCHITECTURE.md) | [Implementation history](IMPLEMENTATION_LOG.md)

## Purpose

This document answers four questions only:

1. What is complete?
2. What is the current product milestone?
3. In what order should it be built?
4. What evidence is required to call it complete?

Detailed implementation history, test counts, commit-by-commit progress, and
completed acceptance checklists belong in `IMPLEMENTATION_LOG.md` and Git
history. Usage instructions belong in the README files. Strategic boundaries
belong in `KARKINOS_GOAL.md`.

## Product Direction

Karkinos is a China-market personal quant research and trading platform. Its
target is a human-supervised, capital-bounded operating loop:

```text
research -> backtest -> decision -> risk -> paper/shadow
-> controlled execution -> reconciliation -> review
```

Broker execution is a gated capability, not the source of investment edge.
Strategy code and AI output may propose research or plans, but may not grant
authority, bypass risk, or call a broker directly.

## Current Baseline

| Track | Status | Current capability |
| --- | --- | --- |
| v0.2-v0.5 | Completed | End-to-end research loop, Strategy Lab, reproducible after-cost/OOS evidence, data-quality gates |
| v0.6-v0.9 | Completed | Account Truth, review workflow, strategy attribution, reliable market-data plane |
| v1.0-v1.3 | Completed | Strategy runtime, Paper Broker/OMS, broker evidence, professional Decision workflow |
| v1.4-v1.7 | Completed | Attribution/cost fidelity, Daily Trading Plan, Operations runbook, non-submitting controlled bridge |
| v1.8 control plane | Foundation implemented | Signed bounded authority, atomic budgets, sessions, live gates, pause/replacement, one-shot submit boundary, interlock, broker-neutral lifecycle evidence, exact-terminal full/partial-cancel/no-fill-cancel clearance, capital-scaling review |
| v1.8 adapter acceptance | Provider-neutral foundation implemented | Versioned manifest, deterministic local conformance evidence, capability/boundary matrix, append-only accept/reject/revoke review, exact live collector binding, and persisted-only operator readiness visibility; no real provider selected or registered |
| AI-native Phase 1-1.18 | Formula research vertical implemented | Provider-neutral, evidence-bound, human-reviewed research, memory, allowlisted Formula DSL, canonical after-cost backtest, and critique workflows without trading authority |

Account Truth and reconciliation remain mandatory safety gates, but they are
not the next product mainline. Phase 1.18 was completed as one explicitly
authorized formula-research vertical; v1.8 remains the active product milestone.
Further AI Phase 1.19+, semantic-memory expansion, and automatic prompt
injection remain deferred until the controlled-execution loop is operationally
closed.

## Active Milestone: v1.8 — Broker-Connected Controlled Pilot

### Outcome

Connect one explicitly selected broker edge and prove this complete loop:

```text
real read-only broker facts
-> per-order preflight and human approval
-> one controlled submission
-> lifecycle collection and recovery
-> execution reconciliation
-> explicit reconciled ledger posting
-> Account Truth and operations review
```

The default mode remains `manual_each_order`. `session_bounded` is a later
promotion decision backed by operating evidence, not a shortcut for v1.8.

### Priorities

| Priority | Capability | Decision |
| --- | --- | --- |
| P0 | One broker adapter decision and isolation boundary | Build first |
| P0 | Real read-only adapter and 20-trading-day soak | Required |
| P0 | Partial fill, cancel, rejection, timeout, disconnect, and unknown-outcome recovery | Required |
| P0 | Human-confirmed, exactly-once reconciled ledger posting | Required |
| P0 | End-to-end `manual_each_order` pilot | v1.8 release gate |
| P1 | Operator UX, alerts, adapter conformance, fault injection, deployment and rollback runbooks | Release gate |
| P2 | `session_bounded` pilot and a second broker adapter | After v1.8 evidence review |
| P3 | AI Phase 1.19+, semantic memory, automatic prompt injection | Deferred |

## Milestones

### M0 — Adapter ADR and Scope Freeze

Select one provider and connection mode. Document process boundaries,
capabilities, authentication, data ownership, callback/poll behavior, rate
limits, failure semantics, deployment, rollback, and privacy. Production must
still register no write adapter or release provider by default.

**Exit gate:** the provider capability matrix and threat model are accepted;
strategy, risk, Decision, and AI modules cannot import the provider SDK.

Current state: the provider-neutral release manifest, deterministic local
conformance suite, append-only report, and review gate are implemented,
including exact conformance-to-review binding and prepare/commit drift and
revocation checks. Operations now projects release, conformance, and collector
evidence through one persisted-only readiness view; an unconfigured provider is
neutral, while evidence drift or a failed active collector is explicit. The
suite validates Karkinos contracts, not a real adapter, and the view exposes no
registration or review mutation control.
Selecting the real provider, accepting its actual ADR/threat model, and
authorizing its deployment remain open and require explicit owner input.

### M1 — Read-Only Adapter and Soak

Collect cash, positions, orders, fills, market-session status, heartbeat,
source time, schema version, cursor, batch, and deployment identity through the
existing broker-neutral collector contracts. GET and alert paths never poll the
broker implicitly.

**Exit gate:** 20 reviewed trading days have complete startup/intraday/EOD
evidence with no unresolved critical cash, position, order, or fill mismatch.
Disconnect, duplicate, out-of-order, cursor-gap, schema-drift, partial-batch,
adapter-restart, and Karkinos-restart drills fail safely and deterministically.
Every drill and conformance result is bound to the exact connector/release
scope; unrelated evidence cannot satisfy the gate, and a newer scoped failure
invalidates an older pass.

### M2 — Full Order Lifecycle and Recovery

Add provider conformance for dry-run, submit, query, callback/poll, cancel, and
idempotent client order identity. Preserve explicit states for accepted,
rejected, partial, partial-cancelled, filled, cancelled, unknown, and recovery
required. Unknown outcomes are query-only and are never automatically
resubmitted. Cancel is a separate human-reviewed command.

**Exit gate:** concurrency, timeout, restart, duplicate callback, callback
reordering, partial fill, cancel race, disconnect, rejection, and broker
not-found tests cannot create duplicate submissions, fills, cancels, or false
terminal states. Any unresolved order continues to block a different order.

**Implemented foundation:** deterministic evidence reaches separately signed exact-terminal clearance
for full fill, no-fill cancel, and partial-fill-then-cancel without ledger mutation. An exact persisted
open/partial lifecycle can produce a provider-neutral manual cancellation package bound to both order
ids and the latest observation, with no broker call or state mutation; newer evidence must still prove
cancellation. Real provider conformance, signed explicit cancel, and real recovery remain release work.

### M3 — Reconciled Ledger Posting

Add a versioned preview-confirm-apply command bound to OMS, controlled intent,
broker/client order identity, lifecycle evidence, fills, fees, taxes,
reconciliation, Account Truth, ledger cutoff, and operator approval. Apply all
ledger events in one transaction. Corrections use compensating events rather
than deleting history.

**Exit gate:** posting is exactly once; partial-plus-cancelled terminal orders
post only actual fills; incomplete or conflicting evidence fails closed; and
Ledger, Holdings, Equity Curve, Overview, realized P/L, and Account Truth
reconcile after posting.

**Implemented foundation:** the provider-neutral
`karkinos.controlled_submission_ledger_posting.v1` boundary now provides a
separately signed preview and exactly-once atomic apply. It rechecks the exact
terminal clearance, OMS and controlled intent, lifecycle and statement
evidence, fills and costs, Account Truth identity, valuation snapshot, and
ledger cutoff/fingerprint inside the write transaction. Full fills,
partial-fill-then-cancel, zero-fill cancel, duplicate retry, evidence drift, and
ledger-race fixtures are deterministic. Posting cannot contact a provider or
grant submit, cancel, strategy, AI, risk, kill-switch, or capital authority.
The provider-neutral `karkinos.controlled_submission_ledger_correction.v1`
boundary now derives one append-only correction from canonical replay, requires
a separate signature, rechecks all identities in the write transaction,
preserves original trades and fees, and is exactly once across retry, restart,
and concurrency. Operations/Decision exposes an optional persisted-journey
review: select an allowlisted reason, review the replay-derived delta, verify an
offline proof, then apply once. Acceptance covers every account projection and
identity/stale gate; broader fault injection and real-provider evidence remain.

### M4 — Operator Journey

Unify preflight, approval, capital at risk, blockers, submission state, unknown
recovery, cancel, reconciliation, posting, and kill switch in Operations and
Trading. Every blocked state must expose its evidence and one safe next action.

**Implemented foundation:** the persisted-only operator projection links each intent through
reconciliation, terminal clearance, ledger posting, and append-only correction, exposing one safe
human next step. Signed reviews cover query-only unknown recovery, terminal clearance, posting, and
optional correction without operator-supplied financial deltas. An exact open lifecycle can also
produce a no-database-edit manual cancellation package; the UI requires external human action and
new evidence, and exposes no cancel endpoint. Signed submission, real signed cancel, real-adapter
recovery evidence, and the complete journey remain open.

**Exit gate:** an operator can complete every normal and recovery flow without
editing the database. Refresh, duplicate clicks, and service restart do not
repeat a side effect. Submission gates are rechecked inside the write
transaction, not only in the UI.

### M5 — Controlled Per-Order Pilot

Run one provider, one account alias, one reviewed strategy, an explicit symbol
allowlist, one unresolved controlled intent at a time, and operator-defined
capital/order/symbol/turnover/loss/drawdown/rate/expiry limits. Any critical
incident returns the system to `disabled`.

**v1.8 release gate:**

- All P0/P1 capability audits and full backend/Web/build checks pass.
- Read-only soak and real adapter deployment/rollback evidence are complete.
- Filled, rejected, unknown recovery, partial fill, cancel/partial-cancel,
  disconnect, restart, reconciliation, and posting paths are demonstrated.
- Every real order has complete strategy, Decision, risk, Account Truth,
  paper/shadow, capital, gateway, operator, lifecycle, reconciliation, and
  ledger lineage.
- Duplicate submit, cancel, fill, and ledger posting counts are zero.
- No unresolved critical reconciliation remains at release.

## Recommended Development Order

1. **Implemented foundation:** adapter ADR/capability/threat/deployment manifest contract.
2. **Implemented foundation:** provider-neutral deterministic conformance fixtures and release binding.
3. **Next after explicit provider approval:** provider read-only adapter, collector integration, health, and soak.
4. **Foundation partially implemented:** query/callback lifecycle and signed
   exact-terminal full/partial-cancel/no-fill-cancel reconciliation; real
   real cancel and real-adapter recovery evidence remain.
5. Default-closed write adapter and per-order submit/cancel gates.
6. **Foundation implemented:** signed, exactly-once reconciled ledger posting,
   append-only compensating correction, and core cross-surface acceptance.
7. Operations/Trading end-to-end UX and alerts.
8. Deployment, rollback, fault drills, and controlled pilot release.

The 20-day soak is a release gate, not an idle development period. Later
milestones may be developed against deterministic fixtures and sanitized
recorded evidence while soak runs, but the real write path stays disabled
until the gate passes.

## After v1.8

`session_bounded` may enter review only after at least 20 reviewed trading days
and 50 provenance-complete controlled orders, with no unresolved critical
reconciliation and measurable slippage, rejection, latency, drawdown,
divergence, incident, and capacity evidence. A new authorization must remain
expiring, equal or narrower than reviewed limits, automatically pausable, and
unable to renew, resume, widen, or scale itself.

## Non-Goals

- Unattended or permanently authorized full-account trading.
- Strategy-direct or AI-directed broker access.
- Automatic authority or capital expansion.
- Broker-password storage in Karkinos.
- Multi-broker and institutional multi-account OMS in v1.8.
- High-frequency or low-latency trading.
- Guaranteed-return or investment-advice claims.

## Documentation Policy

- `KARKINOS_GOAL.md`: North Star, product boundary, and long-term operating loop only.
- `ROADMAP.md` / `ROADMAP.zh.md`: current baseline, active milestone, priority, order, and exit gates only.
- `IMPLEMENTATION_LOG.md`: completed slices, dates, commits, validation commands, and test counts.
- `ARCHITECTURE.md`: durable components, data flow, authority boundaries, and invariants.
- README files: current installation, configuration, workflows, and user-facing behavior.
- Topic documents: stable contracts and operator runbooks that are too detailed for the files above.

When a milestone completes, update its status here in a few lines and move the
evidence summary to `IMPLEMENTATION_LOG.md`. Do not append implementation
diaries, full diffs, or repeated safety disclaimers to the roadmap.
