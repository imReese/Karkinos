# Karkinos Design References

This document points to mature open-source projects that may inform substantial
quantitative-domain and architecture decisions in Karkinos.

References are advisory, not authoritative. Project names are used for
identification and conceptual comparison only. Karkinos must not copy or derive
source code, APIs, or implementation details from an external project without a
separate license review.

Product intent belongs to `GOAL.md`, durable decisions to `ARCHITECTURE.md`,
current scope to `PLAN.md`, and engineering policy to `ENGINEERING.md`.

## When to consult references

Consult the closest relevant project before introducing or materially changing:

* market data, datasets, or point-in-time semantics;
* Alpha, model, forecast, portfolio, or backtest abstractions;
* transaction costs, accounting, risk, orders, or fills;
* provider, broker, execution, or extension boundaries.

Routine fixes, UI work, and local refactors do not require external research.

## Reference map

| Area                            | Primary reference | Main lesson                                                      |
| ------------------------------- | ----------------- | ---------------------------------------------------------------- |
| Data, PIT, research workflow    | Qlib              | Reproducible datasets and research lifecycle                     |
| Alpha → portfolio → execution   | QuantConnect LEAN | Separate investment views, portfolio intent, risk, and execution |
| China-market simulation         | RQAlpha           | Compare market, matching, cost, account, and risk concerns       |
| China-market integrations       | VeighNa           | Keep gateways and applications outside the domain core           |
| Fast quantitative exploration   | vectorbt          | Make experimentation and comparison cheap                        |
| Deterministic runtime semantics | NautilusTrader    | Clear event, order, fill, portfolio, and adapter boundaries      |

## Qlib

Use Qlib primarily as a conceptual reference for research-system design.

Relevant lessons include first-class datasets, point-in-time correctness,
reproducible experiments, and separation between data, predictive research,
portfolio decisions, backtesting, and analysis.

Do not copy its full ML platform or workflow infrastructure without a concrete
Karkinos need.

## QuantConnect LEAN

Use LEAN primarily as a conceptual reference for financial responsibility
boundaries.

Relevant lessons include separating Alpha or forecasts from portfolio intent,
allowing risk to modify that intent, and keeping execution responsible for
orders and fills.

Do not reproduce its brokerage ecosystem or force every Karkinos strategy into
a large framework.

## RQAlpha

Use RQAlpha to compare concerns specific to China-market simulation, including
market rules, matching assumptions, transaction costs, accounts, and risk.

Treat it as a problem-space reference rather than an implementation template.
Do not derive Karkinos code or architecture from its source without a separate
license review.

## VeighNa

Use VeighNa primarily as a conceptual reference for China-market provider and
application boundaries.

Relevant lessons include keeping venue-specific gateways outside the core and
treating identifiers, sessions, contracts, and connectivity explicitly.

Do not make Karkinos broker- or trading-terminal-centric.

## vectorbt

Use vectorbt to compare research ergonomics, especially inexpensive parameter
exploration and result comparison.

Do not derive implementation details from it without a separate license review,
and do not sacrifice timing, cost, market-rule, or point-in-time correctness
for vectorized convenience.

## NautilusTrader

Use NautilusTrader primarily as a conceptual reference for deterministic trading
semantics.

Relevant lessons include clear time, event, order, fill, portfolio, and adapter
boundaries and consistent financial concepts across simulation and execution.

Do not copy its Rust, event-driven, low-latency, or live-trading infrastructure
without demonstrated need.

## Applying a reference

For a substantial design decision:

1. Identify the actual financial or research concept.
2. Inspect the closest relevant upstream design or documentation.
3. Extract the general problem and semantic lesson, not its source code.
4. Check licensing separately before any code, API, or implementation reuse.
5. Choose the smallest Karkinos design that preserves the required semantics.
6. Record durable Karkinos decisions in `ARCHITECTURE.md`, not here.

External precedent is evidence, not a requirement.
