# Karkinos

Karkinos: Investing is a chronic condition. Here is your scalpel.
（Karkinos：投资是一种慢性病。这是你的手术刀。）

Karkinos：面向中国市场的个人量化投研与交易平台。

一个集回测、策略实验、账户事实、风控、信号、对账与复盘于一体的个人金融应用。

Karkinos: A China-market personal quant research and trading platform.

An integrated personal finance app for backtesting, strategy research, account
truth, risk control, signals, reconciliation, and review.

[中文文档](docs/README.zh.md) | [English Docs](docs/README.en.md)

Strategic goal, roadmap, and implementation history live in
[docs/KARKINOS_GOAL.md](docs/KARKINOS_GOAL.md),
[docs/ROADMAP.md](docs/ROADMAP.md), and
[docs/IMPLEMENTATION_LOG.md](docs/IMPLEMENTATION_LOG.md).

---

**Disclaimer**

Karkinos is a personal quant research and trading platform, not investment
advice. Market data, portfolio valuation, backtest results, and trading
outcomes are not guaranteed to be accurate or complete. Do not use this project
as the sole basis for investment decisions.

Do not commit real account data, brokerage credentials, transaction exports,
personal financial data, runtime databases, logs, or screenshots containing
private information. Use example configuration and fake or sanitized data for
public demos and development.

**Highlights**

- Event-driven architecture with deterministic backtesting
- Strategy registry exposes typed parameter schemas, and backtest requests can
  use validated generic `params` while preserving legacy moving-average fields
- Backtest parameter sweeps run bounded typed grids, persist each tested
  configuration, and return deterministic rankings with multiple-testing
  warnings plus a versioned robustness artifact for local-neighbor stability
  and per-parameter sensitivity; the Web Strategy Lab can run the same bounded
  sweep and review the ranked configurations without approving execution
- Backtest strategy comparisons can run multiple strategies or parameter sets
  against one frozen dataset snapshot, reject mismatched snapshots, and return
  saved result ids for audit; the Web Strategy Lab can submit same-strategy
  parameter-set comparisons and review the shared snapshot evidence
- Backtest reports record a dataset snapshot with data-source/cache metadata,
  requested range, symbol universe, row counts, adjustment mode when available,
  and data-quality diagnostics, and the Web report exposes that audit panel for
  saved and freshly run results
- Backtest runs attach a versioned `research_evidence_bundle` with analyzer
  outputs, data-quality gate status, after-cost evidence references,
  China-market assumption gaps, and a manual-review promotion gate that does
  not enable execution
- Backtest results persist a strategy metadata snapshot with strategy identity,
  parameter schema, normalized params, benchmark role, and validation
  requirements so saved reports remain auditable when the registry changes; Web
  reports render the snapshot with readable strategy and parameter labels while
  keeping API keys as secondary audit fields
- Web Backtest reports surface after-cost evidence, single-split or rolling
  out-of-sample status, benchmark comparison, structured cost/slippage
  assumptions, and limitations without turning research output into execution
  approval
- Web Backtest Strategy Lab selects registry strategies, renders typed
  parameter controls with readable labels, exposes strategy metadata and
  validation requirements, and can run a single-symbol research backtest from
  the browser
- Web Backtest now summarizes the single-instrument research loop from dataset
  snapshot through signal preview, risk gate, paper/shadow simulation, and
  attribution boundary in user-readable copy without exposing internal reason
  codes or enabling execution
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- React + TanStack Query + TanStack Router personal finance app
- Responsive platform layout: primary pages reflow at desktop/narrow widths, while wide tables scroll inside their own panels
- Portfolio quote board summarizes asset classes; instrument-level quote, cost, and OHLC/K-line context lives in holding detail pages and the Market research page.
- Portfolio holdings and detail pages expose per-instrument daily PnL, daily return, quote price, cost basis, and baseline source so account-level changes can be traced back to individual stocks or funds.
- Holding detail pages link directly into the single-instrument Strategy Lab
  flow with the current symbol and asset class prefilled for research review.
- Portfolio cockpit construction recommendations are read-only evidence: they
  become actionable only after account-truth and risk gates pass, and they do
  not submit broker orders or bypass manual confirmation.
- Account Truth import preview documents a canonical broker statement CSV format and provides a read-only parser, staged broker evidence store, and reconciliation report core that validates, normalizes, fingerprints, duplicate-checks, persists local CSV rows, and compares broker evidence against cash, positions, fees, taxes, and cost basis without mutating the production ledger.
- Account Truth review APIs expose staged import runs and computed reconciliation
  reports for local review, including row counts, validation status, duplicate
  counts, source metadata, report status, unresolved counts, per-item
  differences, suggested review actions, and broker evidence references.
- Web Account Truth Review Center at `/account-truth` surfaces the latest
  Account Truth Score, import runs, status-filtered reconciliation reports,
  per-item broker/Karkinos differences, evidence references, and manual review
  actions without mutating the production ledger. Cost-basis reconciliation
  items include broker and Karkinos method context, per-share comparison units,
  and precision limitations so broker display rounding and local projections
  can be reviewed explicitly.
- Decision and Strategy Lab promotion review surfaces show Account Truth gate
  status, score, unresolved-difference context, and evidence availability so
  account-truth issues are visible before manual review or research promotion.
- Return calendar platform view: inspect audited attribution by day, week, month, or year with calendar/curve/table views and amount/return-rate toggles. The calendar starts weeks on Sunday, uses market PnL for cells, reads historical daily close from the local `market_bars` OHLC cache before falling back to daily-close snapshots, breaks daily market moves into stock/fund/other buckets, keeps deposits, withdrawals, dividends, and manual adjustments as external-flow context, skips non-trading, stale, or intraday terminal quote moves, treats estimated, cached, stale, or confirmed-NAV-missing periods as valuation gaps instead of confirmed returns, and includes axes in the curve view.
- Read-only decision APIs with portfolio, market-health, and after-cost/OOS evidence review, without automatic trading
- Docker one-click deploy

**Architecture**

```
DataHandler → EventBus → Strategy → Portfolio → RiskManager(-10) → Execution(0)
                        ↑                                              |
                        └──────────── FillEvent ──────────────────────┘
```

**Quick Start**

```bash
git clone <repo-url> && cd Karkinos
cp .env.example .env                   # optional: set tokens / runtime paths
uv sync                                # install dependencies
uv run python -m tools.run_backtest    # run local backtest tool
uv sync --extra server                 # install server extras
cd web && npm install && cd ..
uv run python scripts/configure_data_source.py  # optional: choose AKShare or TuShare safely
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
./scripts/stop_server.sh
```

`http://localhost:8000` is the product/customer entry. It serves the built React app from `web/dist`, so direct links such as `/portfolio`, `/activity`, `/risk`, `/decision`, `/market`, and `/settings` can be refreshed without returning home.

The data-source setup command writes ignored local `config.json` for you. It hides TuShare token input, never accepts tokens as CLI arguments, and is optional when you are happy with the default AKShare provider. Settings saved from the Web app persist local runtime preferences such as `data_source`, `live_poll_interval`, and the current account commission rule (`account_commission_rate`, `account_min_commission`) back into the same ignored config file. Advanced local fee assumptions can use `broker_fee_schedule`, which stores fee rule parameters, optional Shanghai/Shenzhen transfer-fee rates, and known limitations only, not account identifiers or broker credentials.
Manual trade ledger entries that omit an explicit fee use the configured account
fee rule and structured broker fee schedule to record commission, stamp tax,
exchange-specific transfer fee when configured, other fees, total fee, and net
cash impact. Bond and convertible-bond manual trades use the exchange-bond fee
model without stock stamp tax or transfer fees. Entries with an explicit fee
keep the `manual_fee_input` audit marker.

Use this storage boundary:

- `config.json`: local runtime preferences and deploy-specific knobs, including provider selection, poll interval, notification settings, CORS origins, the current account commission rule, structured broker fee schedule, and read-only broker connector client paths/account aliases. Broker passwords, tokens, secrets, account identifiers, screenshots, and private exports do not belong in broker connector or fee-schedule config.
- SQLite under `data/store/`: mutable financial facts and cache state, including watchlists, instrument metadata, ledger entries, quotes, bars, portfolio snapshots, trading controls, and saved backtest indexes.
- `reports/`: human-readable generated artifacts such as backtest JSON reports and data reconciliation outputs. Reports are runtime evidence, not source code.

**Market Data Reliability Workflow**

Karkinos labels market data with the shared statuses `confirmed`, `live`,
`cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`.
Overview, return calendar, Backtest data-audit panels, and strategy replay
evidence use those labels to distinguish confirmed values from local cache,
estimate-only values, missing quotes, stale quotes, and delayed fund NAVs.

Manual refresh and scheduled refresh flows can update intraday quotes, close
prices, and fund NAV confirmation without changing trading behavior. Frozen
market-data datasets can be replayed for research review, paper/shadow
comparison, and audit evidence. Estimated, cached, stale, missing, or
confirmed-NAV-missing values are data-quality evidence only; they are not
investment advice, profitability claims, or execution approval.

Initial screens do not seed portfolio assets, trades, or fund names. Effective
portfolio data comes from the local database or explicit private runtime
configuration; for example, Activity batch fund candidates are derived from
held fund positions instead of built-in defaults.

The Web app localizes portfolio asset classes in the selected UI language
and keeps ledger rows auditable: trade activity surfaces the instrument name
and symbol when present, amount, quantity, price, and commission without
exposing technical confirmation metadata.

Account Truth import preview can parse the canonical broker statement CSV
format documented in
[docs/account-truth-import.zh.md](docs/account-truth-import.zh.md). The preview
validates rows, computes file and row fingerprints, marks duplicate rows, and
returns broker evidence objects. Valid previews can be staged through
`BrokerEvidenceRepository.save_preview()`, which records import-run metadata and
broker evidence events while detecting duplicate files.
`build_reconciliation_report()` compares staged broker evidence with Karkinos
cash, position, fee, tax, and cost-basis facts and returns pass, warning,
mismatch, or blocked review evidence. `ManualReviewRepository.record_decision()`
can persist accepted, ignored, known-difference, ledger-candidate, or
needs-investigation review states for reconciliation items.
`build_account_truth_score()` converts reconciliation state, manual review
state, freshness, and unresolved differences into a 0-100 score plus pass,
degraded, or blocked gate status. These paths do not write production ledger
entries, change holdings, or submit broker orders.
Decision review and strategy promotion readiness consume this score as gate
evidence; degraded, blocked, or missing account-truth evidence prevents
live-like manual-confirm readiness or promotion readiness without authorizing
execution.

The Account Truth review API exposes the same evidence for Web and local review
workflows:

- `GET /api/account-truth/import-runs`
- `GET /api/account-truth/reconciliation-reports`
- `GET /api/account-truth/reconciliation-reports/{import_run_id}`
- `GET /api/account-truth/score`
- `POST /api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`

The listing and report routes are read-only. The review route records a manual
review decision such as `accepted`, `ignored`, `known_difference`,
`ledger_candidate`, or `needs_investigation` for a reconciliation item.
`ledger_candidate` is an audit label only: it does not mutate production ledger
entries, change holdings, store broker credentials, or submit broker orders.
The Web Review Center consumes the same endpoints and keeps those actions as
manual audit decisions, not execution approval.

Backtest results are indexed in the local SQLite database at
`data/store/app.db` so the Web app, risk review surface, and strategy promotion
checks can query them. Each saved backtest also writes a human-readable JSON
artifact under `reports/backtest/backtest-result-<id>.json` by default. Set
`KARKINOS_BACKTEST_REPORT_DIR` to place those local report files elsewhere.
The report directory is runtime data and should stay out of git.

Every Strategy Lab run should be read through its `research_evidence_bundle`.
Treat `gate_status` as the research review state: `pass` means the attached
evidence is internally consistent enough for human review, `degraded` means a
data/OOS/cost/analyzer warning needs review, and `blocked` means the run should
not be promoted until the blocking evidence gap is fixed. The bundle records
the dataset snapshot id, strategy metadata, analyzer outputs, after-cost and
OOS availability, fills/trade statistics, China-market assumptions, known
limitations, and `promotion_gate.does_not_enable_execution=true`. It is
evidence for review, not investment advice, not a profitability claim, and not
authorization to submit broker orders.

Backtest fill records keep the legacy `commission` total and now expose the
same structured fee-breakdown contract used by paper broker evidence, manual
trade preview, and ledger projections: commission, stamp tax, transfer fee,
other fees, total fee, fee-rule id, and known limitations.
When a backtest report includes fill records, the Web equity/drawdown chart
overlays buy/sell markers and a compact marker summary beside the curve. Those
markers are research evidence from the saved backtest fills only; they do not
approve execution or attribute live account returns by themselves.
`POST /api/backtest/signal-preview` can run a registered strategy over explicit
single-symbol bars or a server-side single-symbol date range and return
research-only strategy-runtime audit records
(`buy`, `sell`, `rebalance`, or `no_action`) with dataset snapshot and data
quality context plus a structured review-gate chain for data readiness,
account truth, pre-trade risk, paper/shadow preview, and manual review. It
validates the same strategy parameter schema as backtests and does not persist
signals, create action tasks, submit orders, create fills, or mutate ledger
entries.
`POST /api/backtest/risk-preview` can size one of those research candidates and
run the same pre-trade risk rules against current account context as a
read-only preview. The response reports pass/blocked reasons, requires manual
confirmation, and explicitly does not create orders, persist risk decisions, or
mutate ledger entries.
`POST /api/backtest/paper-shadow-preview` can then simulate a passed, sized
candidate as paper/shadow evidence. It returns paper order/fill evidence,
after-cost fee breakdown, and a shadow-review summary without writing order
facts, fills, ledger entries, or broker submissions.
`POST /api/backtest/attribution-preview` summarizes the same single-symbol
preview chain into an attribution evidence boundary. It reports preview
evidence versus production order/fill facts, returns a read-only manual review
linkage candidate, and keeps strategy P/L unavailable until real signal, review,
order, and fill evidence are linked.

For CI, release review, or manual acceptance checks, export the current
acceptance audit manifests as JSON:

```bash
uv run python scripts/export_acceptance_audit.py --audit all --pretty
uv run python scripts/export_acceptance_audit.py --audit research_evidence
uv run python scripts/export_acceptance_audit.py --audit account_truth
uv run python scripts/export_acceptance_audit.py --audit broker_fee_cost_basis
uv run python scripts/export_acceptance_audit.py --audit all --output reports/acceptance-audit.json
```

The command writes to stdout by default and only creates a file when `--output`
is provided.

Backend tests are grouped with pytest markers so local runs can stay focused:

```bash
uv run python -m pytest -m unit
uv run python -m pytest -m api_contract
uv run python -m pytest -m acceptance
uv run python -m pytest -m "not slow"
```

Full verification remains `uv run python -m pytest`.

Historical OHLCV market bars are stored in the local SQLite table
`data/store/meta.db.market_bars`; Parquet files under `data/store/bars/` are a
local mirror for compatibility and inspection. To import existing Parquet
mirrors into SQLite without fetching remote data, run
`uv run python scripts/sync_market_bars_to_db.py`. Cached data is auditable by
provider, fetch time, range, row count, and diagnostics, but it is not a
guarantee that every provider or public website will show identical values;
differences can come from adjustment mode, delayed fund NAVs, suspended
sessions, stale source data, or provider corrections.
The portfolio return, cost-basis, cash-flow, and baseline-price
semantics are documented in [docs/return-accounting.zh.md](docs/return-accounting.zh.md).
For an explicit one-symbol reconciliation report, run for example:
`uv run python scripts/verify_market_bars.py --symbol <symbol> --start 2026-06-12 --end 2026-06-15`.
The verifier fetches provider bars for comparison and returns JSON differences;
it does not overwrite the local cache.

In `dev` mode the script also starts Vite at `http://localhost:5173` for hot-reload frontend editing. Treat `5173` as a developer-only URL; use `8000` for product-like demos and customer flow checks.

The API only trusts local Vite origins by default:
`http://localhost:5173` and `http://127.0.0.1:5173`. For a real deployment,
set `KARKINOS_CORS_ALLOWED_ORIGINS` or `cors_allowed_origins` in your private
runtime config to the exact browser origins you operate. Avoid `*` for public
or credentialed deployments.

**Strategy Extensions**

Local research strategies belong under `strategy/extensions/`. Karkinos
discovers sanitized `*.strategy.json` manifests from that directory, or from
`KARKINOS_STRATEGY_EXTENSION_DIR`, and exposes their typed parameter schema via
`/api/backtest/strategies`. The committed `.example` files show the interface;
copied private strategy scripts and manifests stay ignored by git.

For private scripts stored directly in the extension directory, `class_path`
may point to the local module in `module:ClassName` form, for example
`my_strategy:MyStrategy`. Karkinos loads that class only when a
registered extension is instantiated for a research backtest, then validates
its declared params before constructing the strategy.

Extension manifests cannot declare live trading, broker submission, or
real-money execution capabilities. Strategy Lab runs remain research evidence
and do not bypass risk gates, paper/shadow review, signal journaling, or manual
confirmation.

For plain-language explanations of the built-in strategies, see the bilingual
strategy primer: [中文](docs/strategy/README.zh.md) /
[English](docs/strategy/README.en.md). It covers Dual Moving Average, Monthly
Rebalance, Bollinger Mean Reversion, and RSI reversal semantics without making
investment-advice or return claims.

**Account Strategy Context**

The Backtest page can show and save the current research-only account strategy
assignment through `/api/account-strategy`. The assignment never enables
automatic trading. Its attribution and contribution endpoints summarize linked
signals, actions, risk decisions, orders, fills, commissions, slippage, and the
latest local valuation evidence when those references exist.

Contribution reporting excludes manual trades, cash flows, and missing-evidence
market movement by default. It is audit tooling and research evidence, not
investment advice or execution approval.

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

Uses ignored local `./config.json` as runtime configuration and persists market cache / SQLite data in the `karkinos-data` Docker volume. Runtime config is not a market-data store; watchlists, quotes, bars, ledger entries, and portfolio state should live in the local database.

Runtime databases, local logs, exported files, screenshots, and local secret
files should stay on your machine and are not intended to be committed.

**Tech Stack**

Python 3.12 + FastAPI + React + TanStack Query + TanStack Router + ECharts + SQLite + Parquet

**License**

MIT
