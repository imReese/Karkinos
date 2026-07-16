# Controlled Capital Execution Plan

[中文](CONTROLLED_EXECUTION_PLAN.zh.md) | [Goal](KARKINOS_GOAL.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md)

## Objective

Karkinos may submit a real order only inside explicit, bounded, observable,
reversible, and evidence-backed human authority. The first real validation uses
a deliberately constrained envelope to limit unknown failure impact; account
capital itself is not authority and does not set the long-term product ceiling.

This document owns controlled-execution invariants and promotion gates. Current
development priority and status live in [ROADMAP.md](ROADMAP.md).

## Terms

- **Account capital:** cash and assets owned by the account.
- **Authorized capital:** the maximum exposure the operator explicitly makes
  available to one controlled scope.
- **Risk envelope:** the strictest combination of account, strategy, symbol,
  liquidity, turnover, loss, drawdown, time, rate, and operational limits.
- **Pilot exposure:** a deliberately constrained initial envelope for a new
  adapter, strategy, policy, or execution mode.
- **Capital scaling:** a new human decision based on reviewed operating
  evidence; never an automatic result of profits or available cash.

Effective authority is the minimum of every applicable limit:

```text
operator authorization
account and strategy policy
symbol, liquidity, and order limits
capital, cash, turnover, loss, and drawdown budgets
fresh market, account, gateway, and reconciliation evidence
kill switch and operational health
```

## Non-Negotiable Invariants

1. Broker submission is disabled without valid operator authorization.
2. `manual_each_order` is the default live-like mode.
3. Strategy and AI code cannot import or call broker adapters.
4. Read-only evidence connectors and write-capable execution gateways are
   distinct identities and permissions.
5. The only write path is reviewed decision → account/risk gates → bounded
   authority → OMS → gateway → broker evidence → reconciliation.
6. Kill switch, stale facts, connector degradation, unresolved reconciliation,
   expired policy, exhausted budget, or source drift blocks new submissions.
7. Unknown submission outcome is query-only and never automatically retried.
8. Broker callbacks and imports are evidence; they do not silently rewrite the
   ledger.
9. Sessions may pause, expire, narrow, or be revoked; they cannot renew,
   resume, widen, or scale themselves.
10. Credentials and private account data stay outside source control and
    canonical audit payloads.

## Authority Modes

| Mode | Human authority | Machine authority | Default |
| --- | --- | --- | --- |
| `disabled` | inspect evidence | none | yes |
| `manual_each_order` | confirm one exact order | validate, submit once, query, reconcile, stop | active target |
| `session_bounded` | sign a short-lived narrow envelope | admit only qualifying orders inside remaining limits | later promotion |

`session_bounded` is not unattended trading. The operator sees capital at risk,
expiry, symbols, limits, gates, and pause state. A replacement requires new
evidence and a new equal-or-narrower signature.

## Delivery Gates

### Gate 0 — Contracts and Default Closure

Required evidence:

- versioned policy, scope, expiry, revocation, and deterministic deny reasons;
- separate connector/gateway identities and same-account binding;
- pure evaluation with no gateway, OMS, ledger, or broker side effect;
- explicit feature flag and no production write adapter by default;
- static strategy-to-broker boundary.

Exit condition: missing, expired, mismatched, stale, or over-budget evidence
always denies. An allowed policy evaluation alone issues no runtime authority.

### Gate 1 — Real Read-Only Broker Soak

Required evidence:

- one canonical adapter release manifest accepted through an append-only human
  review, with exact provider, gateway, deployment, version, fingerprint,
  account alias, mode, capability, and process-boundary binding; rejection,
  revocation, or drift blocks new ingestion;
- one latest passing deterministic local conformance report exactly bound to
  that manifest and human review; this validates Karkinos contracts, not the
  real adapter;
- one reviewed adapter for cash, positions, orders, fills, session status,
  heartbeat, and source timestamps;
- immutable snapshots, cursor, schema, deployment, capability health, and
  freshness;
- startup, intraday, and end-of-day reconciliation;
- disconnect, stale, duplicate, out-of-order, partial-batch, schema-drift, and
  restart drills;
- drill evidence scoped to the exact connector/release, with the newest scoped
  result authoritative over older passes;
- at least 20 reviewed trading days with no unresolved critical mismatch.

Exit condition: the adapter exposes no write capability during soak, and every
fact is traceable to a reviewed provider/deployment/account scope.

### Gate 2 — Per-Order Human-Confirmed Bridge

Required evidence:

- dry-run, submit, query, callback/poll, cancel, and idempotent client-order
  conformance;
- exact OMS/order/account/strategy/symbol/policy/gateway binding;
- a final short-lived operator signature immediately before one submission;
- accepted, rejected, partial, partial-cancelled, cancelled, filled, unknown,
  timeout, reconnect, and startup-recovery behavior;
- cross-order interlock until the previous controlled intent reconciles;
- explicit reconciliation followed by separately confirmed ledger posting.

Exit condition: repeated requests cannot duplicate a broker order. Unknown or
unreconciled state blocks a different order. Partial and cancel quantities are
conserved, and every ledger mutation is exactly once.

### Gate 3 — Session-Bounded Pilot

Required evidence:

- one short-lived account/strategy/symbol envelope with capital, order,
  position, turnover, loss, drawdown, rate, time, and error limits;
- atomic account and per-symbol reservations;
- authenticated order admission bound to a fresh persisted live-gate snapshot;
- one-way pause on account, risk, paper/shadow, reconciliation, gateway,
  market, budget, kill-switch, loss, rejection, account-change, or error facts;
- separately signed equal-or-narrower replacement rather than in-place resume;
- previous-batch reconciliation before the next batch.

Entry condition: the per-order pilot has at least 20 reviewed trading days and
50 provenance-complete controlled orders, no unresolved critical
reconciliation, and measurable execution-quality evidence.

### Gate 4 — Evidence-Based Capital Scaling

Required evidence:

- reviewed days and real order outcomes;
- reconciliation coverage and latency;
- after-cost return, slippage, fill quality, rejection, partial/cancel rates;
- drawdown, divergence, incidents, disconnects, policy violations, capacity,
  and liquidity;
- exact execution-scope provenance for every sampled order;
- human scale-up, hold, scale-down, or disable decision.

Exit condition: larger authority requires a new explicit, expiring operator
decision. The system may recommend or enforce hold, scale-down, pause, or
disable; it never scales up automatically.

## Runtime Safety Rules

- Intent and OMS pending state persist before an external call.
- The external call has one permanent execution claim.
- A timeout does not prove rejection and cannot release the interlock.
- Query and callback evidence use the same broker/client order identity.
- Lifecycle sequence and cumulative quantities are monotonic and conserved.
- Full or partial fills require independent broker evidence and Account Truth
  before reconciliation clearance.
- Signed exact-terminal clearance covers full fill, no-fill cancel, and
  partial-fill-then-cancel. Open partial fills remain blocked; terminal cancel
  records only actual fills and never issues a broker cancel.
- Reconciliation clearance and ledger posting are separate transactions and
  approvals.
- Ledger posting uses the versioned
  `karkinos.controlled_submission_ledger_posting.v1` artifact and a fresh final
  operator signature. The write transaction rechecks exact OMS/intent,
  lifecycle, statement/fill/cost, Account Truth, valuation, and ledger identity
  bindings before committing all entries and the posting record together.
- Partial-cancel posts only actual fills; no-fill cancel records a zero-entry
  no-op. Duplicate retry reuses the immutable posting. Evidence or ledger drift
  rejects the whole transaction.
- Correction uses a separate
  `karkinos.controlled_submission_ledger_correction.v1` preview and signature.
  It accepts no financial values, derives the exact compensating event by
  canonical replay excluding the original posting entries, re-derives under
  the write lock, preserves all original facts, and requires a newer Account
  Truth import after apply. Zero-fill postings and dependent/invalid replays
  remain blocked.
- Posting has no provider contact, submit, cancel, strategy/AI, risk-decision,
  kill-switch, or capital-authority capability.
- GET, alerts, reports, and UI rendering never contact the gateway implicitly.
- A newer blocked fact wins over an older clear preview inside the write
  transaction.

## Operator Visibility

The product must show, from persisted facts:

- mode, account, strategy, symbols, provider, and gateway;
- authorized capital, effective capital at risk, and remaining headroom;
- order, cash, turnover, loss, drawdown, and rate limits;
- expiry, latest live-gate snapshot, pause/revocation state, and kill switch;
- latest controlled intent, broker lifecycle, reconciliation, and posting;
- exact blockers, evidence age, and one safe next action.

No surface may imply execution approval merely because research, a signature,
or one policy evaluation passed.

## Release and Regulatory Gate

Before any broker-connected write capability is enabled, the owner must review
the actual provider agreement, account permissions, program-trading reporting
and testing obligations, deployment, credentials, failure behavior, and
rollback procedure. Karkinos records that review as evidence but does not
self-certify broker or legal approval.

## Completion Boundary

The controlled-execution target is complete when reviewed strategies can
operate under explicit, bounded, expiring human authority; every order can be
recovered, reconciled, and posted from durable evidence; and authority can be
paused, reduced, expired, or revoked safely. Permanently authorized unattended
full-account execution remains a non-goal.
