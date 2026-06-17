# Karkinos Implementation Log

This file keeps historical implementation progress out of the strategic goal
page and roadmap. Entries are factual implementation notes, not user-facing
roadmap promises.

## v0.6 Progress

* 2026-06-17: Started Account Truth with a canonical broker statement CSV
  contract and read-only import preview parser. The parser normalizes local CSV
  rows into broker evidence preview events, validates required columns and
  event types, computes file-level and row-level SHA-256 fingerprints, reports
  deterministic duplicate rows, and records limitations that the preview does
  not mutate the production ledger or enable broker submission. README and
  Chinese docs now describe the import workflow, privacy boundary, and safe
  synthetic examples.
* 2026-06-17: Added staged broker evidence persistence for valid import
  previews. `BrokerEvidenceRepository` creates local `broker_import_runs` and
  `broker_evidence_events` tables, stores source type, file fingerprint, row
  counts, validation status, duplicate counts, timestamps, limitations, and
  typed evidence events for trades, dividends, fees, taxes, transfers,
  position snapshots, and cash snapshots. Duplicate files are recorded as
  warning import runs without duplicating evidence rows, and deterministic
  tests verify the production ledger is not mutated.
* 2026-06-17: Added the first deterministic reconciliation report core.
  `build_reconciliation_report()` compares staged broker evidence against
  Karkinos cash, positions, ledger fees, ledger taxes, and position cost basis,
  returning versioned `pass`, `warning`, `mismatch`, or `blocked` reports with
  per-category differences and suggested review actions. The report remains
  evidence only; it does not write ledger entries, change holdings, or submit
  broker orders.
* 2026-06-17: Added manual review persistence for reconciliation items.
  `ManualReviewRepository` records `accepted`, `ignored`, `known_difference`,
  `ledger_candidate`, and `needs_investigation` decisions keyed by import run
  and reconciliation item. Decisions are idempotent audit notes only;
  `ledger_candidate` does not create production ledger entries without a
  future explicit confirmation path.
* 2026-06-17: Added deterministic Account Truth Score generation.
  `build_account_truth_score()` converts reconciliation report status, manual
  review decisions, account/data freshness, and unresolved cash, position, fee,
  tax, and cost-basis differences into a versioned 0-100 score with
  `pass`, `degraded`, or `blocked` gate status, required actions, blocking
  reasons, and limitations. The score is report/gate evidence only and does
  not mutate ledger, holdings, or broker state.
* 2026-06-17: Connected Account Truth Score evidence to strategy promotion
  readiness. `build_strategy_promotion_readiness()` can now consume explicit
  account-truth score evidence; `degraded`, `blocked`, or explicitly missing
  account-truth evidence adds an `account_truth_gate_pass` missing requirement
  while legacy callers that do not pass score evidence remain unchanged.
* 2026-06-17: Connected Account Truth Score evidence to Decision Cockpit.
  `/api/decision/today` and `/api/decision/intraday` now include
  account-truth gate evidence in summaries and candidates. Missing,
  `degraded`, or `blocked` account-truth evidence changes actionable
  candidates to `review_required` and prevents live-like manual-confirm
  readiness without changing broker submission or ledger mutation behavior.
* 2026-06-17: Added Account Truth acceptance audit coverage and CLI registry
  wiring. `build_account_truth_acceptance_audit()` maps all Account Truth and
  reconciliation acceptance criteria to concrete code, docs, deterministic
  tests, and validation commands. `scripts/export_acceptance_audit.py` now
  supports `--audit account_truth` and includes it in `--audit all` without
  using roadmap-version names or writing artifacts by default.

## v0.5 Progress

* 2026-06-17: Added a research evidence acceptance audit manifest.
  `build_research_evidence_acceptance_audit()` maps all completed
  Quant Research Quality & Production Evidence Hardening checkboxes to
  concrete code, docs, deterministic tests, and validation commands without
  changing execution defaults or schema versions.
* 2026-06-17: Started v0.5 by adding target, scope, acceptance criteria, and a
  dedicated progress section for research evidence hardening. The first backend
  implementation slice is a minimal versioned `ResearchEvidenceBundle` and
  analyzer contract for existing backtest runs, without changing Web UI or
  execution behavior.
* 2026-06-17: Implemented the first v0.5 backend evidence slice. Single
  backtest runs now attach `research_evidence_bundle` to `metrics_json` and
  saved report files. The bundle is versioned, includes deterministic analyzer
  outputs for data quality, after-cost evidence, and OOS presence, records
  China-market assumption gaps, and keeps promotion status as human review
  evidence without enabling execution behavior.
* 2026-06-17: Extended the evidence bundle surface to Strategy Lab sweeps and
  comparisons. Each sweep result and comparison item now exposes the same
  `research_evidence_bundle` contract that is persisted in the saved
  `metrics_json`, so multi-run research outputs can be audited without looking
  up each saved result manually.
* 2026-06-17: Connected research evidence gates to promotion readiness.
  Strategy promotion readiness now reads each saved backtest result's
  `research_evidence_bundle.promotion_gate.status`; degraded or blocked
  evidence adds a `research_evidence_gate_pass` missing requirement even when
  after-cost/OOS, risk, paper/shadow, and divergence evidence are otherwise
  present. This keeps shadow/paper eligibility behind the v0.5 evidence gate.
* 2026-06-17: Added explicit evidence references and trade statistics to the
  research evidence bundle. Backtest evidence now records dataset snapshot
  references, strategy metadata availability, after-cost and OOS evidence
  availability, cost-summary availability, fill and trade counts, turnover,
  commission, slippage, and limitation counts so saved reports can be audited
  from one versioned artifact without enabling execution behavior.
* 2026-06-17: Added deterministic rolling OOS evidence for Strategy Lab
  experiments. Backtest requests can now ask for rolling OOS folds over a
  frozen equity curve, producing fold-level train/test evidence, aggregate
  pass rate, worst and mean out-of-sample return, and total OOS cost. The
  research evidence bundle's OOS analyzer summarizes rolling mode, fold count,
  and aggregate fields while explicitly noting that rolling evidence does not
  refit parameters per fold or enable execution behavior.
* 2026-06-17: Added parameter sweep robustness evidence. Sweep responses now
  include a versioned robustness artifact with the best parameter set, local
  neighbor stability, per-parameter sensitivity ranges, grid-grounded
  overfitting warnings, and limitations requiring after-cost, OOS, risk, and
  data-quality review before any promotion consideration.
* 2026-06-17: Exposed research evidence bundles as first-class API and report
  artifacts. Single backtest responses and saved JSON reports now surface the
  same `research_evidence_bundle` at top level while retaining the nested
  `metrics_json` copy for compatibility. README and Chinese docs now explain
  `pass`, `degraded`, and `blocked` gate states, required review evidence, and
  the boundary that evidence does not enable broker order submission.

## Earlier Progress

* 2026-06-17: Added a per-instrument daily PnL entry point. Portfolio positions
  now carry `today_change`, `today_change_pct`, daily baseline price, baseline
  timestamp, and baseline source through the same API used by the holdings
  table and holding detail page. The Web cockpit shows single-stock/fund daily
  PnL beside quote price, market value, since-buy PnL, and baseline evidence,
  so account-level daily movement can be traced back to individual holdings
  without adding broker submission or execution behavior.
* 2026-06-17: Documented portfolio return-accounting semantics. Added a
  Chinese guide for daily PnL, since-buy floating PnL, realized PnL, cash-flow
  treatment, and baseline-price priority so future cockpit and API work can
  keep cost basis, market movement, and external flows separated.
* 2026-06-16: Cleaned Risk explainability notes and top-panel layout. Risk
  recent impact cards and timeline events now route their details through the
  shared Web ledger public-note formatter, suppressing legacy internal notes
  while preserving user-authored English notes elsewhere. The Risk
  explainability top grid now aligns panels at the top and keeps the
  recent-impact list in a local scrollable region.
* 2026-06-16: Fixed Risk explainability event readability so recent impact
  events and timeline trade events use the shared instrument identity metadata
  path instead of rendering raw symbols or internal action strings.
* 2026-06-16: Fixed the Overview 1D equity-curve cash path so same-day ledger
  events are replayed at their ledger timestamp instead of being projected back
  to the market open.
* 2026-06-16: Fixed the Overview 1D equity-curve tooltip path so category
  point-in-time changes are supplied by backend `*_daily_change` fields
  instead of being inferred from the first visible chart point.
* 2026-06-16: Confirmed the v0.2/v0.3/v0.4 acceptance checkboxes had no
  remaining unchecked items, then added a data integrity slice for provider
  reconciliation through deterministic local-cache-vs-provider OHLCV reports.
* 2026-06-16: Made historical OHLCV storage explicitly SQLite-first for local
  audit and query paths while retaining Parquet as a local mirror.
* 2026-06-15: Added a v0.4 Strategy Lab acceptance audit and marked the v0.4
  acceptance criteria complete.
* 2026-06-15: Split Strategy Lab after-cost report assumptions into structured
  cost and slippage evidence.
* 2026-06-15: Reduced raw Strategy Lab parameter-key exposure in the Web
  Backtest comparison panel.
* 2026-06-15: Surfaced persisted Strategy Lab metadata in saved Web Backtest
  reports.
* 2026-06-15: Persisted Strategy Lab strategy metadata snapshots on saved
  backtest reports.
* 2026-06-15: Added Strategy Lab strategy metadata and readable parameter
  labels to the Web Backtest page.
* 2026-06-15: Added the Web Strategy Lab same-dataset comparison review
  surface.
* 2026-06-15: Added a same-dataset Strategy Lab comparison contract.
* 2026-06-15: Added Web Backtest parameter-sweep review.
* 2026-06-15: Added a Web Backtest validation-evidence report panel.
* 2026-06-15: Surfaced Backtest dataset snapshots in the Web report.
* 2026-06-15: Added dataset snapshot metadata to the single Backtest runner.
* 2026-06-15: Refined the Web Backtest strategy-parameter experience for
  Chinese users.
* 2026-06-15: Added the first backend Strategy Lab parameter-sweep API.
* 2026-06-15: Made local Strategy Lab extension scripts runnable through the
  Backtest API path.
* 2026-06-15: Localized Web Backtest strategy parameter labels and
  descriptions while preserving stable API parameter ids.
* 2026-06-15: Fixed the Web Backtest initial-cash control browser validation
  contract.
* 2026-06-15: Added the first local Strategy Lab extension area.
* 2026-06-15: Wired the Web Backtest page to the strategy registry.
* 2026-06-15: Started v0.4 Strategy Lab backend parameter contracts.
* 2026-06-15: Added the v0.4 Strategy Lab Backtesting Engine target to the
  project goal.
* 2026-06-12: Removed the Activity batch fund form's built-in fund candidates.
* 2026-06-12: Exposed latest risk-gate outcomes on signal action cards.
* 2026-06-12: Added a deterministic Profit Discipline smoke path covering
  fixture data cache metadata, feature calculation, after-cost backtest report,
  generated signal, mandatory pre-trade risk gate, action queue risk summary,
  and signal journal audit chain.
* 2026-06-12: Tagged registered strategies with v0.2 benchmark metadata.
* 2026-06-12: Added reusable out-of-sample validation evidence for completed
  backtests.
* 2026-06-12: Wired OOS validation evidence into the backtest run path.
* 2026-06-12: Added a deterministic v0.2 strategy validation matrix.
* 2026-06-12: Added fixture-backed validation backtests for all v0.2 benchmark
  strategies.
* 2026-06-12: Exposed the v0.2 strategy validation matrix through the backtest
  API.
* 2026-06-12: Added a portfolio cockpit API surface.
* 2026-06-12: Made action-card risk gate state explicit.
* 2026-06-12: Added manual-confirmation readiness to action cards.
* 2026-06-12: Added the first action-to-manual-order execution bridge.
* 2026-06-12: Linked manual order decisions back into the signal journal.
* 2026-06-12: Added a deterministic daily paper/shadow run endpoint.
* 2026-06-12: Added a signal journal review/outcome endpoint.
* 2026-06-12: Made the CI contract explicit for Profit Discipline MVP gates.
* 2026-06-12: Added a strategy promotion readiness surface.
* 2026-06-12: Added a paper/shadow divergence review write path.
* 2026-06-12: Added a v0.2 acceptance audit manifest and aligned the goal
  checklist with deterministic evidence.
* 2026-06-12: Started v0.3 shadow-trading reliability work with schema
  versioning and idempotent same-date/action order facts.
* 2026-06-12: Added the first v0.3 data-quality gate to daily shadow runs.
* 2026-06-12: Started the Daily + Intraday Decision Cockpit API surface.
* 2026-06-12: Added the first read-only intraday decision lane.
* 2026-06-12: Attached persisted strategy validation evidence to decision
  candidates.
* 2026-06-12: Added current-state aggregation to decision summaries.
* 2026-06-12: Added the first frontend Decision Cockpit surface.
* 2026-06-12: Added a deterministic v0.3 Decision Cockpit acceptance path.
* 2026-06-12: Completed the v0.3 checklist audit.
* 2026-06-12: Fixed Web cockpit responsive containment.
* 2026-06-14: Improved portfolio analysis responsiveness and audit surfaces.
* 2026-06-14: Moved the return calendar into the Overview cockpit.
* 2026-06-14: Improved the Overview return-calendar empty state.
* 2026-06-14: Consolidated the Overview performance module.
* 2026-06-14: Polished the Overview return-calendar fallback language and
  holdings display.
* 2026-06-14: Connected explainability attribution to deterministic daily
  portfolio valuation when historical price cache is available.
* 2026-06-14: Tightened the return-calendar attribution contract.
* 2026-06-14: Aligned the return calendar with China-market non-trading day
  semantics.
* 2026-06-14: Fixed return-calendar valuation-gap attribution.
* 2026-06-14: Connected return-calendar daily valuation to the authoritative
  local OHLC cache.
* 2026-06-14: Added traceable daily-change breakdowns to the return calendar.
* 2026-06-14: Clarified ledger and holding labels in the web cockpit.
* 2026-06-15: Tightened current-day return attribution and ledger naming.
* 2026-06-15: Separated current valuation from audited return-calendar
  attribution.
* 2026-06-15: Tightened live quote freshness semantics for fund estimates.
* 2026-06-15: Made TuShare fund permission fallback auditable in the cockpit.
* 2026-06-15: Added a Settings data-source operations surface.
* 2026-06-15: Tightened the Settings cockpit density around backend operations.
* 2026-06-15: Added Settings runtime-boundary and safety-register surfaces.
* 2026-06-15: Began cockpit-density cleanup on the Decision page.
* 2026-06-15: Reworked the Risk page summary into boundary and blocking
  registers.
* 2026-06-15: Standardized portfolio return percentages to two decimal places.
* 2026-06-15: Clarified the Portfolio holdings quote board summary cards.
* 2026-06-15: Deduplicated the Portfolio holdings quote board detail surface.
* 2026-06-15: Split Portfolio quote summaries from instrument detail.
* 2026-06-15: Redesigned the Portfolio positions entry affordance.
* 2026-06-15: Upgraded the holding-detail and Market price-structure surface
  from a compact sparkline into a K-line chart with selectable ranges.
* 2026-06-15: Tightened the holding-detail page header.
* 2026-06-15: Added account-level manual trade commission configuration.
* 2026-06-15: Fixed return-calendar detail labels for aggregated periods.
