# Controlled Capital Execution Plan

[Goal](KARKINOS_GOAL.md) | [Architecture](ARCHITECTURE.md) |
[Roadmap](ROADMAP.md) | [中文路线图](ROADMAP.zh.md)

## Objective

Karkinos should become a human-supervised quant trading system whose execution
authority is explicit, bounded, observable, reversible, and scalable by
evidence.

The product is not permanently limited to a small account or a fixed small
amount. The first live automation trial deliberately receives a small risk
envelope because unproven software, broker behavior, and operating procedures
still contain unknown failure modes. Later envelopes may be increased or
reduced after review.

Profit is not guaranteed. The engineering objective is to improve after-cost
outcomes by enforcing validated strategy selection, execution discipline,
capital limits, reconciliation, and rapid failure containment.

## Terms

* **Account capital**: cash and assets owned by the account. Merely being
  available does not authorize automation.
* **Authorized capital**: the maximum exposure an operator explicitly makes
  available to a controlled execution session.
* **Risk envelope**: the stricter combined limit produced by account, strategy,
  symbol, liquidity, turnover, loss, drawdown, time, and operational gates.
* **Pilot exposure**: the deliberately small initial risk envelope used to
  validate a new connector, strategy, policy, or execution mode.
* **Capital scaling**: an audited increase or decrease in an authorization tier
  based on live evidence. It is not an automatic consequence of profits or
  available cash.

Effective authority must never exceed the strictest applicable constraint:

```text
effective authority
= minimum of
  operator authorization
  account policy
  strategy policy
  symbol and liquidity policy
  remaining daily turnover/loss/drawdown budget
  fresh broker cash and position facts
  connector and market-session capability
```

The envelope is multi-dimensional rather than one misleading scalar. Account,
strategy, symbol, and operator capital limits bound total authorized exposure;
available cash, liquidity, and maximum-order limits bound the proposed
increment; turnover, loss, drawdown, order-rate, and error limits each retain
their own units and block independently.

## Non-Negotiable Invariants

1. Broker submission is disabled when no valid operator authorization exists.
2. `manual_each_order` remains the default live-like mode.
3. Any policy-bounded automation authorization is explicit, time-bounded,
   versioned, locally stored, auditable, revocable, and deny-by-default.
4. Strategy code proposes signals or target positions only. It cannot import or
   call broker adapters and cannot grant itself execution authority.
5. The only execution path is decision evidence -> account truth -> risk ->
   authorization -> OMS -> gateway -> broker evidence -> reconciliation.
6. Kill switch, stale data, stale account truth, connector degradation,
   unresolved reconciliation, limit exhaustion, or policy expiry prevents new
   submissions.
7. Broker callbacks and imported facts are evidence. They do not silently
   rewrite the production ledger.
8. Credentials and real account exports remain outside source control. A
   connector must expose capabilities without exposing secrets.
9. No UI, report, or strategy promotion state may imply guaranteed returns or
   execution approval merely because historical performance passed.

## Authority Modes

| Mode | Human authority | Machine authority | Initial status |
| --- | --- | --- | --- |
| `disabled` | May inspect evidence | None | Default |
| `manual_each_order` | Confirms every order | May validate, submit the confirmed order, monitor, reconcile, and stop | Future controlled bridge |
| `session_bounded` | Grants a short-lived account/strategy/symbol envelope | May submit only qualifying orders inside the remaining envelope | Future pilot, disabled by default |

`session_bounded` is not unattended automation. The operator starts the
session, sees the capital at risk and all limits, can pause or kill it, and must
renew or replace the authorization after expiry. A session may automatically
pause; it may never automatically widen its own authority.

## Delivery Stages

### Stage 0 — Contracts and Safety Model

Deliverables:

* Capital authorization schema, modes, expiry, revocation, policy snapshot, and
  deterministic deny reasons.
* Separate read-only evidence-connector and controlled execution-gateway
  identities with an explicit same-account binding.
* Pure policy evaluation with no gateway or broker side effects.
* Documentation, threat model, assumptions, validation commands, and risk
  impact template.
* Static guard preserving the strategy-to-broker boundary.

Exit criteria:

* Missing, disabled, expired, mismatched, or over-budget authorization always
  denies controlled execution.
* Tests prove policy evaluation cannot submit, cancel, mutate OMS, or write the
  production ledger.

Current implementation status (2026-07-11): the policy/evaluation contract,
append-only evaluation audit service, deterministic sequential rerun reuse, and
status/preview/record/list evidence APIs are implemented. Static `config.json`
is intentionally not an authority source. The runtime authority state remains
disabled even when an evaluation returns `allowed=true`; there is no issue,
revoke, enable, resume, submit, or cancel endpoint. Concurrent duplicate audit
requests are a known residual limitation until a dedicated unique persistence
contract is reviewed. The current local API also records `authorized_by` as
unverified input; authenticated operator identity and signature/approval
evidence are mandatory before any future authority-issuing workflow.
Contract v2 now requires non-overlapping `evidence_connector_ids` and
`execution_gateway_ids`, separate current health/capability facts, and a
verified same-account binding. The evidence connector must remain read-only.
Declared execution-gateway capability is fingerprinted but always remains
runtime-unverified until a future independent gateway verifier is implemented.

### Stage 1 — Real Read-Only Broker Soak

Deliverables:

* One broker-specific read-only adapter for cash, positions, orders, fills,
  trading calendar/session status, heartbeat, and source timestamps.
* Versioned immutable snapshots, capability health, polling history, and stale
  detection.
* Startup, intraday, and end-of-day reconciliation with explicit unmatched and
  multi-partial-fill evidence.
* Operations alerts and operator runbook for disconnection, schema drift,
  duplicate evidence, stale facts, and restart recovery.

Exit criteria:

* No submit or cancel capability is exposed.
* At least 20 trading sessions of evidence are reviewed with no unresolved
  critical cash/position/order/fill mismatch.
* Disconnect, stale-data, duplicate-callback, and restart-recovery drills
  produce deterministic alerts and safe degraded states.

Current foundation status (2026-07-10): broker-neutral capture/status/list
services and APIs persist sanitized QMT/PTrade/local-export snapshot evidence,
deterministic fingerprints, freshness, read capabilities, fact counts, and
provider market-calendar trading-day coverage. Startup, intraday, and
end-of-day runbook phases now persist append-only evidence; end-of-day fails
closed unless execution reconciliation is clear with zero open items.
Disconnect, schema-drift, stale-data, duplicate-evidence, and service-instance
restart-recovery drills record deterministic results and shared Operations
alerts. The operator procedure is documented in
[BROKER_CONNECTOR_SOAK_RUNBOOK.md](BROKER_CONNECTOR_SOAK_RUNBOOK.md). Raw account
ids and broker-write capabilities are excluded. Stage 1.1 now builds a separate
promotion dossier from exactly 20 healthy, clear-reconciled trading days,
passed startup/intraday/end-of-day evidence for every selected day, all five
recovery drills, a stable account alias/hash, and current pass/fresh/zero-
unresolved Account Truth evidence. A short-lived Ed25519 approval may record
signed owner acceptance for that exact fingerprint, including explicit human
assertions that the Account Truth import belongs to the same account alias and
that full process/broker-terminal recovery was performed externally. Source
drift invalidates the acceptance. This is Stage 1 evidence readiness only: it
does not issue capital/runtime authority. Stage 2 now resolves and fingerprints
the current promotion dossier, operational source, Account Truth source, and
verified acceptance id in every per-order dossier, but this still does not wire
any broker submission path. Sequential duplicate observations reuse evidence; concurrent
database uniqueness remains a known persistence limitation.

### Stage 2 — Per-Order Human-Confirmed Broker Bridge

Deliverables:

* Broker-specific dry-run, submit, query, callback/poll, and cancel contracts,
  each advertised as a separate capability.
* Idempotent client order ids, broker acknowledgements, partial-fill
  aggregation, rejection, cancel, timeout, reconnect, and startup recovery.
* `manual_each_order` authorization with a fresh evidence fingerprint and a
  final operator confirmation immediately before submission.
* Reconciliation-before-ledger workflow and kill-switch drills.

Exit criteria:

* Submission remains unavailable unless the connector, account, strategy,
  symbol, order, policy version, and operator confirmation all match.
* Repeated requests cannot duplicate a broker order.
* Unknown broker state blocks new submissions until reconciled.
* Synthetic, dry-run, and broker-supported validation pass before any real
  order is considered.

Current foundation status (2026-07-11): a separate non-submitting per-order
dossier service computes a canonical order fingerprint and binds the current
OMS terms, recorded capital evaluation, Account Truth/research/risk/
paper-shadow evidence, connector soak, exact prior-batch reconciliation, and
kill-switch snapshot. Exact dossier attestations and rejected stale/blocked
attempts are append-only and deterministic. Recording now requires a short-
lived Ed25519 approval bound to the exact dossier and matching configured
operator public key; Karkinos stores no operator private key. A verified
attestation still does not change OMS, grant authority, or contact a broker.
Each preview resolves the current signed Stage 1 promotion for the exact
read-only evidence connector and binds its promotion, operational, Account
Truth, and verified acceptance fingerprints. The separately scoped execution
gateway is included as declared evidence and remains runtime-unverified unless
an exact current Stage 2.4 record is resolved. When promotion is valid, it
clears only the Stage 1 sub-blockers. When runtime verification is valid, it
clears only `execution_gateway_runtime_not_verified`. Runtime authority, a
reviewed live gateway, and broker submission remain hard blockers. The exact
prior-batch gate is source-sensitive evidence, but never
authorizes the next order. The CRITICAL `BrokerGatewayService` and HIGH-risk
`OmsService` are intentionally unchanged in this slice.

Stage 2.4 now provides an isolated runtime gateway verifier and local evidence
API. Verification requires a distinct registered gateway, verified account
binding, fresh source-fingerprinted health, complete submit/cancel/query/dry-run/
idempotency capabilities, and an exact dry-run with no broker order id,
`submitted=false`, and zero side effects. Accepted/rejected records are
append-only; resolution rechecks the source and expires after five minutes.
Production registers no execution gateway by default. A clear verification is
still not authority and there is no submit/cancel/consume operation.

Stage 2.5 now requires the per-order request and recorded capital evaluation to
name the same typed gateway-verification fingerprint. Every dossier preview and
confirmation re-resolves that record and exactly matches the gateway, read-only
connector, account alias, OMS order, canonical order fingerprint, and sanitized
dry-run order contract. Expiry, source drift, provider failure, any order-term
mismatch, or mismatched authority/submission assertions re-block review and
invalidate the previous signed dossier. The production
route injects an empty runtime gateway registry by default, so this path remains
closed until a separately reviewed adapter is registered; no API in this slice
can register one or submit an order.

Stage 3.12 adds the first default-closed one-shot submit/query boundary for one
exact manually confirmed order. It requires a distinct final Ed25519 signature,
current signed release evidence, runtime gateway verification, fresh health,
zero-side-effect dry-run, and clear kill switch. Intent and OMS pending state
persist before one external call; unknown recovery is query-only. Stage 3.13
then adds the missing cross-order safety interlock: any prepared, accepted-but-
unreconciled, or unknown intent blocks every different order in preview and
inside the serialized insert transaction. Reconciliation, alerts, and
Operations expose the unresolved fact. Production still injects no write
adapter/release provider, and matching broker evidence cannot yet self-clear
the interlock or infer an OMS fill/ledger update.

Stage 3.14 now provides a deliberately narrow signed exit for exact full fills.
It binds the latest matching reconciliation item, every selected trade row from
one validated import, fresh clear Account Truth no older than 120 seconds, and
a separate operator signature. A single transaction records the linked fills,
advances OMS to `filled`, persists terminal reconciliation, and releases the
interlock without applying the production ledger. Partial totals and cross-
import aggregation remain blocked. Canonical CSV v2 may retain optional broker
and client order ids, but clearance requires both to match the persisted submit
intent exactly; missing, conflicting, or unsafe identity evidence fails closed.
The identifiers do not grant write authority. Production readiness still
requires a reviewed broker adapter with independently verified, order-linked
partial-fill/cancel callback or poll evidence.

Stage 3.15 adds the evidence plumbing for that missing lifecycle without
claiming production connectivity. A normalized local QMT
`exact_order_lifecycle` export is previewed by default and recorded only by an
explicit CLI acknowledgement. The persisted snapshot binds both order ids,
hashed account scope, monotonic source sequence, capture/file/evidence
fingerprints, cumulative filled/cancelled quantities, and exact fills. Strict
validation and a serialized repository reject credentials, malformed or stale
facts, quantity/status inconsistency, duplicate fills, identity/contract drift,
sequence races, and preview mutation. Reconciliation consumes only persisted
facts and exposes open/partial/cancel/full evidence without touching OMS or the
ledger. The canonical full-fill predicate also executes under the signed-
clearance and next-order SQLite writer transactions, so a partial/cancel/
conflicting observation cannot race a clearance or leave a superseded
clearance usable. Lifecycle `filled` is supporting evidence only: the Stage
3.14 broker statement, Account Truth, and separate signature remain mandatory.
The actual QMT callback/poll collector, deployment/release review, operational
soak, broker cancel, and production write registration remain unimplemented and
disabled.

### Stage 3 — Session-Bounded Controlled Execution

Deliverables:

* Short-lived operator authorization for account, strategy, symbols, execution
  mode, market session, maximum capital, order value, position change,
  turnover, daily loss, drawdown, order rate, and consecutive errors.
* Remaining-budget calculation before every order.
* Automatic pause on kill switch, data/account/connector degradation,
  divergence, rejection spikes, reconciliation gaps, unexpected cash or
  position changes, policy expiry, or budget exhaustion.
* Operator UI for preview, enable, pause, resume with a new review, revoke, and
  inspect the exact reason and capital at risk.

Exit criteria:

* No session can widen, renew, or resume itself.
* The previous execution batch must reconcile before the next batch submits.
* The initial live authorization uses a deliberately small exposure envelope;
  account size itself is not constrained.

Current foundation status (2026-07-10): a proposal-only session-envelope service
accepts a recorded `session_bounded` capital evaluation, an explicit OMS order
set, and a timezone-aware window of at most 30 minutes. It fingerprints each
order and required gateway evidence, then projects capital, cash, gross
turnover/exposure without buy/sell netting, per-order/position/liquidity limits,
and order-rate capacity. Exact envelope attestations and deterministic rejection
attempts are append-only, but they do not issue a session. Current soak
freshness and kill-switch/reconciliation state are rechecked; volatile age
counters do not change the fingerprint until freshness crosses a policy state.
The envelope reads soak only from the v2 evidence connector and fingerprints
the distinct execution gateway. Stage 3.3 requires one unique current gateway
verification fingerprint per OMS order and the exact same typed reference set
in the recorded capital evaluation. Every preview and attestation re-resolves
all order sources; missing/extra/reused fingerprints, provider failure, expiry,
source drift, or gateway/connector/account/order/term mismatch blocks the whole
envelope and invalidates the previous signed artifact.
Stage 3.4 also requires a short-lived session-start Account Truth record built
from the latest broker import, reconciliation, current ledger projection, and
manual-review state. It must be clear/pass/fresh with zero unresolved mismatches
and no more than 120 seconds old. The capital evaluation and envelope request
must name the same typed fingerprint, connector, and account alias. Resolution
rechecks the source and expiry on every preview/attestation. A clear result
removes only the Account Truth evidence blocker; it does not reserve budget,
issue a session, mutate account facts, or contact a broker.
Stage 3.5 adds an atomic reservation layer for a still-current signed envelope.
It fingerprints exact authorization/account scope, China trading day, window,
conservative gross/cash/turnover amounts, order count, and capacities, then uses
SQLite `BEGIN IMMEDIATE` to prevent concurrent double allocation. Reservation
does not issue session authority or enable OMS, ledger, or broker actions.
Stage 3.6 adds an explicit per-symbol runtime-limit map to the signed envelope
and atomic row. The map must exactly match projected symbols, stay below the
capital evaluation's symbol/effective ceilings, and cover conservative gross
projection. Overlapping reservations are accumulated per symbol under the same
write lock; legacy missing evidence fails closed. This clears the per-symbol
evidence gate only and still does not issue a runtime session.
Stage 3.7 implements the internal sliding-window rate-admission ledger. It
requires a current authority-verified session, binds exact session/reservation/
order/request identity, uses server time, and serializes the final slot across
overlapping sessions for the same authorization/account. Stage 3.9 supplies a
persistent token-authenticated provider; production still exposes only
read-only admission status/history, so the primitive is not a public execution
or broker permission.
Stage 3.8 implements the internal automatic-pause state machine. Once an exact
identified session sees a missing or failed hard gate, the first pause event and
one-way `paused` state are stored atomically; later clear facts do not resume it.
The rate-admission transaction checks this durable state before retry or slot
logic, so a stale provider cannot admit a paused session. That Stage 3.8 slice
exposed only read-only pause status/state/history; Stage 3.10 now supplies live-
gate orchestration and Stage 3.11 supplies signed replacement rather than
in-place resume.
Stage 3.9 implements signed runtime issuance and revocation. A second operator
signature and matching possession proof bind the exact current reservation,
attestation, scope, order set, window, and rate; public approval history omits
signature bytes, and the attestation signature alone cannot issue authority. The
token is returned once, stored only as a salted hash, and required by the
internal rate limiter. Expiry, source drift, durable pause, or separately signed
one-way revocation blocks authentication. Admission also rechecks persistent
state transactionally, closing stale-provider revocation races. There is still
no public admit, resume, renew, widen, broker submit/cancel, OMS/ledger mutation,
or automatic capital change.
Stage 3.10 now persists live-gate snapshots and connects them to the one-way
pause controller. It evaluates Account Truth, risk, paper/shadow,
reconciliation, gateway, market-data freshness, runtime budget/rate, kill
switch, loss/drawdown, rejection, account-change, and consecutive-error facts.
Missing evidence pauses. Periodic checks require explicit scheduler startup;
the only operator-triggered check requires the same session token and cannot
resume or widen authority. At this stage, reviewed recovery, production-grade
broker execution/reconciliation sources, and an explicitly authorized submit/
cancel boundary remained. Stage 3.11 now closes reviewed recovery only.
Stage 3.11 completes the reviewed recovery boundary without exposing in-place
resume. An unexpired paused scope blocks ordinary issuance. The owner must
prepare a new current attestation and atomic reservation, wait for continuously
clear post-pause gates, and sign the exact equal-or-narrower replacement. One
transaction revokes the predecessor and issues a new session/token; exact
retries cannot reissue the secret and conflicting concurrent handoffs cannot
both succeed. A blocked or superseding gate fact aborts the handoff. This still
does not create broker submit/cancel, OMS/ledger mutation, renew, widen, or
automatic capital expansion.
Stage 3.13 also enforces reconciliation-before-next-order at the controlled
submission boundary. Different-order concurrency is serialized, unknown
outcomes remain query-only and critical, and accepted acknowledgements remain
blocked until a future independently signed reconciliation-clearance protocol
binds broker fill/cancel evidence and Account Truth. This stage cannot submit
under session authority, apply fills, mutate the production ledger, or widen a
session.
Stage 3.14 completes only the exact-full-fill branch of that protocol. A
distinct final signature and current Account Truth permit atomic real-fill/OMS/
terminal-reconciliation persistence and next-order interlock release, while
partial fills, cancels, automatic ledger mutation, session-authorized submit,
and adapter registration remain absent.
The request and recorded capital evaluation must bind the same resolved clear
prior-batch fingerprint. Stage 1/2 promotion, broker submit capability, and the
live gateway remain hard
blockers. Recording an attestation requires a current
Ed25519 approval for the exact envelope and matching operator, but that approval
cannot issue a session. A proposal can never auto-renew, auto-resume, widen
itself, submit an order, or scale capital.

### Stage 4 — Evidence-Based Capital Scaling

Deliverables:

* Configurable authorization tiers and a promotion/demotion decision record.
* Capacity and liquidity evidence, after-cost slippage, fill quality, rejection
  rate, divergence, drawdown, policy violations, reconciliation latency, and
  operational incident metrics.
* Human-reviewed scale-up, hold, scale-down, or disable recommendations.
* Automatic scale-down or pause when a harder risk gate trips; no automatic
  scale-up.

Exit criteria:

* Larger authority is granted only by a new explicit operator decision tied to
  reviewed evidence and a new expiry.
* Rollback to `manual_each_order` or `disabled` is always available.
* Full-account, permanently authorized, unattended execution remains outside
  the product target.

Current foundation status (2026-07-10): a pure scaling-review evaluator and
append-only audit workflow compare versioned current/proposed tiers against
reviewed trading days, orders/fills/rejects, reconciliation gaps/latency,
slippage, after-cost result, drawdown, capacity/liquidity, paper/shadow
divergence, disconnects, policy violations, and incidents. Scale-up eligibility
requires at least 20 reviewed trading days, 50 orders, typed provenance, and all
quality thresholds; it produces only `request_new_authorization_for_scale_up`.
Invalid/insufficient evidence holds, degraded quality recommends scale-down,
and critical incidents, violations, unresolved reconciliation, or exhausted
drawdown recommends disable. A human may record the recommendation or a safer
choice against the exact evaluation fingerprint, but an unverified local label
cannot exceed the evidence recommendation. No decision issues a new
authorization, mutates runtime limits, resumes execution, submits to a broker,
or automatically scales capital.

Persisted-source resolution status (2026-07-10): the Stage 4.1 resolver now
looks up broker-soak observations, execution-reconciliation runs, paper/shadow
runs, and risk decisions from their existing stores, verifies review-window and
clear-state constraints, and binds sanitized source fingerprints into the
evaluation identity. A source change therefore cannot reuse a prior evaluation.
Account Truth, after-cost, incident-window, and capacity/liquidity now require a
Stage 4.2 computed evidence-window record; a caller cannot supply those computed
facts directly. Any missing, non-clear, out-of-window, fingerprint-invalid, or
metric-mismatched source converts mathematical scale-up eligibility to hold; an
attempted scale-up decision is rejected and audited.

Computed-window status (2026-07-10): Account Truth point snapshots require a
pass/fresh/zero-unresolved score captured within 15 minutes of the broker import,
and a review needs distinct start/end snapshots. After-cost return uses Modified
Dietz over persisted total equity and external cash flows. Incident counts come
from alerts, rejected write attempts, and connector observations. Capacity,
liquidity, and slippage require non-simulated reconciled fills with explicit
broker, Account Truth, reconciliation, capacity-model, and market-data linkage.
Missing inputs produce blocked evidence, not zero/default metrics. Preview and
record endpoints accept the time window only and add no authority issuance,
runtime mutation, execution resume, OMS/ledger write, gateway contact, or broker
submission.

Computed operating-sample status (2026-07-10): Stage 4.3 derives reviewed
trading days, real OMS order outcomes, reconciliation gaps and p95 latency,
paper/shadow divergence, and cash-flow-unitized maximum drawdown from persisted
facts in the same evidence window. `operating_sample:<window_id>` is now a
required clear source, and all nine corresponding review metrics must equal the
recorded fact. Rejected, partial, cancelled, expired, and nonterminal outcomes
remain separate rather than being normalized into a favorable fill rate.
Missing broker-day, real-fill linkage, latest reconciliation coverage,
paper/shadow comparison, drawdown history, or a complete source scan blocks the
window. Reconciliation is currently order-covered, not yet runtime-session or
broker-batch bound. This read-only evidence tightens review eligibility but does
not reserve capital, issue/expand authority, mutate OMS/runtime/ledger state, or
contact a broker.

## First Implementation Slice

The first code slice is deliberately non-submitting:

1. Add a versioned capital-authorization policy contract.
2. Implement pure deterministic evaluation for mode, scope, time window,
   account/strategy/symbol match, capital/order/turnover/loss/drawdown budgets,
   reconciliation readiness, account-truth freshness, connector health, and
   kill switch.
3. Return structured `allowed`, `blocked_reasons`, `effective_limits`, and
   `remaining_budget` evidence.
4. Add deterministic tests proving missing or unsafe facts fail closed and the
   evaluator has no broker, OMS, or ledger side effects.
5. Expose read-only status only after the policy contract is stable; do not add
   submit, cancel, resume, or auto-enable endpoints in this slice.

## Trading-Change Evidence Template

Every trading-related implementation slice records:

* **Assumptions**: market, broker, account, clock, data freshness, fill,
  liquidity, cost, permission, and failure assumptions.
* **Validation**: exact focused tests, deterministic replay, audit command,
  full suite/build commands where relevant, and operator drill.
* **Risk impact**: new authority, prevented failure, residual risk, affected
  execution flows, rollback behavior, and kill-switch behavior.
* **Privacy/compliance**: credential boundary, private evidence location,
  required broker/operator confirmation, and source-control exclusions.

## Regulatory Release Gate

Before enabling any broker-connected programmatic submission, the owner must
confirm reporting, agreement, testing, and risk-control obligations with the
broker for the actual account and connector. Karkinos may record that review as
evidence but must not self-certify legal or broker approval.

Current primary references include the China Securities Regulatory
Commission's [Securities Market Program Trading Management Provisions
(Trial)](https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml) and the
Shanghai Stock Exchange's [Program Trading Management Implementation
Rules](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20250612_10781696.shtml).

## Completion Boundary

This plan is complete when Karkinos can safely operate reviewed strategies
under explicit, bounded, expiring human authority and can scale that authority
up or down through audited evidence. It does not require or permit an
unattended profit robot, permanent full-account authority, strategy-direct
broker access, or a guaranteed-return claim.
