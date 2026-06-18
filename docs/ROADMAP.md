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
| v0.8 | Active | Strategy Assignment & Attribution Engine |

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

Future roadmap candidates should stay subordinate to data integrity, account
truth, risk gates, paper/shadow review, and manual confirmation:

* Data repair and provider reconciliation command center.
* Richer broker-statement import templates for additional sanitized formats.
* Strategy promotion scorecards that combine research evidence, account truth,
  risk evidence, and paper/shadow divergence.
* Paper/shadow operations improvements that do not introduce broker order
  submission or default real-money automation.

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
