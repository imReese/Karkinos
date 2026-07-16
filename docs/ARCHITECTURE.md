# Karkinos Architecture

[中文](ARCHITECTURE.zh.md) | [Goal](KARKINOS_GOAL.md) | [Roadmap](ROADMAP.md) | [Controlled execution](CONTROLLED_EXECUTION_PLAN.md)

## Architectural Principles

1. **Persisted facts before presentation.** API, Web, reports, alerts, and AI
   read canonical persisted projections rather than reconstructing financial
   truth independently.
2. **Evidence before authority.** A signal, report, review, or approval is not
   execution authority unless a dedicated gate explicitly grants a bounded
   capability.
3. **Fail closed.** Missing, stale, partial, ambiguous, conflicting, or drifted
   evidence blocks the affected action.
4. **Separate proposal from mutation.** Preview, review, approval, apply, and
   reconciliation are distinct commands with distinct identities.
5. **Idempotent external effects.** Broker submission, cancellation, evidence
   ingestion, reconciliation, and ledger posting use canonical fingerprints and
   persistent claims.
6. **Human-supervised expansion.** Runtime authority can expire, pause, narrow,
   or be revoked automatically; it cannot widen or renew itself.

## System Layers

```text
Web UI / CLI
    |
FastAPI routes and application services
    |
Research | Decision | Risk | Operations | OMS | Reconciliation
    |
Canonical evidence, audit, ledger, and valuation stores
    |
Market providers | local files | model edge | broker edge
```

### Presentation

The React/Vite product UI and CLI expose operator workflows. Presentation code
may format canonical values and compose navigation, but it does not own
portfolio arithmetic, risk decisions, authority, or broker state.

### Application services

FastAPI routes validate requests and delegate to application services.
Application services own idempotency, transaction boundaries, orchestration,
and response projection. GET paths are read-only: they do not initialize
schema, refresh providers, resume workflows, or contact a broker implicitly.

### Domain

Core domains remain separate:

| Domain | Owns |
| --- | --- |
| Market data | bars, quotes, cache/source health, snapshots, freshness |
| Portfolio and ledger | cash, positions, lots, cost basis, financial events |
| Research | strategies, experiments, evidence bundles, promotion readiness |
| Decision | daily candidates, target weights, blockers, explanations |
| Risk | pre-trade and runtime risk decisions, kill-switch state |
| Operations | scheduled runs, paper/shadow, alerts, review tasks |
| OMS | canonical order identity, lifecycle, transitions, fills |
| Reconciliation | broker/account/order/fill agreement and review |
| Controlled execution | bounded authority, budgets, sessions, submission gates |
| AI research | evidence contexts, workflows, artifacts, reviews, memory lineage |

### Evidence and persistence

SQLite stores append-oriented financial, operational, execution, and AI audit
facts. Canonical fingerprints bind inputs and make restart, duplicate handling,
drift detection, and replay deterministic.

External providers are edges. Their runtime responses become evidence only
after validation and persistence; they never become implicit authority.

## Canonical Financial Identity

A valuation view binds:

- a valuation snapshot id and fingerprint;
- confirmed quote/NAV observations and previous-close baselines;
- a ledger cutoff and ledger fingerprint;
- source, cache, freshness, and data-quality evidence;
- explicit estimated or unavailable status where applicable.

Holdings, Equity Curve, Overview, Decision, Account Truth, and AI evidence must
refer to the same canonical identity when they claim to describe the same point
in time. Historical reconstruction cannot use future prices or unrelated
current quotes.

## Core Flows

### Research

```text
strategy definition
-> frozen dataset snapshot
-> deterministic backtest
-> costs and OOS analysis
-> research evidence bundle
-> human review and promotion readiness
```

Strategy extensions use typed metadata and parameters. Unsafe Web-triggered
arbitrary code execution is outside the contract. Research output cannot bypass
risk, journal, paper/shadow, or manual-confirmation gates.

### Daily decision

```text
portfolio + market + strategies + account evidence
-> candidate actions and target weights
-> batch construction and costs
-> risk gate
-> buy / sell / hold / rebalance / no-action / review-required
```

Every public action includes evidence and blockers. A no-action result is a
first-class outcome, not an error or empty response.

### Paper/shadow operations

```text
daily plan
-> deterministic paper/shadow run
-> simulated OMS orders and fills
-> costs and divergence
-> operator review and alerts
```

Paper/shadow facts never become real fills or ledger mutations. Operations owns
run identity, retry, status, limitations, and recovery tasks.

### Account Truth and reconciliation

```text
candidate adapter release manifest
-> deterministic local conformance report
-> human accept / reject / revoke review
-> exact live collector deployment binding
-> explicit broker import or collector evidence
-> preview and validation
-> persisted broker facts
-> account/execution reconciliation
-> human review
-> optional separately confirmed ledger action
```

Raw provider facts retain source identity. Duplicate, sequence, account,
quantity, and schema conflicts fail closed.

A collector's own release-status field is not authority. Release acceptance
first binds the latest passing deterministic conformance report to the exact
manifest fingerprint. Live callback/poll ingestion then resolves the
append-only adapter release review and binds collector,
deployment fingerprint, provider, gateway, account alias, authorization,
capability matrix, process boundaries, and rollback/privacy evidence at both
prepare and commit. Missing, rejected, revoked, tampered, or drifted release
evidence blocks ingestion. A newer conformance result, including a newer pass,
requires a new human review; a newer failure invalidates the old eligibility.
The local suite validates Karkinos contracts and does not claim a real adapter
works. Acceptance neither registers an adapter nor grants broker-write or
capital authority.

Operations exposes the same persisted release, conformance, and collector
bindings through `karkinos.broker_adapter_readiness.v1`. The projection opens
the database read-only, never creates missing schema, never contacts a provider,
and treats "no real provider selected" as neutral rather than unhealthy. It can
surface drift or collector failure, but it cannot record a review, register an
adapter, or grant execution or capital authority.

Read-only soak promotion also binds recovery evidence to one exact connector.
Unscoped, unrelated, or mixed-connector drills cannot satisfy another
connector's dossier. For each drill type, the newest matching scoped result is
authoritative; a later failure invalidates the earlier pass and changes the
dossier fingerprint, so an old operator acceptance no longer matches.

### Controlled execution

```text
reviewed plan and OMS order
-> account/risk/paper-shadow/gateway/reconciliation gates
-> signed capital evaluation and per-order approval
-> one persistent controlled intent
-> one external effect
-> lifecycle query/callback evidence
-> reconciliation
-> explicitly confirmed posting
```

Strategy code cannot reach the gateway. A prepared, accepted-but-unreconciled,
or unknown intent blocks a different order. Unknown outcomes are query-only and
are never automatically resubmitted.

Reconciliation clearance uses
`karkinos.controlled_submission_reconciliation_clearance.v3` as the canonical
exact-terminal contract. A signed command may record a full fill, a no-fill
cancel, or a partial-fill-then-cancel outcome. An open partial fill remains
blocked. Filled quantity comes from independently persisted broker-statement
and Account Truth evidence; cancelled quantity and terminal state bind the
broker-neutral lifecycle observation. Partial-cancel cost totals must agree
across both evidence sets. The clearance transaction records only actual fills,
advances OMS through the matching terminal states, and releases the cross-order
interlock. It never posts the production ledger, contacts a provider, issues a
cancel, or grants submission/capital authority. A later lifecycle or collector
drift invalidates the clearance and re-blocks the interlock.

Reconciled posting is a separate
`karkinos.controlled_submission_ledger_posting.v1` preview-confirm-apply
contract. Its preview binds the cleared intent and OMS terminal state, exact
broker/client order identities, lifecycle observation, statement rows, fills,
fees/taxes/transfer fees, Account Truth identity, valuation snapshot, ledger
cutoff/fingerprint, and a short-lived operator approval. The write transaction
re-reads those facts and the canonical ledger identity under `BEGIN IMMEDIATE`;
any drift rejects the whole batch. Each real fill produces one confirmed ledger
event with immutable clearance/import lineage, partial-cancel posts only actual
fills, and no-fill cancel produces an applied zero-entry posting. The posting
record and all ledger events commit together and are unique by posting,
clearance, intent, order, fill, and settlement evidence. History cannot be
deleted. Posting never contacts a provider and has no submit, cancel, strategy,
AI, risk-decision, kill-switch, or capital-authority capability.

Corrections use the separate
`karkinos.controlled_submission_ledger_correction.v1` contract. The request
contains only the immutable posting id, an allowlisted reason, and operator
identity; it cannot supply cash, quantity, cost, fee, or P/L values. Preview
replays the canonical ledger twice—once with every fact and once excluding only
the exact original posting entry ids—and derives the compensating cash and full
position-accounting state from that difference. It binds the original entry
fingerprint, Account Truth import and review, valuation snapshot, ledger cutoff
and fingerprint, derived plan, and a new short-lived operator signature. Apply
repeats the derivation under `BEGIN IMMEDIATE` and appends exactly one protected
`controlled_projection_correction` event plus its immutable correction record.
The original trades, fees, and posting record remain queryable. Zero-entry
postings have no financial fact to correct; an invalid replay, dependent trade,
identity drift, duplicate conflicting request, or tampered before-state fails
closed. After apply, Ledger, Holdings, Allocation, Equity, Overview, Cockpit,
and Account State read the same canonical projection and snapshot identity.
Account Truth deliberately becomes stale until newer broker evidence covers the
correction. The correction boundary cannot touch OMS, provider, submit/cancel,
risk, kill switch, strategy/AI, or capital authority.

Account Truth may permit the pre-posting clearance mismatch only when every
non-pass reconciliation item is mathematically identical to that single
controlled order's unposted cash, position, gross, net, fee, tax, transfer-fee,
and cost-basis delta. Missing snapshots or any unrelated delta still block. On
posting, ledger-coverage logic recognizes only ledger rows whose immutable
posting lineage points to the same broker import; any unrelated later ledger
fact makes the evidence stale. The post-apply result publishes a new valuation
snapshot and requires Account Truth to reconcile again; otherwise it reports
manual review required rather than silently claiming success.

### AI research

```text
explicit evidence capture
-> immutable context
-> human-created research task
-> permission-checked read-only tools
-> claim / debate / report
-> human review
-> optional revocable historical memory
```

Provider, model, role, prompt, workflow, tool, evidence, artifact, review, and
memory identities remain separate. Every model stage cites current evidence;
historical memory is labelled non-current. External calls receive no provider
tools or trading authority, and raw reasoning or credentials are not persisted.

The evidence-bound formula research vertical is narrower still:

```text
saved canonical backtest and exact dataset snapshot
-> human-confirmed hypothesis export
-> allowlisted Formula DSL validation
-> human-selected canonical backtest with next-bar semantics
-> optional separately confirmed evidence critique
-> human accept / revise / reject disposition
```

The Formula DSL is a JSON AST over persisted OHLCV fields with bounded
lookbacks and windows. Arbitrary code, unknown operators, and mutated
universe/window/frequency/cost inputs are rejected. The restricted adapter
reuses the exact saved bars and canonical BacktestEngine; it cannot register a
production strategy, create a Decision or trading plan, or reach OMS, ledger,
risk, kill-switch, broker, capital, or authority state.

## Authority Boundaries

| Capability | Research/strategy | AI | Operator | Controlled runtime |
| --- | ---: | ---: | ---: | ---: |
| Read persisted evidence | scoped | scoped | yes | scoped |
| Propose target weights or plans | yes | draft only | yes | no |
| Decide risk | no | no | policy/review | deterministic gate |
| Mutate ledger | no | no | separately confirmed | no |
| Issue capital authority | no | no | signed decision | no |
| Submit one broker order | no | no | final approval | only inside exact gate |
| Cancel a broker order | no | no | separate approval | only inside exact gate |
| Widen or renew authority | no | no | new decision | never |

The execution gateway and read-only evidence connector are distinct identities.
They may not silently share permissions. Production registers neither a write
adapter nor release provider by default.

## Controlled Authority Model

Effective authority is the minimum of all applicable constraints:

```text
operator authorization
account and strategy policy
symbol and liquidity limits
capital, cash, turnover, loss, and drawdown budgets
order value and order-rate limits
fresh account, market, gateway, and reconciliation evidence
kill-switch and operational health
```

Reservations and rate admissions are serialized. Runtime sessions are signed,
short-lived, token-authenticated, and one-way pausable. Recovery creates a new
equal-or-narrower session rather than resuming the old one in place.

## Failure Semantics

- **Rejected:** the provider definitively rejected the command; recovery may
  release the interlock after evidence is persisted.
- **Unknown:** the external effect may have happened; query by the same client
  identity and never resubmit automatically.
- **Partial:** preserve exact fills and remaining quantity; do not normalize it
  into success or failure.
- **Drifted:** a source or fingerprint changed after review; invalidate the
  derived eligibility and require a new review.
- **Paused:** a hard gate failed; later clear evidence does not resume the same
  session.

Alerts and operator views are derived from persisted facts. They may identify a
problem and a safe next action, but they cannot refresh a provider or mutate
authority as a read side effect.

## Deployment and Privacy

- The core application is local-first and uses SQLite for durable state.
- Broker and external-model adapters remain replaceable edge components.
- Credentials are supplied to the relevant edge at runtime and are never
  stored in canonical financial or audit tables.
- Real account exports, runtime databases, logs, screenshots, and secrets stay
  outside source control.
- Adapter release, capability, deployment, authorization, health, and rollback
  evidence is explicit and versioned.

## Architectural Change Rule

Update this file only when a durable component, data flow, authority boundary,
or invariant changes. Version progress, test counts, endpoint-by-endpoint
implementation notes, and completed phase diaries belong in
[IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md) or Git history.
