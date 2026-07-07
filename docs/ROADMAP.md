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
| v1.6 | Active | Operations Center & Paper/Shadow Runbook |
| v1.7 | Active | Controlled Broker Execution Bridge |
| v1.8 | Planned | Small-Capital Controlled Auto Pilot |

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
| L2 Paper/shadow operating loop | Active | Scheduled paper/shadow runs, divergence checks, and run summaries should operate without manual data edits. |
| L3 Manual execution assist | Active | OMS, manual tickets, broker evidence import, and execution reconciliation now support safe operator-driven execution paths. |
| L4 Controlled broker bridge | Planned | Broker-specific order previews or submissions may be prepared only after account truth, risk, paper/shadow, and manual review gates pass. |
| L5 Small-capital auto pilot | Planned | A tightly capped, explicitly enabled pilot may automate limited orders only after L0-L4 prove reliable. |
| L6 Unattended real-money automation | Deferred | Fully automatic real-money order submission remains out of scope until every upstream layer is mature and explicitly accepted. |

The next product step is therefore not "auto-buy" or "auto-sell". It is a
repeatable paper/shadow execution loop with an auditable OMS state machine,
then a controlled non-submitting order-ticket bridge. Real broker submission is
preserved as a future roadmap capability, but it stays behind explicit account,
strategy, symbol, order, risk, account-truth, paper/shadow, kill-switch, and
operator-authority gates.

## Automation Gap Matrix

This matrix records what remains between the current product and a safe
automated-quant platform. It is intentionally stricter than "can generate a
signal" because live-like automation is only credible when execution, risk,
account truth, paper/shadow, monitoring, and audit all agree.

| Capability | Current state | Required before live-like automation | Roadmap owner |
| --- | --- | --- | --- |
| Strategy research and validation | Backtests, sweeps, research evidence bundles, after-cost/OOS evidence, and promotion readiness exist. | Promotion decisions must continue to consume account truth, risk, attribution, and paper/shadow evidence before strategy candidates are treated as operational. | v0.4-v1.0, ongoing |
| Daily decision and trading plan | Decision APIs, candidate pool, blockers, batch pre-trade risk, daily trading plan, order intents, and Today's to-dos exist. | Candidate actions must flow automatically into paper/shadow runs, and Today's to-dos must explain every blocked/manual-ready state without raw reason codes. | v1.5-v1.6 |
| Paper/shadow execution | Paper/shadow evidence exists in isolated preview and summary paths. | A daily paper/shadow execution engine must persist run ids, deterministic inputs, simulated order/fill state, fees/taxes, divergence status, retry/idempotency state, and review outcomes. | v1.6.1 |
| OMS state machine | Paper order evidence and OMS concepts exist, but the daily operations loop still lacks a first-class persisted run state for order-intent lifecycle review. | Order intents need staged/submitted/accepted/partially-filled/filled/rejected/cancelled/expired/reconciled states, deterministic client order ids, idempotent reruns, and immutable audit references. | v1.6.1 |
| Broker execution gateway | Manual-ticket gateway status, preview, and creation exist behind evidence gates; connector health, runtime read-only connector snapshot query, staged account/fill query, local order query, and default-rejected cancel contracts exist; broker submission remains disabled. | Replace deterministic connector fixtures with real local read-only adapters and keep bridge actions behind explicit query/dry-run/export-only boundaries before any real connector can be enabled. | v1.7 |
| Order ticket export | Copy-safe manual ticket preview and recorded manual-ticket events exist after manual confirmation and required evidence; exports include operator-form context for field labels, account alias, fee/tax assumptions, net cash impact, remaining-position/cost-basis preview, regular-session constraints, and non-submission safety flags. | Add export/import ergonomics and operator review surfaces before any live broker bridge. | v1.7 |
| Account truth and broker reconciliation | CSV import preview, staged broker evidence, reconciliation reports, manual review states, Account Truth Score, and execution reconciliation API exist. | Automation gates must require fresh account-truth pass/degraded policy, reconcile fills/orders back into local facts, and block stale or unresolved differences. | v0.6-v0.7, v1.7 |
| Risk controls | Mandatory pre-trade risk gate, batch risk checks, cash buffer, concentration, T+1, data-quality, and kill-switch concepts exist. | Live-like execution must enforce global, strategy, account, and per-symbol controls with policy snapshots, escalation notes, and irreversible audit logs. | v1.5-v1.7 |
| Scheduler and runbook | Operations summary exists, but persistent scheduler run records and deterministic rerun state remain incomplete. | Persist scheduled strategy, risk, paper/shadow, reconciliation, and report runs with input snapshots, result hashes, errors, retries, and operator actions. | v1.6 |
| Monitoring and alerting | Risk/operations surfaces show status and next actions; automation alerts cover kill switch, execution-reconciliation gaps, failed paper/shadow automation runs with retry/limitation context, incomplete read-only broker connector health, runtime-degraded connector snapshots, daily-plan risk blockers, stale market-data snapshots, Account Truth mismatch snapshots, and paper/shadow order divergence; paper/shadow divergence summaries now compare expected strategy behavior, simulated execution, account truth, market context, and cost evidence. | Wire future real read-only connector polling into the same alert contract and keep refining operator-facing divergence review surfaces. | v1.6-v1.7 |
| Strategy promotion pipeline | Promotion readiness consumes evidence; strategy assignment and attribution exist. | Add explicit lifecycle states from research-only to paper, shadow, manual-confirmation, controlled bridge pilot, paused, and retired, with promotion/demotion audit. | v1.6-v1.7 |
| Small-capital controlled auto pilot | Not supported. | Add capped account/strategy/symbol budgets, per-order or policy-bounded approvals, drawdown stops, automatic pause, and mandatory reconciliation before the next run. | v1.8 |
| Real-money unattended automation | Not supported. | Deferred until every upstream capability is mature, small-capital pilot evidence is reviewed, and the product owner explicitly accepts the operational and regulatory risk. | Deferred |

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
| G | Small-capital auto pilot: capped strategy/account budgets, hard stops, reconciliation-before-next-run, and automatic pause on divergence. | Explicit opt-in only. |

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
* `auto_pilot_policies` for any future capped small-capital automation
  experiment.

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

The post-v0.8 roadmap moves Karkinos toward a QMT/PTrade-class personal
quant platform while preserving the Karkinos safety boundary. QMT is a useful
reference for broker facts, account snapshots, order/fill state, and local
client integration. PTrade is a useful reference for strategy lifecycle,
strategy context, and backtest/simulation/live-like API ergonomics.

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
* QMT read-only connector exploration as the first China-market broker client
  reference.
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

* [ ] Operations Center can show health, last run, next action, and limitations
  for core data, account, strategy, risk, paper/shadow, scheduler, and audit
  subsystems.
* [ ] Daily run summaries distinguish successful, degraded, blocked, skipped,
  and manual-action-required states.
* [ ] Paper/shadow run summaries include generated order intents, simulated
  fills, fee/cost assumptions, divergence status, and next manual review step.
* [ ] Scheduler reruns are idempotent and record run ids, input snapshots,
  errors, retry state, and limitations.
* [ ] Acceptance audit CLI includes market data, strategy runtime, paper OMS,
  broker evidence, decision workflow, strategy attribution, portfolio
  construction, and operations capabilities as they are completed.
* [ ] Operations records do not commit runtime logs, private account data,
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
  manual-review alerts with divergence-count evidence. Runtime-degraded
  read-only connector health snapshots can also be polled through the broker
  gateway health contract and scanned into manual-review alerts with
  heartbeat/error context, capability scope, read/query capability flags,
  explicit preview/export/dry-run/cancel/submit blockers, and explicit
  non-submission evidence. Paper/shadow divergence summaries now include a
  richer comparison of expected strategy behavior, simulated execution,
  account-truth state, realized market context, cost evidence, and
  non-submission safety flags, and the Decision daily trading plan panel
  renders those report sections as read-only review evidence while Overview
  Today's to-dos surfaces a compact divergence-review summary and Trading
  execution audit shows the latest paper/shadow run evidence. Accepted
  divergence reviews preserve raw divergence status for audit while exposing a
  runbook effective status for manual-confirmation handoff. Read-only connector
  polling now has a local JSON export adapter in addition to deterministic
  fixtures. Market-session automation now uses a trading-plan fingerprint
  idempotency key as the persisted run id, so repeated scheduler invocations
  for the same plan/date update one audit run while changed inputs create a
  new run. Remaining v1.6 work is continued operator-facing divergence review
  and runbook hardening.

### v1.6.1 Implementation Goal — Paper/Shadow Execution Engine & OMS Run Records

This is the active development goal after the daily trading-plan and risk-block
clarity work. It should turn manual-ready order intents into a repeatable
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

* [ ] Backend storage exists for paper/shadow runs, simulated orders, simulated
  fills, status transitions, evidence refs, and run limitations.
* [ ] A service can create or reuse a paper/shadow run from the current daily
  trading plan and returns deterministic counts and evidence refs.
* [ ] OMS transitions reject invalid state moves and record every accepted move
  with timestamp, reason, and source.
* [ ] Paper/shadow fill simulation covers full fill, partial fill, rejection,
  cancellation, expiration, fee/tax projection, and idempotent rerun behavior.
* [ ] `/api/operations/today` includes latest paper/shadow run id, status,
  order/fill counts, divergence status, structured review queue, and next
  manual review step.
* [ ] Decision and Overview surfaces show paper/shadow next actions and
  structured review queue summaries without exposing raw state-machine
  internals or implying broker submission.
* [ ] Backend deterministic tests cover storage, idempotency, state transitions,
  fill simulation, divergence summary, review queue, and no production-ledger
  mutation.
* [ ] Frontend tests cover not-run, review-required, diverged,
  within-expectations, failed paper/shadow states, and structured review queue
  presentation.
* [ ] README/docs keep the safety boundary explicit: paper/shadow records are
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
  writing production ledger entries.

### Acceptance Criteria for v1.7

* [ ] Broker submission remains disabled by default and unavailable unless an
  explicit controlled bridge is configured.
* [ ] A non-submitting order-ticket export path exists before any live broker
  bridge path is considered.
* [ ] Gateway capabilities and health are visible in API/UI and include
  whether the connector can read account facts, query orders/fills, cancel,
  preview, dry-run, or submit.
* [ ] Every live-like order preview requires account-truth, research-evidence,
  risk, paper/shadow, and manual-confirmation evidence.
* [ ] Kill switch, connector capability checks, and per-order confirmation are
  enforced before any live-like bridge action.
* [ ] Strategy code has no broker adapter access; all bridge actions go through
  policy, risk, OMS, gateway, and reconciliation services. A static guard now
  covers the current strategy tree; future private strategies outside the repo
  should use the same contract before any controlled bridge pilot.
* [ ] Strategy promotion state is visible as read-only paper/shadow lifecycle
  evidence, and it does not expose live-promotion controls.
* [ ] Broker callbacks or imported fills are staged as evidence and reconciled
  before any production ledger mutation is suggested.
* [ ] Manual execution forms show user-readable field labels, fee/tax
  components, net cash impact, and remaining-position/cost-basis preview before
  saving a manual execution record.
* [ ] No broker password storage, default real-money automation,
  guaranteed-profit language, or strategy-direct broker submission is
  introduced.

## Target for v1.8

Karkinos v1.8 — Small-Capital Controlled Auto Pilot — is the first milestone
where limited real-money automation may be considered. It is not unattended
full-account trading. It is an explicitly enabled pilot for strategies that
have already passed research, after-cost/OOS validation, paper/shadow review,
manual execution evidence, broker bridge dry-runs, and reconciliation.

The goal is to test whether automation improves execution discipline and
after-cost outcomes under strict loss, size, and operational limits.

### v1.8 Scope

* Per-account, per-strategy, per-symbol, and per-day pilot budgets.
* Maximum order value, maximum position change, maximum turnover, maximum daily
  loss, maximum drawdown, and maximum consecutive-error limits.
* Policy-bound automation modes such as `manual_each_order`,
  `auto_within_cap`, `pause_on_divergence`, and `reconcile_before_next_run`.
* Automatic pause on kill switch, stale market data, account-truth degradation,
  paper/shadow divergence, gateway health degradation, rejected/cancelled order
  spikes, reconciliation gaps, or unexpected ledger/cash/position changes.
* Operator review screens for enabling, pausing, resuming, and retiring pilot
  strategies.
* Pilot performance review comparing backtest expectation, paper/shadow
  expectation, manual execution, bridge execution, and realized after-cost
  outcome.

### Acceptance Criteria for v1.8

* [ ] Auto pilot is impossible unless the account, strategy, connector, and
  execution mode are explicitly enabled in local policy.
* [ ] Every pilot strategy has promotion evidence from research to paper/shadow
  to manual-confirmation to controlled bridge pilot.
* [ ] Hard caps block orders that exceed pilot budget, cash, concentration,
  turnover, drawdown, liquidity, T+1, limit, suspension, or ST constraints.
* [ ] The system automatically pauses pilot mode on data, broker, risk,
  account-truth, reconciliation, or kill-switch failures.
* [ ] Reconciliation must be clear or manually accepted before the next pilot
  run can place another order.
* [ ] UI shows pilot capital at risk, remaining budget, last order, last
  reconciliation result, current blockers, and the exact pause/resume reason.
* [ ] Tests cover policy gating, budget caps, auto-pause, reconciliation-before-
  next-run, idempotency, and no strategy-direct broker access.
* [ ] Documentation states that v1.8 is a capped experiment, not a profit
  guarantee or default unattended trading mode.

## Deferred Capabilities

These capabilities remain intentionally out of scope until the professional
platform foundation is mature:

* Default automatic real-money trading.
* Unattended full-account real-money order submission.
* Broker password storage.
* Black-box AI strategy auto-buy or auto-sell.
* Community strategy marketplace.
* High-frequency trading.
* Institution-grade multi-account OMS.
* Guaranteed-return or investment-advice claims.
* Returns or account states shown without data-quality and source-status
  disclosure.
