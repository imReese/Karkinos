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

`karkinos.persisted_valuation.v4` keeps an intraday fund estimate available as
explicit non-authoritative evidence, but marks it `confirmed_nav_missing` until
a same-day persisted confirmed NAV exists. Such a snapshot is degraded and
cannot satisfy authoritative Decision, risk, or Decision Quality completeness
gates. This classification is performed from persisted facts only and never
causes a GET path to contact a provider.

`karkinos.current_holding_market_evidence_review.v1` is the canonical operator
projection for those blockers. It reapplies the shared economic-zero quantity
rule, includes real negative positions, excludes closed/history-only facts, and
binds its exact item set to valuation and ledger identities plus a deterministic
review fingerprint. Overview consumes only this report; Market may expose a
targeted explicit ingestion command. Human acknowledgement cannot clear an
item, and the read model cannot query a connector, write a database, or mutate
OMS, production ledger, risk, kill switch, capital authority, or execution.

The batch pre-trade risk boundary is fail-closed on that same identity. It
requires a complete persisted valuation snapshot, a positive ledger cutoff,
and complete persisted market evidence for every candidate before any risk
decision is written. A rejected batch returns an explainable zero-write result;
an accepted batch embeds the exact snapshot and cutoff in every persisted risk
decision. Neither branch creates orders, submits to a broker, or writes the
ledger.

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

`karkinos.current_per_order_confirmation_dossier.v1` is the read-only operator
entry boundary before any controlled intent exists. It selects only canonical
`manually_confirmed` OMS orders, scans append-only capital evaluations newest
first, binds the exact OMS order fingerprint, and requires exactly one valid
prior-batch reconciliation reference and one gateway-verification reference.
It never falls back from a newer matching blocked evaluation to an older pass;
missing, malformed, ambiguous, or bounded-scan-incomplete evidence remains
blocked. The resolved references feed the existing canonical per-order dossier,
whose fingerprint is then used for a three-minute offline Ed25519 approval.
The resulting confirmation is append-only, non-authorizing evidence. Listing
and preview read persisted facts only; neither they nor the confirmation can
contact a provider, mutate OMS/ledger/risk/kill switch/capital authority, or
submit/cancel a broker order. The Trading UI deliberately has no submit or
cancel control for this boundary.

Automation Cockpit consumes that same candidate contract through a fail-closed
application reader. It validates the source schema, count, truncation, and
non-authorizing boundaries before projecting ready/blocked counts into Decision.
Any source drift blocks the handoff; the only UI transition opens Trading and
does not create a broker action or a second financial calculation.

The explicit Automation alert scan consumes this same projection. It writes one
idempotent warning per exact blocked candidate fingerprint, or one source-level
warning when the source contract is untrusted; ready candidates are not alerts.
Repeated scans and service restarts reuse the same alert, while Cockpit GET
remains write-free. Alerting never contacts a provider or changes financial or
execution state.

A terminal rejected intent may be reviewed through
`karkinos.controlled_broker_rejection_evidence.v1`. This read-only contract
binds the canonical OMS order fingerprint, controlled intent, exact gateway,
account, client-order and operator identities, and an allowlisted sanitized
result. It distinguishes a local pre-gateway block from a definitive gateway
rejection; missing or ambiguous evidence fails closed. Export re-runs preview
and rejects drift. The artifact remains copy-only. A separate
`karkinos.controlled_broker_rejection_review.v1` record is inserted under
`BEGIN IMMEDIATE` only after rechecking the exact preview fingerprint. It binds
one reviewer, disposition, evidence time, sanitized result fingerprint, and all
submission identities; the submit intent is unique, so identical restart replay
returns the original record while conflicting reviewers fail closed. The
operator journey then closes as no-retry. Neither boundary can query or contact
a provider, create/retry/cancel an order, mutate OMS/ledger/Account Truth/risk/
kill switch/interlock, or change capital or execution authority. Any later order
starts as a new Decision and must pass every gate again.

`karkinos.controlled_execution_operator_view.v4` evaluates every bounded
persisted controlled intent before selecting the operator's next action. The
chronologically latest journey remains available for audit compatibility, but
the primary attention journey is selected by fail-closed severity: unknown or
prepared outcomes and open broker orders precede reconciliation, clearance,
posting, Account Truth follow-up, and already closed rejection reviews. The
compact attention queue makes older unfinished journeys visible even after a
newer journey is recorded. Its GET path reads persisted facts only and cannot
query a gateway, submit, cancel, post a ledger event, or change authority.
The final `post_ledger_account_truth` stage consumes the canonical Account
Truth promotion evidence rather than recomputing reconciliation. It closes a
posted journey only when the gate passes, evidence is fresh, reconciliation is
clear, no mismatch remains, and current-ledger coverage is `covered`. Immutable
same-import posting lineage may satisfy that coverage; an append-only
correction always requires evidence captured after the correction. Missing,
partial, degraded, stale, or boundary-invalid evidence remains in the attention
queue. This read-side closure changes no Account Truth, ledger, OMS, risk,
kill-switch, broker, or capital-authority state.

An open exact-identity lifecycle may be projected through
`karkinos.manual_broker_cancellation_ticket.v1`. This provider-neutral boundary
prepares a copyable human action package from the persisted controlled intent,
OMS order fingerprint, broker/client order ids, and latest lifecycle
observation. Export re-runs the preview and rejects a stale fingerprint. It
does not register or call an adapter, issue a cancellation, mutate OMS/ledger,
or change risk, kill switch, interlock, or capital authority. The operator must
act in a separately reviewed broker interface; only a newer ingested lifecycle
observation plus Account Truth/reconciliation evidence can prove cancellation.
The existing live-cancel endpoint remains disabled, so this package is not the
M2 explicit-cancel command or a claim of provider support.

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
snapshot. The operator journey then consumes canonical Account Truth evidence:
exact same-import posting lineage may already reconcile, while correction or
unrelated later-ledger drift requires a newer complete import. Any non-pass or
partial result reports manual review required rather than silently claiming
success.

### Evidence-bound strategy contribution

`karkinos.account_strategy_contribution.v2` is the canonical account-strategy
contribution projection. A strategy-linked fill is eligible only after exactly
one production-ledger trade entry binds the same fill id, symbol, asset class,
direction, quantity, price, and commission. Linked-but-unposted fills,
ambiguous entries, identity mismatches, or sells whose strategy-owned inventory
origin cannot be replayed block contribution instead of producing estimated
P/L.

Open strategy inventory is valued only from the exact persisted valuation
snapshot named by the report. The projection binds snapshot id, valuation
as-of, ledger cutoff/fingerprint, quote-set fingerprint, fill and ledger-entry
references, and a contribution fingerprint. Missing, stale, estimated, invalid,
or drifted evidence makes all contribution amounts unavailable. Actual fill
price already contains execution slippage, so slippage is disclosed but is not
deducted a second time; fees and taxes come from the posted ledger fact.

The projection is read-only: it contacts no provider, performs no database
write, and grants no OMS, broker, risk, kill-switch, execution, or capital
authority. An assigned strategy with no linked or unattributed fills has no
contribution due and therefore does not create a circular Decision blocker.
Once a fill exists, incomplete ledger, valuation, or lineage evidence fails
closed and supplies one explicit manual next action to Overview, Decision,
Operations, and Strategy Lab.

An operator may explicitly freeze this projection for AI-assisted outcome
review through `strategy_contribution.read`. The capture request names the
exact current `strategy_id`; the adapter reuses the canonical report, wraps it
in the capture valuation/ledger identity, and rejects assignment or identity
drift. Only a fully bound contribution is authoritative. No-fill, missing, or
unreconciled results remain degraded or blocked evidence, and the capture
performs no provider call, financial recomputation, or authority mutation.

### Evidence-bound post-decision review

`karkinos.decision_outcome_review.v1` is the canonical human disposition of one
persisted signal outcome. Its preview binds the exact signal and action/risk
chain, signal-specific order/fill references, and the existing symbol-scoped
`karkinos.account_strategy_contribution.v2` report. Numeric P/L is never
accepted from the operator and is never recalculated by the review boundary.
The target fingerprint therefore includes the valuation snapshot id, ledger
cutoff, contribution fingerprint, and the exact execution evidence available
when the conclusion was made.

Recording requires a caller-supplied idempotency key, the exact preview
fingerprint, an allowlisted human decision/outcome pair, a reviewer, a note,
and an explicit no-authority confirmation. Evidence-supported or
evidence-not-supported conclusions are available only for acted signals with
linked fills and a fully bound canonical contribution. Risk-blocked or
unexecuted signals can be recorded only as the corresponding process outcome;
otherwise the review remains inconclusive. Snapshot, ledger, action, risk,
order, or fill drift rejects a new confirmation and makes a previously stored
review visibly non-current without deleting it.

The review and its tamper-evident event chain are append-only and restart-safe.
One transaction records the review, hash-chain event, and shared signal-journal
event. Legacy `signal_reviews` remain historical read evidence but are not the
canonical write contract. Preview is database-write-free and provider-free;
confirmation writes only review audit evidence and cannot modify OMS, orders,
fills, ledger, Account Truth, risk, kill switch, broker submit/cancel, AI
memory, model prompts, or capital authority.

### Decision Quality Score evidence

`karkinos.decision_quality_target.v1` is the canonical daily process-quality
projection. It reuses the current Decision payload and evaluates five fixed
dimensions: persisted valuation and Account Truth completeness, deterministic
risk checks, benchmark-aware backtest evidence, signal journaling, and stable
post-decision review identity. A risk-rejected decision may qualify when the
check is complete; benchmark awareness requires an explicit benchmark but does
not require benchmark outperformance. A no-action day records risk and
benchmark as not applicable instead of inventing evidence.

The diagnostic percentage is the number of satisfied dimensions out of five;
the daily North Star result remains binary `qualified` or `blocked`. An
operator must explicitly append a `karkinos.decision_quality_capture.v1`
against the exact target fingerprint. Captures are idempotent, restart-safe,
and protected by a per-capture event hash chain. The longitudinal report uses
the latest valid capture for each decision date and labels its coverage as
explicitly captured days only; uncaptured days are never silently counted.

GET projection and replay are provider-free and database-write-free. Capture
writes audit evidence only and cannot invoke AI, recalculate financial facts,
modify risk decisions, OMS, orders, fills, ledger, Account Truth, kill switch,
broker submit/cancel, model memory, or capital authority. The score measures
decision-process evidence, not investment return, advice, or permission.

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
