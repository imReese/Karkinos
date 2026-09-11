# Karkinos Design References

| Area | Reference | Use for |
| --- | --- | --- |
| Data, PIT, research workflow | [Qlib](https://github.com/microsoft/qlib) | datasets, PIT correctness, experiments, model evaluation |
| Forecast -> Portfolio -> Execution | [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | responsibility boundaries between predictive output, portfolio, risk, execution |
| China-market simulation | [RQAlpha](https://github.com/ricequant/rqalpha) | market rules, matching, transaction costs, accounts, risk |
| China-market integrations | [VeighNa](https://github.com/vnpy/vnpy) | identifiers, sessions, contracts, gateway boundaries |
| Fast research | [vectorbt](https://github.com/polakowo/vectorbt) | parameter exploration, comparison, analysis ergonomics |
| Execution/accounting semantics | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Order/Fill lifecycle, adapters, positions, deterministic runtime semantics |

## Reference rules

- Extract domain semantics and trade-offs, not project structure by default.
- Prefer the smallest Karkinos design that preserves required semantics.
- Do not import brokerage ecosystems, workflow frameworks, low-latency infrastructure, or language choices without a concrete requirement.
- Source-code reuse, adaptation, or vendoring requires a separate license review.
