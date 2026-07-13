# Karkinos

Karkinos: Investing is a chronic condition. Here is your scalpel.
（Karkinos：投资是一种慢性病。这是你的手术刀。）

Karkinos：面向中国市场的个人量化投研与交易平台。

一个集回测、策略实验、账户事实、风控、信号、对账与复盘于一体的个人金融应用。

Karkinos: A China-market personal quant research and trading platform.

An integrated personal finance app for backtesting, strategy research, account
truth, risk control, signals, reconciliation, and review.

[中文文档](docs/README.zh.md) | [English Docs](docs/README.en.md)

Strategic goal, architecture, roadmap, and implementation history live in
[docs/KARKINOS_GOAL.md](docs/KARKINOS_GOAL.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/ROADMAP.md](docs/ROADMAP.md)
([中文路线图](docs/ROADMAP.zh.md)), and
[docs/IMPLEMENTATION_LOG.md](docs/IMPLEMENTATION_LOG.md). The staged plan for
human-supervised broker execution and capital scaling is
[docs/CONTROLLED_EXECUTION_PLAN.md](docs/CONTROLLED_EXECUTION_PLAN.md).

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
- Controlled automation architecture: research evidence, daily plan, risk
  gate, paper/shadow, OMS, manual ticket, reconciliation, and future gated
  broker bridge remain separate authority layers
- Capital-bounded execution target: account capital never grants authority by
  itself; future machine authority is explicit, expiring, revocable, and
  limited by the strictest operator/account/strategy/symbol/risk/liquidity gate
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
- Overview Today’s to-dos: review today’s conclusion, execution state, account
  truth, risk blockers, strategy candidate pool, manual-confirmation queue,
  stock/fund/total daily PnL, top position contributors, market pulse,
  valuation confidence, equity curve, and return calendar summaries before
  drilling into Portfolio, Market, Trading, Decision, or Backtest. Candidate
  counts are shown as research supply, not as the number of trades to execute.
- Market pulse uses a small default China-market index universe as background
  context. Manual quote refresh and the Web scheduler can refresh those index
  quotes alongside account holdings, and missing index move fields are shown as
  data gaps instead of empty values; index quotes do not become user holdings,
  strategy tradables, broker orders, or execution approval.
- Return calendar platform view: inspect audited attribution by day, week, month, or year with calendar/curve/table views and amount/return-rate toggles. The calendar starts weeks on Sunday, uses market PnL for cells, reads historical daily close from the local `market_bars` OHLC cache before falling back to daily-close snapshots, breaks daily market moves into stock/fund/other buckets, keeps deposits, withdrawals, dividends, and manual adjustments as external-flow context, skips non-trading, stale, or intraday terminal quote moves, treats estimated, cached, stale, or confirmed-NAV-missing periods as valuation gaps instead of confirmed returns, and includes axes in the curve view.
- Read-only decision APIs with portfolio, market-health, and after-cost/OOS evidence review, without automatic trading
- Docker one-click deploy

**Architecture**

```
DataHandler → EventBus → Strategy → Portfolio → OrderIntent → Risk Gate → Order/Gateway
                        ↑                                                     |
                        └──────────────── FillEvent ──────────────────────────┘
```

The full architecture is documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Karkinos is designed to improve
after-cost trading outcomes through evidence, risk control, simulation,
reconciliation, and review. Broker submission is a future controlled-bridge
capability, disabled by default, not the default source of trading edge.

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

The data-source setup command writes ignored local `config.json` for you. It hides TuShare token input, never accepts tokens as CLI arguments, and is optional when you are happy with the default AKShare provider. Settings saved from the Web app persist local runtime preferences such as `data_source`, `live_poll_interval`, and account fee assumptions back into the same ignored config file. Account commission settings are stored under `broker_fee_schedule`; legacy top-level commission fields are read only as a migration path. `broker_fee_schedule` stores fee rule parameters, optional Shanghai/Shenzhen transfer-fee rates, and known limitations only, not account identifiers or broker credentials. See [docs/config-reference.zh.md](docs/config-reference.zh.md) for field-level configuration notes.
Manual trade ledger entries that omit an explicit fee use the configured account
fee rule and structured broker fee schedule to record commission, stamp tax,
exchange-specific transfer fee when configured, other fees, total fee, and net
cash impact. Bond and convertible-bond manual trades use the exchange-bond fee
model without stock stamp tax or transfer fees. Entries with an explicit fee
keep the `manual_fee_input` audit marker.

Use this storage boundary:

- `config.json`: local runtime preferences and deploy-specific knobs, including provider selection, poll interval, notification settings, CORS origins, structured broker fee schedule, and read-only broker connector client paths/account aliases. Broker passwords, tokens, secrets, account identifiers, screenshots, and private exports do not belong in broker connector or fee-schedule config.
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

**Automation Maturity**

Karkinos is moving toward a professional automated-quant workflow whose goal is
better after-cost trading outcomes, not faster unchecked order submission. The
default product boundary remains daily plan generation plus manual
confirmation. v1.6 completed the persisted paper/shadow runbook, deterministic
reruns, divergence review, and Operations surfaces. v1.7 completed the
non-submitting controlled-bridge foundation: manual tickets, local read-only
connector evidence, capability/health contracts, manual execution evidence,
and execution reconciliation. This completion does not provide broker submit,
executable broker cancel, automatic ledger mutation, or auto-pilot authority.
v1.8 planning is active, but its real-money submission and automation authority
remain unimplemented and disabled. Unattended full-account real-money
automation remains outside the product target.

v1.8 planning is now organized as Capital-Bounded Controlled Execution. It
starts with a non-submitting authorization contract and a real read-only broker
soak, then advances to per-order human-confirmed submission, short-lived
session-bounded execution, and human-reviewed capital scaling. The first live
tier deliberately uses a small risk envelope to contain unknown failures; this
is not a permanent account-size or product limit. Manual confirmation remains
the default, no session may widen or renew itself, and strategy code never
receives broker authority. See the
[controlled execution plan](docs/CONTROLLED_EXECUTION_PLAN.md).

The first v1.8 Stage 0 implementation is available as non-submitting evidence
only. `/api/automation/capital-authority/status` always reports runtime
authority and broker submission disabled;
`/api/automation/capital-authority/preview` performs a side-effect-free policy
evaluation; and `/api/automation/capital-authority/evaluations` records or
lists append-only evaluation evidence. An `allowed=true` evaluation is not an
execution authorization. These endpoints cannot enable, resume, submit,
cancel, mutate OMS, write the production ledger, or expand capital authority.
The v2 evaluation contract separates `evidence_connector_ids` from
`execution_gateway_ids`: the evidence connector must remain read-only, the
execution gateway is a distinct scoped identity, and a verified same-account
binding is required. Identical or overlapping roles fail closed. Declared
gateway health/capability remains runtime-unverified evidence and cannot
authorize or contact a broker.

Stage 1 now has a broker-neutral read-only soak foundation. The
`/api/automation/broker-soak/capture`, `/status`, and `/observations` endpoints
can consume configured local QMT/PTrade/read-only exports, persist sanitized
snapshot evidence, track freshness and provider-calendar trading-day coverage,
and emit Operations alerts for degraded or blocked observations. Raw account
ids are not returned or stored in snapshot facts, any submit capability is
blocked, and 20 healthy trading days complete only the operational soak. Broker
promotion is never inferred from day count alone; the legacy status remains
blocked until separately reviewed evidence is resolved.
`/api/automation/broker-soak/runs` adds deterministic startup, intraday, and
end-of-day evidence with a mandatory clear reconciliation gate at end of day;
`/drills` records disconnect, schema-drift, stale, duplicate-evidence, and
service-instance restart-recovery checks. See
[`docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md`](docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md).

Stage 1.1 adds a separate signed promotion dossier under
`/api/automation/broker-soak/promotion`. It requires 20 unique healthy days
with clear zero-open-item reconciliation, passed startup/intraday/end-of-day
evidence for every selected day, all five recovery drills, and a current
pass/fresh/zero-unresolved Account Truth source fingerprint. Owner acceptance
uses a short-lived Ed25519 approval for the exact dossier and explicitly
attests the same account alias plus full process/broker-terminal recovery,
which the service cannot verify automatically. Source drift invalidates the
acceptance. `promotion_ready` here means Stage 1 evidence readiness only; it
does not issue capital/runtime authority. Stage 2 now binds this exact current
promotion dossier and acceptance into each per-order dossier, but that linkage
does not enable the broker bridge.

The Stage 2 foundation is also non-submitting. The
`/api/automation/controlled-bridge` status, dossier preview, confirmation, and
history endpoints bind one OMS order to the current capital evaluation,
Account Truth/research/risk/paper-shadow gates, connector soak, prior
reconciliation, and kill-switch state. Exact-fingerprint attestations remain
short-lived Ed25519-verified identity evidence bound to the exact dossier and a
configured operator public key. The dossier also binds the current Stage 1
promotion, operational, Account Truth, and owner-acceptance fingerprints for
the capital-policy evidence connector, while the distinct execution gateway is
bound separately. It remains runtime-unverified unless the request, recorded
capital evaluation, current gateway verification, OMS order, connector,
account alias, and canonical order fingerprint all match exactly; missing
evidence, role overlap, expiry, or source drift fails closed. Karkinos stores no
operator private key, and a verified attestation still cannot change OMS, grant
authority, submit or cancel an order, resume automation, or scale capital.

Stage 2.4 adds `/api/automation/execution-gateway-verification` status, preview,
record, resolve, and history endpoints. A registered runtime gateway must expose
verified evidence-connector/account binding, fresh source-fingerprinted health,
submit/cancel/query/dry-run/idempotency capabilities, and an exact dry-run that
returns no broker order id, `submitted=false`, and zero side effects. Recorded
evidence expires after five minutes and is rechecked for source drift. No
execution gateway is registered by default, and even clear verification cannot
issue authority or submit an order.

Stage 2.5 binds that exact short-lived verification into each per-order
dossier. The capital evaluation must already contain the typed
`execution_gateway_verification:<fingerprint>` reference, and every preview or
confirmation re-resolves the current source before accepting the dossier.
Gateway, read-only connector, account, OMS order, and order fingerprint drift
re-block review and invalidates the prior operator approval. A clear binding
removes only the runtime-verification blocker; runtime authority, live gateway,
and broker submission remain disabled.

The Stage 3 foundation remains proposal-only. The
`/api/automation/controlled-sessions` status, envelope preview, attestation, and
history endpoints project an explicit OMS order set inside a timezone-aware
window of at most 30 minutes. Capital, cash, conservative gross exposure,
turnover, per-order, position-change, liquidity, and rate budgets are checked,
and the v2 evidence-connector/execution-gateway split is fingerprinted. Stage 3.3
additionally requires one unique, current gateway verification per OMS order and
the exact same typed reference set in the recorded capital evaluation; one
missing, reused, expired, drifted, or mismatched order proof blocks the whole
envelope. No budget is reserved and no runtime session is issued. There are no
enable, resume, runtime-revoke, submit, cancel, or automatic scale-up operations.

Stage 3.4 adds `/api/automation/session-start-account-truth` status, preview,
record, resolve, and history evidence. The source is rebuilt from the latest
Account Truth import, reconciliation, ledger projection, and manual reviews; it
must be pass/fresh/clear with zero unresolved mismatches and no more than 120
seconds old. The session request and capital evaluation bind the same typed
fingerprint, connector, and account alias. Source drift or expiry re-blocks the
envelope, while a clear record still cannot reserve budget or issue a session.

Stage 3.5 adds
`/api/automation/controlled-sessions/budget-reservations` status, preview,
record, resolve, and history evidence. A reservation is allowed only for a
still-current signed envelope; SQLite `BEGIN IMMEDIATE` serializes overlapping
capital, cash, China-trading-day turnover, and order-count checks. The record
is a bounded budget hold, not a runtime session or broker permission: OMS,
ledger, submit/cancel, resume/renew, and capital scaling remain unavailable.

Stage 3.6 binds an explicit per-symbol runtime-limit map into the same signed
envelope and atomic reservation. Each limit must cover exactly the projected
symbol set, remain below the recorded capital evaluation's symbol ceiling, and
cover its conservative gross projection. Concurrent overlapping reservations
are summed per symbol; same-symbol excess fails while disjoint symbols still
share the stricter account budget. This does not issue a session or enable a
broker action.

Stage 3.7 adds an internal atomic runtime rate-admission ledger with a
server-time 60-second sliding window, exact session/reservation/order/request
binding, idempotent retries, shared account-rate enforcement, and concurrent
last-slot serialization. Stage 3.9 now supplies its authenticated persistent
session provider, while the API still exposes only read-only status/history:
there is no public runtime-admit, OMS mutation, or broker action.

Stage 3.8 adds an internal durable automatic-pause controller. It evaluates an
allowlisted snapshot of Account Truth, risk, reconciliation, paper/shadow,
gateway, market-data, budget, rate, kill-switch, loss/drawdown, rejection,
account-change, and consecutive-error facts. The first failure persists a
one-way `paused` state, and runtime rate admission rechecks that state inside
its write transaction. Stage 3.9 supplied authenticated session identity while
that slice still had no live gate provider. Stage 3.10 now supplies persisted
gate orchestration, and Stage 3.11 supplies signed replacement rather than
automatic resume. Stage 3.12 adds the first one-shot OMS submit-intent
transition and an injectable broker-contact boundary, but production still
registers no write gateway or signed release-evidence provider by default.

Stage 3.9 adds separately signed runtime-session issuance and one-way
revocation. A current envelope attestation and atomic reservation are
re-resolved, then the owner must sign the exact issuance fingerprint with the
new `issue_controlled_session` action and submit the matching signature as
possession proof; public approval history omits signature bytes. The high-
entropy session token is shown only once and only its salted hash is stored.
Expiry, source drift, pause, or a
separately signed revocation blocks authentication; rate admission atomically
rechecks persistent state against stale providers. This is bounded internal
runtime authority, not broker authority: no public admit/resume/renew/widen,
OMS/ledger mutation, or broker submit/cancel path exists.

Stage 3.10 wires persisted live-gate snapshots into the one-way pause
controller. Account Truth, risk, paper/shadow, reconciliation, gateway,
market-data freshness, runtime budget/rate, kill switch, loss/drawdown,
rejection, account-change, and consecutive-error facts are captured before
each evaluation; missing or invalid facts pause rather than pass. The scheduler
runs this orchestration only when explicitly started, and a token holder may
request only a self-check that can preserve or reduce authority. Snapshots use
a 30-second freshness window, market data uses 120 seconds, and three rate
rejections inside 60 seconds trip the rejection-spike gate. This still creates
no broker submit/cancel, OMS/ledger write, resume/renew/widen, or automatic
capital-change path.

Stage 3.11 adds a signed paused-session replacement protocol without adding an
in-place resume. Ordinary issuance cannot bypass an unexpired paused session in
the same authorization/account/strategy scope. Replacement requires a fresh
attestation and reservation, two continuously clear post-pause snapshots over
at least 60 seconds, a newest snapshot no older than 30 seconds, and a distinct
Ed25519 `replace_paused_controlled_session` approval with signature possession.
One SQLite transaction revokes the predecessor and issues a same-or-narrower
session with a new one-time token; exact retries never reissue it. There is
still no renew, widen, public runtime admit, OMS/ledger mutation, automatic
capital increase, or broker submit/cancel path.

Stage 3.12 adds a deliberately narrow per-order broker submission foundation.
It re-resolves the current manually confirmed dossier and exact prior-batch
reconciliation, requires a separate final Ed25519 signature, current signed
broker/regulatory release evidence, gateway capability/health/dry-run checks,
and a clear kill switch. The submit intent and `submission_pending` OMS state
are committed before one external call; accepted, rejected, and unknown results
are distinct. Unknown results are never resubmitted and may only be recovered
by querying the same idempotent client order id after 30 seconds. Production
still has no configured write adapter or release provider, no automatic or
strategy-direct submission, no broker cancel, and no fill/ledger mutation.

Stage 3.13 adds a fail-closed cross-order submission interlock. Any different
order is blocked while a controlled intent is prepared, accepted but not yet
reconciled, or unknown; the check runs both in preview and inside the SQLite
write transaction, so different-order concurrency cannot bypass it. Execution
reconciliation now classifies those states, unknown outcomes produce a critical
alert, and Operations exposes the query-only recovery task. A definitive
rejection releases the interlock. Accepted broker evidence remains an open
human review item and cannot infer a fill, update the ledger, or clear the next
order; that signed reconciliation clearance is a later stage.

Stage 3.14 implements that narrow signed clearance for exact full fills. The
latest controlled-submission reconciliation item, all matching trade rows from
one validated broker import, and fresh clear Account Truth must agree on the
full OMS quantity and source file. A separate operator signature then permits
one atomic transaction to record linked real fills, advance OMS to `filled`,
persist the clearance, and release the next-order interlock. Partial totals,
cross-import aggregation, automatic ledger mutation, automatic/strategy-direct
submission, and production adapter registration remain disabled. Generic CSV
rows lack a broker order id, so their signed selection is a manual mapping
assumption pending a broker-specific adapter.

Stage 2.1/3.1 now removes the ambiguous "latest reconciliation" shortcut. The
batch-evidence API binds an exact non-paper terminal OMS order set to one
persisted reconciliation run, including current order/transition/fill/item/run
fingerprints and real-fill Account Truth linkage. Per-order and session reviews
must provide the same batch fingerprint already present in their recorded
capital evaluation. Missing, open, duplicated, quantity-incomplete, or later-
changed facts fail closed. A clear batch fact does not authorize the next batch
and adds no broker, OMS, ledger, budget, or runtime-session capability.

Stage 2.2/3.2 adds public-key operator approval evidence. The capital-authority
API can issue a short-lived, nonce-bearing challenge and verify an Ed25519
signature for either an exact per-order dossier or controlled-session envelope.
Per-order confirmations and session attestations require the resulting approval
id and matching operator label. Disabled/rotated keys, expired challenges,
invalid signatures, and cross-artifact reuse fail closed. These endpoints do
not issue authority or add gateway, OMS, ledger, budget, submit, cancel, resume,
or automatic scale-up capability.

The Stage 4 foundation is an evidence-only capital scaling review. The
`/api/automation/capital-scaling` status, preview, evaluation, decision, and
history endpoints compare versioned tiers against operating days, fill/reject
quality, slippage, after-cost result, drawdown, capacity/liquidity,
reconciliation, divergence, disconnect, violation, and incident evidence.
Passing evidence can only request a separate new authorization; it never applies
a tier, mutates limits, resumes execution, or automatically scales capital.
Stage 4.1 now resolves broker-soak, execution-reconciliation, paper/shadow, and
risk references to persisted source facts and binds their sanitized resolution
fingerprint into the evaluation identity. Missing, non-clear, or out-of-window
sources fail closed. Account Truth is now a required evidence kind. Stage 4.2
adds read-only Account Truth point snapshots and computed evidence-window APIs
under `/api/automation/capital-scaling/evidence`: after-cost uses Modified
Dietz over persisted equity/cash-flow facts, incident metrics scan persisted
alerts/write rejections/connector observations, and capacity/liquidity/slippage
require non-simulated reconciled fills with explicit source linkage. Callers
cannot submit aggregate metric values; incomplete coverage records a blocked
fact, and even a clear window can only support a separate authorization request.
Stage 4.3 adds a required computed operating sample to that window: healthy
broker-soak trading days, non-paper OMS outcomes, reconciled real-fill linkage,
latest order-level reconciliation coverage and p95 latency, paper/shadow
divergence, and cash-flow-unitized maximum drawdown are derived from persisted
facts and checked exactly against the review request. Missing or truncated
coverage fails closed. This remains evidence-only and cannot grant authority,
change runtime limits, mutate OMS/ledger state, or contact a broker.

The v1.6 paper/shadow run path is:
daily trading plan -> pre-trade risk -> local paper/shadow run -> divergence
review -> manual confirmation. `POST /api/operations/paper-shadow/run` creates
or reuses an idempotent run record, deterministic simulated order/fill facts,
and a latest-run summary for Operations and Decision. These artifacts are
simulation evidence only: they do not create manual orders, mutate production
ledger entries, change cash or positions, store broker credentials, or submit
broker orders. If an operator accepts a diverged paper/shadow review, Operations
keeps the raw divergence evidence while exposing a runbook handoff status for
manual confirmation.

After a manual-ticket export, Trading links the operator to Account Truth
broker-statement import and execution-reconciliation review. Reconciliation
compares matching manual-execution evidence with staged broker price, quantity,
gross amount, fee, tax, transfer fee, and net amount. Matches and differences
are shown as a read-only Decision comparison and remain review evidence: they
do not change OMS state, write production ledger entries, alter cash or
positions, contact a broker, or submit orders.

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
needs-investigation review states for reconciliation items. Each review is
bound to the exact reconciliation-item fingerprint and appended to audit
history. A stale or current manual label cannot override a material mismatch;
the broker evidence, ledger fact, or explicit reconciliation tolerance must
actually remove the difference. Broker evidence older than the latest local
ledger fact also fails closed as stale.
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
uv run python scripts/export_acceptance_audit.py --audit operations_runbook
uv run python scripts/export_acceptance_audit.py --audit controlled_broker_bridge_foundation
uv run python scripts/export_acceptance_audit.py --audit capital_authorization_policy
uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_foundation
uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_promotion
uv run python scripts/export_acceptance_audit.py --audit per_order_confirmation_foundation
uv run python scripts/export_acceptance_audit.py --audit controlled_session_envelope_foundation
uv run python scripts/export_acceptance_audit.py --audit controlled_broker_submission
uv run python scripts/export_acceptance_audit.py --audit controlled_submission_interlock
uv run python scripts/export_acceptance_audit.py --audit signed_operator_approval
uv run python scripts/export_acceptance_audit.py --audit capital_scaling_review_foundation
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
[English](docs/strategy/README.en.md). It covers the built-in trend,
allocation, mean-reversion, volatility-targeting, and long-only pair-rotation
research strategies without making investment-advice or return claims.

**Account Strategy Context**

The Backtest page can show and save the current research-only account strategy
assignment through `/api/account-strategy`, and it can save symbol-specific
research strategy bindings through `/api/account-strategy/assignments`. These
assignments never enable automatic trading. Attribution and contribution
endpoints summarize linked signals, actions, risk decisions, orders, fills,
commissions, slippage, and the latest local valuation evidence when those
references exist.

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
