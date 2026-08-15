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
The dedicated confirmed-fund-NAV command rejects estimates and previous-day
NAV, binds one caller request id to the exact symbol scope, and uses the unique
audit run identity as its restart-safe idempotency boundary. Replaying that id
returns the persisted run without contacting a provider or publishing another
snapshot; reusing it with different input fails closed.

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

Strategy extensions use typed metadata and parameters; Web-triggered arbitrary code is outside the contract, and research cannot bypass risk, journal, paper/shadow, or manual-confirmation gates.

The optional after-close service admits one run per market date: persisted bars plus complete valuation/ledger identity -> refreshed baseline/content-hashed dataset -> atomic capped call/token reservations -> DeepSeek Formula DSL hypotheses over the saved backtest and a sanitized persisted account allowlist (position count, cash ratio, drawdown, quote/valuation status, symbol/asset-class weights, risks, next-step) -> local validation and canonical after-cost rolling OOS -> evidence critique -> persisted candidate -> exact human-only canonical `paper_shadow` promotion. Stable identities make replay idempotent; policy and Kill Switch are rechecked before stages. Absolute account values, quantities, prices, costs, valuation/ledger identifiers, credentials, trade plans, and broker capabilities are never exported; approval cannot mutate StrategyRegistry, production assignment, OMS, ledger, risk, or broker state. `karkinos.strategy_advancement_gate.v2` hashes the exact ordered timestamp/OHLCV rows, aligns candidate and reviewed-baseline OOS folds, runs a bounded locally bound Formula parameter grid, partitions frozen market states, and requires non-worsening drawdown/turnover, passing daily-bar capacity/liquidity, account-specific broker-reconciled fee/tax evidence, positive after-tax excess, and critique. It also requires a fingerprinted `research_account_capital_constraint`: the research selection must bind the same complete valuation snapshot and ledger cutoff as the captured canonical Account State, the fee review must still bind reconciled Account Truth, and `initial_cash` must not exceed current account equity. The artifact redacts current cash, positions, and equity; passing it grants no capital or execution authority. Unbound or oversized selections fail before provider export. The built-in cost model is an estimate and cannot satisfy the account-specific fee gate. A caller-computed gate fingerprint is integrity evidence, not source authentication: direct generic promotion is therefore blocked, and only the persisted evidence-owned candidate approval path may advance. That path additionally requires a non-empty human reviewer and the exact paper/shadow-only confirmation. The Web reads the canonical promotion state; pause/revoke requires an explicit reason plus the exact safety confirmation and preserves audit history, while re-entry requires a fresh review note plus the exact paper/shadow-only confirmation. Nested evidence fingerprints are recomputed; reserved strategy promotion and every ticket re-resolve the exact candidate, source backtests, critique, human approval, and paper-shadow state. Any non-AI legacy generic promotion state is explicitly ineligible as per-order evidence. Reconciliation persists exact-identity plan/paper/imported-actual quantities, prices, and costs; a reserved strategy's next batch stays blocked unless that comparison is a drift-free pass. Any gap produces named `research_blocked`/no-action evidence, and no gate, approval, ticket, or comparison grants execution or capital authority. Account-specific cost resolution is an append-only Account Truth sub-protocol: configured schedule -> provider-free component preview against the exact current persisted import -> fingerprint-bound human approval -> versioned `reviewed_account_fee_schedule` calculator. The review store contains safe terms, aggregate reconciliation results, dates, and source/scope fingerprints, but no broker rows, file names, or private account identifiers. Both baseline and candidate engines resolve the same active reference, including exchange-specific terms and component rounding. Critique, promotion, and tickets recheck the active review and the action date; revocation, source drift, tampering, or missing coverage fails closed. GET is zero-write, and neither approval nor revocation touches StrategyRegistry, OMS, broker, or capital authority.

### Daily decision

```text
portfolio + market + strategies + account evidence
-> candidate actions and target weights
-> batch construction and costs
-> risk gate
-> buy / sell / hold / rebalance / no-action / review-required
```

Every public action includes evidence and blockers. A no-action result is a first-class outcome, not an error or empty response. `karkinos.strategy_order_generation_gate.v1` makes order generation two-stage: current evidence-owned promotion and reviewed fees permit only `paper_shadow_required`; a manual ticket also requires the same-date persisted run to bind the exact action, fingerprint, simulated order, and `within_expectations` result. The write edge rechecks Account Truth, market, risk, Kill Switch, and strategy/shadow bindings; missing legacy promotion is never grandfathered. `karkinos.daily_decision_evidence_automation.v3` is the canonical no-caller-facts production run and resolves only a fully bound manual-ticket candidate or `no_action`; it directly requires same-market-date Account Truth promotion evidence and a current persisted closure for every prior non-simulation OMS order, including replay of any exact plan/paper/actual source. Its background caller is read-gated by the persisted official SSE calendar and an exclusive 09:35-09:45 Asia/Shanghai decision window, then atomically claims one separate fail-closed attempt record per market date before reading the plan. A stale plan, failure, interruption, or restart cannot reopen that automatic attempt. `karkinos.daily_candidate_trial.v1` reads the complete persisted run history and counts only verified-calendar days with one fingerprint and exact paper/shadow replay in the newest frozen strategy-and-reviewed-fee epoch; prior epochs are superseded rather than merged, including when an old binding returns. Its 20-day / 50-order threshold enables only a fingerprint-bound human GO/NO-GO review, never a ticket, execution/capital authority, or profitability claim.
The production gate and trial replay both verify that the final Decision, plan, and persisted run start are inside the reviewed window. Summary and per-intent quote timestamps must precede the Decision by no more than 300 seconds; Account Truth capture must also precede the Decision and its derived age must remain inside the reviewed maximum. `karkinos.daily_candidate_input_identity.v2` ignores only non-authoritative current-age counter drift while binding production blockers, sanitized risk-failure identity, frozen strategy replay, exact paper/shadow result, and prior-execution closure. The trial recomputes that identity and the derived quote and Account Truth ages, so same-day source or outcome drift creates conflict evidence instead of overwriting an earlier result. For each intent, the final Decision's canonical order-generation gate is also reduced to a fingerprinted safe binding shared by the daily snapshot and ticket: strategy advancement, reviewed fee schedule, comparison, human approval, frozen baseline/candidate dataset identities, and persisted-only dataset replay. A separate privacy-minimized Account Truth binding shares only its source fingerprint, capture/derived-age limit, valuation snapshot, ledger cutoff, reconciliation, coverage, and non-authority boundaries; it contains no account identity or balances. Each atomically claimed background attempt also persists one bounded operator alert for NO-ACTION, read-only ticket review, interruption, or fail-closed failure; configured notification receives at most eight named NO-ACTION blockers and times out after ten seconds. Alert or notification failure is recorded only by sanitized status/error type and cannot reopen the attempt or affect OMS, broker, ledger, or capital authority. Any nested boundary or binding mismatch prevents ticket emission, and a latest excluded day prevents an otherwise mature trial from opening a GO review.

### Paper/shadow operations

```text
daily plan
-> deterministic paper/shadow run
-> simulated OMS orders and fills
-> costs and divergence
-> operator review and alerts
```

Paper/shadow facts never become real fills or ledger mutations. Operations owns run identity, retry, status, limitations, and recovery tasks. `POST /api/trading/shadow-runs/daily` is a compatibility alias over canonical Decision -> Plan -> Paper and rejects caller-owned `base_equity`.

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
quantity, and schema conflicts fail closed. `karkinos.account_truth.evidence_scope.v1` separates the observed event span from reviewed account, date-window, and asset-scope completeness; observed first/last rows alone never prove full coverage. An explicit owner action may append an exact-import, privacy-hashed account-reference review, and a later revocation or source drift blocks it again. `karkinos.account_truth.evidence_readiness.v2` combines that scope with the canonical score and sanitized incomplete-source follow-up without financial recomputation, provider contact, read-side writes, reconciliation eligibility, or execution/capital authority; missing or unreadable persisted evidence fails closed.

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

Trading exposes the same decision as a default-collapsed signed journey: one dossier binds the exact manifest, latest conformance, current review,
decision/reason/time, and short-lived approval. Its approval id enters the
review fingerprint; drift fails closed, while reject/revoke remain safety-only
and the journey cannot select, register, or contact a broker.

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
Trading projects that same persisted-only status as five operator-readable
gates: qualified days, daily phases, recovery drills, Account Truth binding,
and signed owner acceptance. Ambiguous connector identity fails closed, and the
panel exposes no registration, promotion, submission, or cancellation action.

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

Decision exposes a separately opened signed revocation journey for a persisted
runtime session. The operator selects an allowlisted reason, reviews the exact
session/reservation fingerprint, signs a three-minute Ed25519 challenge outside
Karkinos, and confirms the one-way revocation. The command reuses the canonical
runtime-authority transaction and cannot auto-resume, renew, widen, submit, or
cancel. Revocation closes future runtime admission only; it never claims that an
open broker order was cancelled, so lifecycle collection and reconciliation
remain separate mandatory work.

`karkinos.current_per_order_confirmation_dossier.v1` is the read-only operator
entry boundary before any controlled intent exists. It selects only canonical
`manually_confirmed` OMS orders, scans append-only capital evaluations newest
first, binds the exact OMS order fingerprint, and requires exactly one valid
same-strategy prior-batch reconciliation reference and one gateway-verification reference.
It never falls back from a newer matching blocked evaluation to an older pass;
missing, malformed, ambiguous, or bounded-scan-incomplete evidence remains
blocked. The resolved references feed the existing canonical per-order dossier,
whose v5 fingerprint also binds the newest persisted adapter release matching
the exact evidence-connector, execution-gateway, and account scope. That release
must still be human-accepted, conformance-clear, blocker-free, and attached to a
recorded read-only collector run. Missing evidence, revocation, conformance or
manifest drift, scope mismatch, and unsafe projection boundaries all fail
closed and invalidate an earlier signature. V5 additionally treats the four
OMS gateway-gate references as typed identities rather than labels: the exact
Account Truth import, Decision action, risk decision, and paper/shadow run must
resolve from persisted facts, appear in the same capital evaluation, and match
the order symbol, side, strategy, quantity, and limit price where applicable.
The paper/shadow run must contain exactly one clear simulated order for the same
Decision action. A missing provider-free Account Truth projection, forged ref,
or source drift is a review and hard-submission blocker. Before legacy manual-
ticket preview/export/create or manual-execution preview/record, the latest signed
per-order confirmation is re-resolved against current capital, Account Truth,
Decision action, risk, paper/shadow, adapter, soak, gateway, and prior-batch
reconciliation; confirmation, dossier, and four source fingerprints bind every result.
Missing, blocked, or drifted sources fail closed; all previews stay provider-free,
state-free, non-authorizing evidence, and Trading exposes no submit/cancel control.

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

`karkinos.operations_today.v1` also derives one versioned attention item for
each non-pass/non-skipped subsystem. The item fingerprints the source status,
next action, and evidence-based resolution condition while excluding
request-generated timestamps. A refresh with unchanged evidence reproduces the
fingerprint; evidence-status drift changes it. Viewing or acknowledging an item never clears it. The same
read-only payload may enter an explicit AI context capture, but it performs no
provider contact or database write and grants no execution authority. Canonical broker-evidence and reconciliation-review repositories open existing SQLite read-only for queries: construction and GET/list never initialize or migrate schema, absent tables mean no evidence, partial/incompatible schema or invalid records fail closed without repair, and only explicit import/review commands own schema creation or migration. Reviewed incomplete CITIC history exports remain a separate privacy-minimized, non-canonical source store with the same read boundary, and `karkinos.account_truth.citic_source_follow_up.v1` projects only sanitized persisted metadata as an additional Operations attention item outside canonical health. `karkinos.account_truth.citic_history_xls_batch_assessment.v1` checks source-set duplicate and event-identity integrity in memory, but observed event months never establish reviewed query-window coverage; the assessment stays blocked, event-free, non-persisting, and ineligible for Account Truth or reconciliation. `karkinos.account_truth.citic_history_canonical_lineage_assessment.v1` separately compares the runtime XLS batch with the currently selected canonical import using exact financial semantics, broker-order identity, and event identity, then returns only sanitized counts and fingerprints. Semantic similarity without preserved identity is partial evidence rather than canonical provenance; even exact event lineage cannot prove query-window, settlement, snapshot, or full-account completeness. The comparison persists nothing, returns no event/source details, and cannot promote evidence or alter Account Truth, reconciliation, execution, or capital authority. `karkinos.account_truth.citic_source_query_window_review.v1` is a separate append-only, revocable source-level attestation bound to the current file and sanitized-preview fingerprints: it validates a maximum 31-day broker query window against recognized event dates, stores no source or transaction detail, and clears only the source query-window sub-requirement. It never proves canonical coverage, binds an account, promotes events, satisfies settlement/snapshot/reconciliation gates, contacts a provider, or grants execution/capital authority. Rejection closes only the source task; it does not satisfy Account Truth or change reconciliation, risk, execution, or capital authority. Configured-directory scans may expose only one sanitized `YYYY-MM` token derived from an unambiguous local `YYYYMM` filename token to help the owner identify an exact source. The hint is runtime-only, excluded from evidence fingerprints and persistence, never prefills or proves a query window, and an absent or ambiguous hint disables directory-mode source decisions so the owner must select the exact file in the browser. `karkinos.account_truth.citic_broker_soak_candidate.v1` separately proves that a history-trade preview is not a versioned connector snapshot, enumerates the missing read-only source contract and operational prerequisites, and remains permanently ineligible for soak without registering a connector, persisting soak evidence, contacting a broker, or changing execution/capital authority.
`karkinos.account_truth.citic_source_scope_review.v2` binds the exact source/window and privacy-minimized account reference to account type, market, asset, account-value-band, business, filter, and result-completeness declarations. The value band is fingerprinted query-scope metadata only, never a balance fact, order limit, or capital authorization; legacy v1 rows remain readable but incomplete until append-only replacement. The review cannot prove canonical coverage, promote events, satisfy settlement/snapshot/reconciliation gates, contact a provider, or grant execution/capital authority.
The promotion evidence consumed by controlled execution also binds the sanitized CITIC follow-up fingerprint and reviewed query-window integrity: pending, truncated, unreadable, gapped, or overlapping source review can only downgrade clear to blocked, while completing or rejecting review never creates canonical account facts or independently opens execution.
The `/operations` workbench is the read-side operator surface for this contract and for `karkinos.controlled_per_order_pilot_readiness.v1`, the optional real-pilot admission projection over persisted adapter, signed-soak, expiring-write-release, and controlled-order evidence.
Its six fail-closed gates require safe source contracts, exactly one observing read-only release, matching signed soak, exactly one active `manual_each_order` write release, one coherent provider/gateway/account/connector scope, and no unresolved order journey or active session authority.
Source failure, ambiguity, drift, truncation, or authorizing read-side flags block admission; a pass permits only the separate exact-order review and does not complete v1.8, replace per-order evidence, contact a provider, write the database, submit/cancel, mutate financial facts, or change capital authority.
Contract-safe unmet optional prerequisites stay compact and neutral outside canonical Operations health, while a read-only or non-authority contract violation opens immediately as danger.
The workbench validates top-level and attention-item non-authority flags before drill-down, shows source evidence, deterministic fingerprint, safe next action, and exact resolution condition, and has no mutation or broker capability.

An open exact-identity lifecycle may be projected through
`karkinos.manual_broker_cancellation_ticket.v1`. This provider-neutral boundary
prepares a copyable human action package from the persisted controlled intent,
OMS order fingerprint, broker/client order ids, and latest lifecycle
observation. Export re-runs the preview and rejects a stale fingerprint. It
does not register or call an adapter, issue a cancellation, mutate OMS/ledger,
or change risk, kill switch, interlock, or capital authority. The operator must
act in a separately reviewed broker interface; only a newer ingested lifecycle
observation plus Account Truth/reconciliation evidence can prove cancellation.
The generic broker-gateway live-cancel endpoint remains disabled, so this
package is not an execution command or a claim of provider support.

M2 explicit cancellation is a separate
`karkinos.controlled_broker_cancellation.v1` command. It reuses the exact manual
ticket identity, then additionally binds the current signed release, cached
gateway-health fingerprint, and short-lived
`cancel_exact_controlled_broker_order` proof. A dedicated SQLite
`BEGIN IMMEDIATE` claim admits at most one external cancel effect for an intent;
exact duplicate, concurrency, and restart replay cannot call cancel twice.
`prepared`, `cancel_requested`, `cancel_rejected`, and
`cancellation_unknown` are command-audit states, never canonical broker facts.
The separately signed `karkinos.controlled_broker_cancellation_recovery.v1`
waits deterministically and may only query the exact client order id; it cannot
re-cancel. Neither gateway response mutates lifecycle, OMS, ledger, risk, kill
switch, interlock, or capital authority. Only newer explicit lifecycle
ingestion and reconciliation prove the outcome. The production factory remains
default-closed without an explicitly reviewed gateway/release, and no real
adapter support is implied.

M2 execution-edge semantics have a separate offline contract:
`karkinos.broker_execution_edge_manifest.v1` and
`karkinos.broker_execution_edge_conformance_result.v1`. The fixed local suite
exercises default-closed capability declaration, dry-run, exact and concurrent
idempotent submission, timeout/unknown query-only recovery, restart, explicit
cancel identity, duplicate cancel, partial-fill/cancel race, not-found, and
disconnect behavior. It creates only append-only conformance evidence and
cannot register an adapter or clear a real-provider gate. The suite validates
the Karkinos harness, not a third-party implementation; real adapter acceptance
still requires a separately approved runner, ADR/threat review, and deployment
authorization.

Enabling that edge requires a distinct
`karkinos.controlled_broker_write_release.v1` capability release. Its signed
dossier binds the exact provider/gateway/account scope to the newest strict
execution-edge manifest and clear conformance result, the newest exact-scope accepted
read-only adapter release, the exact signed soak-promotion acceptance, and
seven owner-reviewed agreement, account-permission, reporting, acceptance-test,
deployment, risk-control, and rollback references. A release lasts at most 12
hours, permits only `manual_each_order`, and can be revoked once with a separate
offline signature. Expiry, revocation, trusted-key rotation/disable, or any
source drift makes resolution fail closed.

Production submission and cancellation factories resolve only an active
persisted release (unless an explicit test/integration provider is injected),
then independently recheck their existing order-specific proof, gateway health,
claim, risk, and lifecycle gates. The release is necessary but never sufficient:
it registers no adapter, contacts no provider, creates no order, mutates no
financial fact, and grants neither order nor capital authority. Status reads do
not create release tables or refresh upstream evidence.

Trading projects this boundary as a default-collapsed operator review. Opening it reads
persisted status, validates a reviewed credential-free manifest and seven owner references,
then reuses the three-minute offline-signature flow to issue or revoke; the browser blocks
sensitive manifest keys before POST and exposes no submit, cancel, registration, or capital action.

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

### Evidence-bound post-decision review and learning queue

`karkinos.decision_outcome_review.v1` is the canonical human disposition of one persisted signal outcome. Preview binds the exact signal/action/risk chain,
signal-specific order/fill references, and symbol-scoped canonical contribution.
Its target fingerprint includes valuation snapshot, ledger cutoff, contribution,
and execution evidence; operator-supplied P/L is rejected and never recalculated.

Recording requires an idempotency key, exact preview fingerprint, allowlisted
human decision/outcome, reviewer, note, and explicit no-authority confirmation.
Acted conclusions require linked fills and fully bound contribution; risk-blocked
or unexecuted signals retain process outcomes. Any source drift rejects a new
confirmation and makes a prior review non-current without deleting it.

The stored review, event hash chain, and shared signal-journal event are appended
in one transaction. Replay verifies the chain plus exact request fingerprint,
target identity, review identity, signal, reviewer, decision, outcome, note, and
timestamp bindings. Corrupt JSON or row/event mismatch fails closed. Legacy
`signal_reviews` remain historical evidence, not the canonical write contract.

`karkinos.strategy_learning_review.v1` is a read-only projection of the latest
persisted human review per signal; unreviewed signals are explicitly outside its
classification. Every read replays that review and rebuilds the current canonical
target. Audit failure becomes a critical integrity repair; target drift requires
re-preview; unsupported evidence creates only a copyable question for separately
human-started capture and research. No private review note enters the queue.

The queue contacts no provider, writes no database, recalculates no financial fact, invokes no AI, creates no memory, changes no strategy, and grants no OMS,
broker, execution, or capital authority.

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
