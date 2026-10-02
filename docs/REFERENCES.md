# Karkinos Design References

| Area | Reference | Use for |
| --- | --- | --- |
| Data, PIT, research workflow | [Qlib](https://github.com/microsoft/qlib) | datasets, PIT correctness, experiments, model evaluation |
| Forecast -> Portfolio -> Execution | [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | responsibility boundaries between predictive output, portfolio, risk, execution |
| China-market simulation | [RQAlpha](https://github.com/ricequant/rqalpha) | market rules, matching, transaction costs, accounts, risk |
| China-market integrations | [VeighNa](https://github.com/vnpy/vnpy) | identifiers, sessions, contracts, gateway boundaries |
| Fast research | [vectorbt](https://github.com/polakowo/vectorbt) | parameter exploration, comparison, analysis ergonomics |
| Execution/accounting semantics | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Order/Fill lifecycle, adapters, positions, deterministic runtime semantics |

Research/simulation authority design also consults
[LEAN's Algorithm Framework overview](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview)
for the distinction between predictions, portfolio targets, risk and execution,
and [scikit-learn's evaluation guidance](https://scikit-learn.org/stable/modules/cross_validation.html)
for separation of iterative validation from final test data. Karkinos retains its
own publication authority and independent Risk Decision semantics.

## Reference rules

- Extract domain semantics and trade-offs, not project structure by default.
- Prefer the smallest Karkinos design that preserves required semantics.
- Do not import brokerage ecosystems, workflow frameworks, low-latency infrastructure, or language choices without a concrete requirement.
- Source-code reuse, adaptation, or vendoring requires a separate license review.
