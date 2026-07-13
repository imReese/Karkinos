# Karkinos Goal

## North Star

Karkinos is a China-market personal quant research and trading platform, not a
toy backtester.

It is an integrated personal finance app for backtesting, strategy research,
account truth, risk control, signals, reconciliation, and review.

It should help one serious investor make fewer emotional mistakes, deploy only
validated strategies, control downside first, and keep every decision
auditable. The daily product question is:

> Given my portfolio, market data, risk limits, account truth, and validated
> strategies, what should I do today — buy, sell, hold, rebalance, or do
> nothing — and why?

Its long-term execution target is a **human-supervised, capital-bounded quant
trading system**. The owner may authorize increasingly large execution
envelopes only after evidence supports the change, while retaining the ability
to inspect, pause, reduce, expire, or revoke that authority at any time.

Its long-term research experience is **AI-native but evidence-governed**. AI
roles may help decompose questions, inspect canonical projections, debate
claims, draft reports, and preserve reviewed research memory. Provider, model,
role, workflow, and tool identities remain separate so no single model vendor
becomes a platform dependency. AI output is a cited research artifact, never
an account fact, risk decision, capital authorization, OMS transition, or
broker instruction.

## Product Boundaries

Karkinos is a personal finance app for research, portfolio evidence, and
risk-control workflows. It is not default broker automation and not investment
advice. Future broker-connected workflows must be controlled, explicitly
enabled, gated, audited, and disabled by default.

The product boundary is:

* Local market, portfolio, ledger, broker-evidence, research, and risk data can
  be imported, checked, reconciled, scored, and surfaced for review.
* Signals and strategy outputs remain research evidence until they pass data,
  cost, OOS, risk, account-truth, paper/shadow, and manual-review gates.
* Financial data integrity is a product safety boundary: persisted facts are
  authoritative, one canonical calculation owns each financial concept,
  cross-surface totals must reconcile, and missing or unpublished evidence
  fails closed instead of being replaced by a plausible value.
* AI research context must bind immutable evidence references, a valuation
  snapshot, and a ledger cutoff. Runtime provider responses and model memory
  are not authoritative financial inputs.
* AI tools are deny-by-default and read-only. They may project persisted
  portfolio, account-truth, operations, research, and paper/shadow evidence;
  they may not expose OMS, ledger mutation, risk decisions, kill switch,
  capital authorization, broker submission, cancellation, or provider refresh.
* AI trade-plan output is an explicitly non-executable draft. It cannot enter
  the canonical Daily Trading Plan without a separate, future human-review
  handoff and all existing evidence, risk, account-truth, and authority gates.
* Live-like workflows must default to manual confirmation.
* Broker submission is a future controlled-bridge capability, not the default
  product mode and not something strategy code may call directly.
* A future controlled mode may automate orders only inside an explicit,
  time-bounded capital authorization. It must remain disabled when no valid
  authorization exists.
* "Small capital" is an initial live-validation exposure, not a permanent
  product ceiling. Capital authority may scale up or down only through reviewed
  evidence, never merely because account cash is available.
* No broker login, broker password storage, default real-money automation, or
  guaranteed-profit language belongs in the product.
* Secrets, broker credentials, real account exports, runtime databases, logs,
  screenshots, and private financial data must stay out of source control.

## Operating Loop

Karkinos should support the full investment operating loop:

```text
research idea
→ evidence-bound AI research task / multi-role analysis (optional)
→ cited claim, debate, report, and reviewed memory artifacts
→ reproducible backtest
→ after-cost validation
→ account truth / data reconciliation
→ risk gate
→ paper/shadow signal
→ dashboard/action queue
→ signal journal
→ paper/shadow execution review
→ manual confirmation by default
→ manual ticket or future controlled broker bridge
→ execution/account reconciliation
→ post-decision review
→ strategy improvement
```

## Current Roadmap Status

The current roadmap status is maintained in [ROADMAP.md](ROADMAP.md).

The v1.8 planning track is active, but real-money broker submission remains
disabled and unavailable. Planning, policy contracts, read-only adapters, and
deterministic evidence may advance without granting execution authority.

Latest completed milestones:

* **v1.6 — Operations Center & Paper/Shadow Runbook**
  completed the persisted, deterministic paper/shadow operating loop,
  divergence review, scheduler/runbook evidence, and operator-facing
  Operations, Decision, Overview, and Trading surfaces.
* **v1.7 — Controlled Broker Bridge Foundation (Non-Submitting)** completed
  manual-ticket preview/export/dry-run/create, local read-only connector
  evidence, capability and health contracts, manual execution evidence,
  broker-statement handoff, and execution reconciliation. Completion does not
  provide live broker submission, executable broker cancellation, automatic
  production-ledger mutation, or an auto pilot.

Active planning target:

* **AI-native Phase 1 — Architecture and Runtime Foundation** establishes
  provider/model/agent-role decoupling, stateful evidence-bound workflows,
  deterministic orchestration, fail-closed tool permissions, append-oriented
  audit storage, and a local fixture provider. It registers no production AI
  provider, calls no external model, exposes no model workflow, and grants no
  trading authority. Phase 1.1 adds content-addressed canonical-evidence
  captures and context-bound read executors with exact valuation/ledger
  identity checks. Phase 1.2 adds one explicitly human-started, model-free POST
  boundary that reuses existing canonical Portfolio, Account State, Operations,
  Research Evidence, Account Truth, and paper/shadow projections, verifies the
  identity again after capture, and writes only `ai_*` audit/evidence rows. It
  registers no scheduler, startup hook, background task, real provider, model
  call, OMS action, or broker capability. Phase 1.3 adds human-created research
  task records, human context review, and per-task hash-chain replay. A task may
  bind only a completed capture; incomplete evidence remains blocked, and the
  Web boundary stays idle until explicitly opened. Accepting a context records
  human review only: model execution, deterministic fixture execution, and
  background work remain later, separately reviewed phases.

* **v1.8 — Capital-Bounded Controlled Execution** starts with non-submitting
  policy contracts and a real read-only broker soak, then advances through a
  per-order human-confirmed bridge, a time-bounded automation pilot, and
  evidence-based capital scaling. The first live validation uses a deliberately
  small authorization envelope to cap unknown failure impact; that envelope is
  not the account-size or long-term product limit.
* The current v1.8 evidence foundation also binds per-order and session reviews
  to an exact source-sensitive prior-batch reconciliation fingerprint; it no
  longer treats a generic latest reconciliation run as proof that the intended
  batch is clear. This evidence still grants no execution authority.
* Capital-authorization v2 separates a read-only evidence connector from a
  distinct future execution gateway and requires a verified same-account
  binding. The roles may not share an id or overlap in policy scope. Declared
  gateway capability remains runtime-unverified evidence, never authority.
* Stage 2.4 can now produce short-lived, source-rechecked execution-gateway
  readiness evidence from a registered gateway's capabilities, health,
  account binding, and zero-side-effect dry-run. Production registers none by
  default, and verification still cannot issue authority or submit.
* Stage 2.5 now binds that exact current verification into each per-order
  dossier and its recorded capital evaluation. Gateway/connector/account/order
  mismatch, expiry, or source drift invalidates review; a clear binding removes
  only the runtime-verification blocker and still grants no execution authority.
* Stage 3.3 extends the same rule to bounded-session proposals with one unique
  current verification per OMS order and an exact capital-evidence reference
  set. One failed order blocks the whole envelope; a clear set still cannot
  reserve budget, issue a session, or submit to a broker.
* Stage 3.4 now requires a source-rechecked, 120-second session-start Account
  Truth record bound to the same capital evaluation, connector, and account
  alias. Drift, expiry, or unresolved reconciliation blocks the envelope; clear
  evidence still cannot reserve budget or issue runtime authority.
* Stage 3.5 now atomically reserves the exact signed envelope's conservative
  capital, cash, China-trading-day turnover, and order-count budget with SQLite
  write serialization. It revalidates every source first and still cannot issue
  a runtime session, mutate OMS/ledger, or contact/submit to a broker.
* Stage 3.6 requires an explicit signed limit for every projected symbol and
  atomically prevents overlapping sessions from exceeding the strictest
  per-symbol cap. Disjoint symbols may share an authorization only while the
  account-level budget also remains clear; no execution authority is created.
* Stage 3.7 provides a real atomic sliding-window admission ledger for a future
  authenticated bounded session. Stage 3.9 supplies the persistent token-
  authenticated provider, but there is still no public admission endpoint and
  the limiter cannot submit an order or contact a broker.
* Stage 3.8 provides a durable fail-closed automatic-pause primitive. Identified
  sessions pause on missing or failed account, risk, reconciliation,
  paper/shadow, gateway, market-data, budget, rate, kill-switch, loss, rejection,
  account-change, or error facts. Pause state is one-way and atomically blocks
  later rate admission. Stage 3.9 supplied session identity while this slice
  still lacked live gates; Stage 3.10 now orchestrates persisted gates and Stage
  3.11 provides signed replacement instead of an in-place resume.
* Stage 3.9 turns one current signed attestation plus atomic reservation into an
  expiring runtime session only after a second exact Ed25519 issuance approval
  and proof of signature possession; public approval history omits signatures.
  It returns a capability token once, stores only a salted hash, and supports a
  separately signed one-way revocation. Expiry, evidence drift, pause, and
  revocation fail closed; no session may resume, renew, widen, submit, or scale
  itself, and broker authority remains absent.
* Stage 3.10 persistently captures typed live-gate snapshots and evaluates them
  through the durable one-way pause controller. Monitoring may identify an
  enabled session after source drift only so it can pause that original
  session; it never grants runtime or broker authority. Missing Account Truth,
  risk, paper/shadow, reconciliation, gateway, market-data, budget/rate, kill
  switch, loss/drawdown, rejection, account-change, or error evidence fails
  toward pause. Explicit scheduler startup or token-authenticated self-check
  can trigger evaluation, but neither can resume, renew, widen, submit, or
  mutate OMS/ledger/capital state.
* Stage 3.11 replaces the unsafe idea of toggling a paused session back to
  enabled with a separately signed atomic handoff. Ordinary issuance cannot
  bypass an unexpired paused scope. A replacement needs a fresh attestation and
  reservation, continuously clear recovery evidence, and a distinct Ed25519
  approval; it atomically revokes the predecessor and issues only an equal-or-
  narrower session with a new one-time token. It cannot renew, widen, scale
  capital, mutate OMS/ledger, or contact/submit to a broker.
* Stage 3.12 adds a default-closed, one-shot per-order submission boundary. It
  requires a fresh exact confirmation chain, separate final Ed25519 signature,
  signed broker/regulatory release evidence, gateway capability/health/dry-run
  checks, and a clear kill switch. Intent and OMS pending state persist before
  the call; unknown outcomes are query-only and never resubmitted. Production
  has no write adapter or release provider by default, and automatic,
  strategy-direct, cancel, fill-apply, and ledger-sync paths remain absent.
* Stage 3.13 closes the cross-order gap: any prepared, accepted-but-unreconciled,
  or unknown controlled submission blocks every different order in both preview
  and the serialized database transaction. Execution reconciliation, critical
  alerts, and Operations expose the sanitized recovery task. Only a definitive
  rejection clears the interlock today; broker evidence cannot self-clear it,
  infer a fill, write the ledger, or authorize another order.
* Stage 3.14 permits only an independently signed exact-full-fill clearance:
  one validated broker import and fresh clear Account Truth must match the full
  OMS quantity and the controlled intent's exact broker/client order identities,
  then one atomic transaction records linked real fills, advances OMS to
  `filled`, persists terminal reconciliation, and releases the interlock. The
  canonical CSV v2 fields are optional evidence only: missing, conflicting,
  cross-import, or partial rows remain blocked, as does production-ledger
  mutation. A broker-specific callback/poll adapter is still required before a
  pilot.
* Stage 3.15 establishes a broker-neutral order-lifecycle evidence contract
  without adding a broker connection. A normalized export from an explicitly
  identified provider for one exact broker/client order identity is preview-
  only by default and requires a separate record flag plus explicit non-
  authority acknowledgement.
  Persisted observations bind a hashed account reference, gateway, monotonic
  account-scope sequence, capture time, file/evidence fingerprints, order
  status, cumulative fill/cancel quantities, and exact fills. Credential
  fields, stale or malformed snapshots, quantity inconsistency, sequence
  conflict, account drift, identity/contract drift, and preview mutation fail
  closed. Reconciliation may project open, partial, cancelled, or filled facts
  but never contacts a broker or mutates OMS/ledger. The same canonical lifecycle
  guard runs inside signed clearance and the next-order `BEGIN IMMEDIATE`
  transaction: a contradictory fact rejects a racing clearance or re-blocks an
  older clearance. Full lifecycle evidence alone still cannot clear; Stage
  3.14's independent broker statement, fresh Account Truth, and human signature
  remain mandatory.
* Stage 3.16 adds a broker-neutral, explicitly started collector-ingestion
  boundary. It accepts only local deterministic batches, records deployment,
  authorization, connection, batch, callback, cursor, and lifecycle evidence,
  and proves restart replay, idempotency, duplicate handling, out-of-order
  rejection, disconnect, and partial-batch behavior. It does not contain a
  broker SDK, contact a provider, modify OMS/ledger/risk/kill switch/capital
  authority, or register any adapter by default. QMT, PTrade, local-file, and
  other provider adapters remain replaceable edge components that require a
  separate security/capability review and explicit user authorization before
  registration; Karkinos does not claim official support for them.
* Stage 3.17 binds collector operational evidence to the canonical lifecycle
  resolver without making collection mandatory for scopes that have never used
  it. Once a provider/gateway/account scope has recorded a collector run, the
  resolved lifecycle observation must remain bound to that collector history
  and the latest effective run must be recorded and cursor-consistent.
  Prepared restart recovery, a blocked disconnect or partial batch, an unbound
  direct import, or inconsistent run/state evidence re-blocks signed clearance
  and the serialized next-order gate. A duplicate retry cannot mask a later
  blocked run. This binding is a read-only fail-closed projection: it does not
  contact a provider or modify OMS, fills, ledger, risk, kill switch, capital
  authority, or broker permissions.
* Stage 3.18 binds every internal bounded-session order-rate admission to one
  exact, persisted, no-more-than-30-second-old clear live-gate snapshot. The
  snapshot covers Account Truth, risk, paper/shadow, prior reconciliation,
  gateway, market data, reserved budget/rate, kill switch, loss/drawdown,
  rejection, account-change, and error evidence. The admission's SQLite writer
  transaction re-reads the latest snapshot and rejects stale, blocked,
  superseded, or session-identity-drifted evidence, closing the gap between
  preview and admission. This remains an internal evidence ledger: there is no
  public admit endpoint, broker contact, OMS/ledger mutation, or submit/cancel
  authority.
* Stage 3.19 exposes a persisted-fact controlled-execution operator projection
  and makes broker lifecycle health/query an explicit-ingestion read boundary.
  Capital at risk, remaining bounded headroom, expiry, latest order/submission,
  reconciliation, live-gate, pause, and blocker evidence are derived from the
  database only. Generic collector-run evidence is the canonical broker
  lifecycle health source; provider-specific adapters remain default-
  unregistered and separately reviewed. The retired runtime snapshot path is a
  labelled migration entry and returns no live account facts. These surfaces
  cannot contact a provider, issue/renew/resume/widen authority, submit/cancel,
  mutate OMS/ledger/risk/kill-switch state, or scale capital automatically.
* Stage 4.4 makes exact execution scope a required capital-scaling source. The
  canonical v2 evidence window takes its order set from the computed operating
  sample and requires every order to bind either one current clear exact-batch
  reconciliation record or one persisted controlled-session admission whose
  session identity and admission-time window still match. Missing, ambiguous,
  cross-window, stale, source-drifted, orphan, or truncated scope evidence fails
  closed. Historical v1 windows remain append-only audit records but cannot
  satisfy a current scaling review; a new v2 window must be recomputed from
  persisted facts. This evidence cannot issue, renew, resume, or widen capital
  authority and cannot submit or cancel a broker order.
* Per-order and session attestations now also require short-lived,
  artifact-bound Ed25519 approval evidence from a configured operator public
  key. Private keys are not stored by Karkinos, and a verified identity still
  grants no runtime or broker authority.
* Stage 1 can now build a signed promotion dossier that binds 20 clear-
  reconciled read-only trading days, complete daily runbook phases, recovery
  drills, current Account Truth evidence, and explicit owner assertions. This
  is readiness evidence only. Stage 2 now binds its exact current source and
  verified acceptance into every per-order dossier, but no submission path is
  enabled.
* The target product ends at human-supervised controlled execution. Unattended,
  permanently authorized, full-account real-money automation is a non-goal.

## Documentation Map

* [ROADMAP.md](ROADMAP.md): versioned milestones, status summary, acceptance
  criteria, and future candidate milestones.
* [ROADMAP.zh.md](ROADMAP.zh.md): Chinese roadmap summary, automation maturity
  ladder, and documentation cleanup guidance.
* [ARCHITECTURE.md](ARCHITECTURE.md): layered architecture, authority
  boundaries, automation maturity, and controlled broker-bridge requirements.
* [CONTROLLED_EXECUTION_PLAN.md](CONTROLLED_EXECUTION_PLAN.md): staged
  implementation plan for capital authority, read-only broker soak, per-order
  live bridge, bounded sessions, and evidence-based scaling.
* [broker-order-lifecycle-ingestion.zh.md](broker-order-lifecycle-ingestion.zh.md):
  canonical broker-neutral lifecycle evidence and explicit collector-ingestion
  boundary, including deterministic restart and ordering rules.
* [qmt-order-lifecycle-import.zh.md](qmt-order-lifecycle-import.zh.md): retired
  QMT v1 schema compatibility notice and explicit offline migration entry; it
  is not a broker adapter or support statement.
* [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md): historical implementation
  progress moved out of the strategic goal page.
* [BENCHMARKS.md](BENCHMARKS.md): external project notes and architectural
  ideas Karkinos may learn from without copying code.
* [README.md](../README.md): current implemented behavior and user/developer
  usage guidance.
* [README.zh.md](README.zh.md) and [README.en.md](README.en.md): detailed
  current implementation documentation.
* [account-truth-import.zh.md](account-truth-import.zh.md): canonical broker
  statement CSV format, safe examples, import preview, privacy boundary, and
  reconciliation workflow.
* [config-reference.zh.md](config-reference.zh.md): local `config.json`
  field reference, broker fee schedule semantics, and privacy boundary.
* [return-accounting.zh.md](return-accounting.zh.md): portfolio return,
  cost-basis, cash-flow, and baseline-price semantics.

## Safety / Non-Investment-Advice Boundary

Karkinos does not promise profit and should never be treated as the sole basis
for investment decisions.

"Can make money" means the system can operate strategies whose after-cost
evidence remains acceptable under live execution, while measuring slippage,
capacity, drawdown, and operational failures. It is an evaluation objective,
not a return guarantee.

All dashboards, backtests, scores, reconciliation reports, signals, action
queues, paper/shadow runs, and gateway previews are evidence for human review.
They can improve discipline by making data, costs, account facts, risk gates,
execution assumptions, and decision history explicit, but they do not authorize
broker orders by themselves.
