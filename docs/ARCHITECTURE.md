# Karkinos Architecture

Karkinos is a China-market personal quant research and trading platform. Its
purpose is to improve after-cost trading outcomes through disciplined,
auditable, risk-gated decisions. Automatic broker submission is a future
execution capability, not the source of edge and not the default product mode.
The target execution model is human-supervised and capital-bounded: authority
may grow with reviewed evidence, but it is always explicit, limited, expiring,
observable, and revocable.

The core architectural rule is:

```text
prove the decision first
-> simulate and reconcile the execution path
-> require explicit human authority by default
-> start live validation with a deliberately small risk envelope
-> only then consider evidence-based capital scaling
```

This keeps Karkinos focused on process quality instead of turning a
possibly weak or unverified signal into a faster real-money mistake.

## North-Star Workflow

The platform should answer the daily operating question:

> Given my portfolio, market data, risk limits, account truth, and validated
> strategies, what should I do today -- buy, sell, hold, rebalance, or do
> nothing -- and why?

The end-to-end workflow is:

```text
market data and account facts
-> reproducible research dataset
-> strategy runtime / backtest / replay
-> research evidence bundle
-> strategy promotion gate
-> daily decision
-> daily trading plan
-> pre-trade risk gate
-> paper/shadow run
-> divergence review
-> manual confirmation or valid bounded operator authorization
-> manual ticket or controlled broker bridge
-> broker evidence import
-> execution/account reconciliation
-> journal and post-decision review
```

Each step produces evidence. Later steps consume that evidence; they do not
overwrite it or silently bypass it.

## Layered Architecture

```text
Web cockpit
  Overview / Decision / Operations / Trading / Account Truth / Market
    |
    v
Application services
  Decision, daily trading plan, operations, automation, capital authority,
  OMS, gateway, execution reconciliation, strategy promotion, account truth
    |
    v
Domain and engine layer
  EventBus, Strategy Runtime, Portfolio, Risk, Paper Broker, Backtest
    |
    v
Local evidence and state
  SQLite facts, market bars, broker evidence, run records, reports
    |
    v
External adapters
  Market data providers, read-only broker connectors, future gateway
```

The service layer owns workflow authority. Strategy code can propose signals
and candidate actions, but it cannot submit broker orders. Broker connectors
can contribute evidence, but they cannot mutate production ledger state without
review and reconciliation.

## Financial Data Integrity and Valuation

Financial accuracy takes precedence over freshness and UI convenience across
market data, account facts, valuation, PnL, risk, paper/shadow evidence,
reconciliation, and controlled execution.

### Authority Boundary

External providers and broker connectors produce observations, not account
truth. A collector must persist each observation with its provider, effective
timestamp, received timestamp, status, and ingestion run id before an
authoritative calculation may consume it. Runtime caches are provisional
telemetry only. Query endpoints are pure reads: they do not contact providers,
schedule refreshes, or mutate market-data state.

The authoritative flow is:

```text
provider or broker observation
-> auditable ingestion run
-> persisted observation
-> immutable valuation snapshot
-> canonical calculation
-> Overview / Portfolio / Decision / Operations / Explainability projection
```

### Immutable Valuation Identity

Every authoritative result binds:

* `valuation_snapshot_id`, effective `as_of`, and market `trade_date`;
* valuation-policy version;
* exact selected quote, close, or NAV observation for each instrument;
* exact previous-close/NAV baseline used for daily attribution;
* ledger cutoff and ledger fingerprint;
* quote-set fingerprint and completeness/freshness/estimation status.

Policy `karkinos.persisted_valuation.v2` freezes both the valuation price and
daily baseline in the content address. A persisted same-day `1d` market bar is
treated as confirmed close/NAV evidence with an effective China-market close
time of `15:00 Asia/Shanghai`; the original intraday observation remains in the
snapshot for audit. Partial intraday bars must never be stored under that `1d`
confirmed-evidence contract.

`valuation_as_of` follows the newest selected valuation or ledger fact.
`valuation_trade_date` follows market evidence and is not advanced by a later
non-market ledger event. Request time never changes fact time. Historical
reconstructions do not inherit the current snapshot id and current quotes are
never backfilled into past dates.

Snapshots are published only at committed fact boundaries:

* successful or partially successful quote-ingestion completion;
* ledger-entry insertion;
* broker-settlement confirmation;
* application-startup backfill for facts created before this contract.

Successful publication advances the persisted
`valuation_snapshot_publication` pointer. If committed facts imply a different
content id before publication succeeds, authoritative financial reads return
HTTP `503`. They never expose an id that cannot be resolved through
`/api/portfolio/valuation-snapshots/{snapshot_id}`. A quote batch whose facts
persist but whose snapshot cannot publish is recorded as failed, not successful.

### Canonical Daily Accounting

Daily account change obeys one equation:

```text
ending_equity - starting_equity = event_flow + market_move

market_move = symbol_price_contribution
            + trading_fees_and_taxes
            + other_attributed_components
            + explicit_residual
```

Holdings, asset-class totals, symbol contributors, Overview, intraday/daily
equity, and Explainability are projections of the same canonical daily
performance result. Known fees belong to the traded asset class; `Residual` is
reserved for genuinely unexplained differences. A residual above tolerance is
a data-quality failure, not a rounding bucket.

Current positions split overnight quantity from same-day buy lots. Overnight
quantity uses the persisted previous close; same-day lots use their actual
execution cost including the complete persisted fee breakdown. Same-day sells
remain unavailable until realized and remaining-lot attribution can be
performed deterministically.

### Fail-Closed Rules

Authoritative calculations block or degrade explicitly when:

* an ingestion batch is incomplete or cannot link observations to its run;
* a required quote, close, NAV, ledger entry, fee, or corporate action is
  missing;
* confirmed evidence is required but only stale or estimated evidence exists;
* same-day trading cannot be attributed deterministically;
* account reconciliation has unresolved material differences;
* current committed facts have not produced a replayable snapshot.

Missing daily baselines propagate as unavailable (`null` / `--`), never zero.
Historical reconstruction requests prices only for positions open on that date,
so a closed instrument cannot degrade later valuations.

### Deterministic Verification

Trading-related changes cover the relevant cases below:

* overnight holding with no trade;
* full same-day buy and partial same-day addition;
* same-day sell or buy/sell fail-closed behavior;
* fees and taxes;
* deposits, withdrawals, income, and manual adjustments;
* missing, stale, estimated, and unpublished observations;
* cross-endpoint accounting invariants;
* deterministic replay from a frozen snapshot and ledger cutoff.

## Current Core Flows

### Research and Strategy Runtime

Karkinos learns from PTrade-style strategy ergonomics through lifecycle hooks,
strategy context, parameter schemas, and one strategy API that can be reused
across backtest, replay, paper, and shadow modes.

The safe translation is:

```text
strategy hook
-> StrategyRuntimeOutput
-> StrategyRuntimeAuditRecord
-> evidence/risk/account/paper/manual gates
```

The strategy runtime context is read-oriented. It should expose market data,
portfolio facts, parameters, account facts, risk limits, and run metadata. It
must not expose direct broker-order authority.

### Daily Decision and Trading Plan

`build_daily_trading_plan` is the high-risk aggregation point that converts
decision evidence into manual-confirmation order intents. It consumes decision
payloads, account-truth status, market health, portfolio controls, candidate
actions, fees, cash impact, T+1 constraints, limit/suspension/ST checks, and
drawdown/concentration controls.

Its outputs are previews:

* `order_intents` are evidence-linked order candidates.
* `blockers` explain why an action cannot proceed.
* `submission_status` defaults to manual confirmation or blocked states.
* `broker_bridge_status` remains disabled by default.

Changing this flow has a broad blast radius because it feeds Decision,
Operations, and paper/shadow runs. Treat it as a platform contract.

### Operations and Paper/Shadow

Operations Center is the daily runbook. It answers:

```text
what ran
what failed
what is blocked
what is ready for review
what evidence is safe to rely on
what the operator should do next
```

`run_paper_shadow_from_trading_plan` creates or reuses a deterministic
paper/shadow run from the daily trading plan. It records simulated orders and
fills as evidence only. It must not create production ledger entries, mutate
cash or positions, store broker credentials, or submit broker orders.

The paper/shadow run should be the first place where execution assumptions meet
the current plan:

```text
daily trading plan
-> deterministic input fingerprint
-> paper/shadow order request
-> simulated OMS transitions
-> simulated fills / rejects / cancels / expirations
-> divergence status
-> next manual review step
```

### OMS and Gateway Boundary

OMS is the production-facing order lifecycle boundary. Its near-term role is
not "send orders"; its role is to make order authority explicit.

The safe lifecycle is:

```text
awaiting_manual_confirmation
-> manually_confirmed
-> manual_ticket_created
-> broker evidence imported
-> reconciled or exception review
```

Any future broker gateway must remain capability-based:

* manual-ticket gateway: copyable ticket, no broker API submission;
* dry-run gateway: validates payloads and records rejected/accepted previews;
* read-only connector: account/cash/position/order/fill evidence only;
* controlled live gateway: future, disabled by default, gated per account,
  strategy, symbol, order, risk state, account truth, and kill switch.

### Account Truth and Reconciliation

Account truth is the platform's reality check. Broker statements and connector
snapshots are staged as evidence before they influence decisions.

Execution reconciliation compares:

```text
OMS order state
-> broker gateway event
-> imported broker trade/fill evidence
-> local ledger/cash/position expectations
```

When an operator records manual execution evidence and later stages matching
broker trade evidence, reconciliation also compares quantity, price, gross
amount, fee, tax, transfer fee, and net amount. Matches and differences remain
review evidence; neither result changes OMS state or mutates the production
ledger automatically.

No automation path should directly mutate production ledger state just because
broker evidence exists. Matching evidence can recommend review actions; ledger
mutation remains explicit and auditable.

## Authority Boundaries

| Layer | May do | Must not do |
| --- | --- | --- |
| Strategy | Emit signals, candidates, warnings, explanations | Submit broker orders or bypass gates |
| Backtest/research | Produce reproducible evidence and assumptions | Claim deployability without OOS/after-cost/risk review |
| Daily plan | Create order-intent previews and blockers | Create broker orders or ledger entries |
| Risk gate | Pass/block with reasons and policy snapshots | Be optional for actionable candidates |
| Paper/shadow | Simulate order/fill outcomes and divergence | Mutate production cash, positions, or ledger |
| Capital authority | Evaluate explicit operator scope, expiry, and remaining limits | Create its own authorization, widen limits, or bypass upstream gates |
| OMS | Track explicit order authority and transitions | Submit while broker submission is disabled |
| Broker gateway | Export tickets or future gated bridge actions | Store passwords or enable live submission by default |
| Account truth | Stage/import/reconcile broker evidence | Silently rewrite production ledger |
| UI | Explain next actions and evidence | Hide data-quality gaps or imply guaranteed returns |

## Automation Maturity

Karkinos is built to become more automated, but automation matures in layers:

| Level | Name | Meaning |
| --- | --- | --- |
| L0 | Research evidence | Backtests, sweeps, OOS, after-cost evidence, limitations |
| L1 | Daily trading plan | Candidate pool, blockers, risk, account truth, costs |
| L2 | Paper/shadow operating loop | Scheduled simulated execution and divergence review |
| L3 | Manual execution assist | OMS, manual tickets, broker evidence import, reconciliation |
| L4 | Controlled broker bridge | Per-order gated broker adapter, disabled by default |
| L5 | Capital-bounded controlled execution | Starts with a small pilot exposure, then supports human-approved evidence-based scaling |
| L6 | Unattended full-account automation | Non-goal; permanent unsupervised authority is not required |

This ladder preserves the money-making goal: the system should automate the
parts that increase discipline and evidence quality first. Broker submission
comes only after the system proves it can decide, simulate, reconcile, and stop.

## Capital Authority Model

Account capital and machine authority are different facts. Cash or positions in
an account never grant automation permission by themselves. Controlled
execution consumes an operator-issued authorization whose effective limit is
the strictest applicable account, strategy, symbol, liquidity, turnover, loss,
drawdown, time, reconciliation, and broker-fact constraint.

The authority modes are:

* `disabled`: evidence review only; no broker submission.
* `manual_each_order`: the operator confirms each evidence-fingerprinted order;
  the machine may submit and monitor only that confirmed order.
* `session_bounded`: the operator grants a short-lived envelope for specific
  accounts, strategies, symbols, sessions, and limits; qualifying orders may be
  submitted only while every upstream gate remains clear.

`manual_each_order` remains the default. `session_bounded` is a future
controlled mode, not unattended automation. It may pause or expire itself, but
it may not enable, renew, resume, or widen itself. Increasing capital requires
a new operator decision tied to reviewed live evidence.

The first real execution trial uses a deliberately small authorization envelope
to contain unknown connector, OMS, broker, and operational failures. This is a
deployment-stage safety limit, not a permanent account-size or product limit.

See [CONTROLLED_EXECUTION_PLAN.md](CONTROLLED_EXECUTION_PLAN.md) for the staged
delivery and promotion criteria.

## Controlled Live Bridge Requirements

A future real broker submission path is acceptable only if all gates below are
true for the specific account, strategy, symbol, and order:

* strategy stage allows controlled bridge pilot;
* latest research evidence is after-cost and OOS acceptable;
* Account Truth gate is fresh and pass or explicitly policy-accepted degraded;
* pre-trade risk passes with a stored policy snapshot;
* paper/shadow divergence is clear or manually accepted;
* kill switch is off;
* gateway capability and health checks pass;
* order is inside account, strategy, symbol, cash, turnover, and loss limits;
* user has explicitly enabled the account and strategy for the bridge;
* per-order confirmation is required until a later capital-bounded policy
  explicitly permits limited automation under a valid operator-issued session;
* any automated session has an immutable policy version, explicit scope,
  effective and expiry time, capital at risk, remaining limits, and revocation
  evidence;
* no session may automatically widen or renew its own authority;
* all transitions, broker responses, fills, rejects, cancels, and reconciliation
  outcomes are written as immutable evidence.

Capital-authorization v2 separates two identities that must never be collapsed:

* the **evidence connector** is read-only, supplies Account Truth/soak/account
  facts, and is blocked if it exposes submit capability;
* the **execution gateway** is a distinct policy-scoped future write boundary
  for the same reviewed account, but its declared id/health/capability is not
  runtime authority.

The policy lists both allowed identity sets, the context names one of each, and
an explicit same-account binding must be verified. Identical ids or overlapping
policy sets fail closed. Per-order and session fingerprints include the split
identities. The declared execution-gateway binding remains
`runtime_verification_status=unverified` and cannot contact a broker or submit
an order.

Stage 2.4 adds the separate verifier required to produce short-lived runtime
readiness evidence. It inspects a registered gateway's verified account
binding, required submit/cancel/query/dry-run/idempotency capabilities, and a
source-fingerprinted health snapshot no more than 60 seconds old. It derives an
idempotent client order id and runs an exact limit-order dry-run; readiness
requires `submitted=false`, no broker order id, a valid payload fingerprint,
and zero reported side effects. Accepted and rejected attempts are append-only.
Resolution re-runs all checks, detects source drift, and expires after five
minutes. This is non-submitting readiness evidence, not runtime authority. The
production registry is empty by default.

Stage 2.5 consumes that evidence through the per-order dossier boundary. The
request fingerprint must also be present as the exact typed
`execution_gateway_verification:<fingerprint>` reference in the recorded
`manual_each_order` capital evaluation. The dossier resolver then allowlists and
matches the current record's gateway id, evidence connector id, account alias,
OMS order id, and canonical order fingerprint, plus its disabled-authority and
disabled-submission assertions. It also independently compares the sanitized
dry-run order contract with the current OMS symbol, side, asset class, quantity,
order type, and limit price. Missing providers, expiry, source drift, or any
scope mismatch blocks review and changes the dossier fingerprint. A clear match
changes only `execution_gateway_runtime_not_verified`; it does not alter OMS,
reserve budget, create runtime authority, or make live submission available.

No strategy should call a broker adapter directly. The only allowed path is
through policy, risk, OMS, gateway, and reconciliation services. The current
strategy tree is covered by a static broker-boundary guard so adapter imports
and direct broker-style calls fail deterministic tests before future connector
work can rely on them.

Stage 1.1 adds a promotion evidence boundary above raw connector soak. It
selects exactly 20 unique healthy trading days only when each snapshot carries
clear zero-open-item execution reconciliation, requires passed startup,
intraday, and end-of-day evidence for every selected day, and requires all five
safe-degradation/replay drills. The dossier also binds the latest stable
connector account alias/hash and a sanitized Account Truth source fingerprint
recomputed from the persisted import, current ledger projection,
reconciliation items, manual-review states, and score. Only
pass/fresh/zero-unresolved Account Truth evidence is eligible. The owner signs
the exact dossier with Ed25519 and explicitly attests that the import belongs
to the same account alias and that full process/broker-terminal recovery was
performed outside the service; the existing `restart_recovery` drill itself
proves only new-service-instance replay. A matching acceptance means Stage 1
evidence is ready for later review. It does not enable a connector, issue
capital/runtime authority, or remove the independent Stage 2 gateway gates.
The Stage 2 dossier resolves this evidence through the application state and
binds the promotion dossier fingerprint, operational source fingerprint,
Account Truth source fingerprint, and verified acceptance id. Provider failure,
connector mismatch, malformed evidence, or source drift fails closed without
exposing provider details. Resolution uses only the capital policy's read-only
`evidence_connector_id`; its distinct `execution_gateway_id` is bound separately
and remains runtime-unverified until the exact current Stage 2.4 record is
resolved through the Stage 2.5 binding.

The Stage 2 per-order confirmation foundation is a separate evidence boundary,
not a gateway method. It canonicalizes immutable order terms and fingerprints a
dossier containing the current OMS state, capital evaluation, required gateway
evidence, connector-soak status and current freshness, prior reconciliation,
and kill-switch state.
An operator may attest only that exact dossier after its review gates pass, but
the record now requires a short-lived Ed25519 approval whose canonical
challenge binds the operator/key, action, artifact type, exact dossier
fingerprint, server nonce, and expiry. Only configured public keys are stored;
disabled or rotated keys invalidate approval resolution. The attestation cannot
mutate OMS or authorize a broker call. Any evidence change produces a new
dossier fingerprint. The prior reconciliation is an explicit append-only batch
manifest: the request and capital evaluation must name the same recorded clear
fingerprint, and current OMS/transition/fill/reconciliation facts are rehashed
on every preview. A current signed Stage 1 promotion can clear only the Stage 1
Account Truth-linkage, owner-acceptance, and promotion sub-blockers. A reviewed
execution gateway may clear only its runtime-verification blocker after the
capital reference, identities, OMS order, fingerprint, and dry-run terms all
match. Runtime authority, live gateway, and broker submission remain hard-
blocked independently of the verified attestation.

The Stage 3 session foundation follows the same separation. It accepts an
explicit order set only as a non-executing projection under a short-lived
`session_bounded` policy. Budget math is conservative: gross order value is not
reduced by buy/sell netting, and capital, cash, turnover, per-order,
position-change, liquidity, and projected rate constraints block independently.
The envelope fingerprint excludes only the continuously changing age counter;
the source time, maximum age, and fresh/stale state remain bound. An attestation
requires the same exact prior-batch evidence binding and an independent signed
operator approval for the exact envelope. It does not reserve budget or create
runtime authority. Atomic budget consumption, automatic pause, authenticated
session issuance, and broker submission remain separate future components and
hard blockers.

Stage 3.3 applies the shared gateway-verification binding to every projected
order independently. The request is an exact order-id-to-fingerprint map with
no missing, extra, invalid, or reused fingerprints; the capital evaluation must
contain exactly that typed verification-reference set. Every envelope rebuild
re-resolves all sources and matches gateway id, read-only connector, account
alias, OMS order id, canonical order fingerprint, dry-run order terms, and the
disabled-authority/submission assertions. One failed order blocks the entire
envelope and restores `execution_gateway_runtime_not_verified`. A fully clear
set removes only that blocker: it neither reserves budget nor issues a runtime
session and cannot reach broker submit/cancel behavior.

Stage 3.4 adds a separate session-start Account Truth record. Its provider
rebuilds the current sanitized Account Truth source from the latest broker
import, reconciliation, current ledger projection, and manual-review decisions.
The fact must be clear/pass/fresh, have zero unresolved mismatches, carry a
valid source fingerprint, and be no more than 120 seconds old. Accepted and
rejected attempts are append-only; resolution re-runs the source and expires
the record after 120 seconds. The session request and capital evaluation bind
the same typed fingerprint, evidence connector, and account alias. Drift or
identity mismatch changes the envelope and invalidates its approval. A clear
binding removes only `session_account_truth_snapshot_not_bound`; it cannot
reserve budget, issue authority, mutate Account Truth/OMS/ledger, or contact a
broker.

Stage 3.5 introduces an immutable budget-reservation record after the exact
signed envelope is re-resolved. Money is represented as conservative fixed
0.0001 CNY units, while SQLite `BEGIN IMMEDIATE` serializes overlapping
capital, cash, China-trading-day turnover, and order-count checks. Exact reruns
reuse one row and one attestation cannot reserve twice. Expired windows stop
overlap capital/cash use, but daily turnover stays reserved for that trading
day until explicit release semantics are implemented. This state transition
does not issue a session, mutate OMS/ledger, or add broker capability.

Stage 3.6 makes symbol concentration explicit at both signed-review and
transaction boundaries. The envelope must contain exactly one positive,
canonical limit per projected symbol; every limit is capped by the recorded
capital evaluation's symbol and effective-capital ceilings. The reservation
stores projected/capacity maps in fixed units and, under the same write lock,
sums overlapping reservations per symbol. A legacy overlapping reservation
without symbol evidence blocks rather than being treated as zero. The initial
contract applies the capital evaluation's conservative symbol ceiling to every
symbol in the signed policy scope; future account facts may tighten individual
symbols but may never widen this signed map implicitly.

Stage 3.7 adds the runtime admission primitive. Its authenticated session
provider must return a current enabled session, immutable session/reservation
fingerprints, verified budget reservation, clear upstream and kill-switch
gates, exact scope/order set, active window, verified authority, and explicit
maximum rate.
The limiter uses server time and `BEGIN IMMEDIATE` to serialize one shared
authorization/account 60-second window, choosing the strictest overlapping
session rate. Admissions and rejections are evidence only. Stage 3.9 wires the
persistent token-authenticated provider, but production publishes no admission
mutation endpoint and the limiter has no broker or OMS capability.

Stage 3.8 adds the companion automatic-pause state without enabling session
issuance. A future authenticated session provider supplies only immutable
session identity, while a gate provider is reduced to an allowlisted snapshot.
Missing/failed or non-clear hard facts produce deterministic reasons and one
immutable pause event. SQLite persists only a `paused` runtime state; there is
deliberately no update-to-active method. Runtime admission reads that state
again after its own `BEGIN IMMEDIATE`, closing the stale-provider race. The
production route factory uses Stage 3.9 session identity but supplies no live
gate provider and exposes only status, event history, and per-session state
reads, so the envelope retains
`automatic_pause_controller_not_wired_to_live_gates` as a hard blocker. Resume
must later require a new operator review and cannot be inferred from gates
becoming clear.

Stage 3.9 introduces the durable runtime-authority boundary. Envelope approval
and budget reservation remain non-authorizing inputs; issuance re-resolves both
and requires a distinct Ed25519 approval plus possession of the matching
signature over a deterministic issuance fingerprint. Verification and history
APIs omit signature bytes, so a public approval id is not a runtime capability.
One reservation can create only one session under `BEGIN
IMMEDIATE`. The raw capability token is returned only on the first successful
response and only a salted SHA-256 hash is persisted. Internal admission must
authenticate that token, then its own write transaction rechecks the persisted
session fingerprint, reservation, enabled status, effective/expiry time, and
pause state. Revocation is a separately signed, allowlisted-reason, one-way
enabled-to-revoked transition under the same database lock, so a stale provider
cannot race it. Public APIs expose issue/revoke review actions and sanitized
state, but no runtime admit, resume, renew, widen, OMS/ledger write, broker
submit, or broker cancel action. The remaining automatic-pause blocker refers
to live gate-provider orchestration, not session identity or rate wiring.

The Stage 2.1/3.1 batch manifest accepts only a unique non-paper terminal OMS
order set bound to one explicit reconciliation run. Every selected order must
have exactly one persisted `no_action` item whose OMS status has not drifted.
Filled orders additionally require exact real-fill quantity and provider,
broker-order, Account Truth import, and same-run reconciliation linkage. The
record is append-only and source-sensitive; later order, transition, fill,
item, or run changes invalidate it. A clear record satisfies only the prior-
batch evidence gate. It cannot authorize the next batch, accept a mismatch,
reserve budget, modify OMS/ledger state, or contact a broker.

Stage 4 treats capital scaling as a review decision, not a reward for recent
profit. A versioned current/proposed tier is evaluated against execution quality,
cost, drawdown, capacity, liquidity, reconciliation, divergence, disconnect,
policy-violation, and incident evidence with explicit provenance. Protective
recommendations take precedence over expansion: severe evidence recommends
disable, degraded evidence recommends scale-down, insufficient evidence holds,
and only a fully passing review may request a separate new authorization. Human
review can choose a safer result but cannot turn hold/scale-down/disable evidence
into scale-up. The review log never mutates the active authorization or runtime
limits.

Stage 4.1 separates declared metrics from persisted provenance. The public
scaling-review service resolves broker-soak observations, execution-
reconciliation runs, paper/shadow runs, and risk decisions by typed identifiers,
checks their review-window membership and clear state, and returns only sanitized
source fingerprints. The review-input fingerprint and resolution fingerprint
form a separate evaluation identity, so a changed source cannot reuse an older
human decision. Missing or non-clear facts fail closed. Account Truth,
after-cost, incident-window, and capacity/liquidity references must resolve
through one recorded computed evidence window; caller-declared aggregates alone
cannot support scale-up. Protective hold/scale-down/disable analysis remains
evidence-only and does not mutate Account Truth, OMS, runtime authority, gateway
state, or ledger state.

Stage 4.2 provides that computed window without accepting caller-supplied metric
values. Point-in-time Account Truth snapshots keep only a sanitized score/gate
summary and must be captured within 15 minutes of the broker import. A review
window requires distinct clear snapshots near both boundaries. Account-level
after-cost return uses Modified Dietz over persisted total-equity snapshots and
external cash flows. Incident evidence scans persisted critical alerts, rejected
live-write attempts, and connector disconnect observations. Capacity, liquidity,
and slippage use only non-simulated fills whose metadata links broker/provider/
order facts, Account Truth, execution reconciliation, a capacity model, and
market data. Missing coverage records a blocked fact instead of a default value.
The window and every fact are fingerprinted; the resolver rechecks schema,
window, fingerprints, fact status, metric equality, and fill coverage. A fully
resolved result can only record a request for a separate authorization and still
cannot issue authority or mutate execution state.

Stage 4.3 adds an `operating_sample` fact to the same append-only window. It
derives reviewed trading days from healthy read-only connector observations;
counts non-paper OMS orders and their filled, rejected, partial, cancelled,
expired, and nonterminal outcomes; requires real fills to link broker order,
Account Truth import, and execution-reconciliation facts; requires the latest
reconciliation to cover every sampled order; computes p95 latency to the first
persisted no-action reconciliation; counts paper/shadow divergence; and computes
maximum drawdown on cash-flow-unitized portfolio equity. The resolver requires
this fact and compares its nine review inputs exactly. Missing coverage,
nonterminal state, invalid quantity, or a capped 5,000-row scan fails closed.
The present reconciliation evidence is order-covered rather than cryptographically
bound to a runtime session or broker batch; that stronger binding remains a
future execution gate, not an assumption hidden by the aggregate.

## Design Implications

* The architecture optimizes for decision and execution quality, not for the
  fastest order submission.
* The default UI should surface "what to review next" before "what to buy".
* Runtime data, broker evidence, reports, logs, and screenshots remain local
  and out of source control.
* Tests should be deterministic and use synthetic fixtures for live-like paths.
* Every trading-related feature should state what it assumes, what it blocks,
  what evidence it records, and what it refuses to automate.
* Capital should scale through reviewed evidence tiers, not through a permanent
  fixed "small account" restriction and never through automatic scale-up.
