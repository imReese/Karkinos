# Karkinos Design References

Karkinos uses mature open-source projects as design references for established
quantitative concepts and trade-offs.

Conceptual comparison is allowed. Any reuse, adaptation, or vendoring of source
code or other license-governed material requires a separate license review.

## Reference map

| Area | Reference | Main lesson |
| --- | --- | --- |
| Data, PIT, research workflow | [Qlib](https://github.com/microsoft/qlib) | Reproducible datasets and research lifecycle |
| Forecast -> portfolio -> execution | [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | Separate investment views, portfolio intent, risk, and execution |
| China-market simulation | [RQAlpha](https://github.com/ricequant/rqalpha) | Explicit market, matching, cost, account, and risk concerns |
| China-market integrations | [VeighNa](https://github.com/vnpy/vnpy) | Keep venue-specific gateways outside the domain core |
| Fast quantitative exploration | [vectorbt](https://github.com/polakowo/vectorbt) | Make experimentation and comparison cheap |
| Execution and accounting semantics | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Clear order, fill, position, portfolio, and adapter boundaries |

## Qlib

Use Qlib primarily for research-system concepts: first-class datasets,
point-in-time correctness, reproducible experiments, model evaluation, and the
separation of predictive research from portfolio analysis.

Do not copy its full ML platform or workflow infrastructure without a concrete
Karkinos need.

## QuantConnect LEAN

Use LEAN primarily for responsibility boundaries between predictive output,
portfolio construction, risk, and execution.

Do not reproduce its brokerage ecosystem or force every Karkinos workflow into
a large framework.

## RQAlpha

Use RQAlpha to compare China-market simulation concerns such as market rules,
matching assumptions, transaction costs, accounts, and risk.

Treat it as a problem-space reference rather than an implementation template.

## VeighNa

Use VeighNa primarily for China-market provider and venue boundaries, including
identifiers, sessions, contracts, and gateway isolation.

Do not make Karkinos broker- or trading-terminal-centric.

## vectorbt

Use vectorbt primarily for research ergonomics: inexpensive parameter
exploration, comparison, and analysis.

Do not sacrifice timing, cost, market-rule, or point-in-time correctness for
vectorized convenience.

## NautilusTrader

Use NautilusTrader primarily for order/fill lifecycle, execution adapters,
position/accounting semantics, and deterministic event-driven behavior.

Do not copy low-latency, Rust, event-bus, or live-trading infrastructure without
a demonstrated Karkinos requirement.

## Using a reference

For a substantial quantitative or architecture decision:

1. identify the actual financial or research concept;
2. inspect the closest relevant upstream design;
3. separate the useful semantic lesson from its implementation machinery;
4. check licensing separately before reusing license-governed material;
5. choose the smallest Karkinos design that preserves the required semantics.

External precedent is evidence, not a requirement.
