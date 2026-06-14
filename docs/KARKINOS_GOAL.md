# Karkinos Goal — Financial-Grade China-Market Investment Cockpit

## North Star

Karkinos is not a toy backtester.

Karkinos should become a financial-grade China-market personal investment cockpit that helps one serious investor make fewer emotional mistakes, deploy only validated strategies, control downside first, and compound capital through auditable, after-cost, risk-gated decisions.

The daily product question is:

> Given my portfolio, market data, risk limits, and validated strategies, what should I do today — buy, sell, hold, rebalance, or do nothing — and why?

## Product Workflow

Karkinos should support the full investment operating loop:

```text
research idea
→ reproducible backtest
→ after-cost validation
→ risk gate
→ paper/live signal
→ dashboard/action queue
→ signal journal
→ post-trade review
→ strategy improvement
````

## v0.2 Target: Profit Discipline MVP

The next major goal is **Karkinos v0.2 — Profit Discipline MVP**.

By v0.2, Karkinos should have one reliable end-to-end workflow:

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

## Financial-Grade Definition

Karkinos reaches financial-grade personal use only when these are true:

### 1. Data Integrity

* Market data is cached, versioned, and auditable.
* Each dataset records provider, fetch time, symbol, date range, adjustment mode if applicable, row count, and data-quality diagnostics.
* Backtests can be reproduced from frozen datasets.
* Missing data, suspensions, limit-up/limit-down behavior, T+1 constraints, corporate actions, and asset-specific assumptions are modeled or explicitly flagged.

### 2. Backtest Credibility

Every strategy report should include, when data is available:

* gross return
* net return after commission, taxes if applicable, and slippage
* turnover
* exposure
* maximum drawdown
* Sharpe / Sortino / Calmar where applicable
* benchmark comparison
* trade count
* win/loss distribution
* liquidity assumptions
* known limitations

Backtests must avoid:

* look-ahead bias
* survivorship bias
* unrealistic fills
* hidden future data
* overfitting through excessive parameter tuning

### 3. Risk Control Before Execution

No actionable real-money-like signal should bypass a pre-trade risk gate.

Risk gates should cover:

* max position weight
* concentration
* cash reserve
* max daily notional
* turnover limit
* max drawdown / loss budget
* liquidity
* ST/suspension filters where applicable
* kill switch
* data-quality failure

Manual confirmation must remain the default for live-like execution.

### 4. Portfolio Cockpit

The Web UI should help answer:

* What do I hold now?
* What should my target weights be?
* Where is the portfolio drifting?
* What signals fired today?
* Which signals passed or failed risk checks?
* What action is recommended?
* Why is this action recommended?
* What happens if I do nothing?
* What did I decide, and what happened later?

### 5. Signal Journal and Audit Trail

Every generated signal should be journaled with:

* strategy id/name
* symbol
* timestamp
* source data snapshot id if available
* signal/action/target weight
* risk-gate result
* user decision: acted, ignored, deferred
* later outcome
* review notes

The goal is not just to generate trades. The goal is to improve decision quality through reviewable evidence.

## Definition of “Money-Oriented but Honest”

Karkinos does not promise profit.

The project should improve the owner’s after-cost investment results by:

* reducing emotional trading
* avoiding unrewarded risk
* enforcing position discipline
* requiring out-of-sample validation
* making costs and slippage visible
* journaling decisions
* reviewing outcomes
* blocking unsafe trades

A strategy is deployable only if it passes all gates below:

* beats a relevant benchmark after costs in out-of-sample testing
* drawdown is within the owner’s loss budget
* turnover is realistic after China-market costs and liquidity
* performance survives parameter perturbation
* performance survives at least one market-regime split
* paper/shadow trading does not materially diverge from backtest expectations
* risk gate can block the strategy under unsafe data or market conditions

## Priority Order

When Codex or any coding agent chooses what to implement next, prefer this order:

1. Data integrity and reproducible datasets
2. After-cost backtest credibility
3. Mandatory pre-trade risk gate
4. Signal journal and audit trail
5. Portfolio dashboard action queue
6. Paper/shadow mode
7. Strategy promotion pipeline
8. Strategy research improvements
9. Broker/live execution integrations

Do not jump to broker automation before the earlier layers are trustworthy.

## Non-Goals for Now

* No guaranteed-profit claims.
* No default full-automatic real-money trading.
* No opaque black-box AI strategy deployment without validation and risk controls.
* No expanding into every asset class before the China-market daily workflow is reliable.
* No committing secrets, brokerage credentials, real account exports, runtime databases, logs, screenshots, or private financial data.

## Engineering Style

Prefer:

* small, reviewable PR-sized changes
* deterministic tests
* synthetic test data instead of live-provider-dependent tests
* explicit assumptions over silent guesses
* stable public APIs
* clear migration paths
* readable reports and dashboard explanations

Avoid:

* large rewrites without tests
* hidden strategy assumptions
* magic profitability claims
* adding heavy dependencies without justification
* coupling research code directly to real-money execution

## Acceptance Criteria for v0.2

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
* [x] README and docs make clear that Karkinos is research and portfolio tooling, not investment advice.

## North Star Metric

**Decision Quality Score**

The percentage of daily portfolio decisions that are:

* data-complete
* risk-checked
* benchmark-aware
* cost-aware
* journaled
* later reviewable

Secondary metrics:

* after-cost excess return versus benchmark
* max drawdown versus loss budget
* paper/live divergence
* number of unsafe trades blocked by risk gate
* time from idea to reproducible backtest
* strategy promotion pass rate

## Acceptance Criteria for v0.3

Karkinos v0.3 — Daily + Intraday Decision Cockpit — moves the system toward
daily and intraday decision review without enabling default real-money
automation.

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
* [x] The frontend decision cockpit shows daily and intraday candidate actions,
  risk state, evidence, and manual-confirmation entry points.
* [x] Deterministic tests cover data/cache → feature/strategy signal → action
  candidate → risk gate → journal → decision API/dashboard.
* [x] README/docs describe the behavior boundary: research and investment
  cockpit, not investment advice, and no default automatic real-money trading.

<!-- codex-progress:start -->
## Codex Progress

* 2026-06-12: Removed the Activity batch fund form's built-in fund candidates.
  Batch fund candidates now come from held fund positions, preserving an empty
  initial state until portfolio data exists in the database or explicit private
  runtime configuration.
* 2026-06-12: Exposed latest risk-gate outcomes on signal action cards.
  The action queue now carries the linked risk decision id, pass/fail state,
  severity, and reasons so dashboard consumers can distinguish actionable,
  blocked, and not-yet-checked signals without bypassing manual confirmation.
* 2026-06-12: Added a deterministic Profit Discipline smoke path covering
  fixture data cache metadata, feature calculation, after-cost backtest report,
  generated signal, mandatory pre-trade risk gate, action queue risk summary,
  and signal journal audit chain. Backtest reports now print gross turnover as
  total traded notional alongside commission and slippage.
* 2026-06-12: Tagged registered strategies with v0.2 benchmark metadata.
  The backtest strategy API now exposes ETF trend-following, defensive
  allocation, and A-share/ETF mean-reversion roles plus explicit OOS and
  after-cost validation requirements, without changing strategy execution.
* 2026-06-12: Added reusable out-of-sample validation evidence for completed
  backtests. The analytics helper splits in-sample / OOS equity, attributes
  recorded commission and slippage to each segment, computes benchmark excess
  return when supplied, and serializes explicit limitations without making
  profit guarantees.
* 2026-06-12: Wired OOS validation evidence into the backtest run path.
  Backtest requests can now provide an OOS split date and benchmark return;
  mapped benchmark strategies attach serialized after-cost validation evidence
  under metrics_json.oos_validation for persistence and API consumers.
* 2026-06-12: Added a deterministic v0.2 strategy validation matrix.
  The analytics layer can now inspect persisted-style backtest payloads and
  report whether the three required benchmark strategies each have both
  after-cost evidence and out-of-sample validation, including explicit missing
  requirements for promotion review.
* 2026-06-12: Added fixture-backed validation backtests for all v0.2 benchmark
  strategies. The deterministic fixtures run ETF trend-following, defensive
  allocation, and A-share mean-reversion through the existing BacktestEngine,
  then emit persisted-style after-cost and OOS evidence rows that satisfy the
  strategy validation matrix without relying on live market data.
* 2026-06-12: Exposed the v0.2 strategy validation matrix through the backtest
  API. Dashboard and CI consumers can now call `/api/backtest/strategy-validation`
  to inspect whether saved results prove each benchmark strategy has after-cost
  and OOS evidence before promotion review.
* 2026-06-12: Added a portfolio cockpit API surface. `/api/portfolio/cockpit`
  now combines account summary, per-position actual weight, action target
  weight, drift, pending/deferred action cards, and risk alerts so dashboard
  consumers can inspect portfolio readiness without bypassing manual execution.
* 2026-06-12: Made action-card risk gate state explicit. Action queue and
  cockpit responses now expose `risk_gate_status` as `not_checked`, `passed`,
  or `blocked`, preserving the existing pass/fail fields while preventing
  ungated actionable signals from being mistaken for approved work.
* 2026-06-12: Added manual-confirmation readiness to action cards. Signal action
  and portfolio cockpit responses now distinguish `awaiting_risk_gate`,
  `ready_for_manual_confirmation`, and `blocked_by_risk_gate`, while keeping
  manual confirmation required even after a risk gate passes.
* 2026-06-12: Added the first action-to-manual-order execution bridge. Trading
  controls can now create a `pending_confirm` manual order and shared order fact
  only from a risk-passed action card, while blocked or not-yet-checked actions
  are rejected before any order record is written.
* 2026-06-12: Linked manual order decisions back into the signal journal.
  Confirming a pending manual order now marks the originating action as `acted`;
  rejecting it marks the action as `ignored`; both decisions surface as
  manual-order status events in the signal audit chain.
* 2026-06-12: Added a deterministic daily paper/shadow run endpoint. Trading
  controls can now record `paper_shadow` order facts from risk-passed action
  cards without per-action manual data edits, while skipping blocked or
  not-yet-checked actions and avoiding broker submission or fills.
* 2026-06-12: Added a signal journal review/outcome endpoint. Generated signals
  can now receive immutable post-decision review notes and later outcome labels
  in the audit chain without changing action status, creating orders,
  submitting to a broker, or recording fills.
* 2026-06-12: Made the CI contract explicit for Profit Discipline MVP gates.
  GitHub Actions now runs the deterministic Profit Discipline smoke path as a
  named backend step, keeps the full backend suite, and uses a non-mutating
  frontend format check alongside frontend build and tests.
* 2026-06-12: Added a strategy promotion readiness surface. The backtest API
  now combines v0.2 after-cost/OOS validation, risk-gate block evidence,
  paper/shadow order evidence, and explicit paper/shadow divergence review
  evidence into non-automatic promotion gates that keep live-like execution
  manual by default.
* 2026-06-12: Added a paper/shadow divergence review write path. Operators can
  now attach auditable divergence status and review notes to existing
  `paper_shadow` order facts without changing order status, submitting to a
  broker, creating fills, or bypassing manual live-like controls.
* 2026-06-12: Added a v0.2 acceptance audit manifest and aligned the goal
  checklist with deterministic evidence. Each completed checkbox now maps to
  local tests, docs, API surfaces, and validation commands, while preserving
  manual confirmation as the live-like default and avoiding investment-advice
  claims.
* 2026-06-12: Started v0.3 shadow-trading reliability work. Daily shadow runs
  now expose schema versioning and idempotent reuse of same-date/action order
  facts, avoiding repeated writes or duplicate order events when operators rerun
  the safe local paper/shadow process.
* 2026-06-12: Added the first v0.3 data-quality gate to daily shadow runs.
  The safe paper/shadow endpoint now requires a live, positive latest quote for
  each risk-passed action, returns a versioned data-quality summary, and skips
  actions with missing, stale, or invalid quote evidence before any shadow order
  fact is written.
* 2026-06-12: Started the Daily + Intraday Decision Cockpit API surface.
  `/api/decision/today` now returns a read-only daily decision summary from
  existing action tasks, risk-gate state, signal journal entries, and latest
  quote freshness, including no-action reasons and manual-confirmation
  requirements without creating orders or enabling automatic trading.
* 2026-06-12: Added the first read-only intraday decision lane.
  `/api/decision/intraday` now filters pending stock and common exchange-traded
  ETF action candidates into a polling/minute-level cockpit view, keeps open-end
  fund-style actions in the daily lane, returns explicit no-action reasons, and
  preserves manual confirmation as the live-like default.
* 2026-06-12: Attached persisted strategy validation evidence to decision
  candidates. Daily and intraday decision responses now read the latest saved
  backtest result for each action's `strategy_id` and include after-cost,
  out-of-sample validation, cost summary, limitations, and explicit
  missing-evidence reasons without running a new backtest or creating orders.
* 2026-06-12: Added current-state aggregation to decision summaries. Daily and
  intraday decision responses now include portfolio cash / positions / equity,
  latest quote cache health, action-task status counts, and signal / journal /
  risk-gate audit counts so the cockpit can explain action and no-action states
  without adding any execution side effects.
* 2026-06-12: Added the first frontend Decision Cockpit surface. The React app
  now exposes `/decision` in the main navigation, fetches the read-only daily
  and intraday decision APIs, displays candidate actions, risk-gate state,
  after-cost/OOS evidence, quote freshness, no-action reasons, and links ready
  candidates to the existing manual Trading approvals workspace without
  executing orders.
* 2026-06-12: Added a deterministic v0.3 Decision Cockpit acceptance path. The
  new test runs fixture market-cache data through feature calculation,
  after-cost backtest reporting, strategy signal generation, action-task
  creation, mandatory pre-trade risk, signal journal audit, and the daily /
  intraday decision API contract that the dashboard consumes, while preserving
  manual confirmation as the live-like default.
* 2026-06-12: Completed the v0.3 checklist audit. Current evidence covers the
  read-only daily and intraday decision APIs, current-state aggregation,
  complete candidate evidence bundles, explicit no-action reasons, the frontend
  `/decision` cockpit, deterministic API/dashboard acceptance coverage,
  README/docs behavior boundaries, and manual-confirmation-only live-like
  behavior.
* 2026-06-12: Fixed Web cockpit responsive containment. The app shell no longer
  uses root/main `overflow-hidden` to silently clip content, the toolbar folds
  secondary status chips below 2xl widths, Decision Cockpit evidence and manual
  confirmation cards remain shrinkable, and wide portfolio/activity/trading/
  backtest tables scroll inside local panels. Frontend tests now cover the app
  shell overflow contract, Decision responsive accessibility, Activity batch
  form shrinkability, and Portfolio table-local horizontal scrolling.
* 2026-06-14: Improved portfolio analysis responsiveness and audit surfaces.
  The 1D equity series now skips live intraday provider calls on closed-market
  days and immediately returns a cache-based flat session fallback, avoiding
  AKShare timeout waits. The explainability return calendar now supports a
  cockpit-style calendar view for month-by-day, year-by-month, and annual
  attribution while preserving table and curve views.
* 2026-06-14: Moved the return calendar into the Overview cockpit. The compact
  performance-analysis layout now keeps daily, monthly, and annual attribution
  beside the net-value workspace, while Risk no longer owns the main return
  calendar module.
* 2026-06-14: Improved the Overview return-calendar empty state. When daily
  attribution snapshots are not available, the cockpit now shows current
  position PnL, market value, top PnL contributors, and the missing historical
  snapshot requirement instead of a bare empty message or fake calendar data.
* 2026-06-14: Consolidated the Overview performance module. The net-value
  curve and return calendar now live inside one performance-analysis card so
  trend, attribution, and missing-snapshot explanations share the same cockpit
  context without changing trading or API behavior.
* 2026-06-14: Polished the Overview return-calendar fallback language and
  holdings display. The empty-state now explains that the calendar is warming
  up, links to activity and market data surfaces, and prioritizes asset names
  over symbols in current-position PnL cards.
* 2026-06-14: Connected explainability attribution to deterministic daily
  portfolio valuation when historical price cache is available. The return
  calendar can now consume a ledger-history timeline built from cash/trade
  entries plus historical close or quote cache, while falling back to the legacy
  equity curve when no historical price lookup exists. Ledger events are mapped
  to Shanghai trading dates before external-flow attribution, avoiding synthetic
  market PnL from UTC timestamp boundaries.
<!-- codex-progress:end -->
