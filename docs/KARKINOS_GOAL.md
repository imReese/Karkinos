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

* [ ] One reproducible end-to-end workflow: data fetch/cache → features → backtest → report → signal → risk gate → dashboard/journal.
* [ ] At least three benchmarkable strategies:

  * [ ] ETF rotation / trend-following baseline
  * [ ] Defensive allocation baseline: equity ETF + bond/gold/cash proxy
  * [ ] A-share/ETF mean-reversion or momentum candidate
* [ ] Each strategy has out-of-sample validation and after-cost report.
* [ ] Portfolio dashboard exposes target weights, actual weights, drift, action queue, and risk alerts.
* [ ] Signal journal stores every generated signal, whether acted on or ignored.
* [ ] Pre-trade risk gate is mandatory for every actionable signal.
* [ ] Manual-confirm execution path is complete.
* [ ] Paper/shadow mode can run daily without manual data edits.
* [ ] CI runs backend tests, frontend checks, and at least one deterministic smoke path.
* [ ] README and docs make clear that Karkinos is research and portfolio tooling, not investment advice.

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

<!-- codex-progress:start -->
## Codex Progress

* 2026-06-12: Removed the Activity batch fund form's built-in fund candidates.
  Batch fund candidates now come from held fund positions, preserving an empty
  initial state until portfolio data exists in the database or explicit private
  runtime configuration.
<!-- codex-progress:end -->
