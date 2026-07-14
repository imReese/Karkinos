# Karkinos Roadmap

[中文路线图](ROADMAP.zh.md) | [Architecture](ARCHITECTURE.md) | [Goal](KARKINOS_GOAL.md)

This file owns versioned roadmap planning and acceptance criteria. It is not a
user manual; current usage guidance belongs in the README files.

## Status Summary

| Milestone | Status | Capability |
| --- | --- | --- |
| v0.2 | Completed | Profit Discipline MVP |
| v0.3 | Completed | Daily + Intraday Decision Platform |
| v0.4 | Completed | Strategy Lab Backtesting Engine |
| v0.5 | Completed | Quant Research Quality & Production Evidence Hardening |
| v0.6 | Completed | Account Truth & Reconciliation Engine |
| v0.7 | Completed | Account Truth Review Center |
| v0.8 | Completed | Strategy Assignment & Attribution Engine |
| v0.9 | Completed | Data Plane & Market Reliability |
| v1.0 | Completed | Strategy Runtime Foundation |
| v1.1 | Completed | Paper Broker & OMS |
| v1.2 | Completed | Broker Evidence Connector |
| v1.3 | Completed | Professional Decision Workflow |
| v1.4 | Completed | Strategy Attribution 2.0 + Broker Fee & Cost Basis Fidelity |
| v1.5 | Completed | Daily Trading Plan & Portfolio Construction |
| v1.6 | Completed | Operations Center & Paper/Shadow Runbook |
| v1.7 | Completed | Controlled Broker Bridge Foundation (Non-Submitting) |
| v1.8 | Planning active | Capital-Bounded Controlled Execution |
| AI-native Phase 1 | Foundation implemented | Provider-neutral, evidence-bound research workflow runtime |
| AI-native Phase 1.1 | Read boundary implemented | Immutable canonical-evidence captures and context-bound read executors |
| AI-native Phase 1.2 | Capture boundary implemented | Explicit human-started, model-free canonical context capture |
| AI-native Phase 1.3 | Task/review boundary implemented | Human-created evidence-bound tasks, review UI, and hash-chain replay with model execution off |
| AI-native Phase 1.4 | Offline fixture lifecycle implemented | Explicit accepted-task claim/debate/report/memory workflow with drift invalidation and no external model |
| AI-native Phase 1.5 | Human memory disposition implemented | Exact analysis review, recall eligibility, append-only replay, and automatic drift invalidation |

Completion evidence recorded on 2026-07-10: the operations runbook acceptance
audit is 19/19, the controlled broker bridge foundation audit is 15/15, the
backend suite is 859/859, the Web suite is 405/405, and the production build
and frontend format check pass. These checks prove the non-submitting
foundation only; they do not enable L4 broker submission or any v1.8 execution
authority. v1.8 planning and non-submitting policy-contract work may proceed
while all broker-write capabilities remain disabled.

Cross-cutting financial-data reliability hardening completed on 2026-07-12:
persisted observations became the only authoritative read source; content-
addressed valuation v2 freezes confirmed close/NAV, previous-close baselines,
ledger cutoff, and evidence fingerprints; quote/ledger/startup commit boundaries
publish replayable snapshots; unpublished facts fail closed; canonical daily
performance now reconciles Holdings, Equity Curve, Overview, and Explainability;
and historical reconstruction rejects future-price fallback and closed-position
quote contamination. Final validation passed 1,131 backend tests, 36 affected
Web tests, the production Web build, real-account cross-surface invariants, and
snapshot-id replay. This improves evidence reliability only and grants no broker
submission or execution authority.

## AI-Native Research Track

This track improves how a serious investor frames questions, gathers evidence,
tests competing explanations, writes conclusions, and recalls reviewed work. It
does not replace canonical financial calculations or create a parallel trading
authority path.

### Phase 1 — Architecture and Runtime Foundation

Implemented scope:

* provider, model, and agent-role registrations are separate contracts;
* stateful workflows bind one immutable evidence context containing a valuation
  snapshot, ledger cutoff/fingerprint, and persisted evidence references;
* claims, debates, reports, non-executable trade-plan drafts, reviews, and
  memory artifacts are typed and evidence-citing;
* the deterministic orchestrator owns stage order, restart checkpoints,
  idempotency, duplicate handling, partial/failure status, evidence-drift
  blocking, and audit replay;
* the tool permission registry is deny-by-default and permits only registered
  persisted reads or pure computation; authority namespaces are unregistrable;
* the SQLite audit store writes only `ai_*` registry, context, workflow, run,
  tool-call, artifact, and hash-chained event tables;
* the only provider implementation is a deterministic local fixture. No real
  model, network request, API key, or vendor-specific dependency is present.

Phase 1 acceptance requires deterministic coverage for restart, duplicate
execution, stage failure, partial results, evidence drift, unauthorized tool
requests, and audit replay. It also verifies that an AI trade-plan draft cannot
mutate OMS, ledger, risk, kill switch, capital-authority, broker submission, or
cancellation state.

Phase 1.1 implements the storage and read side of the first migration step:

* an explicit caller can persist a content-addressed copy of an already-built
  canonical projection without asking the AI runtime to recalculate it;
* Portfolio, Account State, Operations, Research Evidence, Account Truth, and
  paper/shadow read tools resolve only references in the frozen context;
* all records share one exact valuation snapshot, ledger cutoff, and ledger
  fingerprint, or context assembly fails closed;
* duplicate capture is idempotent, changed content gets a new reference, and
  restart reads the same SQLite evidence row;
* incomplete, stale, estimated, or unreconciled records remain explicit and
  non-authoritative;
* no scheduler hook, real provider, or external model call is registered.

Phase 1.2 connects that storage boundary to production canonical reads without
starting an AI workflow:

* `POST /api/ai/research-contexts/capture` requires an explicit acknowledgement,
  operator label, research question, idempotency key, account alias, and exact
  evidence selection;
* Portfolio and Account State share one canonical Portfolio snapshot;
  Operations reuses its existing persisted-fact builder, while Research
  Evidence and paper/shadow require exact persisted record ids;
* the selected valuation snapshot must already be persisted and replayable;
  valuation snapshot, ledger cutoff, or ledger fingerprint drift during the
  command blocks the capture;
* restart and duplicate requests restore the same content-addressed evidence
  and context; a changed request cannot reuse an idempotency key, and a failed
  audit stage can retry without duplicating evidence;
* the command writes only `ai_canonical_evidence`, `ai_context_snapshots`, and
  `ai_context_capture_runs` plus existing AI schema initialization. It does not
  call a provider or model, start a workflow, refresh market/broker data, or
  mutate account, execution, risk, reconciliation, or authority state.

Phase 1.3 records human research intent and context review without enabling
analysis execution:

* `POST /api/ai/research-tasks` accepts only a completed Phase 1.2 capture and
  replays its context/evidence identity before creating an audit task;
* tasks bind exact valuation snapshot, ledger cutoff/fingerprint, context
  fingerprint, and immutable evidence summaries; non-authoritative evidence is
  retained but sets `blocked_by_evidence`;
* human reviews can accept a complete context, request evidence revision, or
  close without analysis. Acceptance is rejected for incomplete evidence and
  never starts a workflow or model;
* task creation and review are independently idempotent, and task/review events
  form a replayable per-task SHA-256 chain;
* the Strategy Lab boundary is idle until a human opens it, performs no polling,
  and records context capture before task creation. Saved backtest evidence is
  optional and requires the exact result id; task GETs do not initialize schema
  or write audit facts;
* only `ai_research_tasks`, `ai_research_task_reviews`, and
  `ai_research_task_events` are added. No provider/model registration, model
  call, scheduler, background task, OMS/ledger/risk/capital write, broker
  submit, or cancel capability is introduced.

Phase 1.4 exercises the provider-neutral runtime through an explicit offline
fixture lifecycle without presenting it as model intelligence:

* only a task in `context_accepted` with complete authoritative evidence may
  cross `POST /api/ai/research-tasks/{task_id}/fixture-analyses`, and an exact
  acknowledgement plus human operator label is required;
* the deterministic fixture reads every bound evidence reference through the
  deny-by-default canonical tool boundary, then persists cited claim, debate,
  report, and human-review-required memory artifacts in fixed stage order;
* the task/context/valuation/ledger identities are rechecked before execution;
  completed results and memory become explicitly invalid if immutable evidence
  later drifts, and combined task/workflow replay fails closed;
* task-to-workflow mapping and workflow audit facts make restart and exact
  duplicate commands idempotent. GET routes are read-only and do not initialize
  schema, poll, refresh providers, or start background work;
* only the local deterministic fixture provider/model registration is created.
  There is no network request, API key, external-model invocation, provider
  selector, Decision handoff, account-fact status, or OMS/ledger/risk/kill-
  switch/capital/broker authority.

Phase 1.5 adds human disposition and research-memory eligibility without a
Decision or execution handoff:

* `POST /api/ai/research-task-analyses/{analysis_id}/reviews` requires an exact
  acknowledgement, human reviewer, note, and one final decision: accept as
  reviewed memory, request revision, or reject;
* acceptance requires a completed, non-partial, replay-valid workflow with the
  exact claim/debate/report/memory lifecycle, completed evidence tool calls,
  one memory artifact, and matching stored/recomputed artifact fingerprints;
* the immutable review binds an analysis-target fingerprint covering workflow,
  context, valuation/ledger-bound evidence status, artifact identities, tool
  calls, memory sources, and workflow audit evidence. Its own event is stored
  in a SHA-256 chain;
* exact restart and concurrent duplicate commands reuse one review/event.
  Changed input under the same key and a second final decision fail closed;
* every GET and replay rebuilds the target. Later evidence, artifact, context,
  or audit drift preserves the historical decision but changes accepted memory
  to `invalidated_by_evidence_drift` and removes recall eligibility;
* revision and rejection remain recordable for invalid evidence. GET routes do
  not initialize schema, and no automatic memory retrieval, provider/model
  call, Decision input, trade-plan creation, account-fact promotion, financial
  write, or execution authority is introduced.

Planned migration, each behind a separate review:

1. **Completed foundation and reviewed-memory boundary:** immutable storage, identity
   validation, context-bound read executors, explicitly human-started canonical
   capture, human task/review records, and the accepted-task deterministic
   claim/debate/report/memory lifecycle plus exact human disposition and
   drift-sensitive research recall eligibility exist without recomputation,
   GET-side provider refresh, external model invocation, or authority;
2. **Next review:** add an explicit, read-only retrieval policy that can select
   only current `reviewed_memory` artifacts for a future evidence-bound context;
   retrieval must remain off until separately started and must rebind current
   evidence rather than treating memory as fact;
3. separately review and explicitly authorize one or more real provider adapters without
   making any vendor canonical;
4. consider a one-way, human-reviewed handoff from a trade-plan draft into the
   existing Decision workflow. Existing account-truth, risk, paper/shadow,
   manual confirmation, capital, OMS, gateway, reconciliation, and kill-switch
   gates remain authoritative.

## Automation Maturity Track

Karkinos is moving toward a professional automated-quant workflow whose purpose
is to improve after-cost trading outcomes. The edge should come from better
data, better validation, better risk control, better execution discipline, and
better review. Broker submission is an execution capability, not the source of
edge, so it must mature after the decision, simulation, and reconciliation
layers are reliable.

For the full architecture, see [ARCHITECTURE.md](ARCHITECTURE.md).

The intended maturity ladder is:

| Level | Status | Meaning |
| --- | --- | --- |
| L0 Research evidence | Completed | Registered strategies, reproducible backtests, after-cost/OOS evidence, and promotion readiness exist. |
| L1 Daily trading plan | Completed | The system generates a daily plan with candidates, blockers, costs, risks, and manual-confirmation next steps. |
| L2 Paper/shadow operating loop | Completed | Scheduled paper/shadow runs, divergence checks, persisted review state, and run summaries operate without manual data edits. |
| L3 Manual execution assist | Completed | OMS, manual tickets, broker evidence import, manual-execution evidence, and execution reconciliation support safe operator-driven execution paths. |
| L4 Controlled broker bridge | Planned | Broker-specific order previews or submissions may be prepared only after account truth, risk, paper/shadow, and manual review gates pass. |
| L5 Capital-bounded controlled execution | Planning active | Start with a deliberately small live risk envelope, then allow human-reviewed evidence-based scaling without granting permanent or self-expanding authority. |
| L6 Unattended full-account automation | Non-goal | Permanently authorized, unsupervised real-money execution is not required for the Karkinos product target. |

The completed v1.6-v1.7 foundation is not "auto-buy" or "auto-sell". It is a
repeatable paper/shadow execution loop, auditable OMS state, a controlled
non-submitting order-ticket bridge, local read-only connector evidence, and
execution reconciliation. Real broker submission remains an unimplemented
future capability behind explicit account, strategy, symbol, order, risk,
account-truth, paper/shadow, kill-switch, connector-health, reconciliation, and
operator-authority gates. v1.8 planning is active, but its broker-write and
automation capabilities are not implemented or enabled.

## Automation Gap Matrix

This matrix records what remains between the current product and a safe
automated-quant platform. It is intentionally stricter than "can generate a
signal" because live-like automation is only credible when execution, risk,
account truth, paper/shadow, monitoring, and audit all agree.

| Capability | Current state | Required before live-like automation | Roadmap owner |
| --- | --- | --- | --- |
| Strategy research and validation | Backtests, sweeps, research evidence bundles, after-cost/OOS evidence, and promotion readiness exist. | Promotion decisions must continue to consume account truth, risk, attribution, and paper/shadow evidence before strategy candidates are treated as operational. | v0.4-v1.0, ongoing |
| Daily decision and trading plan | Decision APIs, candidate pool, blockers, batch pre-trade risk, daily trading plan, order intents, Today's to-dos, and automatic paper/shadow handoff exist. | Continue requiring public explanations for every blocked/manual-ready state and keep order intents non-submitting. | v1.5-v1.6, ongoing |
| Paper/shadow execution | Persisted daily runs include deterministic inputs, simulated order/fill state, fees/taxes, divergence, retry/idempotency, and review outcomes. | Keep evidence fresh and require divergence review before any later live-like authority. | v1.6.1, ongoing |
| OMS state machine | Paper/shadow lifecycle states plus one-shot submission evidence, deterministic client order ids, atomic intent persistence, controlled-intent reconciliation, and signed exact-full-fill `submitted -> accepted -> filled` clearance now exist. Stage 3.15 also projects explicitly imported broker-neutral open/partial/cancel/full lifecycle facts without mutating OMS. | Any reviewed real adapter still needs broker-order-linked callback/poll evidence and operational soak; partial/cancel or unhealthy collector facts cannot clear, and ledger application remains separate. | v1.6.1, Stage 3.12-3.18, future L4 |
| Broker execution gateway | Manual-ticket/read-only evidence remains available; one-shot submit/query is injectable, the cross-order interlock is atomic, a separately signed clearance can consume one identity-linked validated full-fill import, and the generic lifecycle/collector contracts fail closed on sequence, identity, deployment, and quantity drift. Production registers no collector, provider adapter, write adapter, or release provider by default. | Independently review an explicitly user-authorized provider adapter and its operational soak before any broker-specific write adapter/release source or pilot. Generic local JSON is evidence plumbing, not production connectivity or provider support. | v1.7, Stage 3.12-3.16, future L4 |
| Order ticket export | Copy-safe ticket export, operator forms, manual-execution preview/evidence, and explicit links to broker-statement import and execution reconciliation exist. | Validate operator ergonomics with local workflows before considering any broker-write capability. | v1.7, ongoing |
| Account truth and broker reconciliation | CSV import, staged broker evidence, account reconciliation, execution reconciliation, and manual-versus-broker price/cost/net comparison exist without automatic ledger mutation. | Future automation must require fresh account truth and block stale, mismatched, or unresolved execution evidence. | v0.6-v0.7, v1.7, ongoing |
| Risk controls | Mandatory pre-trade risk gate, batch risk checks, cash buffer, concentration, T+1, data-quality, and kill-switch concepts exist. | Live-like execution must enforce global, strategy, account, and per-symbol controls with policy snapshots, escalation notes, and irreversible audit logs. | v1.5-v1.7 |
| Scheduler and runbook | Operations summary, persistent scheduler records, deterministic rerun keys, input snapshots, errors, retries, limitations, and operator review state exist. | Continue operational soak and preserve idempotency as scheduled workflows expand. | v1.6, ongoing |
| Monitoring and alerting | Risk/operations surfaces show status and next actions; automation alerts cover kill switch, execution-reconciliation gaps, failed paper/shadow automation runs, persisted broker-lifecycle collector evidence, daily-plan risk blockers, stale market-data snapshots, Account Truth mismatch snapshots, and paper/shadow divergence. Controlled-execution operator visibility projects bounded capital, headroom, expiry, order/reconciliation, live-gate, pause, and blocker facts from the database only. | Keep all broker evidence refresh behind explicit ingestion. Before any real-provider use, separately review and authorize the chosen default-unregistered edge adapter; GET and alert paths must never poll it implicitly. | v1.6-v1.8, Stage 3.19 |
| Strategy promotion pipeline | Research/paper lifecycle, readiness evidence, audit-only pause/retire states, and default rejection of controlled-bridge pilot promotion exist. | A future L4/L5 pilot must add explicit enablement without allowing promotion evidence to authorize execution by itself. | v1.6-v1.7, future L4-L5 |
| Capital-bounded controlled execution | The control plane includes signed expiring authority, atomic budgets, token-authenticated sessions, live gates, pause/replacement, evidence-based scale review, a one-order submit boundary, a cross-order interlock, signed full-fill clearance, and persisted broker-neutral lifecycle evidence that can only narrow or re-block authority. | Supply a reviewed real adapter/release source, prove partial-fill/cancel/reconciliation and ledger runbooks, then run an explicitly approved bounded pilot. Initial exposure is deliberately constrained; later scale remains evidence-reviewed. | v1.8, Stage 3.12-3.16 |
| Unattended full-account automation | Not supported. | Keep permanently authorized, unsupervised execution outside the product target. | Non-goal |

## Controlled Automation Architecture

The controlled-automation track is the bridge between the current
paper/shadow foundation and any future broker-connected workflow. It is not a
single "turn on auto trading" feature. It is a layered operating architecture
with separate authority boundaries:

```text
strategy promotion
-> automation orchestrator
-> risk and permission gate
-> OMS core
-> broker gateway abstraction
-> execution reconciliation
-> monitoring, alerts, and audit
```

The default product mode remains manual confirmation. Broker submission must
stay disabled unless a future controlled bridge is explicitly configured,
audited, and gated.

Recommended implementation phases:

| Phase | Target | Default broker behavior |
| --- | --- | --- |
| A | Controlled automation skeleton: policies, run records, automation status, and Today's to-dos integration. | No broker gateway. |
| B | OMS foundation: canonical order lifecycle, transitions, idempotency, and paper/shadow/manual-ticket modes. | No broker submission. |
| C | Broker gateway abstraction: dry-run adapter, manual-ticket export, capability checks, and connector health. | Dry-run or export only. |
| D | Execution reconciliation: compare OMS/order/fill facts with broker evidence and Account Truth. | No automatic ledger mutation. |
| E | Strategy promotion pipeline: research, paper, shadow, manual-confirmation, bridge-pilot, paused, retired. | Promotion does not authorize execution by itself. |
| F | Future controlled live bridge: explicit account enablement, kill switch, connector capability check, and per-order confirmation. | Disabled by default. |
| G | Capital-bounded controlled execution: start with small pilot exposure, use expiring operator authority, enforce hard stops and reconciliation-before-next-run, then scale only through reviewed evidence. | Explicit opt-in only; no automatic scale-up. |

Key new contracts should include:

* `automation_policies` for global/account/strategy/symbol/execution-mode
  controls.
* `automation_runs` for scheduled or operator-triggered run records.
* `oms_orders` and `oms_transitions` for the production order lifecycle.
* `broker_gateway_configs` and `broker_gateway_health` for connector
  capability state.
* `execution_reconciliation_runs` and `execution_reconciliation_items` for
  order/fill/cash/position agreement.
* `strategy_promotion_states` for strategy lifecycle gates.
* `capital_authorization_policies` and immutable authorization decisions for
  future per-order or session-bounded execution; the initial live tier is small
  exposure, not a permanent account-size ceiling.

The first user-visible ladder should be:

```text
Today's plan is ready
-> risk has passed or blocked
-> paper/shadow simulation has run
-> divergence is clear or needs review
-> manual confirmation can continue, or execution remains blocked
-> reconciliation confirms or flags account differences
```

## v0.2 Completed Summary

Karkinos v0.2 established the first reliable end-to-end workflow:

```text
data fetch/cache
→ feature calculation
→ reproducible backtest
→ after-cost report
→ signal generation
→ mandatory risk gate
→ dashboard/action queue
→ signal journal
→ review
```

### Acceptance Criteria for v0.2

* [x] One reproducible end-to-end workflow: data fetch/cache → features → backtest → report → signal → risk gate → dashboard/journal.
* [x] At least three benchmarkable strategies:

  * [x] ETF rotation / trend-following baseline
  * [x] Defensive allocation baseline: equity ETF + bond/gold/cash proxy
  * [x] A-share/ETF mean-reversion or momentum candidate
* [x] Each strategy has out-of-sample validation and after-cost report.
* [x] Portfolio dashboard exposes target weights, actual weights, drift, action queue, and risk alerts.
* [x] Signal journal stores every generated signal, whether acted on or ignored.
* [x] Pre-trade risk gate is mandatory for every actionable signal.
* [x] Manual-confirm execution path is complete.
* [x] Paper/shadow mode can run daily without manual data edits.
* [x] CI runs backend tests, frontend checks, and at least one deterministic smoke path.
* [x] README and docs make clear that Karkinos is a personal quant research and trading platform, not investment advice.

## v0.3 Completed Summary

Karkinos v0.3 moved the system toward daily and intraday decision review
without enabling default real-money automation.

### Acceptance Criteria for v0.3

* [x] `GET /api/decision/today` returns a daily decision summary.
* [x] `GET /api/decision/intraday` returns an intraday candidate-action view
  for stocks and exchange-traded ETFs.
* [x] Decision summaries aggregate current portfolio state, market/cache
  health, signals, action tasks, risk decisions, and journal evidence.
* [x] Each summary explicitly returns `buy`, `sell`, `hold`, `rebalance`,
  `no_action`, or `review_required`.
* [x] Each candidate action includes an evidence bundle with strategy, signal,
  risk gate, after-cost/OOS validation, data freshness, manual-confirmation
  state, and journal references.
* [x] No-action responses include explicit reasons.
* [x] The frontend decision platform shows daily and intraday candidate actions,
  risk state, evidence, and manual-confirmation entry points.
* [x] Deterministic tests cover data/cache → feature/strategy signal → action
  candidate → risk gate → journal → decision API/dashboard.
* [x] README/docs describe the behavior boundary: research and investment
  platform, not investment advice, and no default automatic real-money trading.

## Target for v0.4

Karkinos v0.4 — Strategy Lab Backtesting Engine — turned the registered-strategy
backtest path into an auditable research platform for China-market personal
investment decisions.

The goal is not to copy a generic quant framework. Karkinos should learn from
established open-source systems while preserving its own platform, audit, and
risk-first boundaries.

### v0.4 Scope

* Strategy authors can write local Python strategy scripts in a dedicated
  extension area without placing strategy code inside `backtest/`.
* Strategy scripts must use an explicit, versioned Karkinos strategy interface
  and metadata contract.
* The system can discover, validate, and list built-in and local extension
  strategies without executing arbitrary untrusted code from the Web UI.
* The Web Backtest page can select a strategy from the registry, render its
  typed parameters, choose one symbol or a configured universe, and run a
  reproducible experiment.
* Backtest requests support generic strategy parameters rather than only fixed
  `short_period` / `long_period` fields.
* Backtest reports include dataset snapshot metadata, strategy metadata,
  parameter values, after-cost metrics, OOS split evidence, known limitations,
  and risk assumptions.
* Parameter sweeps are supported for bounded, typed parameter grids, with
  deterministic result ranking and explicit overfitting warnings.
* Strategy comparison is supported across multiple strategies or parameter
  sets on the same frozen dataset.
* Extension scripts cannot enable broker submission, live-like execution, or
  automatic real-money trading. All outputs remain research evidence until they
  pass existing risk gates and manual-confirmation workflows.

### Acceptance Criteria for v0.4

* [x] A documented `strategy/extensions/` or equivalent local extension area
  exists for private strategy scripts, with examples that do not contain
  secrets or private financial data.
* [x] Built-in and extension strategies share one typed metadata contract:
  id, display name, description, asset universe, supported frequencies,
  parameters, defaults, constraints, benchmark role, and validation
  requirements.
* [x] `/api/backtest/strategies` returns typed strategy parameter schemas for
  both built-in and extension strategies.
* [x] `POST /api/backtest/run` accepts generic strategy parameters and records
  the exact parameter payload in the persisted result.
* [x] The Web Backtest page uses the strategy registry instead of a free-text
  strategy field, renders validated controls for strategy parameters, and
  supports one-symbol historical backtests from the browser.
* [x] At least one custom extension strategy can be added locally, discovered
  by the registry, run from the Web UI, and verified by deterministic tests.
* [x] Backtest runs record frozen dataset identity, provider/cache metadata,
  date range, symbol universe, adjustment mode when available, row count, and
  data-quality diagnostics.
* [x] Backtest reports expose after-cost metrics, cost assumptions, slippage
  assumptions, fills, equity/drawdown curves, benchmark comparison, OOS split
  evidence, and limitations in both API and Web UI.
* [x] Parameter sweep runs support bounded grids, persist each tested
  configuration, and present rankings with explicit overfitting / multiple
  testing warnings.
* [x] Strategy comparison can compare multiple strategies or parameter sets on
  the same dataset snapshot without silently changing data inputs.
* [x] Strategy outputs can be promoted only as research evidence; they cannot
  bypass pre-trade risk gates, signal journaling, paper/shadow review, or
  manual confirmation.
* [x] Backend deterministic tests cover built-in strategy run, extension
  strategy discovery, generic parameter validation, one-symbol Web/API run,
  parameter sweep, after-cost/OOS reporting, and blocked unsafe extension
  behavior.
* [x] Frontend tests cover strategy selection, dynamic parameter controls,
  one-symbol run setup, report rendering, and parameter-sweep result review.
* [x] README and Chinese docs explain how to add a local strategy, run it from
  Web, interpret reports, and keep the output as research rather than
  investment advice.

## Target for v0.5

Karkinos v0.5 — Quant Research Quality & Production Evidence Hardening —
turned Strategy Lab output into a stronger research-evidence pipeline before
any shadow or paper review.

### v0.5 Scope

* Each backtest, sweep, and comparison run produces a unified
  `ResearchEvidenceBundle` that references the dataset snapshot, strategy
  metadata, cost evidence, OOS evidence, analyzer outputs, assumptions,
  limitations, and gate status.
* Data quality can degrade or block research evidence when bars, cache
  metadata, provider reconciliation, adjustment mode, or source freshness are
  insufficient.
* OOS validation supports stronger split structures such as rolling,
  walk-forward, and regime-aware summaries, with explicit limitations when the
  configured experiment lacks enough data.
* Parameter sweeps include stability and sensitivity evidence rather than
  ranking only by headline return.
* Analyzer contracts are explicit and composable, covering return, risk, cost,
  drawdown, turnover, exposure, trade statistics, benchmark, data quality, and
  China-market assumptions over time.
* China-market assumptions are visible in research output, including T+1,
  limit behavior, suspension or special-treatment gaps, trading calendar,
  taxes and fees, and fund or NAV latency where relevant.
* Promotion into shadow or paper review is blocked or degraded unless the
  evidence gate sees enough data-quality, after-cost, OOS, risk, and audit
  evidence.
* Web reports explain pass, degraded, blocked, and review-required outcomes in
  plain language without presenting research output as investment advice.

### Acceptance Criteria for v0.5

* [x] `ResearchEvidenceBundle` exists as a versioned backend artifact and is
  generated for single backtests.
* [x] Parameter sweeps and strategy comparisons persist and expose the same
  evidence-bundle contract for each constituent run.
* [x] Analyzer outputs are produced through an explicit contract rather than
  ad hoc report fields.
* [x] Data-quality analyzer status can mark experiments `pass`, `degraded`, or
  `blocked`, and blocked data prevents promotion readiness.
* [x] Evidence bundles reference dataset snapshot id, strategy metadata,
  after-cost evidence, OOS evidence, cost summary, fills/trade statistics, and
  limitations when available.
* [x] Walk-forward or rolling OOS evidence can be generated deterministically
  for at least one strategy fixture.
* [x] Parameter sweep reports include stability or sensitivity evidence and
  overfitting warnings grounded in the tested grid.
* [x] China-market assumptions are recorded in each evidence bundle, including
  which assumptions are modeled and which are known gaps.
* [x] Strategy promotion readiness consumes evidence-bundle gate status and
  cannot mark a strategy ready when required evidence is missing or blocked.
* [x] API and saved report files expose the evidence bundle without changing
  live-like execution defaults or enabling automatic real-money trading.
* [x] Backend deterministic tests cover bundle generation, analyzer contract,
  data-quality degraded/blocked states, and promotion-gate consumption.
* [x] README/docs explain how to interpret the evidence bundle and keep it as
  research evidence rather than investment advice.

## Target for v0.6

Karkinos v0.6 — Account Truth & Reconciliation Engine — makes local account
facts auditable before any decision, research promotion, paper/shadow review,
or manual-confirm workflow relies on them.

### v0.6 Goal

v0.6 answers:

> Are real account facts, Karkinos ledger, portfolio holdings, cash, fees,
> taxes, cost basis, and market cache internally consistent? If not, where are
> the differences, how large are they, how risky are they, and do they affect
> today's action suggestions or strategy promotion?

### v0.6 Scope

* Canonical broker statement CSV format and safe synthetic examples.
* Import preview: parse, normalize, validate, and fingerprint local CSV rows
  without writing production ledger entries.
* Staged broker evidence with import run metadata and typed evidence events.
* File-level and row-level duplicate detection.
* Reconciliation against ledger, cash, positions, fees, taxes, and cost basis.
* Manual review states for reconciliation items.
* Account Truth Score.
* Decision Cockpit and promotion-readiness degradation/blocking when account
  truth is insufficient.
* Capability-based acceptance audit manifest and CLI registry coverage.

### Acceptance Criteria for v0.6

* [x] A canonical broker statement CSV format is documented with safe
  synthetic examples.
* [x] Import preview parses, normalizes, validates, and fingerprints local CSV
  rows without writing production ledger entries.
* [x] Import runs store source type, file fingerprint, row counts, validation
  status, duplicate counts, timestamps, and limitations.
* [x] Imported rows normalize into typed broker evidence events: trade
  buy/sell, dividend, fee, tax, transfer, position snapshot, and cash snapshot.
* [x] File-level and row-level duplicate detection exists and is deterministic.
* [x] Valid imports can be persisted as broker evidence without auto-mutating
  existing ledger entries.
* [x] Reconciliation compares broker evidence against Karkinos ledger, cash,
  positions, fees, taxes, and cost basis.
* [x] Reconciliation reports expose pass/warning/mismatch/blocked status,
  per-symbol differences, cash differences, fee/tax differences, cost-basis
  differences, and suggested review actions.
* [x] Manual review can mark reconciliation items as accepted, ignored, known
  difference, ledger candidate, or needs investigation.
* [x] Account Truth Score is exposed through API/report and reflects cash,
  position, fee, cost-basis, data freshness, and unresolved mismatch state.
* [x] Decision platform and promotion readiness degrade or block when account
  truth is insufficient.
* [x] No broker login, broker password storage, broker order submission, or
  default real-money automation is introduced.
* [x] Backend deterministic tests cover parser, validation, duplicate
  detection, staging, reconciliation, review decisions, account truth score,
  and decision-platform degradation.
* [x] README/docs explain the import workflow, privacy boundary, and that
  broker evidence is audit tooling, not investment advice.
* [x] Acceptance audit manifest and CLI include the account truth /
  reconciliation capability using capability-based naming.

## Target for v0.7

Karkinos v0.7 — Account Truth Review Center — should turn account-truth and
reconciliation evidence into a usable review workflow for the financial app.

### v0.7 Goal

v0.7 answers:

> Which account-truth differences still need human review, what evidence
> supports each difference, what action was taken, and should decision or
> promotion workflows be degraded or blocked until the issue is resolved?

### v0.7 Scope

* User-facing Account Truth review surface.
* Import-run listing with validation, duplicate, timestamp, source, and
  limitation metadata.
* Reconciliation report listing, filtering, and detail inspection.
* Reconciliation item review actions with explicit state transitions.
* Ledger-candidate safety: review can prepare candidates, but production
  ledger mutation still requires explicit user confirmation.
* Account Truth Score visibility with component-level reasons in API and Web
  UI.
* Decision and strategy-promotion gates that surface account-truth degradation
  or blocking state.
* Capability-based acceptance audit manifest and CLI registry coverage.

### Acceptance Criteria for v0.7

* [x] A user-facing Account Truth review surface exists.
* [x] Import runs can be listed with row counts, validation status, duplicate
  counts, source type, timestamps, and limitations.
* [x] Reconciliation reports can be listed and inspected by status: pass,
  warning, mismatch, blocked.
* [x] Reconciliation items show broker value, Karkinos value, difference,
  severity, suggested action, symbol, and evidence references.
* [x] Manual review actions can mark differences as accepted, ignored, known
  difference, ledger candidate, or needs investigation.
* [x] Ledger candidates do not mutate the production ledger without explicit
  user confirmation.
* [x] Account Truth Score is visible in API and Web UI with component-level
  reasons.
* [x] Decision summaries degrade or block when unresolved account-truth issues
  are material.
* [x] Strategy promotion readiness shows account-truth gate status.
* [x] Backend deterministic tests cover import-run listing, reconciliation
  report detail, review actions, ledger-candidate safety, score computation,
  decision degradation, and promotion gate integration.
* [x] Frontend tests cover Account Truth review rendering, status filters,
  review action submission, score display, and blocked/degraded states.
* [x] README/docs explain the review workflow as audit tooling, not investment
  advice.
* [x] Acceptance audit manifest and CLI include the account-truth review
  capability using capability-based naming.

## Future Candidate Milestones

The previous candidate backlog has been promoted into the concrete
Professional Quant Platform track below. Future candidates should continue to
stay subordinate to data integrity, account truth, risk gates, paper/shadow
review, and manual confirmation.

## Target for v0.8

Karkinos v0.8 — Strategy Assignment & Attribution Engine — should connect
research strategies to account context without pretending that every portfolio
change was strategy-driven.

### v0.8 Goal

v0.8 answers:

> Which strategy is currently assigned to my account or a subset of assets,
> what evidence supports that assignment, which signals and manual reviews came
> from it, which orders or fills can be attributed to it, and what contribution
> can be stated without mixing in manual trades, cash flows, or unattributed
> market movement?

### v0.8 Scope

* Account strategy assignment for the whole account, an asset class, or one
  symbol.
* Explicit assignment states such as research-only, paper review, shadow
  review, manual-confirmation review, disabled, and retired.
* Strategy assignment must be auditable and must not enable broker submission
  or default real-money automation.
* Backtest and strategy pages should show available strategies, current account
  strategy assignment, latest research evidence, and whether attribution is
  available.
* Signals, action candidates, risk decisions, manual confirmations, paper or
  shadow orders, fills, fees, taxes, and ledger entries should carry enough
  references to attribute downstream effects to a strategy when the evidence is
  present.
* Strategy contribution reports should separate realized P/L, unrealized P/L,
  fees, taxes, slippage, unattributed account movement, manual trades, and cash
  flows.
* Decision and promotion views should show when a strategy is assigned but
  attribution is incomplete, stale, or blocked.

### Acceptance Criteria for v0.8

* [x] A capability-based account strategy assignment API exists and can read
  the current assignment without enabling automatic trading.
* [x] Account strategy assignment can be updated for account, asset-class, or
  symbol scope with status, effective date, notes, timestamps, and limitations.
* [x] Assignment storage is auditable and does not mutate ledger entries,
  broker evidence, orders, fills, or positions.
* [x] Backtest Web shows available strategies first, then run configuration,
  latest result, current account strategy assignment, and research gates in a
  user-readable order.
* [x] Backtest Web clearly states when strategy P/L attribution is not started,
  partial, stale, blocked, or complete.
* [x] Strategy IDs remain internal audit keys while Web surfaces localized
  strategy names and explanations.
* [x] Signals, action candidates, risk decisions, review decisions, orders, and
  fills retain deterministic references required for strategy attribution.
* [x] Strategy contribution report separates realized P/L, unrealized P/L,
  fees, taxes, slippage, manual/unattributed movement, and cash flows.
* [x] Strategy contribution API never assigns cash deposits, withdrawals,
  manual trades, or missing-evidence movements to a strategy by default.
* [x] Overview, Portfolio, Backtest, Decision, and review surfaces expose
  strategy contribution only when the attribution chain is supported by
  evidence.
* [x] Decision summaries degrade or block strategy-driven recommendations when
  the assigned strategy lacks required account-truth, research, or attribution
  evidence.
* [x] Backend deterministic tests cover assignment defaults, updates,
  attribution references, contribution separation, and degraded decision state.
* [x] Frontend tests cover strategy catalog first-screen rendering, current
  account strategy assignment, no-auto-trading wording, attribution status, and
  contribution estimate visibility.
* [x] README/docs explain strategy assignment and contribution reporting as
  audit tooling and research evidence, not investment advice.
* [x] Acceptance audit manifest and CLI include the strategy assignment and
  attribution capability using capability-based naming.

## Professional Quant Platform Track

The post-v0.8 roadmap moves Karkinos toward a professional personal quant
platform while preserving the Karkinos safety boundary. External broker and
strategy platforms may inform requirements, but none is a core dependency,
default route, registered adapter, or support claim.

Karkinos should not copy either product. It should combine those professional
platform patterns with local account truth, reproducible research evidence,
risk-first decision review, paper/shadow operation, and manual confirmation.

### Track Principles

* Data, strategy, account, and risk evidence must be auditable before any
  decision workflow relies on them.
* Strategies may produce signals, candidates, and explanations, but they must
  not bypass research-evidence, risk, account-truth, paper/shadow, or manual
  review gates.
* Broker facts may be imported or read as evidence, but broker login,
  broker-password storage, broker order submission, and default real-money
  automation remain out of scope until an explicitly controlled future bridge.
* User-facing surfaces should show localized, human-readable status instead of
  internal reason codes.
* Generated reports, runtime databases, broker credentials, screenshots, logs,
  and private account data must stay out of source control.

## Target for v0.9

Karkinos v0.9 — Data Plane & Market Reliability — should make market data,
fund NAVs, historical bars, intraday snapshots, and replay datasets a trusted
foundation for the financial app.

### v0.9 Goal

v0.9 answers:

> Is the market data behind today's valuation, calendar returns, strategy
> research, and intraday review confirmed, estimated, cached, missing, or
> stale — and can the same frozen data be replayed deterministically?

### v0.9 Scope

* A unified market-data adapter boundary for daily bars, intraday bars,
  snapshots, and future tick data.
* A normalized market event model with source, timestamp, session, adjustment,
  and freshness metadata.
* Local data-quality diagnostics for missing dates, non-trading days, stale
  quotes, delayed fund NAVs, adjustment gaps, and source differences.
* Manual and scheduled refresh flows for intraday quotes, close prices, and
  fund NAV confirmation.
* Dataset freezing and replay so the same evidence can drive backtests,
  Strategy Runtime dry-runs, paper/shadow review, and post-decision replay.
* Web data-status surfaces that distinguish confirmed values, estimated values,
  cache-only values, missing data, and confirmed NAV gaps in user-readable
  language.

### Acceptance Criteria for v0.9

* [x] A capability-based market data adapter interface exists for daily bars,
  intraday bars, snapshots, and future tick events.
* [x] Daily bars, intraday bars, snapshots, and replay events normalize into a
  shared data-status vocabulary: confirmed, live, cache, estimated, missing,
  stale, and confirmed NAV missing.
* [x] Market data records keep source, timestamp, trading session, adjustment
  mode when available, and freshness metadata.
* [x] Data-quality diagnostics detect missing trading dates, non-trading days,
  stale quotes, delayed fund NAVs, adjustment gaps, and provider differences.
* [x] Manual refresh and scheduled refresh flows can update intraday quotes,
  close-price bars, and fund NAV confirmation without changing trading
  behavior.
* [x] Dataset snapshots can be frozen and replayed deterministically for
  backtests, strategy runtime dry-runs, paper/shadow review, and audit replay.
* [x] Overview valuation, return calendar, Backtest, and Strategy Runtime use
  the same data-status vocabulary and do not present estimated values as
  confirmed returns.
* [x] The 1D net-value chart can represent intraday market movement, cash-flow
  changes, stock movement, fund confirmation state, and stale data without
  fabricating missing observations.
* [x] Web data-status surfaces expose localized, user-readable status and next
  actions instead of internal reason codes.
* [x] Backend deterministic tests cover adapter normalization, freshness
  diagnostics, scheduled refresh boundaries, dataset freezing, and replay
  determinism.
* [x] Frontend tests cover data-status rendering, estimated-versus-confirmed
  labeling, and 1D chart behavior with missing or stale observations.
* [x] README/docs explain the market-data reliability workflow and privacy
  boundary without presenting data estimates as investment advice.
* [x] Acceptance audit manifest and CLI include the market-data reliability
  capability using capability-based naming.

## Target for v1.0

Karkinos v1.0 — Strategy Runtime Foundation — should upgrade strategies from
one-shot backtest functions into a safe lifecycle runtime.

### v1.0 Scope

* A strategy lifecycle with initialization, pre-market, bar, tick,
  after-market, order-update, and fill-update hooks.
* A read-only strategy context for market data, account facts, positions,
  risk limits, strategy parameters, and current run metadata.
* Standardized strategy outputs: observation signal, buy candidate, sell
  candidate, rebalance candidate, risk warning, and no-action explanation.
* Built-in strategies and local extension strategies using one registry,
  one parameter schema contract, and one documentation pattern.
* Backtest, replay, paper, and shadow paths that use the same strategy runtime
  contract without allowing strategies to submit broker orders directly.
* A shared market calendar used by Strategy Runtime and Web return surfaces to
  explain non-trading days, weekends, and market holidays.

### Acceptance Criteria for v1.0

* [x] A capability-based strategy runtime interface supports initialize,
  before-market, bar, tick, after-market, order-update, and fill-update hooks.
* [x] Strategy context is read-only for broker/account facts and cannot submit
  broker orders.
* [x] Strategy outputs normalize into auditable signal and candidate-action
  records before risk, account-truth, paper/shadow, or manual-review gates.
* [x] Built-in and extension strategies share one registry and parameter
  schema contract.
* [x] Strategy Runtime and the Web return calendar consume a shared market
  calendar to explain non-trading days, weekends, and market holidays without
  showing them as missing prices or zero-return trading days.
* [x] Strategy docs explain built-in strategies, custom strategy placement,
  parameter meanings, risk assumptions, and non-investment-advice boundaries.
* [x] Backend deterministic tests cover lifecycle ordering, read-only context,
  output normalization, extension discovery, and blocked unsafe strategy
  behavior.

## Target for v1.1

Karkinos v1.1 — Paper Broker & OMS — should provide professional order
lifecycle evidence for simulation and review without mutating the production
ledger or submitting broker orders.

### v1.1 Scope

* A paper broker with simulated order submission, fill generation, partial
  fills, cancellations, rejections, slippage, fees, and taxes.
* An order-management state machine with deterministic client order ids,
  broker or paper order ids, fill ids, strategy ids, signal ids, and risk
  decision references.
* Paper reports that separate simulated orders/fills from real ledger entries.
* Shadow review surfaces that compare strategy candidates, paper outcomes, and
  actual account movement.

### Acceptance Criteria for v1.1

* [x] Paper broker orders and fills are stored as simulation evidence and do
  not mutate production ledger entries.
* [x] OMS state transitions cover staged, submitted, accepted, partially
  filled, filled, rejected, cancelled, expired, and reconciled states.
* [x] Paper order evidence references signal, strategy, risk decision,
  dataset, cost model, and account-truth context when available.
* [x] Shadow review can compare strategy candidates, paper outcomes, and real
  account movement without attributing unsupported differences to a strategy.
* [x] Backend deterministic tests cover paper fills, partial fills,
  cancellations, rejections, slippage, fee/tax modeling, and OMS idempotency.

## Target for v1.2

Karkinos v1.2 — Broker Evidence Connector — should make broker facts easier to
import or read without introducing broker order submission.

### v1.2 Scope

* A broker connector interface for read-only account snapshots, cash,
  positions, orders, fills, and connector health.
* A broker-neutral read-only connector contract exercised with deterministic
  local fixtures; any real broker adapter requires separate review and user
  authorization.
* Local ignored configuration for connector paths and account aliases, with no
  broker password storage.
* Broker evidence persistence and reconciliation against Karkinos ledger,
  cash, positions, fees, taxes, and cost basis.
* Broker net-cash impact, fee/tax/transfer-fee components, and broker-reported
  cost-basis method can be captured as evidence so local accounting differences
  are explainable instead of hidden behind one generic commission field.
* User-readable diagnostics for disconnected clients, missing permissions,
  stale snapshots, incomplete fields, and connector limitations.

### Acceptance Criteria for v1.2

* [x] A capability-based broker connector interface can read account, cash,
  position, order, fill, and health facts without order submission.
* [x] Connector configuration stays in ignored local config and never stores
  broker passwords or secrets in source control.
* [x] Read-only broker facts normalize into broker evidence and reconciliation
  inputs without automatically mutating production ledger entries.
* [x] Decision and Strategy Lab degrade or block when connector evidence shows
  material unresolved account-truth issues.
* [x] Reconciliation distinguishes gross trade amount, net cash impact,
  commission, tax, transfer fees, and broker-reported remaining cost basis so
  sell-side cash and cost-basis differences can be reviewed explicitly.
* [x] Backend deterministic tests use fake connector fixtures for healthy,
  disconnected, stale, permission-limited, duplicate, and incomplete broker
  evidence states.

## Target for v1.3

Karkinos v1.3 — Professional Decision Workflow — should turn data, account,
strategy, risk, paper/shadow, and manual-review evidence into a daily workflow
that a serious investor can follow without reading internal modules.

### v1.3 Scope

* A daily workflow that orders tasks by risk and reliability: data refresh,
  account truth, strategy signal, risk check, paper/shadow comparison, manual
  confirmation, and review.
* Decision surfaces that show buy, sell, hold, rebalance, no-action, and
  review-required outcomes with evidence and blockers.
* User-readable next actions for data gaps, stale account facts, risk
  blockers, missing strategy evidence, and pending manual confirmations.

### Acceptance Criteria for v1.3

* [x] Daily decision workflow surfaces prioritize data and account-truth
  blockers before strategy opportunities.
* [x] Each candidate action shows strategy source, market data status, account
  truth status, risk status, research evidence, paper/shadow evidence, cost
  impact, uncertainty, and manual-confirmation state.
* [x] Decision views do not present action suggestions as certain when data or
  account facts are stale, estimated, missing, or blocked.
* [x] Frontend tests cover localized no-action, degraded, blocked, and
  review-required decision states.

## Target for v1.4

Karkinos v1.4 — Strategy Attribution 2.0 + Broker Fee & Cost Basis Fidelity —
should answer whether assigned strategies are helping the account after
separating manual trades, broker fees, taxes, cash flows, unsupported movement,
and market changes. It should also make ledger costs explainable against the
broker-facing cost basis shown in a user's securities app.

### v1.4 Scope

* Account, asset-class, and symbol-level strategy assignment health.
* Local broker fee schedules in ignored runtime config, without storing account
  numbers, screenshots, broker passwords, or private exports.
* Fee models for China-market instruments and venues, including A-shares,
  funds/ETF/LOF, bonds, convertible bonds, BSE, NEEQ, Hong Kong Connect,
  stamp tax, transfer fees, broker-absorbed regulatory fees, and explicit
  unknowns.
* Signal, review, order, fill, fee, tax, ledger, and position references for
  attribution.
* Strategy-level realized P/L, unrealized P/L, fees, taxes, slippage, manual
  movement, unattributed movement, and cash-flow separation.
* Ledger entries that distinguish gross trade amount, net cash impact,
  commission, stamp tax, transfer fee, other fees, fee-rule version, and
  cost-basis method.
* Shared user-facing ledger formatting across Overview, Activity, Portfolio,
  holding detail, Risk, Decision, and review surfaces so internal entry types,
  reason codes, and legacy note prefixes never leak into the UI.
* Ledger notes that are normalized into consistent public notes while core
  accounting fields such as quantity, price, gross amount, net cash impact,
  commission, tax, transfer fee, and cost basis remain structured fields rather
  than free-text remarks.
* Position views that distinguish moving average buy cost from broker displayed
  cost basis, where broker displayed cost basis means the remaining position
  cost shown by the broker after realized sell proceeds, sell-side taxes, and
  transfer fees have been applied to the still-held quantity.
* Strategy health indicators for stale evidence, drift from historical
  behavior, paused status, and suggested parameter review.

### Acceptance Criteria for v1.4

* [x] Strategy performance attribution separates realized, unrealized, fee,
  tax, slippage, manual, unattributed, and cash-flow components.
* [x] Local `config.json` supports a structured broker fee schedule without
  storing account identifiers, screenshots, broker passwords, credentials, or
  private exports.
* [x] Fee calculation returns a deterministic breakdown for commission, stamp
  tax, transfer fee, other fees, total fee, fee-rule id, and known limitations.
* [x] Buy and sell ledger entries preserve gross trade amount, net cash impact,
  fee breakdown, cost-basis method, and fee-rule version.
* [x] A shared public ledger formatter is used by Overview, Activity,
  Portfolio, holding detail, Risk, Decision, and review surfaces for action
  titles, entry types, notes, instrument names, timestamps, quantities, prices,
  amounts, fees, and cash impact.
* [x] User-facing ledger surfaces do not render internal values such as
  `trade_buy`, `trade_sell`, raw reason codes, legacy note prefixes, duplicate
  symbol/name fragments, or mixed Chinese/English operational notes.
* [x] Public ledger notes follow a consistent localized format and never carry
  core accounting facts that should be structured columns or detail fields.
* [x] Portfolio cost views show both moving average buy cost and broker
  displayed cost basis when enough evidence exists, with localized
  explanations of the difference.
* [x] Sell-side realized P/L and remaining-position broker cost basis use net
  proceeds after commission, stamp tax, transfer fees, and configured
  broker-specific rules.
* [x] Account Truth reconciliation compares broker-reported cost basis against
  Karkinos broker/local cost basis and exposes differences, severity, method
  context, precision limitations, and suggested review actions.
* [x] Backtest, paper broker, manual trade preview, and ledger projections use
  the same fee model contract without enabling automatic real-money trading.
* [x] Backend deterministic tests cover A-share buy/sell, stamp tax,
  Shanghai/Shenzhen transfer-fee differences, ETF/fund, convertible bond,
  broker displayed cost basis, realized P/L, and net cash impact.
* [x] Frontend tests cover fee-breakdown display, cost-basis-method display,
  broker/local cost-basis difference warnings, shared ledger formatting, and
  the absence of internal entry types or raw reason codes in user-visible
  ledger surfaces.
* [x] Strategy health can mark assigned strategies as healthy, degraded,
  stale, paused, or needing review.
* [x] Manual trades and missing-evidence movement are never attributed to a
  strategy by default.
* [x] Web surfaces explain strategy contribution in localized user-facing
  language and keep internal strategy ids secondary.

### Active Goal Audit: Data-Trusted Single-Instrument Strategy Loop

This active-goal audit tracks the current read-only preview chain for one
instrument. It proves that deterministic evidence exists from dataset and
strategy selection through signal, risk, paper/shadow, and attribution-preview
boundaries. It does not claim production strategy P/L attribution, broker order
submission, or automatic real-money trading.

### Acceptance Criteria for Data-Trusted Single-Instrument Strategy Loop

* [x] Dataset snapshot evidence and strategy registry are both present in the one-symbol flow.
* [x] A single-symbol after-cost backtest can feed the preview chain without writing production trading facts.
* [x] Today's signal preview returns standardized candidate actions or no-action reasons as research evidence.
* [x] The preview path runs a read-only risk gate before paper/shadow simulation.
* [x] Paper/shadow preview simulates order and fill evidence while remaining isolated from the real ledger.
* [x] Attribution preview exposes evidence counts and a manual review linkage candidate without claiming strategy P/L.
* [x] Portfolio holding detail exposes symbol-filtered attribution evidence, evidence-chain refs, and review-readiness prerequisites without claiming strategy P/L.
* [x] Decision candidate cards link directly to symbol-scoped holding attribution review without creating orders or mutating the ledger.
* [x] Web Backtest explicitly explains the post-risk paper/shadow next step and blocks strategy P/L attribution when production fills are not linked.
* [x] Web strategy-loop surfaces use localized, user-readable language without exposing internal reason codes or raw evidence refs.

## Target for v1.5

Karkinos v1.5 — Daily Trading Plan & Portfolio Construction — should move from
research evidence and isolated previews into a daily operating plan: what the
system believes should be reviewed today, what is blocked, what can become a
manual-confirmation order intent, and why.

### v1.5 Scope

* A daily trading-plan builder that gathers market-data health, account truth,
  portfolio state, assigned strategy evidence, candidate signals, risk gates,
  paper/shadow evidence, fee/cost estimates, and manual-review state into one
  auditable plan.
* Today's to-dos as the canonical user-facing action queue for the daily plan:
  data/account blockers first, then manual-confirmation candidates, strategy
  evidence review, portfolio-construction suggestions, and normal status.
* Clear separation between a large research candidate pool and the much smaller
  set of items that need human action today.
* Manual-confirmation order intents that include target position, quantity,
  estimated gross amount, fee/tax breakdown, net cash impact, risk rationale,
  blockers, and evidence references before the user records any execution.
* Target weights, cash buffer, rebalance thresholds, and low-cost rebalance
  suggestions.
* Account-level, asset-class, symbol, industry, concentration, liquidity, and
  drawdown constraints.
* China-market constraints such as T+1, trading unit, limit up/down,
  suspension, special-treatment risk, fund NAV latency, and fee/tax impact.
* Portfolio-construction explanations that show why to rebalance, hold cash,
  avoid concentration, or defer action.

### Acceptance Criteria for v1.5

* [x] A daily trading-plan API can assemble data health, account truth,
  strategy candidates, risk preview, paper/shadow evidence, fee/cost preview,
  and manual-review status without creating broker orders or mutating the
  production ledger.
* [x] Today's to-dos renders the daily plan with a top-level conclusion,
  execution status, review queue, and evidence-linked next actions.
* [x] Candidate-pool size is never presented as the number of trades the user
  must execute; manual-ready and blocked counts are separate.
* [x] Manual-confirmation order intents include target weight, quantity,
  estimated price, gross amount, fee/tax breakdown, net cash impact, remaining
  position/cost-basis effect, and risk/account-truth status.
* [x] Portfolio construction recommendations pass account-truth and risk gates
  before appearing as actionable candidates.
* [x] Rebalance suggestions include target/actual weight, drift, expected
  cost, cash impact, and risk rationale.
* [x] China-market constraints are explicit in risk evidence and user-facing
  explanations.
* [x] Backend deterministic tests cover concentration, cash buffer, T+1,
  trading unit, limit, suspension, fee/tax, and drawdown constraints.
* [x] Frontend tests cover daily-plan conclusions, blocker ordering,
  manual-ready order intents, and the absence of broker-submission language.

## Target for v1.6

Karkinos v1.6 — Operations Center & Paper/Shadow Runbook — should make
Karkinos observable as a local personal finance system and turn paper/shadow
review into a repeatable daily operating loop.

### v1.6 Scope

* Operations surfaces for market data, refresh jobs, broker evidence,
  account-truth reconciliation, strategy runs, paper/shadow runs, scheduler
  jobs, acceptance audits, and system alerts.
* Scheduled daily strategy-plan and paper/shadow runs that can be rerun
  deterministically, explain skipped/degraded/blocked states, and never submit
  broker orders.
* Paper/shadow divergence reports that compare expected strategy behavior,
  simulated orders/fills, current account truth, and realized market context.
* Event logs for market-data events, broker-evidence events, strategy events,
  risk events, order events, review events, and generated reports.
* Daily run summaries that explain what ran, what failed, what needs action,
  and what evidence is safe to rely on.

### Acceptance Criteria for v1.6

* [x] Operations Center can show health, last run, next action, and limitations
  for core data, account, strategy, risk, paper/shadow, scheduler, and audit
  subsystems.
* [x] Daily run summaries distinguish successful, degraded, blocked, skipped,
  and manual-action-required states.
* [x] Paper/shadow run summaries include generated order intents, simulated
  fills, fee/cost assumptions, divergence status, and next manual review step.
* [x] Scheduler reruns are idempotent and record run ids, input snapshots,
  errors, retry state, and limitations.
* [x] Acceptance audit CLI includes market data, strategy runtime, paper OMS,
  broker evidence, decision workflow, strategy attribution, portfolio
  construction, and operations capabilities as they are completed.
* [x] Operations records do not commit runtime logs, private account data,
  screenshots, or generated reports to source control.

Initial v1.6 implementation note:

* `/api/operations/today` now provides a read-only daily operations runbook
  with subsystem health, next action, limitations, daily-plan counts, and
  paper/shadow simulation-review status. Overview embeds the runbook in
  "Today's to-dos", and Decision embeds the paper/shadow summary in the daily
  trading plan panel. Automation alerts now cover failed paper/shadow
  automation runs and incomplete read-only broker connector health as
  acknowledgeable runbook evidence, risk-blocked daily plans can be scanned
  into manual-review alerts, stale market-data health snapshots can be scanned
  into manual-review alerts with stale-symbol evidence, and degraded or
  blocked Account Truth snapshots can be scanned into manual-review alerts,
  and diverged or review-required paper/shadow runs can be scanned into
  manual-review alerts with divergence-count evidence. Persisted generic broker
  lifecycle collector evidence can be scanned into manual-review alerts with
  provider/gateway provenance, evidence-store state, blockers, explicit-
  ingestion and third-party-review requirements, and no-contact/no-submission
  flags. GET and alert paths never poll a registered edge adapter. The old
  runtime snapshot entry is a labelled migration surface and returns no live
  account facts. Paper/shadow divergence summaries now include a
  richer comparison of expected strategy behavior, simulated execution,
  account-truth state, realized market context, cost evidence, and
  non-submission safety flags, and the Decision daily trading plan panel
  renders those report sections as read-only review evidence while Overview
  Today's to-dos surfaces a compact divergence-review summary and Trading
  execution audit shows the latest paper/shadow run evidence. Accepted
  divergence reviews preserve raw divergence status for audit while exposing a
  runbook effective status for manual-confirmation handoff. Broker lifecycle
  ingestion uses explicit local commands and deterministic fixtures; no edge
  adapter is registered by default. Market-session automation now uses a
  trading-plan fingerprint
  idempotency key as the persisted run id, so repeated scheduler invocations
  for the same plan/date update one audit run while changed inputs create a
  new run. Paper/shadow run payloads also persist a
  deterministic `input_snapshot` with normalized order-intent inputs,
  account-truth state, constraint summary, outcome overrides, fingerprint, and
  no-broker/no-ledger-mutation safety flags for operator rerun review.

### v1.6.1 Completed Implementation — Paper/Shadow Execution Engine & OMS Run Records

This completed implementation turns manual-ready order intents into a repeatable
paper/shadow execution run without creating production ledger entries, broker
orders, or live fills.

#### v1.6.1 Scope

* Persist a `paper_shadow_run` record for each daily run with run id, plan date,
  input decision/trading-plan references, created timestamp, status, counts,
  limitations, and deterministic fingerprint.
* Convert daily trading-plan order intents into paper/shadow order records with
  deterministic client order ids, strategy/action/risk references, side,
  quantity, price basis, gross amount, fee/tax estimate, and execution mode.
* Add an OMS state machine for paper/shadow records:
  `staged`, `submitted`, `accepted`, `partially_filled`, `filled`,
  `rejected`, `cancelled`, `expired`, and `reconciled`.
* Simulate paper fills deterministically from current quote evidence, with
  support for full fill, partial fill, reject, cancel, and expired outcomes in
  fixtures.
* Keep paper/shadow orders and fills as simulation evidence only. They must not
  mutate production `ledger_entries`, cash, positions, broker evidence, or
  manual orders.
* Produce a divergence summary and structured review queue comparing order
  intents, simulated fills, current account facts, and broker/account truth
  state.
* Surface the latest paper/shadow run in `/api/operations/today`, Decision, and
  Today's to-dos with next actions for not-run, running, failed, diverged,
  within-expectations, and review-required states.
* Make reruns idempotent for the same plan fingerprint while allowing an
  explicit new run when inputs change.

#### v1.6.1 Acceptance Criteria

* [x] Backend storage exists for paper/shadow runs, simulated orders, simulated
  fills, status transitions, evidence refs, and run limitations.
* [x] A service can create or reuse a paper/shadow run from the current daily
  trading plan and returns deterministic counts and evidence refs.
* [x] OMS transitions reject invalid state moves and record every accepted move
  with timestamp, reason, and source.
* [x] Paper/shadow fill simulation covers full fill, partial fill, rejection,
  cancellation, expiration, fee/tax projection, and idempotent rerun behavior.
* [x] `/api/operations/today` includes latest paper/shadow run id, status,
  order/fill counts, divergence status, structured review queue, and next
  manual review step.
* [x] Decision and Overview surfaces show paper/shadow next actions and
  structured review queue summaries without exposing raw state-machine
  internals or implying broker submission.
* [x] Backend deterministic tests cover storage, idempotency, state transitions,
  fill simulation, divergence summary, review queue, and no production-ledger
  mutation.
* [x] Frontend tests cover not-run, review-required, diverged,
  within-expectations, failed paper/shadow states, and structured review queue
  presentation.
* [x] README/docs keep the safety boundary explicit: paper/shadow records are
  simulation evidence and do not submit broker orders.

## Target for v1.7

Karkinos v1.7 — Controlled Broker Execution Bridge — should only be considered
after data, account truth, strategy runtime, paper/shadow, OMS, risk,
operations monitoring, and manual review are mature. This milestone is a
controlled bridge design, not a default trading bot.

The purpose is to reduce execution friction after Karkinos has already proved
the decision and simulated the execution path. The milestone should make broker
handoff safer and more auditable; it should not make strategy code capable of
calling a broker directly. A deterministic strategy broker-boundary scanner now
checks the current strategy tree for forbidden broker/gateway adapter imports
and direct broker-style calls, so future connector work has a regression guard
for this authority boundary.

v1.7 is complete as a **non-submitting controlled-bridge foundation**. This
completion does not include a live broker submit method, executable broker
cancel, automatic ledger mutation, or a v1.8 auto pilot. L4 broker submission
therefore remains planned and unavailable.

### v1.7 Scope

* Broker-specific order previews that remain manual by default.
* Exportable or bridge-ready order tickets for environments where the user
  still performs final broker-side submission manually.
* A broker gateway contract with explicit capabilities for health checks,
  order preview, dry-run validation, query-only account/order/fill state, and
  disabled-by-default submission. Current backend capability includes
  connector health, runtime read-only connector snapshot query, manual-ticket
  preview/dry-run/create, local order query, staged broker-evidence
  account-facts query, staged fill query, and default-rejected broker
  cancellation without broker write contact; manual-ticket
  actions are blocked when the global kill switch is enabled, and gateway
  status exposes that blocker in both the API and the Decision Cockpit's
  read-only automation panel.
  Connector health, gateway query/read capability labels, staged account-facts
  summaries, staged fill-polling summaries, and read-only local order-query
  evidence are also visible in that panel, including a read-only staged-fill
  reconciliation review hint when execution reconciliation has open items,
  without broker contact, credentials, submit controls, cancel controls, or
  ledger-sync controls. Automation Cockpit and Decision Cockpit also surface
  runtime read-only connector snapshot summaries for cash, positions, orders,
  and fills under the same non-submitting contract, without exposing account
  ids or adding submit/cancel/ledger-sync controls. Read-only connector health
  now also exposes an
  explicit capability scope plus preview/export/dry-run/cancel/submit blockers
  so future controlled-bridge review can distinguish query authority from
  execution authority.
  The same panel also surfaces strategy promotion state as read-only lifecycle
  evidence: stage, paper/shadow gate status, missing requirements, optional
  backtest evidence id, and an explicit live-like disabled boundary. Promotion
  visibility does not authorize execution by itself.
* Explicit per-order human confirmation, kill switch, connector capability
  checks, account-truth gate, strategy evidence gate, and risk gate.
* A white-list model for any future broker submission capability.
* Full audit trail from signal to evidence bundle, risk decision,
  account-truth state, manual confirmation, order preview, and broker or
  manual execution record.
* Execution reconciliation that compares OMS orders, gateway events, broker
  evidence, cash, positions, fills, fees, taxes, and local ledger expectations
  before recommending any ledger update. Recent reconciliation run status and
  the first open item are visible in the Decision Cockpit as read-only review
  evidence, with no ledger-sync or broker-action controls. Matching staged
  broker trade evidence now carries a read-only fee/tax/net-amount summary in
  reconciliation payloads, and Decision Cockpit renders the gross amount,
  fee/tax, transfer fee, net amount, and review-required safety flags so
  operator review can happen before ledger updates.
* Manual trade entry surfaces use explicit labels and calculated previews for
  trade time, instrument, side, quantity, fill price, gross amount, fee/tax
  breakdown, net cash impact, remaining position, and broker-cost-basis impact;
  users should not need to infer what an unlabeled number means. The broker
  gateway now has a non-mutating manual execution preview that calculates an
  operator-entered fill, fee/tax/transfer fee, net cash impact, position/cost
  preview, ledger-entry draft, and deterministic preview fingerprint after
  manual-ticket creation, while still requiring a later explicit operator save
  before any production ledger record.
  Trading approvals exposes this preview after manual-ticket export without
  save-ledger, apply-fill, or broker-submit controls.
  The gateway can also record a matching-fingerprint manual execution evidence
  event for audit continuity without creating fills, changing OMS status, or
  writing production ledger entries. Trading links the operator from the
  exported ticket to broker-statement import and execution-reconciliation
  review. Reconciliation compares matching manual-execution evidence with
  staged broker price, quantity, gross amount, fee, tax, transfer fee, and net
  amount; differences enter the review queue without changing OMS or the
  production ledger. Decision renders the compared manual and broker values as
  read-only evidence without sync, apply-fill, cancel, or submit controls.

### Acceptance Criteria for v1.7

* [x] Broker submission remains disabled by default and unavailable unless an
  explicit controlled bridge is configured.
* [x] A non-submitting order-ticket export path exists before any live broker
  bridge path is considered.
* [x] Gateway capabilities and health are visible in API/UI and include
  whether the connector can read account facts, query orders/fills, cancel,
  preview, dry-run, or submit.
* [x] Every live-like order preview requires account-truth, research-evidence,
  risk, paper/shadow, and manual-confirmation evidence.
* [x] Kill switch, connector capability checks, and per-order confirmation are
  enforced before any live-like bridge action.
* [x] Strategy code has no broker adapter access; all bridge actions go through
  policy, risk, OMS, gateway, and reconciliation services. A static guard now
  covers the current strategy tree; future private strategies outside the repo
  should use the same contract before any controlled bridge pilot.
* [x] Strategy promotion state is visible as read-only paper/shadow lifecycle
  evidence, and it does not expose live-promotion controls.
* [x] Broker callbacks or imported fills are staged as evidence and reconciled
  before any production ledger mutation is suggested.
* [x] Manual execution forms show user-readable field labels, fee/tax
  components, net cash impact, and remaining-position/cost-basis preview before
  saving a manual execution record.
* [x] No broker password storage, default real-money automation,
  guaranteed-profit language, or strategy-direct broker submission is
  introduced.

## Target for v1.8

Karkinos v1.8 — Capital-Bounded Controlled Execution — is the program that
moves the non-submitting foundation toward human-supervised real execution. It
does not permanently limit Karkinos to a small account. Instead, it separates
account capital from machine authority and starts each new live capability with
a deliberately small authorization envelope until real evidence supports a
larger one.

The target is not unattended full-account trading. The owner grants either one
order or a short-lived capital envelope, sees the capital at risk and remaining
limits, and can pause, reduce, expire, or revoke authority. The system may
automatically pause or scale down, but it may never enable, renew, resume, or
scale itself up.

Detailed delivery order, invariants, promotion evidence, and release gates are
maintained in
[CONTROLLED_EXECUTION_PLAN.md](CONTROLLED_EXECUTION_PLAN.md).

### v1.8 Delivery Sequence

| Stage | Capability | Broker-write boundary | Promotion evidence |
| --- | --- | --- | --- |
| 0 | Capital authorization policy contract and deterministic fail-closed evaluation | No submit or cancel | Contract tests and authority-boundary audit |
| 1 | One real broker-specific read-only adapter and operational soak | Read-only only | At least 20 reviewed trading sessions, recovery drills, no unresolved critical reconciliation mismatch |
| 2 | Per-order human-confirmed broker bridge | One evidence-fingerprinted confirmed order at a time | Idempotency, callback/poll recovery, partial-fill aggregation, cancel/reject/timeout and reconciliation evidence |
| 3 | Session-bounded controlled execution | Explicit short-lived account/strategy/symbol envelope | Budget, expiry, auto-pause, kill-switch, reconciliation-before-next-batch and operator-control evidence |
| 4 | Evidence-based capital scaling | New human authorization required for every higher tier | Capacity, liquidity, slippage, drawdown, incidents, reconciliation latency and after-cost review |

Stages are sequential promotion gates, not calendar promises. Stage 0 and Stage
1 can advance without broker submission. A later stage cannot use its own
successful history to self-authorize the next stage.

### v1.8 Scope

* Separate account capital from explicitly authorized capital and effective
  risk-envelope limits.
* Versioned operator authority for account, strategy, symbols, execution mode,
  effective/expiry time, and policy fingerprint.
* Per-account, per-strategy, per-symbol, per-session, and per-day budgets.
* Maximum authorized capital, order value, position change, turnover, daily
  loss, drawdown, order rate, and consecutive-error limits.
* Policy-bound modes `disabled`, `manual_each_order`, and future
  `session_bounded`; manual confirmation remains the default.
* Automatic pause on kill switch, stale market data, account-truth degradation,
  paper/shadow divergence, gateway health degradation, rejected/cancelled order
  spikes, reconciliation gaps, or unexpected ledger/cash/position changes.
* Operator review screens for previewing capital at risk, enabling with expiry,
  pausing, reviewing before resume, revoking, and retiring controlled sessions.
* Controlled-execution performance review comparing backtest expectation,
  paper/shadow expectation, manual execution, bridge execution, capacity,
  liquidity, slippage, incidents, and realized after-cost outcome.
* Human-reviewed capital tier promotion and demotion. Automatic scale-up is
  forbidden; automatic pause or scale-down is allowed when a hard risk gate
  requires it.
* Programmatic-trading reporting, broker agreement, connector testing, and
  compliance review are explicit release evidence; Karkinos does not
  self-certify approval.

### Acceptance Criteria for v1.8

* [ ] Controlled execution is impossible unless the account, strategy,
  connector, symbols, execution mode, policy version, effective time, expiry,
  and operator decision are explicitly valid.
* [ ] Every controlled strategy has promotion evidence from research to
  paper/shadow to manual confirmation to controlled bridge.
* [ ] Hard caps block orders that exceed authorized capital, remaining budget,
  cash, concentration,
  turnover, drawdown, liquidity, T+1, limit, suspension, or ST constraints.
* [ ] The system automatically pauses controlled mode on data, broker, risk,
  account-truth, reconciliation, or kill-switch failures.
* [ ] Reconciliation must be clear or manually accepted before the next
  controlled batch can place another order.
* [ ] UI shows authorized and effective capital at risk, remaining budget,
  authorization expiry, last order, last
  reconciliation result, current blockers, and the exact pause/resume reason.
* [ ] No session can enable, widen, renew, or resume itself; every scale-up
  requires a new human decision tied to reviewed evidence.
* [ ] Tests cover fail-closed policy evaluation, expiry/revocation, budget caps,
  auto-pause, reconciliation-before-next-batch, idempotency, recovery, and no
  strategy-direct broker access.
* [ ] Documentation and UI state that the first live tier is a small validation
  exposure, not a permanent capital limit, profit guarantee, or unattended
  trading mode.

### First v1.8 Implementation Slice

The first implementation slice is Stage 0 and must remain non-submitting:

* Add a versioned capital-authorization policy contract with `disabled`,
  `manual_each_order`, and future `session_bounded` modes.
* Add pure deterministic evaluation for scope, validity window, capital/order/
  turnover/loss/drawdown budgets, account truth, reconciliation readiness,
  connector health, and kill switch.
* Return structured allow/block reasons, effective limits, remaining budget,
  assumptions, and evidence refs without contacting a broker or mutating OMS or
  ledger state.
* Add focused deterministic tests before exposing a read-only API or UI status.
* Record the GitNexus blast radius, validation commands, and risk impact for
  every trading-related code change.

Stage 0 first-slice status on 2026-07-10: the isolated versioned policy model,
pure evaluator, deterministic decision fingerprint, structured limits/budgets/
block reasons, safety flags, and focused tests are implemented. There is
intentionally no static config authority, UI, OMS, gateway, broker, or ledger
integration. The second Stage 0 slice now adds append-only evaluation evidence
and status/preview/record/list APIs while keeping runtime authority and broker
submission disabled. Static config remains whitelist preview only and cannot
issue capital authority.

### Stage 0 Completed Acceptance Criteria

* [x] A versioned capital-authorization contract evaluates disabled, per-order,
  and session-bounded modes fail closed across scope, expiry, evidence gates,
  and multi-dimensional hard limits.
* [x] Evaluation returns deterministic fingerprints, structured block reasons,
  effective limits, remaining budgets, and explicit no-submit/no-cancel/no-OMS/
  no-ledger/no-self-expansion safety flags.
* [x] Capital-authorization v2 separates the read-only evidence connector from
  the execution gateway, requires both explicit policy scopes, rejects
  identical/overlapping roles, and requires a verified same-account binding.
* [x] Declared execution-gateway id, health, and submit capability are
  fingerprinted evidence only; the shared binding remains runtime-unverified
  and cannot contact a broker, submit, or authorize execution.
* [x] Preview remains side-effect free, while recorded evaluations use
  append-only local audit events and reuse an existing sequential input
  fingerprint without granting runtime authority.
* [x] Capital-authority status, preview, record-evaluation, and list-evaluation
  APIs expose evidence only; even an allowed evaluation leaves execution
  authority and broker submission disabled.
* [x] API payloads reject undeclared credential fields, and static config cannot
  grant capital execution authority.
* [x] Deterministic tests cover missing, disabled, expired, mismatched,
  over-budget, upstream-gate, persistence, route, sequential-rerun, and
  no-authority behavior.

### Stage 1 Read-Only Broker Soak Foundation

* [x] Explicitly configured generic local read-only exports can be captured as
  sanitized cash, position, order, fill, health, capability, and source-time
  evidence without storing or returning raw account ids.
* [x] Each observation has deterministic snapshot and observation fingerprints,
  append-only local evidence, and sequential rerun reuse without broker-write,
  OMS, or production-ledger side effects.
* [x] Missing read capabilities, any submit capability, stale/future/invalid
  timestamps, source-health degradation, missing cash, or connector exceptions
  fail closed into degraded or blocked soak evidence.
* [x] Healthy-day coverage requires a provider market-calendar snapshot and an
  explicit trading day; missing calendars and closed days do not count toward
  the 20-trading-day target.
* [x] Capture, status, and observation APIs remain read-only with respect to the
  broker, OMS, and ledger, while degraded/blocked observations create sanitized
  Operations alerts.
* [x] Twenty healthy trading days complete only the operational soak;
  `promotion_ready` remains false until Account Truth reconciliation and
  explicit owner acceptance are linked.
* [x] Startup, intraday, and end-of-day runbook phases persist deterministic
  evidence; missing or unhealthy read-only connector observations block the
  phase.
* [x] End-of-day runbook evidence requires a clear execution reconciliation
  with zero open items; otherwise it blocks and creates a sanitized Operations
  alert.
* [x] Disconnect, schema-drift, stale-data, duplicate-evidence, and
  restart-recovery drills record deterministic pass/fail evidence and verify
  safe degradation or sequential persisted-evidence reuse.
* [x] Run and drill APIs reject undeclared fields and credentials, expose only
  sanitized evidence, and cannot submit/cancel orders, mutate OMS/ledger, or
  grant capital authority.
* [x] A broker-neutral operator runbook documents local-export setup,
  startup/intraday/end-of-day cadence, drill preparation, expected safe states,
  review steps, and the unchanged no-write boundary.

### Stage 1.1 Signed Broker Soak Promotion Dossier

* [x] Promotion uses a sanitized, source-sensitive Account Truth fact built
  from the latest persisted import, current ledger projection, reconciliation
  items, review decisions, and score; only pass/fresh/zero-unresolved evidence
  is clear.
* [x] A promotion dossier selects exactly 20 unique healthy read-only trading
  days whose snapshots each bind a clear execution reconciliation with zero
  open items and one stable connector account alias/hash.
* [x] Every selected trading day requires persisted passed startup, intraday,
  and end-of-day runbook evidence for the same connector; incomplete phase
  coverage blocks owner acceptance.
* [x] Disconnect, schema-drift, stale-data, duplicate-evidence, and
  service-instance restart drills must all pass; full process and broker-terminal
  recovery remains an explicit signed owner assertion rather than an automated
  claim.
* [x] The deterministic promotion fingerprint binds the selected observations,
  phase/run ids, drill ids, latest snapshot, account alias/hash, and exact
  Account Truth source fingerprint; source drift requires a new review.
* [x] Owner acceptance requires a short-lived Ed25519 approval for the exact
  promotion dossier and matching operator label; accepted/rejected records are
  append-only, exact reruns reuse evidence, and cross-dossier approval fails
  closed.
* [x] Promotion status, dossier preview, acceptance, and history APIs reject
  undeclared credential fields and expose no capital/runtime authority issue,
  budget reservation, OMS/ledger mutation, gateway contact, submit, cancel,
  resume, or automatic-promotion action.
* [x] Deterministic Account Truth, promotion-service, signature, and route tests
  cover full evidence, missing coverage, blocked Account Truth, source drift,
  exact reuse, rejection audit, credential rejection, and zero execution side
  effects.

### Stage 2 Non-Submitting Per-Order Confirmation Foundation

* [x] A canonical order fingerprint and deterministic dossier bind OMS order
  terms, capital-evaluation evidence, Account Truth/research/risk/paper-shadow
  gateway gates, latest connector soak, prior reconciliation, and kill-switch
  state.
* [x] Dossier review fails closed when the OMS order is not manually confirmed,
  the capital evaluation is missing/stale/mismatched/not allowed, required
  gateway evidence is missing or blocked, the latest soak is unhealthy or no
  longer fresh, prior reconciliation is not clear, or the kill switch is
  unavailable/enabled.
* [x] A current signed Stage 1 promotion may clear only its Stage 1 blockers,
  and an exact current non-submitting gateway verification may clear only the
  runtime-verification blocker; evidence-connector read-only integrity, runtime
  authority, live gateway, and broker submission remain explicit hard blockers.
* [x] Every per-order dossier resolves and fingerprints the current Stage 1
  promotion dossier, operational source, Account Truth source, and verified
  owner-acceptance id for the exact capital-policy connector.
* [x] Missing, invalid, mismatched, or failed promotion resolution remains
  blocked without leaking provider details; source drift changes the per-order
  dossier and invalidates the old artifact-bound operator approval.
* [x] An exact dossier fingerprint can be attested only when review gates and
  an artifact-bound signed operator approval pass; the append-only record is
  sequentially reusable verified-identity evidence that does not authorize
  execution.
* [x] Stale fingerprints and blocked dossiers create deterministic rejected
  confirmation evidence without changing OMS, contacting a broker, or mutating
  the production ledger.
* [x] Status, preview, confirmation, and list APIs reject undeclared credential
  fields and expose no enable, issue-authority, submit, cancel, resume, or
  scale-up operation.
* [x] Deterministic service and route tests cover evidence aggregation,
  fail-closed gates, hard submission blockers, exact-fingerprint reuse,
  rejection audit, credential rejection, and zero execution side effects.

### Stage 2.4 Non-Submitting Execution Gateway Runtime Verification

* [x] Runtime verification resolves a distinct registered execution gateway,
  verified evidence-connector/account binding, complete submit/cancel/query/
  dry-run/idempotency capabilities, and a healthy source-fingerprinted snapshot.
* [x] Gateway health must be healthy, timezone-aware, no more than 60 seconds
  old, not materially future-dated, and bound to a valid source fingerprint;
  missing/stale/provider failure evidence fails closed without leaking details.
* [x] The verifier derives a deterministic client order id and requires dry-run
  acceptance for the exact order fingerprint with a valid payload fingerprint,
  no broker order id, submitted=false, and zero reported side effects.
* [x] Exact accepted or rejected verification attempts are append-only and
  deterministic; sequential accepted reruns reuse one event without submitting
  or cancelling.
* [x] Resolution re-runs current capability, binding, health, and dry-run checks,
  rejects source drift, and expires recorded verification after five minutes.
* [x] Production registers no execution gateway by default; status therefore
  reports no runtime gateway, disabled execution authority, and broker submission
  false.
* [x] Status, preview, record, resolve, and list APIs reject undeclared credential
  fields and expose no gateway registration, authority issue, budget, OMS/ledger,
  submit, cancel, resume, or scale-up operation.
* [x] Deterministic service and route tests cover ready, missing registration,
  capability/account/health failure, unsafe dry-run, source drift, expiry, reuse,
  rejection audit, credential rejection, and zero broker side effects.

### Stage 2.5 Exact Runtime Gateway Verification Binding

* [x] The recorded manual-each-order capital evaluation must contain the exact
  typed execution-gateway verification fingerprint requested by the per-order
  dossier.
* [x] Every dossier re-resolves the current verification and exactly binds
  gateway id, read-only evidence connector, account alias, OMS order id,
  canonical order fingerprint, and the dry-run order contract.
* [x] Missing providers and gateway, connector, account, order, fingerprint,
  status, authority, or submission-state mismatches fail closed with sanitized
  evidence.
* [x] Expiry or source drift changes the dossier fingerprint, re-blocks review,
  restores the runtime-verification hard blocker, and invalidates the prior
  artifact-bound approval.
* [x] A clear non-submitting verification removes only the runtime-verification
  blocker; runtime authority, live gateway, broker submission, and strategy
  direct execution remain blocked.
* [x] Preview and confirmation APIs accept only a valid verification fingerprint,
  inject the closed-by-default runtime registry resolver, reject credentials,
  and expose no submit path.
* [x] Deterministic tests cover exact binding, capital-reference mismatch, scope
  mismatch, provider failure, source drift, approval invalidation, route wiring,
  and zero execution authority.

### Stage 3 Non-Executing Session-Bounded Envelope Foundation

* [x] A proposal requires one recorded `session_bounded` capital evaluation, an
  explicit deduplicated OMS order set, timezone-aware start/expiry timestamps,
  and a maximum 30-minute window contained by the capital policy.
* [x] Canonical order fingerprints, required gateway evidence, conservative
  gross exposure without buy/sell netting, cash, capital, turnover, per-order,
  position-change, liquidity, and projected order-rate budgets are bound into a
  deterministic session envelope.
* [x] Missing/duplicate orders, unsupported OMS states, unpriced market orders,
  out-of-scope symbols, missing/blocked evidence, stale connector soak, open
  reconciliation, kill switch, invalid time, or projected budget excess fails
  closed before attestation.
* [x] An exact fresh envelope can be attested only after review gates pass;
  sequential reruns reuse append-only evidence, while stale fingerprints or
  blocked envelopes create deterministic rejection evidence.
* [x] Exact per-order gateway verification and current session-start Account
  Truth may clear only their respective evidence blockers; Stage 1/2 promotion,
  read-only evidence-connector integrity, per-symbol runtime limits, atomic budget
  reservation, runtime rate limiting, automatic pause, session issuance/resume,
  live gateway, and broker submission remain hard blockers after exact
  prior-batch reconciliation and signed operator approval pass.
* [x] Every proposal and attestation states that it does not issue/enable a
  runtime session, reserve/consume budget, mutate OMS/ledger, contact a broker,
  submit/cancel orders, auto-resume/renew/expand, or scale capital authority.
* [x] Status, preview, attestation, and list APIs reject undeclared credential
  fields and expose no issue, enable, runtime-pause, resume, revoke-runtime,
  submit, cancel, or scale-up action.
* [x] Deterministic service and route tests cover time/scope/evidence/budget
  gates, freshness-stable fingerprints, exact attestation reuse, rejection
  audit, credential rejection, hard blockers, and zero execution side effects.

### Stage 3.3 Per-Order Gateway Verification Set Binding

* [x] A session request maps every OMS order id to one unique gateway-verification
  fingerprint, and the recorded `session_bounded` capital evaluation contains
  exactly the same typed verification-reference set.
* [x] Every envelope re-resolves each current verification and independently
  matches gateway, read-only connector, account alias, OMS order id, canonical
  order fingerprint, and sanitized dry-run order terms.
* [x] Missing, extra, reused, invalid, or mismatched verification references and
  any single-order resolution failure block the whole session envelope.
* [x] Verification expiry or source drift changes the envelope fingerprint,
  restores the runtime-verification hard blocker, and invalidates the prior
  artifact-bound operator approval.
* [x] A fully clear verification set removes only the runtime-verification
  blocker; session authority, atomic budget reservation, automatic pause, live
  gateway, broker submission, and strategy direct execution remain disabled.
* [x] Preview and attestation APIs validate the bounded fingerprint map, inject
  the closed-by-default runtime registry resolver, reject credentials, and expose
  no session-issue or submit path.
* [x] Deterministic tests cover exact multi-order binding, capital-reference-set
  mismatch, missing/reused references, scope/order mismatch, provider failure,
  source drift, approval invalidation, route wiring, and zero execution authority.

### Stage 3.4 Session-Start Account Truth Binding

* [x] Session-start evidence rebuilds current Account Truth and requires a clear
  reconciliation, passing gate, fresh source no more than 120 seconds old, zero
  unresolved mismatches, and explicit zero-authority boundaries.
* [x] Clear and rejected attempts are append-only and deterministic; resolution
  rechecks the current source, detects drift, and expires records after 120 seconds.
* [x] The session request and recorded `session_bounded` capital evaluation bind
  the same typed Account Truth fingerprint, evidence connector, and account alias.
* [x] Missing providers, identity mismatch, expiry, or source drift re-blocks the
  envelope, restores the Account Truth hard blocker, and invalidates the prior
  artifact-bound operator approval without leaking source details.
* [x] A clear binding removes only `session_account_truth_snapshot_not_bound`;
  session authority, atomic budget reservation, automatic pause, live gateway,
  broker submission, and strategy direct execution remain disabled.
* [x] Status, preview, record, resolve, and history APIs use the current Account
  Truth source, reject credentials, and expose no authority, session-issue,
  budget, ledger, or broker-submit action.
* [x] Deterministic tests cover clear/blocked facts, freshness, append-only reuse,
  source drift, expiry, capital-reference and identity mismatch, provider failure,
  envelope approval invalidation, route wiring, and zero execution authority.

### Stage 3.5 Atomic Session Budget Reservation

* [x] Reservation requires a recorded signed envelope and re-resolves its exact
  capital evaluation, Account Truth, gateway dry-runs, prior-batch reconciliation,
  kill switch, time window, and currently trusted operator approval.
* [x] The immutable reservation fingerprint binds the attestation, envelope,
  authorization/account scope, China trading day, exact window, conservative
  gross/cash/turnover amounts, order count, capacities, and fixed 0.0001 CNY units.
* [x] SQLite `BEGIN IMMEDIATE` serializes overlapping reservations and atomically
  rejects unavailable capital, cash, daily turnover, or order-count budget before
  insert.
* [x] Exact reruns reuse one immutable reservation, each attestation can reserve
  only once, and malformed, stale, blocked, or transaction-rejected attempts are
  append-only audit evidence.
* [x] Source drift, signature/key expiry, blocked gates, or window expiry
  invalidates reservation readiness/resolution; expired daily turnover remains
  conservatively reserved for that China trading day until release semantics exist.
* [x] Status, preview, record, resolve, and history APIs reject undeclared
  credentials and expose no session-issue, OMS/ledger mutation, broker
  submit/cancel, renewal, resume, or capital-scale action.
* [x] Deterministic tests cover exact signed-envelope binding, source
  revalidation, fixed precision, idempotency, real concurrent contention, every
  budget dimension, rejection audit, route wiring, and zero execution authority.

### Stage 3.6 Atomic Per-Symbol Runtime Budget

* [x] Every envelope requires an explicit positive per-symbol limit for exactly
  the projected symbol set; missing, extra, malformed, or over-precision values
  fail closed before attestation.
* [x] Each signed symbol limit is no greater than both the recorded capital
  evaluation's symbol ceiling and effective capital, and each conservative
  projected gross amount fits inside its own limit.
* [x] The canonical symbol-limit map is part of the envelope and attestation
  identity, so any limit change changes the envelope fingerprint and invalidates
  the prior artifact-bound operator approval.
* [x] The immutable reservation persists fixed-precision projected and capacity
  maps per symbol, and exact reruns retain those maps without granting session or
  broker authority.
* [x] The same SQLite `BEGIN IMMEDIATE` transaction sums overlapping
  reservations per symbol, allows disjoint symbols inside shared capital,
  rejects same-symbol contention above the strictest limit, and fails closed on
  legacy rows without symbol evidence.
* [x] Envelope APIs require the bounded symbol map, reject undeclared credentials
  and invalid precision, and still expose no session-issue, OMS/ledger mutation,
  broker submit/cancel, resume, renewal, or scale-up action.
* [x] Deterministic tests cover exact-set validation, capital ceilings,
  projection excess, approval invalidation, fixed precision, persisted maps,
  real concurrent same-symbol contention, disjoint symbols, route validation,
  and zero execution authority.

### Stage 3.7 Runtime Rate Limiter Foundation

* [x] Production exposes only read-only status/history routes; there is no
  public preview, admit, submit, or cancel endpoint. Stage 3.9 later supplied
  authenticated sessions and Stage 3.18 requires their fresh live-gate source.
* [x] Internal admission requires a current enabled and authority-verified
  bounded session, a verified budget reservation, clear upstream/kill-switch
  gates, exact session and reservation fingerprints, authorization/account/
  strategy scope, an in-scope order, an active window, and an explicit positive
  rate limit.
* [x] SQLite `BEGIN IMMEDIATE` enforces a server-time 60-second sliding window
  shared by authorization/account, uses the strictest overlapping session rate,
  and admits only one contender for the final concurrent slot.
* [x] Exact request retries reuse one immutable admission, while a second request
  for the same session/order or reuse of one request id for another order fails
  closed and is audited.
* [x] Pause, authority drift, limiter disablement, expiry, out-of-scope orders,
  unsafe rates, and provider failure block before admission without leaking
  session tokens or broker credentials.
* [x] Accepted admissions and rejected attempts are append-only evidence only:
  they do not issue, enable, resume, renew, or widen a session; mutate
  OMS/ledger; contact a broker; or authorize submission/cancellation.
* [x] Deterministic tests cover default closure, sanitized preview, exact
  binding, persistence, retry, boundary time, real concurrency, shared strictest
  rate, replay conflicts, session drift, route exposure, and zero broker
  authority.

### Stage 3.8 Automatic Pause Controller Foundation

* [x] Production wires only the persisted read-only session resolver,
  configures no live gate provider, and exposes only read-only status, state,
  and event routes; there is no public evaluate, pause, resume, submit, or
  cancel endpoint.
* [x] Internal evaluation requires an exact current, enabled,
  authority-verified session identity and binds a sanitized allowlisted gate
  snapshot, reservation id, and deterministic fingerprints without retaining
  provider credentials.
* [x] Missing gate evidence, Account Truth, risk, prior reconciliation,
  paper/shadow divergence, gateway health, market data, budget, rate, kill
  switch, loss/drawdown, rejection, account-change, and consecutive-error facts
  all fail toward pause.
* [x] The first valid pause is persisted as immutable evidence plus a durable
  one-way `paused` runtime state; later clear gates do not automatically resume,
  renew, or replace that state.
* [x] Runtime rate admission checks durable pause state inside its `BEGIN
  IMMEDIATE` transaction, so an applied pause blocks new admissions even if a
  stale provider still claims that the session is enabled.
* [x] Exact and concurrent evaluations reuse one pause event, identity conflicts
  fail closed, and rejected or provider-failure evidence remains append-only and
  sanitized.
* [x] Deterministic tests cover default closure, clear no-op evaluation, every
  hard gate, persistence, real concurrency, no automatic resume, identity drift,
  route exposure, atomic rate blocking, secret sanitization, and zero broker
  authority.

### Stage 3.9 Signed Runtime Session Authority

* [x] Issuance re-resolves one exact current reservation and attestation, binds
  account/strategy/orders/window/rate, and requires a new Ed25519
  `issue_controlled_session` approval plus possession of its signature for the
  deterministic issuance fingerprint; public approval history is sanitized
  and the earlier envelope approval cannot be reused as authority.
* [x] SQLite `BEGIN IMMEDIATE` permits only one session per reservation,
  validates the persisted reservation identity again, reuses exact/concurrent
  retries, and rejects a conflicting session or reservation identity.
* [x] A high-entropy runtime token is returned only on the first successful
  issue response, only a salted hash is stored, list/resolve/rejection evidence
  never exposes it, and every internal rate-admission request requires exact
  token authentication.
* [x] Every resolution rechecks time, durable pause state, and the current
  reservation/attestation chain; expiry, source drift, pause, or identity
  mismatch fails closed without automatically renewing, widening, or resuming
  the session.
* [x] Revocation binds an exact session fingerprint and allowlisted reason to a
  separate Ed25519 `revoke_controlled_session` approval plus matching signature
  possession, persists one immutable event, changes enabled to revoked only
  once, and exposes no resume or re-enable transition.
* [x] Rate admission rechecks persistent enabled status, session/reservation
  fingerprints, effective/expiry time, and pause state inside its own `BEGIN
  IMMEDIATE` transaction, so a stale authenticated provider cannot race
  revocation or pause.
* [x] Public routes expose signed issuance preview/record, sanitized session
  visibility, signed revocation preview/record, and history only; there is no
  resume, renew, widen, runtime admit, broker submit, or broker cancel endpoint.
* [x] Deterministic tests cover exact signatures, replay, real concurrent
  issuance, token secrecy/authentication, expiry, source drift, signed
  revocation, stale-provider race blocking, strict route models, and zero
  broker, OMS, production-ledger, capital-scale, auto-resume, or auto-renew side
  effects.

### Stage 3.10 Persisted Live-Gate Pause Orchestration

* [x] Monitoring resolves the original persistent enabled session even when
  upstream reservation or attestation evidence drifts, while explicitly
  granting no runtime, resume, renewal, widening, or broker authority.
* [x] A typed allowlisted snapshot derives Account Truth, risk, paper/shadow,
  reconciliation, gateway, market data, budget/rate, kill switch,
  loss/drawdown, rejection, account-change, and consecutive-error facts from
  persisted sources; missing or invalid facts fail toward pause.
* [x] Gate snapshots are append-only, fingerprint-bound, sanitized, idempotent
  for an exact observation, queryable by session, and rejected as stale after
  the bounded freshness window.
* [x] Every orchestration evaluation captures current evidence before applying
  the existing durable one-way pause; clear gates are a no-op and no evaluation
  can automatically resume a paused session.
* [x] Periodic evaluation runs only when the explicitly started trading
  scheduler is active, and an operator may trigger evaluation only by
  authenticating the same session token; neither path exposes runtime admission
  or execution authority.
* [x] Persisted runtime admissions enforce the bounded order-count and
  request-rate view, while stale quotes, kill switch activation, rejection
  spikes, consecutive errors, loss/drawdown exhaustion, and unexpected account
  change deterministically trip pause.
* [x] Source drift and provider, identity, persistence, or evaluation failures
  remain fail-closed and sanitized; stored and returned snapshot evidence
  contains no runtime token or provider credential.
* [x] Deterministic service, route, scheduler, persistence, and source-drift
  tests verify pause orchestration with zero broker submission/cancellation, OMS
  or production-ledger mutation, capital widening, session issue/resume, or
  strategy-to-broker path.

### Stage 3.11 Signed Paused-Session Replacement

* [x] Ordinary issuance fails closed while an unexpired enabled session in the
  same authorization/account/strategy scope is durably paused; recovery must
  use the distinct signed replacement contract or explicitly revoke and start a
  genuinely new authorization chain.
* [x] Replacement requires a new current attestation, a new atomic reservation,
  and a short-lived Ed25519 `replace_paused_controlled_session` approval plus
  matching signature possession over the exact replacement artifact; issue,
  revoke, or envelope approvals cannot be reused.
* [x] Recovery binds two post-pause clear gate snapshots spanning at least 60
  seconds, requires the newest snapshot to be no older than 30 seconds, resets
  the stability window after any blocked observation, and rechecks the latest
  fact inside the replacement transaction.
* [x] The replacement must preserve authorization, account, strategy, and
  operator identity; use a subset of prior orders and symbols; and never
  increase reserved gross, cash, turnover, order count, per-symbol amount,
  request rate, or session duration.
* [x] One SQLite `BEGIN IMMEDIATE` transaction records replacement and
  revocation evidence, changes the paused predecessor from enabled to revoked,
  and inserts the new bounded session, so old and replacement authority are
  never simultaneously usable.
* [x] The replacement returns a newly generated token only on the first
  successful response, stores only its salted hash, reuses exact retries without
  reissuing the token, and allows only one of two conflicting concurrent
  handoffs.
* [x] Strict preview/record/history routes expose signed replacement only;
  undeclared credentials are rejected and there is still no in-place resume,
  renew, widen, runtime admit, broker submit, or broker cancel endpoint.
* [x] Deterministic signature, recovery-window, widening, idempotency,
  concurrency, stale-preview, route, and token-secrecy tests verify zero broker
  contact, OMS or production-ledger mutation, capital scale-up, automatic
  resume, or strategy-direct execution.

### Stage 3.12 One-Shot Controlled Broker Submission & Recovery

* [x] Production remains default-closed: the submission service is unavailable
  without an explicitly injected write gateway, current signed release-evidence
  resolver, trusted operator key, and kill-switch provider; no automatic or
  strategy-direct mode is enabled.
* [x] One exact non-paper `manually_confirmed` OMS order must re-resolve its
  current per-order confirmation, Account Truth, risk, paper/shadow, exact
  prior-batch reconciliation, signed connector promotion, and runtime gateway
  verification; source or fingerprint drift fails closed.
* [x] Broker contact requires a separate short-lived Ed25519
  `submit_confirmed_broker_order` approval and signature-possession proof over
  the exact order, client order id, gateway, release evidence, dry-run, and
  submit fingerprint; earlier approvals cannot be reused.
* [x] One SQLite `BEGIN IMMEDIATE` transaction persists the immutable submit
  intent and moves OMS from `manually_confirmed` to `submission_pending` before
  any external call; exact retries are read-only and concurrent requests permit
  at most one gateway submission.
* [x] Submit preview and the final pre-call check require the exact gateway
  capabilities, fresh healthy status, side-effect-free dry-run, current signed
  broker/regulatory release assertions, and a clear kill switch; changed or
  missing facts reject before broker contact.
* [x] Definitive accepted and rejected gateway responses persist distinct
  intent/OMS outcomes with sanitized broker evidence, while ambiguous responses
  become `submission_unknown`; no path writes fills or the production ledger.
* [x] An unknown submission can never call submit again; after a deterministic
  30-second wait, recovery may only query the same idempotent client order id,
  and query failure or ambiguity remains unknown.
* [x] Strict status/preview/submit/query-recovery/history routes reject
  undeclared credentials and expose no strategy submission, automatic
  execution, session-wide submission, capital widening, broker cancel, fill
  apply, or ledger-sync action; deterministic tests cover terminal, unknown,
  retry, concurrency, signature, and kill-switch boundaries.

### Stage 3.13 Unreconciled Submission Interlock & Visibility

* [x] Preview and status fail closed when any other controlled intent is
  `prepared`, `submitted`, or `submission_unknown`; the response identifies
  only sanitized intent/order/status evidence and never treats an accepted
  broker acknowledgement as reconciliation.
* [x] The same interlock is rechecked inside SQLite `BEGIN IMMEDIATE` before
  intent insertion, so two different concurrently confirmed orders cannot both
  receive permission for an external call.
* [x] Only a definitive rejected/not-found outcome removes the current
  interlock in this stage; unknown and accepted-but-unreconciled outcomes remain
  blocked, exact retries remain read-only, and recovery remains query-only.
* [x] Execution reconciliation consumes persisted submit intent evidence and
  distinguishes pending/unknown, accepted awaiting broker evidence, matching
  staged broker evidence, quantity/evidence conflict, and definitive rejection
  without inferring fills.
* [x] Matching imported broker evidence remains an open human reconciliation
  item; it does not infer an OMS fill, apply a broker callback, write a fill,
  mutate the production ledger, or clear the next-order interlock.
* [x] Automation alert scanning raises a critical, sanitized alert for an
  unknown controlled submission, states that new submissions are blocked, and
  exposes only query recovery with resubmission disabled.
* [x] Operations surfaces controlled-submission review and unknown counts, the
  sanitized first open item, and the query-recovery next action from each
  order's latest reconciliation fact ahead of ordinary execution review,
  without deleting history or adding a submit, retry, or ledger action.
* [x] Deterministic concurrency, terminal, unknown, reconciliation, alert, and
  Operations tests preserve manual final authority and prove no strategy-direct
  or automatic submission, broker cancel, fill apply, ledger sync,
  reconciliation self-clear, or capital widening.

### Stage 3.14 Signed Full-Fill Reconciliation Clearance

* [x] Clearance is available only for the current `submitted` controlled intent
  and its latest exact `controlled_submission_broker_evidence_available`
  reconciliation item; superseded or changed evidence fails closed.
* [x] Matching broker trade events must come from one validated import and
  aggregate to the exact OMS quantity; partial totals, cross-import aggregation,
  side/symbol drift, and changed row fingerprints remain blocked.
* [x] Canonical broker evidence v2 may persist optional `broker_order_id` and
  `client_order_id`, but controlled clearance requires both to match the exact
  persisted submit intent. Missing, unsafe, or conflicting identities fail
  closed and cannot release the interlock; the fields never grant broker-write
  authority.
* [x] Clearance re-resolves Account Truth no older than 120 seconds and requires
  clear gates, zero unresolved reconciliation items, covered ledger evidence,
  and the same broker import and file fingerprint as the selected trade events.
* [x] Final clearance requires a separate short-lived Ed25519
  `clear_controlled_submission_reconciliation` approval and
  signature-possession proof bound to the exact clearance fingerprint;
  submission signatures cannot be reused.
* [x] One SQLite `BEGIN IMMEDIATE` transaction records real fills, moves OMS
  `submitted -> accepted -> filled`, persists the signed clearance, and appends
  a terminal no-action reconciliation fact without mutating the production
  ledger.
* [x] The cross-order interlock releases only after that atomic persisted
  clearance; exact concurrent retries are idempotent, conflicting retries fail
  closed, and an open or manually tagged reconciliation item cannot release it.
* [x] Recorded fills retain provider, broker-order, Account Truth import,
  row-fingerprint, and clearance-run linkage so exact prior-batch reconciliation
  can consume them while ledger application remains a separate reviewed
  workflow.
* [x] Strict status/preview/record/history routes reject undeclared credentials
  and expose no strategy-direct or automatic submission, partial-fill
  clearance, broker cancel, automatic ledger sync, session widening, or capital
  increase action.

### Stage 3.15 Broker-Neutral Exact-Order Lifecycle Evidence Foundation

* [x] A strict normalized `karkinos.broker_order_lifecycle_export.v1` contract
  accepts one `exact_order_lifecycle` snapshot for one exact broker/client order
  identity. `provider` records provenance but never selects or contacts an adapter.
* [x] `scripts/import_broker_order_lifecycle.py` is preview-only by default.
  Persistence requires `--record` and the exact acknowledgement
  `record_broker_order_lifecycle_evidence_without_execution_authority`; source
  paths and raw account ids are not persisted.
* [x] The parser rejects credential/unknown fields, non-UTF-8 or oversized
  input, stale/future/non-timezone timestamps, unsafe ids, invalid status or
  fill/cancel arithmetic, duplicate trades, mismatched order identities,
  inconsistent fill totals, and average-price drift.
* [x] An independent SQLite repository stores sanitized account hashes,
  source/file/evidence fingerprints, account/gateway sequence, exact normalized
  order/fill facts, and explicit blockers. `BEGIN IMMEDIATE` makes retries
  idempotent and fails closed on sequence regression/reuse, account identity
  change, broker/client mapping drift, order-contract drift, and post-preview
  mutation.
* [x] Read resolution uses only persisted rows and does not create missing
  tables. Execution reconciliation projects open, partial-fill, partial-fill-
  cancel, zero-fill cancel, full-fill-awaiting-independent-evidence, blocked,
  and identity-conflict states without changing OMS, fills, ledger, broker, or
  capital authority.
* [x] Lifecycle full-fill alone remains insufficient for clearance. The one-
  import broker statement, fresh clear Account Truth, exact identities, and
  separate Stage 3.14 operator signature remain required; partial/cancel rows
  cannot clear or infer terminal OMS state.
* [x] One canonical lifecycle-clearance predicate runs in reconciliation, the
  signed-clearance `BEGIN IMMEDIATE` transaction, interlock preview, and the
  next-order submit transaction. A pre-clearance contradiction rejects the
  transaction; a later contradiction reopens reconciliation and makes the old
  intent unresolved before another external call.
* [x] Deterministic tests cover preview/record acknowledgement, privacy,
  idempotency, sequence and identity drift, partial fill, partial cancel, full-
  fill evidence separation, signed-clearance race rejection, post-clearance
  re-blocking, next-order transaction rejection, and zero OMS/ledger/cancel
  side effects.
* [x] The retired `karkinos.qmt_order_lifecycle_export.v1` schema is isolated
  behind `scripts/migrate_legacy_qmt_order_lifecycle.py`; the canonical importer
  rejects it and no existing historical row is silently rewritten.

### Stage 3.16 Broker-Neutral Collector Ingestion Boundary

* [x] A strict `karkinos.broker_order_lifecycle_collector_batch.v1` contract
  binds run/deployment/version/release/user-authorization evidence, provider and
  account scope, connection/batch state, cursor transition, callback telemetry,
  and exactly one canonical lifecycle fact for a complete batch.
* [x] The local CLI is preview-only by default and explicitly started by the
  operator. Callback/poll/replay/fixture are evidence labels only; no broker SDK,
  provider connection, scheduler, or auto-start registration exists.
* [x] Two-phase prepare/commit persists the sanitized lifecycle observation
  before cursor advance. Deterministic fixtures cover restart replay, exact
  idempotency, different-run duplicates, cursor conflicts/regression/gaps,
  deployment drift, duplicate/out-of-order callback telemetry, disconnect, and
  partial batches.
* [x] Collector evidence cannot submit/cancel, call strategy code, modify OMS,
  fills, production ledger, risk, kill switch, capital authority, or interlock
  release. Read paths do not create absent databases.
* [ ] Before any real-provider soak, separately review the chosen edge adapter's
  dependencies, credentials, read-only capabilities, deployment/release/rollback,
  recovery semantics, and user authorization. QMT, PTrade, local-file watchers,
  and other adapters remain replaceable and default-unregistered; none is an
  official support claim.

### Stage 3.17 Collector Operational Evidence Binding

* [x] The canonical lifecycle resolver derives a broker-neutral collector
  binding from persisted run/state rows only; it never contacts a provider or
  creates missing collector tables.
* [x] Scopes with no collector history remain explicitly `not_configured` and
  preserve the Stage 3.15 offline-import boundary. Once a scope records a
  collector run, later lifecycle facts must remain bound to that collector
  history rather than bypassing it through a direct import.
* [x] Recorded, observation-bound, cursor-consistent evidence resolves healthy.
  Prepared restart recovery, blocked disconnect/partial batches, unbound facts,
  and run/state drift resolve non-healthy; duplicate runs cannot mask a later
  effective failure.
* [x] One additive fail-closed blocker is consumed by execution reconciliation,
  the signed-clearance writer transaction, interlock resolution, and the next-
  order writer transaction. A race can only reject or invalidate clearance.
* [x] Deterministic fixtures cover healthy binding, restart prepare/commit,
  direct-import bypass rejection after scope adoption, partial/disconnected
  re-blocking, signed-clearance race rejection, post-clearance next-order
  rejection, and the optional no-history path.
* [x] The binding grants no submit/cancel/live permission and cannot modify OMS,
  fills, production ledger, risk, kill switch, capital authority, or collector
  cursor/state from a read path.

### Stage 3.18 Fresh Live-Gate-Bound Session Order Admission

* [x] Internal admission v2 binds the exact latest persisted live-gate snapshot
  id, fingerprint, observed time, and session fingerprint into its deterministic
  evidence identity; a snapshot may be no more than 30 seconds old.
* [x] Preview fails closed when the snapshot provider is absent or fails, or
  when the snapshot is missing, stale, future, blocked, or belongs to another
  session identity. Provider values are reduced to a strict sanitized allowlist.
* [x] The admission `BEGIN IMMEDIATE` transaction re-reads the latest snapshot
  before checking replay/rate limits. A newer blocked or different snapshot
  wins over a clear preview and leaves no admission row.
* [x] Existing session enabled/expiry/revocation/pause, order scope, reservation,
  shared strictest rate, request idempotency, and concurrency gates remain
  mandatory; the change removes no prior blocker.
* [x] Production wires the authenticated session and persisted live-gate readers
  but still exposes status/history only. There is no public runtime-admit,
  strategy-direct, broker submit/cancel, or recovery action.
* [x] Deterministic tests cover missing providers, stale/blocked/future/identity
  drift, preview-to-transaction replacement, revocation race, rate/budget
  exhaustion, exact retry, concurrency, sanitization, and zero OMS/fill/ledger/
  broker side effects.

### Stage 3.19 Persisted-Fact Operator View and Explicit Lifecycle Read Boundary

* [x] Automation Cockpit v2 derives controlled-session authorized capital,
  effective capital at risk, capital/cash/turnover headroom, remaining order
  slots, symbol scope, expiry, latest order/submission, reconciliation,
  live-gate, pause, and blocker evidence from persisted database facts only.
* [x] Missing, stale, future, expired, revoked, paused, unreconciled, invalid,
  unavailable, or truncated inputs fail closed. The view cannot issue, renew,
  resume, widen, submit, cancel, or automatically scale capital.
* [x] Broker health/query and automation alerts consume only persisted generic
  broker-order-lifecycle collector runs. GET/alert paths never call an adapter,
  open an export file, contact a provider, or silently refresh account facts.
* [x] `provider` remains provenance. Third-party adapters are replaceable,
  default-unregistered edge components requiring separate dependency,
  credential, capability, failure-mode, release, rollback, and user-
  authorization review before use.
* [x] The former runtime connector snapshot entry is an explicitly labelled
  migration surface to the canonical lifecycle evidence view. It returns no
  live cash, position, order, or fill facts and grants no execution authority.
* [x] Decision Cockpit and alerts expose only sanitized read-only evidence and
  no submit/cancel/resume/ledger-sync/capital-widening controls. Deterministic
  fakes prove empty defaults, blocked evidence, restart-safe persistence,
  adapter-call rejection, pause/reconciliation visibility, and zero broker or
  financial-state side effects.

### Stage 4 Evidence-Based Capital Scaling Review Foundation

* [x] Versioned current/proposed capital tiers and a deterministic evidence
  contract cover reviewed trading days, orders/fills/rejects, reconciliation
  latency/gaps, slippage, after-cost result, drawdown, capacity, liquidity,
  paper/shadow divergence, disconnects, policy violations, and incidents.
* [x] Scale-up review requires at least 20 reviewed trading days, 50 orders,
  required Account Truth and provenance references, passing fill/rejection/
  slippage/after-cost/drawdown/capacity/liquidity/reconciliation/divergence/
  disconnect thresholds, and a proposed tier that actually widens at least one
  explicit limit.
* [x] Invalid or insufficient evidence recommends hold, degraded execution
  quality recommends scale-down, and critical incidents, policy violations,
  unresolved reconciliation, or current-tier drawdown exhaustion recommends
  disable before any scale-up review.
* [x] Preview is side-effect free; recorded evaluations use deterministic
  fingerprints and append-only sequential reuse without changing authority.
* [x] Human review decisions bind one persisted evaluation fingerprint; a human
  may choose the recommendation or a safer action but cannot request scale-up
  when the evidence recommendation is hold/scale-down/disable.
* [x] Even an eligible scale-up decision only records a request for a separate
  new authorization; automatic scale-up, new authorization issuance, runtime
  limit mutation, execution resume, and broker submission remain disabled.
* [x] Status, preview, evaluation, decision, and list APIs reject undeclared
  credential fields and expose no apply-tier, issue-authority, mutate-limit,
  enable/resume execution, submit/cancel, or automatic scale-up action.
* [x] Deterministic service and route tests cover eligibility, hold, scale-down,
  disable, invalid evidence, provenance, fingerprint reuse, safer human choice,
  rejected overreach, credential rejection, and zero authority side effects.

### Stage 4.1 Fail-Closed Persisted Evidence Resolution

* [x] Broker-soak observations, execution-reconciliation runs, paper/shadow
  runs, and risk decisions resolve by typed identifier from persisted stores
  rather than by trusting the caller-provided reference string alone.
* [x] Missing, invalid, out-of-window, or non-clear persisted source facts fail
  closed with typed blockers; only sanitized source fingerprints and status
  fields are returned.
* [x] Account Truth, after-cost, incident-window, and capacity/liquidity refs
  must resolve through a recorded computed evidence window; caller-declared
  aggregate metrics alone remain blocked.
* [x] Preview and recorded evaluation evidence bind the review-input fingerprint
  to a deterministic persisted-source resolution fingerprint, so source changes
  create a different evaluation identity while exact reruns reuse the
  append-only record.
* [x] A mathematically eligible scale-up recommendation is converted to hold
  when persisted sources are unresolved; attempted human overreach is rejected
  and audited without issuing authority.
* [x] Evidence resolution remains read-only with respect to Account Truth, OMS,
  runtime limits, broker gateway, and production ledger; automatic scale-up and
  broker submission remain disabled.

### Stage 4.2 Computed Scaling Evidence Windows

* [x] Account Truth point snapshots persist only a sanitized
  pass/fresh/zero-unresolved score summary, require capture within 15 minutes
  of the source import, and reuse an append-only deterministic identity.
* [x] A review window requires two distinct clear Account Truth point snapshots
  near its start and end boundaries; missing, stale, blocked, reused-as-both, or
  out-of-tolerance boundary evidence fails closed.
* [x] After-cost return is computed from persisted start/end portfolio equity
  and time-weighted external cash flows using Modified Dietz; incomplete
  boundary or Account Truth coverage blocks the fact.
* [x] Incident evidence counts persisted critical alerts, rejected live submit/
  cancel attempts, and read-only connector disconnect observations without
  treating acknowledgement as deletion of incident history.
* [x] Capacity/liquidity and slippage metrics use only non-simulated fills with
  broker/provider/order linkage plus Account Truth, reconciliation,
  capacity-model, and market-data references; incomplete real-fill metadata
  blocks the fact and maximum utilization is retained.
* [x] Evidence-window preview accepts only a time window and boundary tolerance;
  computed metrics cannot be supplied by the caller, while recorded windows are
  append-only, fingerprinted, and sequentially reusable.
* [x] Any capped source scan that reaches its 5,000-row limit is marked
  truncated and blocks the computed fact instead of treating unseen rows as
  evidence that no incident, cash flow, fill, or boundary fact exists.
* [x] The resolver requires Account Truth and verifies the recorded window,
  per-fact fingerprint, exact review window, clear status, metric equality, and
  fill coverage before a scale-up request can be recorded.
* [x] Evidence status/snapshot/window APIs reject undeclared credential or
  metric fields and expose no authority issue, limit mutation, OMS/ledger write,
  broker submit/cancel, resume, or automatic scale-up operation.

### Stage 4.3 Computed Operating Sample

* [x] The operating sample computes reviewed trading days and non-paper OMS
  order counts from persisted broker-soak, order, transition, and fill facts
  inside the review window.
* [x] Filled, rejected, partially filled, cancelled, expired, and nonterminal
  outcomes remain distinct; filled counts require reconciled real quantity and
  invalid or overfilled samples fail closed.
* [x] The latest reconciliation run must cover every sampled order, unresolved
  items are counted, and p95 latency is derived from persisted order/fill/
  transition time to the first no-action reconciliation.
* [x] Paper/shadow divergence is counted from persisted paper/shadow order facts
  for the same window, and a real order sample without paper/shadow comparison
  evidence is blocked.
* [x] Maximum drawdown is computed from cash-flow-unitized portfolio equity so
  deposits and withdrawals do not masquerade as trading profit or loss.
* [x] Missing Account Truth, healthy broker-day, real-fill linkage, OMS terminal
  state, reconciliation latency, paper/shadow sample, drawdown series, or
  complete capped scan blocks the operating sample.
* [x] `operating_sample:<window_id>` is a required clear source and the resolver
  compares all nine caller-declared sample, reconciliation, divergence, and
  drawdown metrics to the recorded fact exactly.
* [x] Operating-sample source references, metrics, blockers, and assumptions
  participate in the evidence-window fingerprint, so exact reruns reuse one
  append-only record and source changes produce a new identity.
* [x] Operating-sample computation and resolution are read-only with respect to
  Account Truth, OMS, runtime limits, production ledger, and broker gateway;
  they never issue authority or submit/cancel an order.

### Stage 4.4 Exact Execution-Scope Binding

* [x] Evidence-window v2 derives the reviewed order ids once in the computed
  operating sample and adds a required `execution_scope:<window_id>` fact; the
  caller cannot supply or replace that order set.
* [x] Every sampled order must bind either one persisted controlled-session
  rate admission or one recorded exact batch-reconciliation fact that remains
  current and clear.
* [x] Runtime bindings recheck admission schema, immutable row/payload identity,
  live-gate verification evidence, non-authority flags, matching persisted
  session identity, and the admission-time effective/expiry window. A session
  may be expired or revoked now without erasing valid historical evidence.
* [x] Exact-batch bindings are re-resolved against current OMS, transition,
  fill, and reconciliation facts and must be wholly contained in the review
  sample; later source drift or a cross-window batch blocks the fact.
* [x] Missing, duplicate/ambiguous, invalid, orphan, or truncated session/batch
  evidence fails closed and reports deterministic counts without inferring a
  favorable scope.
* [x] Capital-scaling review, decision, audit, evidence-window, and resolution
  contracts use v2 semantics and require execution-scope provenance before a
  scale-up request can be recorded.
* [x] Historical v1 windows remain append-only/listable but cannot satisfy the
  current resolver. Migration is an explicit recomputation into a new v2
  record; existing evidence is never rewritten or silently upgraded.
* [x] Deterministic tests cover exact-batch success, missing binding, batch
  source drift, valid historical session admission, and legacy v1 rejection.
  The feature cannot issue/renew/resume/widen authority, mutate OMS/ledger/risk/
  kill switch, or submit/cancel a broker order.

### Stage 2.1 / 3.1 Exact Prior-Batch Reconciliation Evidence

* [x] A batch manifest binds a non-empty unique set of at most 100 non-paper OMS
  orders to one explicit persisted execution-reconciliation run.
* [x] Every batch order must have exactly one no-action reconciliation item
  whose recorded OMS status still matches a current filled, rejected,
  cancelled, or expired terminal state.
* [x] A filled batch order requires exact real-fill quantity plus provider,
  broker-order, Account Truth import, and same-run reconciliation linkage;
  incomplete or excess fill evidence blocks the batch.
* [x] OMS order, transition, real-fill, reconciliation item, and run facts
  participate in one deterministic fingerprint, and any later source change
  invalidates the recorded prior-batch gate.
* [x] Exact clear or blocked batch evidence is append-only and sequentially
  reusable, while stale fingerprints and invalid acknowledgement attempts
  create deterministic rejection evidence.
* [x] Per-order dossier review requires the request and recorded capital
  evaluation to reference the same resolved clear prior-batch fingerprint
  instead of trusting the latest reconciliation run.
* [x] Session-envelope review requires the request and recorded capital
  evaluation to reference the same resolved clear prior-batch fingerprint;
  missing, blocked, or changed batch facts fail closed.
* [x] Batch status, preview, record, resolve, and list APIs reject undeclared
  credential fields and cannot issue or expand authority, reserve budget,
  mutate OMS/ledger, contact a broker, or submit/cancel an order.

### Stage 2.2 / 3.2 Signed Operator Approval Evidence

* [x] Trusted operator identities are configured with an operator id, key id,
  enabled flag, and Ed25519 public key only; malformed keys, unsupported
  algorithms, duplicate identities, and private/secret fields fail closed.
* [x] Each short-lived challenge binds a server nonce, operator/key identity,
  action, artifact type, exact artifact fingerprint, issued time, and expiry
  into one canonical signing payload.
* [x] Ed25519 verification fails closed for invalid signatures, expiry, action/
  type/fingerprint mismatch, disabled or rotated keys, and cross-artifact reuse;
  rejections are append-only and exact verification reruns reuse one approval
  record.
* [x] Per-order confirmation requires a current verified approval for the exact
  dossier fingerprint and matching operator label; only the recorded evidence
  clears the identity blocker, without changing OMS or authorizing broker
  submission.
* [x] Controlled-session attestation requires a current verified approval for
  the exact envelope fingerprint and matching operator label; it clears only
  the recorded identity blocker and never issues, enables, or resumes a runtime
  session.
* [x] Approval resolution rechecks the currently enabled trusted public key and
  fingerprint, so disabling or rotating a key invalidates earlier approval
  evidence instead of preserving stale identity authority.
* [x] Status, challenge, verification, and list APIs reject undeclared
  credential/private-key fields, expose only sanitized public-key fingerprints
  and signing payloads, and provide no authority, budget, OMS, ledger, gateway,
  submit, cancel, resume, or scale-up action.
* [x] Deterministic service, configuration, integration, and route tests use the
  maintained cryptography library to cover valid signatures, invalid
  signatures, expiry, replay, key rotation, exact-artifact binding, credential
  rejection, and zero execution-authority side effects.

## Deferred Capabilities

These capabilities remain intentionally out of scope until the professional
platform foundation is mature:

* Default automatic real-money trading.
* Unattended or permanently authorized full-account real-money order
  submission.
* Broker password storage.
* Black-box AI strategy auto-buy or auto-sell.
* Community strategy marketplace.
* High-frequency trading.
* Institution-grade multi-account OMS.
* Guaranteed-return or investment-advice claims.
* Returns or account states shown without data-quality and source-status
  disclosure.
