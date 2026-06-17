# Benchmark Notes

Karkinos may learn from mature open-source finance and quant systems, but it
must not copy their code or dilute its own safety boundary. These notes are
architecture and product-design references only.

## Learning Boundary

Use these projects to learn architecture, interfaces, testing discipline,
auditability, risk controls, data import/reconciliation, and UX patterns.

Do not copy code, vendor-specific internals, broker credentials, broker login
flows, order-submission defaults, or profitability claims.

## Reference Projects

* OpenBB: learn from a modular research terminal/workspace model, clear data
  provider boundaries, and discoverable commands. For Karkinos, this suggests
  explicit local data and report surfaces rather than hidden provider calls.
* Microsoft Qlib (`https://github.com/microsoft/qlib`): learn data-driven
  research workflow discipline: data preparation, feature generation, model or
  strategy execution, backtest, evaluation, and report review. Karkinos should
  keep point-in-time dataset manifests, feature manifests, and reproducible
  experiment records.
* QuantConnect LEAN (`https://github.com/QuantConnect/Lean`): learn modular
  engine boundaries where data, brokerage adapters, indicators, reports,
  optimizers, and research tooling are separate extension points. Karkinos
  should express this as run manifests and safe adapter interfaces, not
  broker automation.
* backtrader: learn strategy/analyzer/broker/feed separation and local research
  ergonomics. Karkinos should preserve explicit cost, risk, and account-truth
  evidence rather than hiding assumptions inside strategy code.
* vectorbt: learn fast parameter exploration and vectorized research UX.
  Karkinos should pair sweeps with stability evidence, OOS review, and
  overfitting warnings.
* Freqtrade (`https://github.com/freqtrade/freqtrade`): learn practical ops
  ergonomics: validated config files, resolved-config inspection, data
  download/list commands, saved backtest analysis, dry-run-first operation,
  and lookahead / recursive-formula diagnostics.
* RQAlpha: learn China-market assumption modeling around A-shares, ETF/fund
  calendars, T+1, transaction costs, and asset-specific constraints.
* VeighNa / vn.py (`https://github.com/vnpy/vnpy`): learn gateway/app/datafeed
  /database separation, local paper account concepts, data manager, risk
  manager, portfolio manager, and RPC-style routing discipline. Karkinos'
  near-term use is read-only broker evidence import and reconciliation, not
  broker-side order submission.
* Ghostfolio: learn portfolio tracking, allocation, holdings, and personal
  finance dashboard UX patterns.
* rotki: learn local-first privacy posture, account history import, asset
  history, auditability, and reconciliation-style accounting discipline.
* Portfolio Performance: learn local portfolio accounting UX, statement import,
  transaction taxonomy, performance attribution, and explainable holdings views.

## Borrowed Design Themes

* Provider and broker-evidence imports should be explicit, local, fingerprinted,
  and reproducible.
* Research outputs should carry dataset, feature, parameter, cost, OOS,
  analyzer, and limitation evidence.
* Account truth should gate decisions and promotion, not mutate the production
  ledger automatically.
* Dry-run, paper/shadow, and manual-confirmation boundaries should be visible
  in the UI and API.
* Diagnostics should prefer deterministic local tests and synthetic examples
  over live-provider-dependent checks.
