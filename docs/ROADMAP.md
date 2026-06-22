# Karkinos Roadmap

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
| v1.1 | Active | Paper Broker & OMS |
| v1.2 | Planned | Broker Evidence Connector |
| v1.3 | Planned | Professional Decision Workflow |
| v1.4 | Planned | Strategy Attribution 2.0 |
| v1.5 | Planned | Risk & Portfolio Construction |
| v1.6 | Planned | Operations Center |
| v1.7 | Planned | Controlled Broker Execution Bridge |

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
* [ ] Backend deterministic tests cover paper fills, partial fills,
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
* User-readable diagnostics for disconnected clients, missing permissions,
  stale snapshots, incomplete fields, and connector limitations.

### Acceptance Criteria for v1.2

* [ ] A capability-based broker connector interface can read account, cash,
  position, order, fill, and health facts without order submission.
* [ ] Connector configuration stays in ignored local config and never stores
  broker passwords or secrets in source control.
* [ ] Read-only broker facts normalize into broker evidence and reconciliation
  inputs without automatically mutating production ledger entries.
* [ ] Decision and Strategy Lab degrade or block when connector evidence shows
  material unresolved account-truth issues.
* [ ] Backend deterministic tests use fake connector fixtures for healthy,
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

* [ ] Daily decision workflow surfaces prioritize data and account-truth
  blockers before strategy opportunities.
* [ ] Each candidate action shows strategy source, market data status, account
  truth status, risk status, research evidence, paper/shadow evidence, cost
  impact, uncertainty, and manual-confirmation state.
* [ ] Decision views do not present action suggestions as certain when data or
  account facts are stale, estimated, missing, or blocked.
* [ ] Frontend tests cover localized no-action, degraded, blocked, and
  review-required decision states.

## Target for v1.4

Karkinos v1.4 — Strategy Attribution 2.0 — should answer whether assigned
strategies are helping the account after separating manual trades, fees, taxes,
cash flows, unsupported movement, and market changes.

### v1.4 Scope

* Account, asset-class, and symbol-level strategy assignment health.
* Signal, review, order, fill, fee, tax, ledger, and position references for
  attribution.
* Strategy-level realized P/L, unrealized P/L, fees, taxes, slippage, manual
  movement, unattributed movement, and cash-flow separation.
* Strategy health indicators for stale evidence, drift from historical
  behavior, paused status, and suggested parameter review.

### Acceptance Criteria for v1.4

* [ ] Strategy performance attribution separates realized, unrealized, fee,
  tax, slippage, manual, unattributed, and cash-flow components.
* [ ] Strategy health can mark assigned strategies as healthy, degraded,
  stale, paused, or needing review.
* [ ] Manual trades and missing-evidence movement are never attributed to a
  strategy by default.
* [ ] Web surfaces explain strategy contribution in localized user-facing
  language and keep internal strategy ids secondary.

## Target for v1.5

Karkinos v1.5 — Risk & Portfolio Construction — should move from single-order
checks toward portfolio construction and explainable rebalancing.

### v1.5 Scope

* Target weights, cash buffer, rebalance thresholds, and low-cost rebalance
  suggestions.
* Account-level, asset-class, symbol, industry, concentration, liquidity, and
  drawdown constraints.
* China-market constraints such as T+1, trading unit, limit up/down,
  suspension, special-treatment risk, fund NAV latency, and fee/tax impact.
* Portfolio-construction explanations that show why to rebalance, hold cash,
  avoid concentration, or defer action.

### Acceptance Criteria for v1.5

* [ ] Portfolio construction recommendations pass account-truth and risk gates
  before appearing as actionable candidates.
* [ ] Rebalance suggestions include target/actual weight, drift, expected
  cost, cash impact, and risk rationale.
* [ ] China-market constraints are explicit in risk evidence and user-facing
  explanations.
* [ ] Backend deterministic tests cover concentration, cash buffer, T+1,
  trading unit, limit, suspension, fee/tax, and drawdown constraints.

## Target for v1.6

Karkinos v1.6 — Operations Center — should make Karkinos observable as a local
personal finance system.

### v1.6 Scope

* Operations surfaces for market data, refresh jobs, broker evidence,
  account-truth reconciliation, strategy runs, paper/shadow runs, scheduler
  jobs, acceptance audits, and system alerts.
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
* [ ] Acceptance audit CLI includes market data, strategy runtime, paper OMS,
  broker evidence, decision workflow, strategy attribution, portfolio
  construction, and operations capabilities as they are completed.
* [ ] Operations records do not commit runtime logs, private account data,
  screenshots, or generated reports to source control.

## Target for v1.7

Karkinos v1.7 — Controlled Broker Execution Bridge — should only be considered
after data, account truth, strategy runtime, paper/shadow, OMS, risk, and
manual review are mature.

### v1.7 Scope

* Broker-specific order previews that remain manual by default.
* Explicit per-order human confirmation, kill switch, connector capability
  checks, account-truth gate, strategy evidence gate, and risk gate.
* A white-list model for any future broker submission capability.
* Full audit trail from signal to evidence bundle, risk decision,
  account-truth state, manual confirmation, order preview, and broker or
  manual execution record.

### Acceptance Criteria for v1.7

* [ ] Broker submission remains disabled by default and unavailable unless an
  explicit controlled bridge is configured.
* [ ] Every live-like order preview requires account-truth, research-evidence,
  risk, paper/shadow, and manual-confirmation evidence.
* [ ] Kill switch, connector capability checks, and per-order confirmation are
  enforced before any live-like bridge action.
* [ ] No broker password storage, default real-money automation,
  guaranteed-profit language, or strategy-direct broker submission is
  introduced.

## Deferred Capabilities

These capabilities remain intentionally out of scope until the professional
platform foundation is mature:

* Default automatic real-money trading.
* Broker password storage.
* Black-box AI strategy auto-buy or auto-sell.
* Community strategy marketplace.
* High-frequency trading.
* Institution-grade multi-account OMS.
* Guaranteed-return or investment-advice claims.
* Returns or account states shown without data-quality and source-status
  disclosure.
