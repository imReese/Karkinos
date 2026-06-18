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

## Product Boundaries

Karkinos is a personal finance app for research, portfolio evidence, and
risk-control workflows. It is not broker automation and not investment advice.

The product boundary is:

* Local market, portfolio, ledger, broker-evidence, research, and risk data can
  be imported, checked, reconciled, scored, and surfaced for review.
* Signals and strategy outputs remain research evidence until they pass data,
  cost, OOS, risk, account-truth, paper/shadow, and manual-review gates.
* Live-like workflows must default to manual confirmation.
* No broker login, broker password storage, broker order submission, default
  real-money automation, or guaranteed-profit language belongs in the product.
* Secrets, broker credentials, real account exports, runtime databases, logs,
  screenshots, and private financial data must stay out of source control.

## Operating Loop

Karkinos should support the full investment operating loop:

```text
research idea
→ reproducible backtest
→ after-cost validation
→ account truth / data reconciliation
→ risk gate
→ paper/shadow signal
→ dashboard/action queue
→ signal journal
→ manual confirmation where applicable
→ post-decision review
→ strategy improvement
```

## Current Roadmap Status

The current roadmap status is maintained in [ROADMAP.md](ROADMAP.md).

Current active milestone:

* **v0.8 — Strategy Assignment & Attribution Engine**
* Status: active roadmap milestone.
* Purpose: make account strategy assignment explicit, then connect strategy
  signals, manual review, orders, fills, fees, and position changes into an
  auditable contribution view before claiming strategy-level account returns.

Latest completed milestone:

* **v0.7 — Account Truth Review Center**
* Status: completed roadmap milestone.
* Purpose: turn account-truth and reconciliation evidence into a usable review
  workflow before decision summaries, promotion readiness, paper/shadow review,
  or manual-confirm workflows rely on unresolved account differences.

## Documentation Map

* [ROADMAP.md](ROADMAP.md): versioned milestones, status summary, acceptance
  criteria, and future candidate milestones.
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
* [return-accounting.zh.md](return-accounting.zh.md): portfolio return,
  cost-basis, cash-flow, and baseline-price semantics.

## Safety / Non-Investment-Advice Boundary

Karkinos does not promise profit and should never be treated as the sole basis
for investment decisions.

All dashboards, backtests, scores, reconciliation reports, signals, and action
queues are evidence for human review. They can improve discipline by making
data, costs, account facts, risk gates, and decision history explicit, but they
do not authorize broker orders by themselves.
