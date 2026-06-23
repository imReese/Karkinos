# Karkinos Implementation Log

This file keeps historical implementation progress out of the strategic goal
page and roadmap. Entries are factual implementation notes, not user-facing
roadmap promises.

## v1.4 Progress

* 2026-06-23: Added a shared Web instrument display helper and applied it to
  the Decision page's candidate cards, signal action queue, and signal journal
  rows. When backend evidence provides a display name, Decision surfaces now
  show the instrument name before the symbol instead of relying on raw symbols
  or legacy candidate titles. Trading execution-audit order and fill facts now
  reuse the same name-plus-symbol helper and prefer display names carried by
  the execution facts before falling back to current holdings. Activity and
  holding-detail execution details also avoid duplicating net cash impact after
  it has already been shown as the primary signed amount, while keeping gross
  amount, quantity, price, and fee breakdowns structured. Frontend tests cover
  that the user-visible Decision surface renders name-plus-symbol labels and
  does not expose the old internal candidate title as the primary audit label,
  that Trading audit rows use fact-level instrument names, and that public
  execution details avoid repeating cash-impact fields. This is display
  formatting only; it does not submit broker orders, mutate account facts,
  change API paths, or change live-like manual-confirmation defaults.
* 2026-06-22: Started the shared public ledger formatter migration by moving
  ledger instrument, note, amount, and entry-type formatting into a shared Web
  module. Overview, Risk explainability conversion, Activity compatibility
  imports, and holding-detail ledger traces now use the shared formatter path,
  and holding-detail tests prove raw ledger entry types such as internal trade
  codes are not rendered in that surface. This is display formatting only; it
  does not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Upgraded account strategy contribution attribution so fully
  linked strategy fills remain the only source of strategy net contribution,
  while tax, fee, slippage, manual ledger movement, missing-evidence fills, and
  external cash flow are separated into distinct report fields. Deterministic
  backend coverage proves that metadata-only strategy fills and manual trades
  are excluded from net strategy contribution by default. This is attribution
  evidence only; it does not submit broker orders, mutate broker facts, or
  change live-like manual-confirmation defaults.
* 2026-06-22: Added structured trade-cost fields to persisted ledger entries.
  Buy and sell ledger rows can now preserve gross trade amount, signed net cash
  impact, JSON fee breakdown, fee-rule id, fee-rule version, and cost-basis
  method while keeping the legacy `amount` and `commission` fields compatible.
  Manual Portfolio trades and Ledger trade imports populate these fields for
  audit and reconciliation. This is accounting evidence only; it does not
  submit broker orders, mutate broker facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Started Strategy Attribution 2.0 + Broker Fee & Cost Basis
  Fidelity with a structured local broker fee schedule and deterministic fee
  breakdown contract. Ignored `config.json` can now hold safe fee-rule
  parameters such as commission rates, minimum commissions, stamp tax,
  transfer fee, other fee rate, rule id, and known limitations while rejecting
  credential-like fields. `StockACommission` and `ETFCommission` expose
  component-level fee breakdowns while legacy total-fee `calculate()` calls
  remain compatible. This is accounting evidence only; it does not submit
  broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.

## v1.3 Progress

* 2026-06-22: Completed localized frontend coverage for Decision no-action,
  degraded, blocked, and review-required states. The Web Decision page now
  formats lane summary decisions through the shared public-label formatter, so
  Chinese and English surfaces do not expose raw internal decision codes such
  as no-action or review-required state ids. Tests assert that localized
  no-action, degraded account truth, blocked data quality, review-required
  decision state, and no-action reasons remain user-readable. This is display
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.
* 2026-06-22: Added decision certainty evidence for candidate actions so stale,
  cached, estimated, unknown, missing, or unavailable market/account evidence
  cannot appear as a certain actionable suggestion. Decision summaries now
  degrade stale/estimated data to review-required, block missing/unavailable
  evidence, hide manual approval entry points until review is complete, and
  localize certainty reasons and required actions in the Web Decision page.
  This is review evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
* 2026-06-22: Added candidate-level evidence-chain fields and Web rendering for
  strategy source, market data status, account truth, risk status, research
  evidence, paper/simulation evidence, cost impact, uncertainty, and manual
  confirmation state. The surface localizes user-facing labels and keeps
  internal action codes out of the UI. This is review evidence only; it does
  not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Connected the decision workflow task surface to the Web Decision
  page with localized task labels, status labels, and next-action labels.
  Decision workflow rendering now places data refresh and account truth before
  strategy evidence, paper/shadow review, and manual confirmation, and tests
  assert that internal action codes are not shown to users. This is display
  and review-order evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
* 2026-06-22: Started Professional Decision Workflow with a stable decision
  summary workflow task surface. Daily and intraday decision summaries now
  order data refresh, account truth, risk review, strategy evidence,
  paper/shadow review, and manual confirmation so data and account-truth
  blockers are visible before strategy opportunities. This is API review
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.

## v1.1 Progress

* 2026-06-22: Added shadow review comparison evidence for strategy candidates,
  paper outcomes, and real account movement. The new
  `analytics.shadow_review` report only attributes a real account movement to a
  strategy when candidate id, paper order id, and strategy id references align;
  unsupported movement remains explicitly unattributed with a review action.
  The report is audit evidence only and does not mutate account facts, ledger
  entries, broker orders, or manual-confirmation defaults.
* 2026-06-22: Added an explicit paper OMS state machine with deterministic
  transitions for staged, submitted, accepted, partially filled, filled,
  rejected, cancelled, expired, and reconciled states. Paper order payloads now
  retain full OMS transition evidence in addition to the compact status
  history, and tests cover idempotent repeated transitions plus invalid path
  rejection. The state machine is paper-only review evidence and does not
  submit broker orders, mutate production ledger entries, or change manual
  confirmation defaults.
* 2026-06-22: Added the first Paper Broker & OMS evidence slice. The new
  `execution.paper_broker` module records paper-only order and fill evidence
  into the existing order/fill fact tables with
  `karkinos.paper_broker.v1` payloads, status history, fee/slippage fields, and
  optional strategy, signal, risk decision, dataset, cost model, and
  account-truth references. Tests verify that paper evidence does not mutate
  production ledger entries. This does not introduce broker submission, broker
  credentials, default real-money automation, or any change to manual
  confirmation defaults.

## v1.0 Progress

* 2026-06-22: Completed the v1.0 documentation and backend coverage acceptance
  evidence. The bilingual strategy primer now explains built-in strategy ids,
  parameter meanings, risk assumptions, custom strategy placement under
  `strategy/extensions/` or `KARKINOS_STRATEGY_EXTENSION_DIR`, sanitized
  extension templates, and the non-investment-advice/manual-confirmation
  boundary. Added deterministic documentation coverage tests, and confirmed
  existing backend tests cover lifecycle ordering, read-only runtime context,
  output normalization, extension discovery, and blocked unsafe extension
  manifests.
* 2026-06-22: Added a shared market-calendar contract for Strategy Runtime and
  the Web return calendar. `data.market_calendar` and the Web shared
  `market-calendar` helper expose the same
  `karkinos.market_calendar.v1` schema semantics for trading days, weekends,
  configured market holidays, and configured closed days. Strategy Runtime
  context now carries the calendar as read-only review context, while the Web
  return calendar explains non-trading blank dates as weekend, holiday, or
  closed instead of rendering them as missing prices or zero-return trading
  days. This is calendar explanation evidence only; it does not fetch broker
  data, submit orders, change risk gates, or change manual-confirmation
  defaults.
* 2026-06-22: Tightened the shared Strategy Registry contract for built-in and
  extension strategies. Registry entries and `/api/backtest/strategies` now
  expose the same capability-based contract version, strategy schema version,
  source type, extension flag, parameter schema, validation metadata, and
  research-only execution boundary for both built-in and local extension
  strategies. The boundary explicitly keeps broker order submission disabled
  and requires risk, account-truth, paper/shadow, and manual confirmation gates
  before any candidate could be reviewed. Existing `params` and
  `parameter_schema` fields remain aligned for compatibility.
* 2026-06-22: Added standardized Strategy Runtime output normalization.
  Lifecycle hooks may now return observation signals, buy candidates, sell
  candidates, rebalance candidates, risk warnings, or no-action explanations.
  `StrategyRuntimeRunner` stamps each output with deterministic audit ids,
  hook/source-event references, strategy/run ids, reason text, evidence, and
  downstream gate requirements. Candidate actions explicitly require risk,
  account-truth, paper/shadow, and manual review gates and set
  `does_not_enable_execution=true`, so this contract does not submit broker
  orders or change live-like manual-confirmation defaults.
* 2026-06-22: Hardened the Strategy Runtime context boundary. Runtime context
  now carries account facts, position facts, risk limits, parameters, and
  metadata as recursively frozen read-only mappings, exposes only a false
  `broker_order_submission_enabled` safety flag, and does not provide broker,
  broker-client, or order-submission methods to strategies. Deterministic tests
  prove context immutability and the absence of broker submit capability. This
  does not change existing backtest behavior, broker submission, real-money
  trading defaults, or live-like manual-confirmation requirements.
* 2026-06-22: Added the capability-based Strategy Runtime lifecycle contract.
  `strategy.runtime` now exposes the canonical initialize, before-market, bar,
  tick, after-market, order-update, and fill-update hooks through a deterministic
  runner and audit trace. The contract is exported from the strategy package and
  covered by backend tests for hook vocabulary and invocation order. This does
  not change existing backtest behavior, broker submission, real-money trading
  defaults, or live-like manual-confirmation requirements.

## v0.9 Progress

* 2026-06-22: Added Market Data Reliability acceptance evidence for frontend
  market-data tests. The audit manifest now groups tests for shared
  data-status rendering, Overview estimated valuation labels, return-calendar
  confirmed versus unconfirmed valuation handling, 1D equity-curve missing and
  stale observation behavior, dashboard next actions, and Backtest unconfirmed
  dataset warnings. This is frontend test and audit evidence only; it does not
  change valuation inputs, broker submission, trading behavior, or manual
  confirmation defaults.
* 2026-06-22: Added Market Data Reliability acceptance evidence for backend
  deterministic tests. The audit manifest now groups the adapter normalization
  contract tests, freshness diagnostics tests, manual and scheduled refresh
  boundary tests, and frozen dataset replay determinism tests under the backend
  coverage criterion. This is test and audit evidence only; it does not change
  market-data inputs, broker submission, trading behavior, or live-like manual
  confirmation defaults.
* 2026-06-22: Added Market Data Reliability acceptance evidence for Web
  data-status surfaces. The audit manifest now ties the shared localized
  market-data status formatter to Overview quick actions, Market selected
  symbol detail, Settings valuation notices, Backtest dataset snapshot warnings,
  and the global app-shell status indicators, with tests proving user-facing
  next actions do not leak internal reason codes. This is display and audit
  evidence only; it does not change valuation inputs, broker submission,
  trading defaults, or manual-confirmation behavior.
* 2026-06-21: Tightened the Overview 1D net-value chart missing-observation
  contract. The Web chart now treats `missing` or `error` quote-status points
  as gaps for quote-dependent series (`total`, stocks, funds, and other
  assets) while preserving the cash series and localized quote status in the
  tooltip. This prevents missing intraday observations from being displayed as
  confirmed total or stock/fund values and keeps the chart from fabricating a
  continuous market-data path. This is a display-safety change only; it does
  not change valuation data, broker submission, trading behavior, or manual
  confirmation defaults.
* 2026-06-21: Tightened the backend 1D equity-series missing-observation
  contract. The portfolio equity-series API can now return `null` for
  quote-dependent buckets on missing or error quote observations while keeping
  cash, public quote status, and missing-symbol evidence intact. This prevents
  the API from materializing average-cost or stale baseline values as if they
  were intraday market observations. This is a data-contract safety change
  only; it does not change broker submission, trading behavior, risk gates, or
  manual confirmation defaults.
* 2026-06-21: Hardened return-calendar and explainability conversion for
  nullable valuation points. Equity-series points with missing quote-dependent
  values are now excluded from numeric equity-curve and component-breakdown
  conversion while their valuation status and missing-symbol evidence remain
  available to downstream diagnostics. This prevents missing valuation points
  from crashing attribution surfaces or being displayed as confirmed returns.
  This is a reporting-safety change only; it does not change valuation source
  data, broker submission, trading behavior, risk gates, or manual confirmation
  defaults.
* 2026-06-21: Documented the v0.9 market-data reliability workflow and privacy
  boundary in the user README set. The docs now explain the shared status
  vocabulary, manual and scheduled refresh boundaries, frozen replay datasets,
  local storage boundaries, and that estimated, cached, stale, missing, or
  confirmed-NAV-missing data is data-quality evidence rather than investment
  advice, return guarantee, or execution approval. The market-data acceptance
  audit manifest now includes this documentation evidence.
* 2026-06-21: Extended the shared Web market-data next-action formatter to
  Overview and Market data-status surfaces. Overview now prefers localized
  cache/stale/estimated/missing/confirmed-NAV-missing guidance before showing
  provider fallback actions, while Market exposes the same guidance in both
  the data-health panel and selected-symbol detail. Provider-specific actions
  such as continuing with local cached data remain intact. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
* 2026-06-20: Added a shared Web market-data next-action formatter for
  unconfirmed statuses and connected Settings valuation notices to it. Cache
  and stale states now guide users to refresh quotes or check the data source,
  estimated states guide users to wait for confirmation or refresh, missing
  states guide users to backfill or run first sync, and confirmed-NAV-missing
  states guide users to wait for or sync fund NAV confirmation. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
* 2026-06-20: Added the capability-based Market Data Reliability acceptance
  audit manifest and CLI registry entry. `build_market_data_reliability_acceptance_audit()`
  maps the completed v0.9 data-plane criteria to deterministic evidence paths
  and validation commands, while `scripts/export_acceptance_audit.py --audit
  market_data_reliability` exports the manifest through the shared CI-friendly
  JSON surface. This is audit/reporting evidence only; it does not change
  trading behavior, broker submission, live-like defaults, or manual
  confirmation requirements.
* 2026-06-20: Connected the shared v0.9 market-data status vocabulary to Web
  public labels and the return calendar valuation guard. The Web formatter now
  localizes `confirmed`, `live`, `cache`, `estimated`, `missing`, `stale`, and
  `confirmed_nav_missing` without leaking internal codes, and the return
  calendar treats estimated, cached, stale, or confirmed-NAV-missing periods as
  valuation gaps instead of confirmed returns. The Overview 1D equity curve now
  uses the same localized status text and marks category changes as needing
  confirmation when the underlying valuation point is estimated, cached,
  missing, or otherwise unconfirmed. Historical market bars and daily closes now
  normalize to the shared public `confirmed` status while keeping their source
  evidence separate. Current valuation points preserve explicit shared
  statuses such as `estimated`, `cache`, and `confirmed_nav_missing` instead of
  collapsing them into `live`. Market data health aggregation now preserves a
  full-cache state as `cache` rather than relabeling it as stale, and the
  Overview data-status card plus global toolbar treat cache, estimated,
  missing, partial, stale, and confirmed-NAV-missing states as unconfirmed
  market data instead of healthy live quotes. This changes display semantics
  only; it does not change portfolio data, broker submission, trading
  defaults, or manual-confirmation behavior. The Overview total-assets rail
  also labels estimated, missing, or confirmed-NAV-missing valuation status
  with localized public text instead of showing those figures as confirmed.
  Market research now counts cache, estimated, missing, stale, and
  confirmed-NAV-missing quotes as data needing review through the shared
  frontend status helper, and the user-facing summary uses review-oriented
  wording instead of calling every unconfirmed quote stale. Settings data
  status now uses the same shared helper so estimated, missing, and
  confirmed-NAV-missing valuations are shown as review-required rather than
  healthy confirmed quotes. Backtest dataset snapshots now surface per-symbol
  data status in the report table and show a research-evidence warning when a
  saved report contains unconfirmed market data, so estimated rows are not
  presented as confirmed inputs for after-cost metrics. Frozen replay datasets
  now provide deterministic replay evidence for Strategy Runtime dry-runs,
  including status counts, unconfirmed statuses, required action, and safety
  flags, so estimated replay inputs cannot be treated as confirmed returns.
* 2026-06-20: Added deterministic frozen market-data replay datasets.
  `data.market_data_replay` freezes normalized `MarketDataRecord` values into
  a stable `karkinos.market_data_dataset.v1` payload, computes a deterministic
  dataset fingerprint, and replays records in canonical order for backtest,
  strategy-runtime dry-run, paper/shadow review, and audit replay consumers.
  The frozen dataset carries explicit safety evidence that it does not change
  trading behavior, enable broker order submission, or alter manual
  confirmation defaults.
* 2026-06-20: Added a capability-based market-data refresh contract for manual
  and scheduled refresh flows. `data.market_data_refresh` builds and runs
  auditable refresh tasks for intraday quotes, close-price bars, and fund NAV
  confirmation through the market-data adapter boundary. Each refresh run
  returns trigger, task, refreshed-symbol, failed-symbol, record-count, and
  safety evidence showing that trading behavior, broker order submission, and
  manual-confirmation defaults were not changed.
* 2026-06-20: Added market-data quality diagnostics to the shared v0.9
  contract. `build_market_data_quality_report()` now detects missing expected
  trading sessions, records that appear on configured non-trading days, stale
  quotes, confirmed fund NAV gaps, mixed adjustment modes, and provider price
  differences. The diagnostics return localized messages, deterministic
  pass/degraded/blocked status, and JSON-safe evidence payloads. This is a
  backend data-quality contract only; it does not change broker submission,
  trading defaults, refresh behavior, or manual-confirmation requirements.
* 2026-06-20: Started Data Plane & Market Reliability with a shared market
  data contract. `data.market_data` defines the capability-based
  `MarketDataAdapter` boundary for daily bars, intraday bars, snapshots, ticks,
  and replay records, plus the shared status vocabulary (`confirmed`, `live`,
  `cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`).
  `MarketDataRecord` and `MarketDataRecordMetadata` preserve source, source
  symbol, timestamp, trading session, adjustment mode, freshness metadata, and
  limitations. Deterministic tests cover status normalization, Chinese labels,
  event-kind serialization, and the adapter contract without changing broker
  submission, trading defaults, or manual-confirmation behavior.

## v0.8 Progress

* 2026-06-18: Added the first account strategy assignment and attribution loop.
  `/api/account-strategy` can read and update a research-only assignment while
  forcing `auto_trade_enabled=false`; attribution and contribution endpoints
  link available signal, risk, order, fill, fee, and valuation evidence without
  mutating ledger, broker, order, fill, or position state. Backtest Web now
  starts with the strategy catalog, shows the current account assignment, and
  surfaces attribution/contribution status as audit evidence rather than a
  profitability claim.
* 2026-06-18: Connected strategy attribution readiness into promotion and
  decision gates. Strategy promotion readiness blocks an assigned strategy when
  attribution evidence is pending; Decision summaries and candidate cards now
  surface the strategy-attribution gate and fall back to review-required when
  a strategy-driven candidate lacks linked contribution evidence. Backend and
  frontend deterministic tests cover the degraded decision state and visible
  gate status without changing broker submission, trading defaults, or manual
  confirmation requirements.
* 2026-06-18: Added Strategy Assignment acceptance audit coverage to the shared
  capability registry. `build_strategy_assignment_acceptance_audit()` and
  `scripts/export_acceptance_audit.py --audit strategy_assignment` map the
  completed v0.8 checklist items to deterministic backend, frontend, and
  documentation evidence while leaving unfinished roadmap items visible in
  `docs/ROADMAP.md`.
* 2026-06-18: Completed account, asset-class, and symbol scope handling for
  account strategy assignment updates. Asset-class assignments now persist the
  selected class and filter attribution evidence by matching signal asset
  class, with deterministic route tests covering the boundary.

## v0.7 Progress

* 2026-06-18: Started Account Truth Review Center with read-only review APIs.
  `/api/account-truth/import-runs` lists staged broker import metadata, while
  `/api/account-truth/reconciliation-reports` and
  `/api/account-truth/reconciliation-reports/{import_run_id}` compute report
  summaries and details against current Karkinos ledger, cash, positions,
  fees, taxes, and cost basis. Reconciliation items include item keys,
  severity, broker value, Karkinos value, difference, suggested review action,
  symbol, detail, and broker evidence references. The routes do not mutate the
  production ledger, holdings, broker state, or credentials.
* 2026-06-18: Added the first manual review action API for Account Truth
  differences. `POST
  /api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`
  records `accepted`, `ignored`, `known_difference`, `ledger_candidate`, or
  `needs_investigation` decisions and returns the persisted audit state. Report
  detail responses include the latest review decision per item. Deterministic
  tests verify that recording a `ledger_candidate` does not create production
  ledger entries.
* 2026-06-18: Added the first Web Account Truth Review Center. `/account-truth`
  shows Account Truth Score component reasons, staged import runs, status
  filters for reconciliation reports, per-item broker/Karkinos differences,
  evidence references, and manual review action buttons. `GET
  /api/account-truth/score` exposes the same component-level score evidence to
  the Web UI. Frontend tests cover rendering, status filtering, review action
  submission, score display, and blocked-state presentation; backend tests
  cover the score endpoint and ledger-candidate non-mutation safety.
* 2026-06-18: Surfaced Account Truth gate evidence in Decision and Strategy
  Promotion review surfaces. Decision summaries and candidates now show pass,
  degraded, blocked, or not-evaluated account-truth state with score and
  unresolved-difference context; Strategy Lab promotion readiness shows the
  same gate status and evidence availability. Frontend tests cover degraded and
  blocked decision states plus promotion-gate rendering without changing broker
  submission, production ledger mutation, or manual-confirmation defaults.
* 2026-06-18: Added Account Truth Review Center acceptance audit coverage.
  `build_account_truth_review_acceptance_audit()` maps the v0.7 review
  workflow checklist to deterministic backend, frontend, documentation, and CLI
  evidence. `scripts/export_acceptance_audit.py --audit account_truth_review`
  exports the manifest through the shared capability registry without using a
  roadmap version in function, file, or CLI names.

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
* 2026-06-18: Added research-only account strategy assignment and attribution
  evidence surfaces without enabling automatic trading.
* 2026-06-18: Added a strategy contribution estimate API and Backtest surface
  that separates linked-fill unrealized P/L, commission, slippage, and net
  contribution while excluding manual trades, cash flows, and missing-evidence
  movement by default.
* 2026-06-18: Added five-tier Backtest P/L attribution status copy for account
  strategy evidence: not started, partial, stale, blocked, and complete.
* 2026-06-18: Extended account strategy attribution evidence references across
  signal, action, risk, review, order, and fill records.
* 2026-06-18: Added evidence-gated strategy contribution surfaces to Overview
  and Portfolio while reusing Backtest and Decision attribution gates.
* 2026-06-22: Fixed return-calendar valuation status semantics so live,
  confirmed, and complete periods display returns normally; cache, stale,
  estimated, and confirmed-NAV-missing periods display returns with an
  unconfirmed marker; and only missing or unavailable prices render as
  valuation gaps.
* 2026-06-22: Added acceptance-audit evidence for the 1D net-value chart
  contract. Existing frontend and backend deterministic tests now prove that
  the 1D chart can show intraday market movement, cash-flow changes,
  stock/fund movement, fund confirmation state, stale status, and missing
  quote-dependent observations without fabricating values. This is audit
  wiring only; it does not change broker submission, trading behavior, risk
  gates, or manual-confirmation defaults.
* 2026-06-22: Completed the v1.1 paper broker and OMS backend coverage slice.
  Paper broker tests now cover paper-only fills, partial fills, cancellations,
  rejections, slippage, fee/tax cost modeling, and OMS idempotency without
  mutating the production ledger or introducing broker order submission.
* 2026-06-22: Started v1.2 Broker Evidence Connector with a capability-based
  read-only connector contract and deterministic fake connector fixtures for
  account, cash, position, order, fill, and health facts. The connector surface
  does not expose broker order submission.
* 2026-06-22: Added local read-only broker connector configuration parsing for
  ignored `config.json`. Connector config accepts client path and account alias
  only, rejects password/secret/token/credential fields, and keeps source
  examples synthetic.
* 2026-06-22: Added read-only broker connector evidence normalization. Synthetic
  connector snapshots now convert fills, cash snapshots, and position snapshots
  into staged broker evidence that can feed reconciliation without mutating the
  production ledger or enabling broker order submission.
* 2026-06-22: Wired staged broker evidence into shared Account Truth gate
  construction. Decision summaries and Strategy Lab promotion readiness now
  block when latest read-only broker evidence reconciles to unresolved material
  differences, while preserving manual-confirm-only live-like behavior.
* 2026-06-22: Added deterministic fake connector evidence-state coverage for
  healthy, disconnected, stale, permission-limited, duplicate, and incomplete
  snapshots. Disconnected snapshots now block without emitting stale evidence
  rows, incomplete snapshots surface explicit diagnostics, and duplicate
  connector rows are marked deterministically. This remains read-only broker
  evidence and does not submit broker orders, mutate production ledger entries,
  or change manual-confirmation defaults.
* 2026-06-22: Completed the v1.2 broker evidence reconciliation detail slice.
  Canonical broker statement previews and staged evidence now preserve optional
  transfer-fee and broker cost-basis method fields. Reconciliation reports
  expose trade gross amount, signed net cash impact, fee, tax, transfer-fee,
  and cost-basis differences as reviewable items. This is audit evidence only;
  it does not mutate production ledger entries, submit broker orders, or change
  manual-confirmation defaults.
* 2026-06-22: Added shared public formatting for generated Trading manual-order
  notes. Decision-generated order notes now render as user-readable copy on
  Trading queue and audit surfaces without exposing internal action ids; order
  execution behavior and manual-confirmation defaults are unchanged.
* 2026-06-22: Moved the Overview latest-ledger cards onto the shared public
  ledger formatter for entry titles, instrument labels, and cleaned public
  notes. Legacy note prefixes and technical note segments remain hidden from
  the user-facing ledger cards.
* 2026-06-22: Stopped Decision manual-order preparation from writing internal
  signal action ids into order notes. Prepared manual orders now use the
  shared public queue note from the Trading API hook while preserving manual
  confirmation and broker-submit defaults.
* 2026-06-22: Localized Decision signal-journal audit event labels on
  user-facing candidate and journal surfaces. Dotted internal event keys remain
  backend audit identifiers, while the Web UI now shows public event copy
  without changing signal, journal, risk-gate, or manual-confirm behavior.
* 2026-06-22: Connected Risk explainability recent-driver and timeline titles
  to the shared public ledger formatter for generated ledger kinds. Internal
  ledger kind values such as cash-flow entry types now render as localized
  public titles while existing human-authored titles are preserved. This is UI
  formatting only; it does not change risk computation, ledger facts, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Account Truth review evidence references for
  user-facing reconciliation items. Broker evidence ids now render as readable
  source, subject, event-type, and import-run labels instead of raw
  machine-formatted reference strings. This is review-surface formatting only;
  it does not change import parsing, reconciliation, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Account Truth reconciliation item categories on the
  Web review surface. Difference cards now display public labels such as cash,
  position, fee, and cost basis through the shared public-label formatter
  instead of rendering raw backend category fields. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Replaced Account Truth reconciliation report summary shorthand
  such as raw cash/fee delta labels with localized public labels for cash
  difference and fee difference. This is report-summary display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Localized generated Account Truth reconciliation detail copy on
  the Web review surface. Known backend-generated reconciliation explanations
  now pass through the shared public-note formatter in Chinese locale instead
  of exposing English operational sentences. This is detail-text display
  formatting only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Added stable Account Truth reconciliation detail codes alongside
  the legacy detail text. Reconciliation item generation and the Account Truth
  report API now expose a machine-stable `detail_code`, and the Web review
  surface prefers that code for localized public-note rendering while keeping
  old `detail` payloads as fallback. This is an additive review-surface
  contract change only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Structured dynamic Account Truth reconciliation detail context
  for broker cost-basis method evidence. Cost-basis reconciliation items now
  expose `detail_context` for values such as the broker cost-basis method, and
  the Web review surface renders those context fields as localized labels and
  values instead of exposing raw method codes in generated detail text. This is
  an additive review-surface contract change only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Added category-aware numeric formatting to Account Truth
  reconciliation item values on the Web review surface. Position differences
  now show share units, cost-basis differences show four-decimal CNY price
  values, and cash/fee/tax-like differences use CNY amount formatting instead
  of unqualified raw numbers. This is display formatting only; it does not
  change reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Extended Account Truth report summaries to use the same
  category-aware money formatting for cash and fee differences. Report cards
  now display localized CNY amounts instead of raw decimal strings while the
  reconciliation report payload remains unchanged. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Added tax-difference visibility to Account Truth reconciliation
  report summary cards. Existing `tax_difference` payload values now render as
  localized CNY amounts alongside cash and fee differences, making fee/tax
  evidence visible without changing the reconciliation payload or accounting
  calculations. This is display formatting only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Extended the shared public ledger formatter to render structured
  trade cost facts on Web ledger surfaces. Activity and Overview ledger rows
  can now show gross trade amount, signed net cash impact, commission, stamp
  tax, transfer fee, and localized cost-basis method labels from structured
  fields instead of hiding those facts in notes. This is display formatting
  only; it does not change ledger persistence, fee calculation, trading,
  broker behavior, or manual-confirmation defaults.
* 2026-06-22: Moved holding-detail ledger traces onto the same structured
  ledger cost formatter used by Activity and Overview. Holding detail now
  exposes gross amount, signed net cash impact, commission, stamp tax,
  transfer fee, and localized cost-basis method labels from structured ledger
  fields while keeping public notes separate. This is display formatting only;
  it does not change ledger persistence, fee calculation, trading, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Risk explainability ledger fallback details for
  generated cash-flow and ledger adjustment events. Risk review surfaces now
  use the active Web language for public fallback descriptions after shared
  ledger-note cleanup removes internal import notes. This is display
  formatting only; it does not change risk math, ledger persistence, trading,
  broker behavior, or manual-confirmation defaults.
* 2026-06-23: Moved Backtest strategy validation rows to use localized
  strategy display names as the primary label while keeping strategy ids as
  secondary audit metadata. This makes research-gate status easier to read
  without changing strategy execution, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Moved Decision candidate strategy evidence to the same
  user-facing strategy display-name convention. Candidate cards and evidence
  chains now show localized strategy names first while preserving internal
  strategy ids as secondary audit metadata. This is display formatting only; it
  does not change decision generation, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Added strategy identity to the Web strategy contribution report
  using localized display names first and internal strategy ids as secondary
  audit metadata. This makes contribution evidence attributable to a readable
  strategy without changing attribution math, ledger facts, broker behavior,
  trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Extracted shared Web strategy display formatting for readable
  strategy names and secondary audit ids. Backtest, Decision, and Strategy
  Contribution surfaces now use the same formatter instead of page-local
  copies. This is display formatting only; it does not change strategy
  execution, attribution math, ledger facts, broker behavior, trading, risk
  gates, or manual-confirmation defaults.
* 2026-06-23: Risk explainability events now hydrate shared ledger formatting
  with instrument names from the current account snapshot. Generated broker or
  ledger event titles that only carry a symbol now render readable name +
  symbol labels in recent drivers, timeline events, and position drivers. This
  is display formatting only; it does not change risk math, ledger
  persistence, broker behavior, trading, risk gates, or manual-confirmation
  defaults.
* 2026-06-23: Localized Risk blocking-register alert kinds so user-facing risk
  cards show readable labels such as cash buffer instead of raw internal codes.
  This is display formatting only; it does not change risk calculations,
  trading, broker behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Localized Risk blocking-register severity labels so user-facing
  alert badges show review labels such as warning instead of raw severity
  codes. This is display formatting only; it does not change risk
  calculations, trading, broker behavior, risk gates, or manual-confirmation
  defaults.
* 2026-06-23: Promoted cash-interest ledger entries to first-class cash income
  in portfolio projection, explainability timeline flow breakdown, and the
  shared public ledger formatter. Activity now reuses shared action titles,
  short labels, signed amounts, and cash-impact semantics instead of
  page-local ledger type branches. This changes cash-interest classification
  from market movement to income flow where evidence exists; it does not change
  ledger persistence, fee math, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Moved holding-detail ledger traces onto the shared public ledger
  activity summary for action titles, cash-impact wording, and signed primary
  amounts while keeping structured gross amount, net cash impact, fee, tax, and
  transfer-fee lines visible. Cost-basis method is no longer mixed into
  execution detail lines and should remain in dedicated cost-basis views. This
  is presentation alignment only; it does not change ledger persistence, fee
  math, broker behavior, trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Updated portfolio projection cost math to consume structured
  trade fee breakdowns when present, including commission, stamp tax, transfer
  fee, and other fee components. This keeps local moving-average buy cost and
  cash projection aligned with the same ledger fee evidence shown in user
  surfaces. It does not mutate ledger entries, change broker behavior, submit
  orders, bypass risk gates, or alter manual-confirmation defaults.
* 2026-06-23: Added Portfolio holding-detail support for broker-facing
  cost-basis evidence when the position API provides it. The Web detail view
  now distinguishes local moving average cost, broker displayed unit cost,
  broker displayed cost basis, localized cost-basis method, and the difference
  between broker and local cost-basis totals. The positions API can carry these
  optional evidence fields without mutating ledger entries. This is
  presentation and payload-surface work only; it does not change projection
  math, reconciliation decisions, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Hydrated Portfolio position cost-basis fields from staged broker
  evidence when no explicit broker cost-basis fields are already attached to
  the projected position. The positions API now reads the latest imported
  position snapshot cost basis from Account Truth evidence and derives broker
  displayed unit cost, broker displayed total cost basis, local-vs-broker
  difference, method, and availability status. This uses already-imported
  evidence only; it does not read broker credentials, mutate the production
  ledger, submit orders, bypass risk gates, or change manual-confirmation
  defaults.
* 2026-06-23: Added a Portfolio holding-detail cost-basis review prompt when
  broker displayed cost evidence differs from Karkinos local moving-average cost
  by a material display threshold. The prompt is localized and points users back
  to Account Truth evidence before relying on cost-basis P/L. This is
  presentation-only audit guidance; it does not change ledger math, broker
  behavior, trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Moved the Activity page net-cash-impact summary onto the shared
  public ledger summary formatter. The page now respects structured
  `net_cash_impact` evidence and first-class cash-interest entries instead of
  using a local `entry_type` branch. This is UI summary alignment only; it does
  not mutate ledger entries, change broker behavior, submit orders, bypass risk
  gates, or alter manual-confirmation defaults.
