# Karkinos: A China-market personal quant research and trading platform

[中文](README.zh.md) | [Back to Summary](../README.md) | [Goal](KARKINOS_GOAL.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md)

---

## Overview

Karkinos is an integrated personal finance app for backtesting, strategy
research, account truth, risk control, signals, reconciliation, and review.
It is designed for the Chinese market with an event-driven architecture,
backtest-first workflow, and daily-bar-oriented assumptions, supporting
A-shares, ETFs, gold spot, and exchange-traded bonds.

Key Features:

- **Evidence-governed AI research** — provider/model/role registration,
  immutable valuation-and-ledger-bound contexts, deny-by-default read tools,
  deterministic fixture workflows, cited artifacts, and hash-chain replay.
  A separate explicit saved-backtest report command may send only one selected,
  complete canonical research-evidence payload to the configured
  OpenAI-compatible model after exact data-export consent. Account holdings and
  execution-authority facts are excluded; the result remains a
  non-authoritative report requiring human review. The configured reasoning
  mode remains available, while a versioned JSON-only prompt supplies an exact
  structural example, evidence-review rubric, and final self-check. A
  DeepSeek-compatible edge explicitly keeps thinking/high effort within a 4K
  output budget and a cancellable 180-second end-to-end deadline. Raw reasoning
  is never stored, and provider-side tools remain disabled. A separately
  reviewed result may be promoted only through an explicit, revocable,
  versioned historical-memory boundary. The artifact binds exact report,
  review, retrieval, source-memory,
  context, evidence, provider/model/prompt, quality/cost, and audit identities;
  it is not a current fact and must rebind current evidence before future use.
  Phase 1.12 remains unchanged, and Phase 1.16 adds no retrieval, automatic
  recall, Decision input, trade plan, financial write, broker action, capital,
  or execution authority.
- **Event-Driven Architecture** — All components communicate through EventBus, ensuring deterministic backtesting
- **Multi-Asset Support** — A-shares, ETFs, gold spot, exchange-traded bonds; Instrument field values carry asset differences
- **Target Weight Signals** — Strategies output target weights (0~1), Portfolio auto-converts to share counts
- **T+1 Support** — Built-in freeze/thaw mechanism in Position, auto-advanced on settlement day
- **Live Monitoring** — Standalone Live mode + built-in Scheduler in Web service, with signal push notifications
- **Notifications** — Console / Telegram / WeChat (ServerChan) channels
- **Web UI** — React + TypeScript + TanStack Router + TanStack Query + ECharts personal finance app
- **Holdings and market detail** — the Portfolio quote board summarizes asset classes, while instrument-level quote, cost, and OHLC/K-line context lives in holding detail pages and the Market research page
- **Single-instrument strategy research entry** — holding detail pages can hand
  the current symbol and asset class into the Strategy Lab one-symbol research
  flow for dataset, backtest, signal, risk-preview, simulation, and attribution
  boundary review
- **Responsive Platform Layout** — Primary pages reflow across desktop and narrow widths, with wide tables scrolling only inside their own panels
- **Return Calendar** — Review monthly day-by-day, yearly month-by-month, and annual return attribution from audited timeline data; estimated, cached, stale, or confirmed-NAV-missing periods still show their return value but are marked unconfirmed, while only missing or unavailable prices are shown as valuation gaps
- **Account Truth review API** — Read-only endpoints list staged import runs
  and computed reconciliation reports with row counts, validation status,
  duplicate counts, source metadata, report status, unresolved differences,
  suggested review actions, and broker evidence references; a manual review
  endpoint records item decisions such as `ledger_candidate` without mutating
  the production ledger
- **Account Truth Review Center** — Web `/account-truth` shows Account Truth
  Score, import runs, status-filtered reconciliation reports, per-item
  broker/Karkinos differences, evidence references, and manual review actions
  without mutating the production ledger. Cost-basis differences show broker
  and local method context, per-share comparison units, and precision
  limitations.
- **Account Truth gate linkage** — Decision and Strategy Lab promotion review
  surfaces show Account Truth gate status, score, unresolved-difference
  context, and evidence availability before manual review or research promotion
- **Single-instrument loop summary** — Web Backtest summarizes dataset
  snapshot, strategy registry, after-cost backtest, today's signal, risk gate,
  paper/shadow simulation, and attribution boundary as a readable review card;
  it is research evidence only and does not create orders, fills, ledger
  entries, or broker submissions
- **Docker One-Click Deploy** — Multi-stage build, all-in-one frontend + backend image

## Architecture

```
DataHandler → EventBus → Strategy → Portfolio → OrderIntent → Risk Gate → Order/Gateway
                        ↑                                                     |
                        └──────────────── FillEvent ──────────────────────────┘
```

Backtests use deterministic OrderIntent approval wiring. Live mode uses
`PreTradeRiskManager` before `ManualConfirmGateway`; the legacy `RiskManager`
subscribes by priority but EventBus handlers do not consume or stop propagation.

For the full controlled automation and broker-bridge architecture, see
[Karkinos Architecture](ARCHITECTURE.md).

**Core Principles:**

- **Event-Driven**: All components communicate through EventBus, ensuring deterministic backtesting
- **Target Weight Signals**: Strategies output target weights (0~1), Portfolio converts to share counts
- **Instrument Carries Asset Differences**: All asset-specific behavior is expressed through field values — no isinstance checks downstream
- **Backtest First**: Synchronous event bus with SimulatedClock for reproducibility
- **T+1 Support**: Built-in freeze/thaw mechanism in Position, auto-advanced on settlement day

For plain-language explanations of built-in strategies, see the
[Strategy Primer](strategy/README.en.md). It covers trend, allocation,
mean-reversion, volatility-targeting, and long-only pair-rotation research
strategies, including current signal rules, parameters, failure modes, and
evidence boundaries. It is research documentation, not investment advice or a
return claim.

## Market Data Reliability Workflow

Karkinos labels market data with one shared vocabulary across quotes, fund NAVs,
historical bars, intraday snapshots, and replay datasets: `confirmed`, `live`,
`cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`.
Overview, the return calendar, Backtest data-audit panels, and strategy replay
evidence use those statuses to separate confirmed values from local cache,
estimate-only values, missing quotes, stale quotes, and delayed fund NAVs.

Manual refresh and scheduled refresh flows can update intraday quotes, closing
bars, and fund NAV confirmation. They update local market-data evidence only:
they do not submit broker orders, change trading behavior, or bypass manual
confirmation. Frozen market-data datasets can be replayed for backtests,
strategy runtime dry-runs, paper/shadow review, and audit replay so the same
inputs can be checked deterministically.

Overview Today’s to-dos first shows today’s conclusion and execution state,
then groups data issues, candidate actions, approvals, and normal statuses by
review priority. Strategy candidate counts are research supply, not the number
of trades to execute. Market pulse uses a small default China-market index
universe as broad market context. Manual refresh and the Web scheduler can
refresh those index quotes alongside account holdings; missing index move
fields are displayed as data gaps instead of empty values. They remain
background data and do not become user holdings, strategy tradables, broker
orders, or execution approval.

## Automation Maturity

Karkinos is moving toward a professional automated-quant workflow whose goal is
better after-cost trading outcomes, not faster unchecked order submission. v1.5
now provides a daily trading plan and portfolio-construction layer that combines
strategy evidence, portfolio state, account truth, risk gates, paper/shadow
evidence, fees, taxes, cost basis, blockers, constraint checks, and next review
steps into evidence-linked manual-confirmation intents. v1.6 completed the
paper/shadow runbook, deterministic scheduler state, exception queues, and
health checks. v1.7 completed the non-submitting controlled-bridge foundation:
manual tickets, local read-only connector evidence, capability/health
contracts, manual execution evidence, and execution reconciliation. Completion
does not provide broker submit, executable cancel, automatic ledger mutation,
or auto-pilot authority. v1.8 planning is active, but execution authority and
production broker submission remain disabled by default; later non-default
submission foundations do not give strategies broker access or enable
automatic execution.
When an operator accepts a diverged paper/shadow review, Operations preserves
the raw divergence evidence and exposes a runbook effective status for manual
confirmation handoff; this is not execution authorization or broker
submission.

After manual-ticket export, Trading links the operator to Account Truth broker
statement import and execution-reconciliation review. Reconciliation compares
manual execution evidence with matching broker price, quantity, gross amount,
fee, tax, transfer fee, and net amount. Matches and differences remain manual
review evidence in the read-only Decision comparison and do not change OMS,
write the production ledger, alter cash or positions, contact a broker, or
submit orders.

The automation ladder is: research evidence -> daily trading plan ->
paper/shadow operating loop -> manual execution assist -> controlled broker
bridge -> capital-bounded controlled execution. The first live tier uses a
deliberately small authorization envelope to contain unknown failure impact;
this is not a permanent account-size or product limit. Later capital tiers
require new human approval tied to reviewed evidence. Unattended, permanently
authorized full-account execution remains outside the product target.

The target authority modes are `disabled`, default `manual_each_order`, and a
future short-lived `session_bounded` mode. Account cash never grants machine
authority by itself, no session may widen or renew itself, and strategy code
never receives broker authority. Delivery stages and release gates are defined
in the [controlled execution plan](CONTROLLED_EXECUTION_PLAN.md).

The first v1.8 Stage 0 implementation is non-submitting evidence only. The
capital-authority status endpoint always reports runtime authority and broker
submission disabled; preview evaluates a proposed policy/context without
persistence; and evaluation endpoints append or list audit evidence. Even an
`allowed=true` result does not issue, enable, resume, or expand authority and
cannot submit, cancel, mutate OMS, or write the production ledger. Static
`config.json` remains unable to grant capital execution authority because a
future real authorization must be short-lived, revocable, and append-only
audited.

Capital-authorization v2 fixes the role boundary between broker facts and
broker writes. Policies now scope distinct read-only `evidence_connector_ids`
and future `execution_gateway_ids`; contexts require both identities, separate
health/capability facts, and a verified same-account binding. Identical or
overlapping roles fail closed. Even healthy submit-capable gateway facts remain
runtime-unverified evidence and cannot contact a broker or grant authority.

The Stage 1 read-only broker soak foundation can capture an explicitly configured
generic local JSON export through `/api/automation/broker-soak/capture` and
expose `/status` plus `/observations`. It stores sanitized snapshot fingerprints,
cash/position/order/fill facts, health, freshness, capabilities, and provider
market-calendar trading-day evidence without exposing raw account ids. Missing
calendar evidence, stale snapshots, connector errors, or any submit capability
produce degraded/blocked Operations alerts. Twenty healthy trading days
complete only the operational soak; the legacy Stage 1 status does not promote
a connector from day count alone.

`/api/automation/broker-soak/runs` records startup, intraday, and end-of-day
operating evidence, while `/drills` verifies safe disconnect, schema-drift,
stale-data, duplicate-evidence, and service-instance restart behavior. The
end-of-day phase requires clear execution reconciliation. Follow
[`BROKER_CONNECTOR_SOAK_RUNBOOK.md`](BROKER_CONNECTOR_SOAK_RUNBOOK.md).

Stage 1.1 adds a separate signed promotion-evidence review under
`/api/automation/broker-soak/promotion`. Its deterministic dossier binds the
first 20 clear-reconciled soak days, startup/intraday/end-of-day coverage, all
five recovery drills, a stable sanitized account alias/hash, and a current
Account Truth result that is clear, passing, fresh, and has zero unresolved
items. The owner must sign the exact dossier with a configured Ed25519 identity
and explicitly assert that the Account Truth import belongs to the same reviewed
account and that a full process/broker-terminal restart was performed outside
this service. Any source drift invalidates the acceptance. This records Stage 1
promotion readiness only. Stage 2 now binds the exact current promotion,
operational, Account Truth, and verified owner-acceptance fingerprints into each
per-order dossier using the read-only evidence connector. The distinct execution
gateway is bound separately and remains runtime-unverified until an exact current
Stage 2.4 record is resolved, so this grants no runtime or capital authority and
cannot submit or cancel broker orders.

The non-submitting Stage 2 foundation exposes
`/api/automation/controlled-bridge/status`, per-order dossier preview, exact
fingerprint attestation, and confirmation history. A dossier binds OMS terms,
capital-evaluation evidence, Account Truth/research/risk/paper-shadow gates,
connector soak, prior reconciliation, and kill-switch state. Operator labels
must match a short-lived Ed25519 approval bound to the exact dossier and a
configured public key. Karkinos stores no operator private key, and every
verified attestation remains incapable of changing OMS, granting authority,
contacting a broker, or scaling capital. Missing/invalid Stage 1 evidence,
provider failure, connector mismatch, or source drift fails closed; a valid
promotion clears only its three Stage 1 sub-blockers while evidence-connector
read-only integrity, runtime authority, live gateway, and broker submission
remain blocked. Runtime verification clears only when the exact Stage 2.4
evidence is current and matches every bound identity and order field.

Stage 2.4 exposes `/api/automation/execution-gateway-verification` for status,
preview, append-only record, resolve, and history. A runtime-registered gateway
must pass verified account binding, fresh source-fingerprinted health, complete
submit/cancel/query/dry-run/idempotency capabilities, and an exact zero-side-
effect dry-run. Resolution rechecks source facts and expires after five minutes.
Production registers no execution gateway by default; clear evidence still
cannot issue authority or submit/cancel an order.

Stage 2.5 requires the recorded manual-each-order capital evaluation to carry
the exact typed `execution_gateway_verification:<fingerprint>` reference. Every
per-order preview and confirmation re-resolves that fingerprint and exactly
matches the runtime gateway, read-only evidence connector, account alias, OMS
order, and canonical order fingerprint. Missing, expired, drifted, or mismatched
evidence re-blocks review and invalidates the previous artifact-bound approval.
A clear binding removes only the runtime-verification blocker; runtime authority,
live gateway, broker submission, and strategy-direct execution stay disabled.

The proposal-only Stage 3 foundation exposes
`/api/automation/controlled-sessions/status`, envelope preview, exact
attestation, and history. It binds an explicit OMS order set to a maximum
30-minute policy window and projects conservative gross capital, cash, turnover,
per-order, position, liquidity, and rate budgets. It also binds the v2 read-only
evidence connector separately from the execution gateway. Stage 3.3 requires a
unique current verification for every OMS order and the exact same typed
reference set in the recorded capital evaluation. Each source is re-resolved
and matched to its gateway, connector, account, order fingerprint, and dry-run
terms; one failure blocks the whole envelope. It does not reserve budget,
issue or resume a runtime session, mutate OMS, contact a broker, or scale
authority.

Stage 3.4 exposes `/api/automation/session-start-account-truth` for a short-lived
Account Truth start gate. It rebuilds the latest import/reconciliation/ledger/
manual-review source and requires pass, fresh, clear, zero unresolved mismatches,
and a maximum age of 120 seconds. The request and recorded capital evaluation
must bind the same typed fingerprint, read-only connector, and account alias.
Resolve rechecks source drift and expiry; clear evidence removes only the Account
Truth evidence blocker and cannot reserve budget or issue a runtime session.

Stage 3.5 exposes
`/api/automation/controlled-sessions/budget-reservations`. It revalidates the
exact signed envelope and atomically reserves conservative capital, cash,
China-trading-day turnover, and order-count capacity with SQLite write
serialization. This is budget state only: it cannot issue/resume a session,
mutate OMS/ledger, contact a broker, submit/cancel, or scale capital.

Stage 3.6 requires an exact positive per-symbol limit map in the signed
envelope. Limits cannot exceed the capital evaluation's symbol/effective
ceiling, and the atomic transaction aggregates overlapping reservations per
symbol. Same-symbol contention fails closed while disjoint symbols remain
subject to the shared account budget. No runtime or broker authority is added.

Stage 3.7 implements the internal atomic 60-second runtime rate-admission
ledger. It binds an enabled authenticated session, reservation, scoped order,
request id, active window, and strictest shared account rate. Stage 3.9 supplies
its persistent token-authenticated session provider, but
only read-only status/history APIs are exposed; no public admit, OMS, submit,
or cancel action exists.

Stage 3.18 requires each internal admission to bind the exact latest persisted
clear live-gate snapshot id, fingerprint, session identity, and observed time,
with a 30-second maximum age. The SQLite writer transaction re-reads the latest
snapshot, so newer blocked or changed evidence wins over a clear preview.
Missing, stale, future, blocked, or identity-drifted evidence fails closed.
Production remains status/history-only: no broker contact, OMS/fill/ledger/
capital/kill-switch mutation, submit, or cancel authority is added.

Stage 3.19 adds a persisted-fact operator view and explicit broker-lifecycle
read boundary. Automation Cockpit shows bounded-session authorized capital,
effective capital at risk, cash/capital/turnover headroom, remaining order
slots, expiry, last order/submission, reconciliation, live-gate, pause, and
blocker evidence without contacting a provider. Broker health and alerts read
only recorded generic collector runs; missing or blocked evidence requires an
explicit ingestion command. The former runtime snapshot entry is migration-
only and returns no live account facts. These views cannot issue, renew, resume,
widen, submit, cancel, mutate OMS/ledger/risk/kill-switch state, or scale
capital automatically.

Stage 3.8 implements the internal durable automatic-pause primitive. It checks
an allowlisted set of Account Truth, risk, reconciliation, paper/shadow,
gateway, market-data, budget, rate, kill-switch, loss/drawdown, rejection,
account-change, and consecutive-error facts. A hard failure persists an
immutable event and one-way `paused` state; rate admission rechecks that state
inside its transaction. Stage 3.9 supplied session identity while that slice
still had no live gate provider. Stage 3.10 now orchestrates persisted gates,
and Stage 3.11 uses signed replacement instead of automatic resume; broker
actions remain absent.

Stage 3.9 implements separately signed runtime-session issuance and one-way
revocation. It re-resolves the current attestation and atomic reservation and
requires a second exact Ed25519 issuance approval plus possession of its
signature; public approval history omits signature bytes. The high-entropy
token is returned once and only its salted hash is stored. Expiry, evidence drift,
pause, or signed revocation blocks authentication, while admission atomically
rechecks persisted state. This is bounded internal runtime authority, not
broker authority: no public admit/resume/renew/widen, OMS/ledger mutation, or
broker submit/cancel action exists.

Stage 3.10 wires persisted live-gate snapshots to the one-way pause controller.
Each evaluation first captures Account Truth, risk, paper/shadow,
reconciliation, gateway, market-data freshness, runtime budget/rate, kill
switch, loss/drawdown, rejection, account-change, and consecutive-error facts;
missing or invalid evidence fails toward pause. Periodic evaluation runs only
with explicit scheduler startup, while a session-token holder can request only
its own safety check and cannot resume or widen authority. Snapshot freshness
is 30 seconds, quote freshness is 120 seconds, and three rate rejections within
60 seconds trip the spike gate. No broker submit/cancel, OMS/production-ledger
mutation, resume/renew/widen, or automatic capital change is added.

Stage 3.11 adds signed paused-session replacement without re-enabling the old
session in place. Ordinary issuance fails closed for an unexpired paused scope.
Replacement requires a fresh attestation and atomic reservation, continuously
clear post-pause snapshots for at least 60 seconds with the newest no older than
30 seconds, and a distinct Ed25519 `replace_paused_controlled_session` approval
plus possession proof. One SQLite transaction revokes the predecessor and
issues only an equal-or-narrower session with a new one-time token; exact
retries do not reissue it. Renew/widen, public runtime admission, OMS/ledger
mutation, automatic capital increase, and broker submit/cancel remain absent.

Stage 3.12 adds a default-closed one-shot submission foundation for one exact
manually confirmed order. A separate final Ed25519 signature, current signed
broker/regulatory release evidence, fresh gateway capability/health/dry-run
checks, and a clear kill switch are mandatory. Intent and OMS pending state are
persisted before the only external call; an unknown result is never resubmitted
and can only be queried after 30 seconds by the same client order id. Production
still injects no write adapter or release provider, and automatic/strategy
submission, cancel, fill apply, ledger sync, and capital widening are absent.

Stage 3.13 adds a serialized cross-order interlock. A prepared, accepted-but-
unreconciled, or unknown controlled intent blocks every different order in both
preview and the database write transaction. Reconciliation classifies the
persisted intent, critical alerts flag unknown outcomes, and Operations exposes
query-only recovery. A definitive rejection can release the interlock; matching
broker evidence cannot yet self-clear it, infer a fill, mutate OMS/ledger, or
authorize another order.

Stage 3.14 adds a separately signed exact-full-fill clearance. All selected
trade rows must come from one validated broker import, sum to the exact OMS
quantity, and match fresh clear Account Truth from the same file. One atomic
transaction records evidence-linked real fills, advances OMS to `filled`,
persists terminal reconciliation, and releases the interlock. Partial totals,
cross-import aggregation, production-ledger mutation, automatic/strategy-direct
submission, and production adapter registration remain disabled. Canonical CSV
v2 rows may carry optional broker and client order ids, but controlled
clearance requires both to match the persisted submit intent exactly. Missing,
conflicting, cross-import, or partial evidence fails closed. The identifiers
remain evidence rather than authority, and a broker-specific callback/poll
adapter is still required before a pilot.

Stage 3.15 adds a broker-neutral exact-order lifecycle evidence contract,
not a live broker connection. `scripts/import_broker_order_lifecycle.py` previews by
default; persistence requires `--record` and the explicit non-authority
acknowledgement. It stores sanitized account hashes, monotonic source sequence,
file/evidence fingerprints, exact broker/client order ids, cumulative fill and
cancel quantities, and linked fills. Credentials, malformed/stale facts,
quantity inconsistency, sequence/identity/contract drift, and preview mutation
fail closed. Reconciliation projects persisted open/partial/cancel/full facts
without broker contact or OMS/ledger mutation. The same canonical predicate is
rechecked inside signed clearance and the next-order submit transaction, so a
contradictory observation rejects a racing clearance or re-blocks an older one.
Lifecycle full-fill still cannot replace the independent broker statement,
fresh Account Truth, and Stage 3.14 signature. Production registers no
collector, write adapter, release provider, executable cancel, or pilot authority.

Stage 3.16 adds an explicitly started local collector-ingestion boundary. It
binds deployment, release, user authorization, provider/account scope,
connection/batch state, cursor transitions, callback telemetry, and one
canonical lifecycle fact. Deterministic fixtures prove restart replay,
idempotency, duplicates, out-of-order/gap rejection, disconnect, and partial
batches. Callback and poll are metadata only: there is no SDK, provider contact,
scheduler, or default adapter registration. The collector cannot modify OMS,
fills, ledger, risk, kill switch, capital authority, or interlock state. QMT,
PTrade, local-file, and other adapters require separate review and explicit user
authorization; Karkinos does not claim official support for them.

Stage 3.17 binds persisted collector operation evidence into the canonical
lifecycle resolver. Collection remains optional for scopes with no collector
history. After a provider/gateway/account scope adopts it, the lifecycle fact
must be observation-bound to a matching recorded run and the latest effective
run must agree with cursor state. Pending restart recovery, blocked disconnect
or partial batches, unbound direct imports, and inconsistent state re-block
signed clearance and the serialized next-order gate. Duplicate replay cannot
mask a later failure. The binding is read-only and can only narrow eligibility;
it adds no provider contact, OMS/fill/ledger/risk/kill-switch/capital mutation,
or submit/cancel/live permission.

Stage 2.1/3.1 replaces the generic latest-reconciliation check with an exact
prior-batch fingerprint. The batch manifest binds terminal non-paper OMS
orders, transitions, real fills, reconciliation items, and the selected run;
filled orders also require broker, Account Truth import, and same-run linkage.
Per-order and session requests must match the fingerprint recorded in the
capital evaluation, and current source drift fails closed. This evidence cannot
authorize a next batch or add any broker-write capability.

Stage 2.2/3.2 adds signed operator approval evidence. The capital-authority API
exposes sanitized status plus challenge, verification, and history endpoints.
Each challenge binds a server nonce, operator/key, action, artifact type, exact
artifact fingerprint, issued time, and expiry. Per-order and session records
require the verified approval id; invalid, expired, disabled/rotated-key, or
cross-artifact evidence fails closed without creating runtime authority.

The evidence-only Stage 4 foundation exposes
`/api/automation/capital-scaling/status`, preview, persisted evaluation, human
decision, and history. It evaluates versioned capital tiers against operating
sample size, fill/reject quality, slippage, after-cost result, drawdown,
capacity/liquidity, reconciliation, divergence, disconnect, violation, and
incident evidence. Eligible evidence can only request a separate new
authorization; it cannot apply a tier, mutate runtime limits, resume execution,
or automatically scale up.
Stage 4.1 resolves broker-soak, execution-reconciliation, paper/shadow, and risk
references to persisted facts and binds the sanitized resolution fingerprint
into the evaluation identity. Missing, non-clear, or out-of-window sources fail
closed. Account Truth is also required. Stage 4.2 records sanitized Account
Truth points and computes after-cost, incident, capacity, liquidity, and
slippage facts from existing persisted data without accepting metric values from
the caller. Incomplete boundary or source linkage produces blocked evidence;
only an exact all-clear window may support a separate authorization request.
Stage 4.3 adds a required computed operating sample: healthy connector-soak
days, non-paper OMS outcomes, reconciled real-fill linkage, latest order-level
reconciliation coverage and p95 latency, paper/shadow divergence, and cash-flow-
unitized maximum drawdown are derived from persisted facts. The resolver checks
all nine review metrics exactly; missing or truncated coverage fails closed and
never changes authority or execution state.
Stage 4.4 adds a required exact execution-scope fact. Every sampled order must
bind either a persisted controlled-session admission or a current clear exact
batch wholly contained in the review sample. Identity mismatch, competing
bindings, orphan admissions, cross-window batches, source drift, and truncated
scans fail closed. V1 windows remain historical audit records; current reviews
require an append-only v2 recomputation. The fact cannot issue, resume, renew,
or widen authority, mutate OMS/ledger/risk/kill-switch state, or submit/cancel a
broker order.

Operations alerts can surface incomplete or runtime-degraded read-only broker
connector health, including runtime snapshots polled through the broker-gateway
health contract, capability scope, and explicit preview, export, dry-run,
cancel, and submit blockers. Those alerts are operator review evidence only:
they do not submit orders, cancel orders, store credentials, or grant execution
authority.

Estimated, cached, stale, missing, or confirmed-NAV-missing data is data-quality
evidence. It must not be displayed as confirmed returns and is not investment
advice, a profitability claim, or execution approval. Quotes, bars, and market
cache belong in local SQLite / data-cache storage; `config.json` stores only
local runtime preferences, provider settings, and read-only broker connector
client paths/account aliases. Broker passwords, tokens, secrets, credentials,
private statement exports, and public demo holdings do not belong there.

## Project Structure

```
Karkinos/
├── core/                   # Core infrastructure
│   ├── types.py            # Type definitions (Symbol, Money, enums, constants)
│   ├── events.py           # Event types (Market, Signal, Order, Fill, RiskAlert)
│   ├── event_bus.py        # Synchronous event bus (priority-based subscription)
│   └── clock.py            # Clock abstraction (SimulatedClock / LiveClock)
├── domain/                 # Domain model layer
│   ├── instrument.py       # Instrument (frozen dataclass + factory functions)
│   ├── bar.py              # Bar data (OHLCV)
│   ├── tick.py             # Tick data
│   ├── order.py            # Order (state tracking)
│   ├── fill.py             # Fill record
│   ├── position.py         # Position (T+1 freeze/thaw, mark-to-market, P&L)
│   └── portfolio.py        # Portfolio (target weight → share count conversion)
├── data/                   # Data pipeline layer
│   ├── source.py           # DataSource ABC
│   ├── providers/          # Data source adapters
│   │   ├── akshare_source.py  # AKShare adapter (stock/ETF/gold/bond)
│   │   └── tushare_source.py  # Tushare adapter (stock daily)
│   ├── store.py            # Parquet + SQLite storage engine
│   ├── handler.py          # DataHandler (bar replay)
│   ├── features.py         # FeatureEngine (SMA/EMA/RSI/ATR/Bollinger)
│   ├── live.py             # LiveDataFeed (real-time quote polling)
│   └── manager.py          # DataManager (cache-first → fetch-on-demand)
├── strategy/               # Strategy framework layer
│   ├── base.py             # Strategy ABC (on_init/on_data/on_fill)
│   ├── signals.py          # SignalType + Signal data model
│   └── examples/           # Example strategies
│       ├── dual_ma.py      # Dual moving average crossover
│       └── monthly_rebalance.py  # Monthly target-weight rebalance
├── execution/              # Execution engine layer
│   ├── engine.py           # ExecutionEngine ABC
│   ├── simulator.py        # SimulatedExecution (backtest)
│   ├── broker.py           # LiveExecution (placeholder)
│   ├── slippage.py         # Slippage models (fixed/percent/volume)
│   └── commission.py       # Commission models (A-share/ETF/gold/bond)
├── risk/                   # Risk management layer
│   ├── manager.py          # RiskManager (legacy OrderEvent checks; cannot consume EventBus events)
│   ├── rules.py            # RiskRule ABC + RiskCheckResult
│   └── limits.py           # Position limit / max drawdown / concentration rules
├── backtest/               # Backtest engine
│   ├── engine.py           # BacktestEngine (main loop)
│   └── result.py           # BacktestResult (result container)
├── analytics/              # Analytics layer
│   ├── metrics.py          # Sharpe / Sortino / max drawdown / win rate / annualized return
│   ├── report.py           # Report generation
│   └── equity.py           # Equity curve utilities
├── server/                 # Web service layer
│   ├── app.py              # FastAPI app factory + lifecycle management
│   ├── __main__.py         # CLI entry point (--host/--port/--reload/--no-live)
│   ├── bridge.py           # EventBusBridge (sync → async event bridging)
│   ├── db.py               # SQLite persistence (signals/backtests/quote snapshots/ledger)
│   ├── models.py           # Pydantic v2 request/response models
│   ├── scheduler.py        # TradingScheduler (live trading loop)
│   ├── config.py           # Typed configuration loader (BacktestConfig + ServerConfig)
│   ├── dependencies.py     # FastAPI dependency injection
│   ├── routes/             # REST routes
│   │   ├── market.py       #   /api/market — quotes/watchlist/kline
│   │   ├── portfolio.py    #   /api/portfolio — snapshot/allocation/equity-curve
│   │   ├── signals.py      #   /api/signals — history/latest
│   │   ├── backtest.py     #   /api/backtest — run/results
│   │   └── settings.py     #   /api/settings — config/live/notifications
│   └── ws/                 # WebSocket
│       ├── hub.py          #   ConnectionHub (connection management + broadcast)
│       └── handlers.py     #   /ws endpoint (real-time event push)
├── notification/           # Notification system
│   ├── notifier.py         # Notifier ABC + factory + message formatting
│   ├── console.py          # ConsoleNotifier (terminal output)
│   ├── telegram.py         # TelegramNotifier (Bot API)
│   └── wechat.py           # WeChatNotifier (ServerChan)
├── web/                    # React frontend
│   ├── src/
│   │   ├── app/            # Router, layout, global preferences, i18n copy
│   │   ├── features/       # Account / portfolio / activity modules
│   │   └── styles/         # Tailwind-powered global styles
│   └── package.json
├── tools/                  # Local developer / operations CLI tools
│   ├── run_backtest.py     # Local backtest tool
│   └── live_monitor.py     # Compatibility standalone monitor (Web service uses TradingScheduler)
├── live.py                 # Compatibility wrapper; prefer tools.live_monitor
├── main.py                 # Compatibility wrapper; prefer tools.run_backtest
├── config.example.json     # Configuration template
├── Dockerfile              # Multi-stage build (Node build + Python runtime)
├── docker-compose.yml      # One-click deployment
└── tests/                  # Tests
```

## Installation

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Install Dependencies

```bash
# Clone the repository
git clone <repo-url> && cd Karkinos

# Install core dependencies (uv creates .venv automatically)
uv sync

# Install server extras (FastAPI / uvicorn / aiosqlite / websockets)
uv sync --extra server
```

## Quick Start

### Run Backtest

```bash
# Run default dual moving average strategy with synthetic data
uv run python -m tools.run_backtest
```

Example output:

```
==================================================
         Karkinos Backtest Report
==================================================
Initial Cash:      1,000,000.00 CNY
Final Equity:        985,210.62 CNY
Total P&L:          -14,789.38 CNY
Total Return:            -1.48%
Annualized Return:       -3.11%
Sharpe Ratio:            -3.24
Sortino Ratio:           -3.55
Max Drawdown:             1.98%
Win Rate:                 8.40%
Duration (days):           168
--------------------------------------------------
Positions:
  SYNTH001: qty=500, avg_cost=17.4904, pnl=-1543.03
==================================================
```

### Start Web Server

```bash
# Install server dependencies
uv sync --extra server

# Development mode with reload, background process, PID and log files
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000

# Stop the service
./scripts/stop_server.sh

# Production-style startup
./scripts/start_server.sh prod --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> for the Web dashboard.

In development mode the launcher starts both backend and frontend:

```bash
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
```

This starts:

- backend API on `http://127.0.0.1:8000`
- Vite frontend on `http://127.0.0.1:5173`

Stop both with:

```bash
./scripts/stop_server.sh
```

Open <http://localhost:5173> for the React UI during local development, or use `http://localhost:8000` for the production build served by FastAPI.

### Docker Deployment

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f
```

By default the container reads `./config.json` as runtime config and persists market cache / SQLite data in the `karkinos-data` volume. `config.json` is not market data, holdings, or asset metadata storage; those records belong in local SQLite tables such as `latest_quotes`, `market_bars`, `ledger_entries`, and `instrument_metadata`.

See [Docker Deployment](#docker-deployment) section for details.

## Configuration

### config.json Fields

Do not hand-edit tokens into `config.json`. Use the local onboarding command:

```bash
uv run python scripts/configure_data_source.py
```

The command lets you choose `akshare` or `tushare`, prompts for a TuShare token only when needed, hides token input, and writes ignored local `config.json` for you. `config.example.json` is only a reference for advanced runtime fields.

#### Server Runtime Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | Server listen address |
| `port` | int | `8000` | Server listen port |
| `live_auto_start` | bool | `true` | Auto-start Web built-in live monitoring |
| `data_source` | string | `"akshare"` | Data source (`akshare` / `tushare`) |
| `tushare_token` | string | `""` | Local TuShare token written by the onboarding script; `TUSHARE_TOKEN` can also be used |
| `notification` | object | `{"type":"console"}` | Notification config |
| `live_poll_interval` | int | `60` | Live polling interval (seconds) |
| `broker_fee_schedule` | object | local defaults | Local broker fee rule parameters: stock/ETF commission rates, minimum commission, stamp tax, default transfer fee, optional Shanghai/Shenzhen transfer-fee rates, bond/convertible-bond exchange fees, other fee rate, rule id, and known limitations. Account identifiers, screenshots, statements, broker passwords, tokens, secrets, or credentials are rejected. |
| `broker_connectors` | array | `[]` | Default-unregistered read-only edge connector config. Allowed fields are `connector_id`, `connector_type`, `enabled`, `client_path`, and `account_alias`; broker passwords, tokens, secrets, or credentials are rejected. Only the broker-neutral `local_export_readonly` local JSON fixture/export boundary is built in; it parses `schema_version="karkinos.readonly_broker_snapshot_export.v1"`, and missing or unsupported schemas return degraded health. Broker-specific adapter types require separate review and explicit user authorization. |
| `controlled_bridge_policy` | object | disabled | Controlled-bridge whitelist preview. It may list connector ids, account aliases, strategy ids, and symbols for review, but the completed non-submitting v1.7 foundation still rejects automation and broker submission; passwords, tokens, secrets, or credentials are rejected. |
| `cors_allowed_origins` | array | local Vite origins | Frontend origins allowed to call the API |

Capital, holdings, watchlists, asset names, historical prices, and latest quotes are not runtime config: capital and trades come from the ledger, user-tracked assets come from `watchlist_assets`, asset identity comes from `instrument_metadata`, latest quotes come from `latest_quotes`, and historical bars come from `market_bars` / the local data cache.
Manual trade ledger entries that omit an explicit `fee` use the configured
`broker_fee_schedule` to record commission, stamp tax, exchange-specific
transfer fee when configured, other fees, total fee, and net cash impact.
Legacy top-level `account_commission_rate` / `account_min_commission` values are
read only as a local-config migration path.
Bond and convertible-bond manual trades use the exchange-bond fee model without
stock stamp tax or transfer fees.
Entries with an explicit `fee` keep the `manual_fee_input` audit marker.

#### notification Format

```json
"notification": {
    "type": "console",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "wechat_sendkey": ""
}
```

`type` values: `console`, `telegram`, `wechat`

### Environment Variables

| Variable | Description | Config Field |
|----------|-------------|-------------|
| `TUSHARE_TOKEN` | Tushare API token | — (auto-enables Tushare data source) |
| `KARKINOS_HOST` | Server listen address | `ServerConfig.host` |
| `KARKINOS_PORT` | Server listen port | `ServerConfig.port` |

### Priority Chain

```
CLI args > Environment variables > config.json > Defaults
```

Example: `python -m server --port 9000` takes precedence over `KARKINOS_PORT=8080`, which takes precedence over `"port": 8000` in config.json.

## CLI Reference

### python -m tools.run_backtest (Local Backtest Tool)

```bash
uv run python -m tools.run_backtest
```

Reads `config.json`, runs backtest, and outputs report. Uses `DataManager` cache-first strategy for data fetching.
The root `main.py` file is only a compatibility wrapper. It is not the Web service entry point.

### python -m server (Server)

```bash
uv run python -m server [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--host` | str | `0.0.0.0` | Listen address |
| `--port` | int | `8000` | Listen port |
| `--reload` | flag | `False` | Enable hot-reload dev mode |
| `--no-live` | flag | `False` | Disable auto-start of live monitoring |

### python -m tools.live_monitor (Standalone Monitor Tool)

```bash
uv run python -m tools.live_monitor
```

Standalone compatibility monitor, independent of the Web server. It reads `config.json`, polls market data, runs strategy, and pushes signals via notification channels. The professional Web/Live path should use `python -m server` or `./scripts/start_server.sh`; that path uses `TradingScheduler`, `PreTradeRiskManager`, and `ManualConfirmGateway`. The root `live.py` file is only a compatibility wrapper. Press `Ctrl+C` to exit.

## API Reference

### REST Endpoints

#### Market — /api/market

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/market/watchlist` | Get watchlist + latest quotes |
| GET | `/api/market/quote/{symbol}` | Get quote for a single symbol |
| GET | `/api/market/kline/{symbol}?start=&end=` | Get historical K-line data |

#### Portfolio — /api/portfolio

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Get portfolio snapshot (cash/equity/positions/allocation) |
| GET | `/api/portfolio/cockpit` | Get portfolio platform weights, actual weights, drift, action queue, and risk alerts |
| GET | `/api/portfolio/state` | Get account overview, snapshot, risk summary, and next step |
| GET | `/api/portfolio/risk-summary` | Get portfolio risk summary |
| GET | `/api/portfolio/live-holdings` | Get live holdings grouped by asset class |
| GET | `/api/portfolio/allocation` | Get asset allocation weights |
| GET | `/api/portfolio/equity-curve` | Get equity curve |

`/api/portfolio/cockpit` includes read-only
`construction_recommendations` evidence. A recommendation is marked
`actionable=true` only when the account-truth gate is `pass` and the matching
risk gate is `passed`; missing or degraded account truth, unchecked risk, or
blocked risk returns review rationale and required next actions instead of
submitting broker orders or bypassing manual confirmation.

#### Signals — /api/signals

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/signals?limit=&offset=` | Get signal history (paginated) |
| GET | `/api/signals/latest?limit=` | Get latest signals |
| GET | `/api/signals/actions?limit=` | Get action cards with latest risk-gate summary |
| GET | `/api/signals/journal?limit=&offset=` | Get signal → action → risk audit chain |
| POST | `/api/signals/journal/{signal_id}/review` | Record a post-decision signal review/outcome event |

Action cards expose `risk_gate_status` as `not_checked`, `passed`, or `blocked`
so an actionable signal without a risk decision is never presented as executable.
They also expose manual-confirmation readiness: `awaiting_risk_gate`,
`ready_for_manual_confirmation`, or `blocked_by_risk_gate`. Even when the risk
gate passes, manual confirmation remains required before execution.

`POST /api/signals/journal/{signal_id}/review` records the later outcome and
review notes for a generated signal as an immutable audit event. It does not
change an action task, create an order, submit to a broker, or mark a fill.

#### Decision Cockpit — /api/decision

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/decision/today` | Get today's read-only decision summary, candidate actions, evidence bundle, and no-action reasons |
| GET | `/api/decision/intraday` | Get a read-only intraday candidate-action view for stocks and common exchange-traded ETFs |

`GET /api/decision/today` aggregates existing action tasks, risk-gate state,
signal journal entries, and latest quote freshness into `buy`, `sell`, `hold`,
`rebalance`, `no_action`, or `review_required`. Candidate actions attach the
latest saved after-cost / out-of-sample validation evidence for the same
`strategy_id`; when no matching evidence exists, the response carries an
explicit missing-evidence reason. It reads existing facts only: it does not
create orders, submit to a broker, or change the manual-confirmation default.

The decision `summary` also includes portfolio cash / holdings / equity,
latest quote cache health, action-task status counts, and signal / journal /
risk-gate audit counts so the decision view can explain why it is acting or staying
still.

`GET /api/decision/intraday` uses the same evidence-bundle shape but only admits
stock and common exchange-traded ETF candidates. Open-end fund and long-horizon
allocation actions stay in the daily lane. The endpoint is for polling/minute-
level decision review, not high-frequency or millisecond trading, and it never
executes automatically.

#### Trading Controls — /api/trading

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/trading/actions/{action_id}/manual-order` | Create a pending manual order only from a risk-passed action card |
| POST | `/api/trading/shadow-runs/daily` | Record a daily paper/shadow run from risk-passed action cards |
| GET | `/api/trading/orders?status=` | List manual orders awaiting or past operator confirmation |
| POST | `/api/trading/orders/{order_id}/confirm` | Mark a manual order as operator-confirmed |
| POST | `/api/trading/orders/{order_id}/reject` | Mark a manual order as operator-rejected |
| GET | `/api/trading/order-facts` | List shared order facts for manual, paper, and live-like paths |
| POST | `/api/trading/order-facts/{order_id}/shadow-divergence-review` | Record paper/shadow divergence review evidence |
| GET | `/api/trading/fills` | List persisted fill facts |
| GET | `/api/trading/kill-switch` | Read the runtime kill switch |
| PUT | `/api/trading/kill-switch` | Update the runtime kill switch |

`POST /api/trading/actions/{action_id}/manual-order` accepts an operator-supplied
quantity and stores a `pending_confirm` manual order plus shared order fact. It
rejects `awaiting_risk_gate` and `blocked_by_risk_gate` actions and does not
submit to a broker or mark the order filled. Confirming or rejecting that manual
order updates the originating action card decision state (`acted` or `ignored`)
and is surfaced in the signal journal audit chain.

`POST /api/trading/shadow-runs/daily` records deterministic `paper_shadow`
order facts for action cards that already passed the risk gate. It skips
blocked or not-yet-checked actions, does not create manual orders, does not
submit to a broker, and does not mark fills. Re-running the same `run_date` and
action reuses the existing order fact; `shadow_run_schema_version`,
`reused_count`, and `reused_orders` make idempotent reruns auditable without
writing duplicate orders or order events.
Before writing, the daily shadow run also checks `latest_quotes` for the action
symbol. Missing quotes, non-`live` quote status, or non-positive prices are
reported in `data_quality.issues` and skipped with a `data_quality:*` reason
without creating a shadow order.
The persisted daily paper/shadow run also carries a structured
`review_queue`. Diverged, failed, or missing simulations include the affected
run/order references, severity, required operator action, reason, optional
filled/remaining quantity, and explicit no-broker-submission/no-ledger-mutation
flags. `/api/operations/today` surfaces that queue as runbook evidence; it is
not a broker order, live fill, or ledger update. Overview shows a compact
review-queue summary in Today's to-dos, and Decision shows the operator review
items as public action labels with the same non-submission safety boundary.

`POST /api/trading/order-facts/{order_id}/shadow-divergence-review` records an
operator review such as `within_expectations` on an existing `paper_shadow`
order fact. It does not change order status, submit to a broker, or create a
fill.

#### Broker Gateway — /api/broker-gateway

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/broker-gateway/status` | List safe gateway capabilities, including non-submitting manual-ticket and disabled live gateways |
| GET | `/api/broker-gateway/connectors/health` | List read-only broker connector configuration health and non-submitting capabilities |
| GET | `/api/broker-gateway/connectors/{connector_id}/snapshot` | Query one runtime read-only connector snapshot for cash, positions, orders, and fills without account-id leakage, gateway events, OMS mutation, ledger mutation, or broker submission |
| GET | `/api/broker-gateway/account-facts` | Query cash, position, and fill facts from staged broker evidence without broker contact |
| GET | `/api/broker-gateway/fills/query` | Query staged broker fill evidence, optionally filtered by symbol, without broker contact or OMS mutation |
| GET | `/api/broker-gateway/orders/{order_id}/query` | Query local OMS status, gateway audit events, and staged broker fill evidence for one order |
| POST | `/api/broker-gateway/orders/{order_id}/broker-cancel` | Reject broker-side cancellation by default and record an audit event without changing OMS status |
| POST | `/api/broker-gateway/orders/{order_id}/manual-ticket/preview` | Preview a copyable manual broker ticket after manual confirmation and required account/research/risk/paper-shadow evidence |
| POST | `/api/broker-gateway/orders/{order_id}/manual-ticket/export` | Generate a read-only JSON manual-ticket export payload without recording events or changing OMS status |
| POST | `/api/broker-gateway/orders/{order_id}/manual-ticket/dry-run` | Record an accepted or rejected manual-ticket dry-run validation event without changing OMS status |
| POST | `/api/broker-gateway/orders/{order_id}/manual-ticket` | Record a manual broker ticket event without broker API submission |
| POST | `/api/broker-gateway/orders/{order_id}/manual-execution/preview` | Preview an operator-entered manual fill and ledger draft after manual-ticket creation without writing ledger entries |
| POST | `/api/broker-gateway/orders/{order_id}/manual-execution` | Record reviewed manual execution evidence with a matching preview fingerprint without creating fills, changing OMS, or writing ledger entries |

Manual-ticket preview and creation require account-truth, research-evidence,
risk, paper/shadow, manual-confirmation evidence, and a clear kill switch. All
manual-ticket paths keep `submitted_to_broker=false`; preview and export are
read-only, and ticket creation records an audit event only. Gateway status includes the
current kill-switch state; when it is enabled, the manual-ticket gateway reports
`blocked_by_kill_switch` and disables preview/dry-run capabilities in the
status payload. The Decision Cockpit automation panel also shows this
read-only gateway status so operators can see kill-switch and gateway blockers
without receiving broker submit or cancel controls. Connector health is a
local read-only capability contract: it exposes configured connector ids,
aliases, health status, capability scope, read/query flags, and explicit
preview/export/dry-run/cancel/submit blockers without contacting broker
clients, storing credentials, or enabling submission. Runtime read-only
connector snapshot query can expose cash, positions, orders, and fills as
operator-review evidence, but it hides account ids and still disables preview,
export, dry-run, cancel, submit, gateway-event creation, OMS mutation, and
ledger mutation. Automation Cockpit and Decision Cockpit show a compact runtime
snapshot summary with connector id, alias, snapshot status, cash, and
position/order/fill counts under the same non-submitting contract.
The same Decision Cockpit panel summarizes read-only connector health, gateway
query/read/preview/export/dry-run capability labels, staged account facts,
staged fill polling, and local order-query evidence so operators can see
configured read capability, OMS
state, gateway audit counts, and evidence counts without leaking local client
paths or receiving broker submit or cancel controls. When staged fills and open
execution reconciliation items both exist, it also shows a read-only
reconciliation review hint so the evidence can be compared before any ledger
update.
The panel also shows strategy promotion state from the Automation Cockpit as
read-only lifecycle evidence: strategy id, stage, paper/shadow gate status,
missing requirements, optional backtest evidence id, and a live-like disabled
boundary. When a strategy is manually paused or retired, the panel shows the
audit-only lifecycle boundary, does-not-authorize-execution flag, and disabled
controlled-bridge-pilot marker. It does not expose live-promotion,
controlled-bridge-pilot, broker-submit, broker-cancel, or ledger-sync controls.
The strategy lifecycle audit API only records status and events:

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/strategy-promotion/states` | Read strategy promotion / lifecycle states |
| POST | `/api/strategy-promotion/{strategy_id}/promote` | Record paper/shadow promotion when readiness evidence passes; live-like remains rejected by default |
| POST | `/api/strategy-promotion/{strategy_id}/lifecycle` | Record manual pause or retirement lifecycle state; controlled bridge pilot remains rejected by default |
| GET | `/api/strategy-promotion/{strategy_id}/events` | Read strategy promotion and lifecycle audit events |

Manual-ticket dry-run records accepted or rejected validation events for audit,
including kill-switch rejections, but does not change OMS status or submit
broker orders. After a manual ticket is created, manual-execution preview can
calculate an operator-entered fill's gross amount, fee/tax/transfer-fee cost,
net cash impact, position/cost preview, and production-ledger draft. The
preview keeps `dry_run=true`, requires an explicit later operator save, and
does not create gateway events, change OMS status, write ledger entries, or
contact a broker. The response also includes a deterministic
`preview_fingerprint` so later review can reference the exact economics draft
and policy snapshot that was inspected. Trading approvals exposes the same
read-only preview after manual-ticket export and does not render save-ledger,
apply-fill, or broker submit controls. The manual-execution record endpoint
requires the matching `preview_fingerprint` and stores a gateway audit event
only; it does not create fills, change OMS status, write ledger entries, or
contact a broker. Account-facts query summarizes cash balances, positions, and
fills from staged broker evidence only; it is not a live broker account
snapshot. Broker lifecycle health/query reads persisted generic collector runs
only and never calls an adapter or returns current cash, positions, orders, or
fills. The former runtime connector snapshot entry is an explicitly labelled
migration surface that returns the canonical lifecycle evidence view and no
live account facts. Automation Cockpit passes persisted bounded-session and
lifecycle evidence to Decision Cockpit as a compact review summary without
adding submit, cancel, resume, fill-apply, ledger-sync, or capital-widening
controls. Fill query reads staged broker
trade evidence only and can filter by symbol; it does not contact broker
clients, create gateway events, mutate OMS status, or update ledger facts.
Order query reads local OMS facts, gateway audit events, and staged broker
evidence only; Decision Cockpit can show the queried OMS status and evidence
counts for the first open reconciliation item, but it does not contact broker
clients, create events, or mutate OMS/ledger state. Broker-cancel requests are
rejected by default and recorded
as `live_cancel_rejected` audit events; they do not cancel at the broker or
change local OMS status.

#### Execution Reconciliation — /api/execution-reconciliation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/execution-reconciliation/runs` | Run OMS/gateway/broker-evidence reconciliation for a date |
| GET | `/api/execution-reconciliation/runs` | List recent execution reconciliation runs |
| GET | `/api/execution-reconciliation/runs/{run_id}` | Read one reconciliation run with item-level suggested actions |

Execution reconciliation compares OMS order states, broker gateway events, and
staged broker trade evidence. It identifies missing manual-ticket actions,
missing broker evidence, broker quantity mismatches, or broker evidence awaiting
review, and matching evidence carries a read-only broker cost summary with
gross amount, fees, taxes, transfer fees, and net amount. It does not mutate
the production ledger or submit/cancel broker orders.
Decision Cockpit summarizes the latest run status and first open item as
read-only review evidence only. When staged broker cost evidence is attached,
the same panel shows gross amount, fee/tax, transfer fee, net amount, and
review-before-ledger-update flags for operator review. When staged fill
evidence is available, the panel points the operator toward reconciliation
review before any ledger update; it does not provide ledger-sync, fill-apply,
or broker-action controls.

#### Backtest — /api/backtest

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/backtest/strategies` | List strategies with typed parameter schemas and benchmark / OOS / after-cost requirements |
| GET | `/api/backtest/strategy-validation` | Get the benchmark strategy after-cost / OOS evidence matrix |
| GET | `/api/backtest/strategy-promotion-readiness` | Get promotion-readiness gates for benchmark strategies |
| POST | `/api/backtest/signal-preview` | Preview strategy outputs from explicit single-symbol bars or a server-side single-symbol date range as research-only audit records without writing signals, orders, fills, or ledger entries |
| POST | `/api/backtest/risk-preview` | Run a read-only pre-trade risk preview for a sized single-symbol research candidate; returns pass/blocked reasons without creating orders, risk decisions, fills, or ledger entries |
| POST | `/api/backtest/paper-shadow-preview` | Run a read-only paper/shadow simulation for a risk-passed single-symbol candidate; returns paper order/fill evidence, fee breakdown, and shadow-review summary without writing order/fill facts or ledger entries |
| POST | `/api/backtest/attribution-preview` | Summarize the same single-symbol preview chain into an attribution evidence boundary; shows preview evidence versus production order/fill facts without attributing strategy P/L |
| POST | `/api/backtest/run` | Run backtest (in thread pool), return result |
| POST | `/api/backtest/sweep` | Run bounded parameter grids, persist each tested configuration, and return deterministic rankings with multiple-testing warnings |
| POST | `/api/backtest/compare` | Compare multiple strategies or explicit strategy parameter sets on one frozen dataset snapshot |
| GET | `/api/backtest/results` | List all backtest result summaries |
| GET | `/api/backtest/results/{result_id}` | Get single backtest detail + equity curve |

`POST /api/backtest/run` accepts generic `params`, for example
`{"short_period": 5, "long_period": 20}`. The backend validates types, ranges,
unknown parameters, and strategy-specific cross-field constraints before
execution. Each run records `metrics_json.dataset_snapshot` with configured
data sources, cache metadata availability, requested range, symbol universe,
row counts, first/last timestamps, adjustment mode when available, cache
dataset ids, and data-quality diagnostics. The snapshot is reproducibility
evidence for research comparison, not a guarantee of market-data completeness.
The Web Backtest report surfaces the same snapshot as a data-audit panel for
both freshly run results and saved report history.
`POST /api/backtest/signal-preview` uses the same strategy registry and
parameter schema to convert explicit single-symbol bars, or backend-loaded
data for a single symbol and date range, into research-only strategy-runtime
audit records. The response marks
`does_not_enable_execution=true`, includes dataset snapshot id and data-quality
status, and includes a structured review-gate chain for data readiness,
account truth, pre-trade risk, paper/shadow preview, and manual review. It does
not write to `signals`, the action queue, order/fill facts, or ledger entries.
`POST /api/backtest/risk-preview` can then size one research candidate and
reuse the pre-trade risk rules against current account context. It returns
pass/blocked reasons, keeps manual confirmation required, and does not create
orders, persist risk decisions, mutate ledger entries, or submit broker orders.
`POST /api/backtest/paper-shadow-preview` can then simulate that same candidate
after a passed risk preview. It returns paper order/fill evidence,
after-cost fee breakdown, and a shadow-review summary while remaining read-only:
it does not write order/fill facts, mutate the production ledger, or submit
broker orders.
`POST /api/backtest/attribution-preview` summarizes the same single-symbol
preview chain into an attribution evidence boundary: how much preview evidence
exists, whether production order/fill facts are still zero, and whether manual
review linkage is the next step. When ready, it returns a read-only manual
review linkage candidate; it does not write ledger entries or attribute strategy
P/L before real signal, review, order, and fill facts are linked.
Saved results also persist `metrics_json.strategy_metadata` with the strategy
identity, display name, description, asset universe, supported frequencies,
parameter schema, normalized params, benchmark role, and validation
requirements used for that run, so historical reports remain explainable even
if the registry or an extension manifest changes later. The Web report renders
this as a strategy-audit snapshot with readable strategy and parameter labels,
while keeping internal parameter keys visible only as secondary API/audit
fields.
The same report also surfaces the after-cost evidence bundle and
out-of-sample validation payload: net versus gross return, cost drag,
turnover, benchmark role/status, split point, structured cost assumptions,
slippage assumptions, general assumptions, and limitations.
These panels are research evidence only and do not approve execution.
Backtest fill records keep the legacy `commission` total while exposing the
same structured fee-breakdown contract used by paper broker evidence, manual
trade preview, and ledger projections: commission, stamp tax, transfer fee,
other fees, total fee, fee-rule id, and known limitations.
When a backtest report includes fills, the Web equity/drawdown chart overlays
buy/sell markers and shows a compact marker summary beside the curve. These
markers come only from the saved backtest fills as research evidence; they do
not approve execution or attribute live-account returns by themselves.

`GET /api/backtest/strategy-validation` reads saved backtest results and reports
whether each registered benchmark strategy has after-cost and out-of-sample
evidence. It is for audit and promotion checks, not investment advice.

The Web Backtest Strategy Lab renders registry strategy metadata, asset
universe, supported frequencies, benchmark role, validation requirements, and
readable parameter labels while preserving internal parameter keys for the API
contract and parameter-set audit trail.

The Web Backtest Strategy Lab can run the same bounded parameter sweep for the
selected strategy and optional one-symbol universe. It renders the tested
configuration ranking, saved result ids, scores, costs, and multiple-testing
warnings so the operator can review parameter perturbation evidence before any
promotion or paper/shadow workflow.

`POST /api/backtest/compare` accepts either `strategies` or explicit `runs`
with `strategy` and `params`, then saves each valid run only after all compared
results prove they used the same `metrics_json.dataset_snapshot.snapshot_id`.
If any run produces a different or missing snapshot id, the endpoint returns
409 instead of silently ranking results from different data inputs. Returned
items include the saved result id, normalized params, metrics, equity curve,
and shared dataset snapshot id for audit.
The Web Backtest Strategy Lab can submit explicit same-strategy parameter sets
to this endpoint and renders the saved result ids, normalized params, returns,
drawdowns, costs, warnings, and shared snapshot id without approving execution.

`GET /api/backtest/strategy-promotion-readiness` combines saved after-cost/OOS
validation, blocked-risk evidence, paper/shadow order facts, and explicit
paper/shadow divergence review evidence. It never promotes a strategy
automatically and does not change execution defaults.

#### Account Strategy — /api/account-strategy

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/account-strategy` | Read the current account research strategy assignment without enabling auto trading |
| PUT | `/api/account-strategy` | Save the research-context strategy assignment; the server forces `auto_trade_enabled=false` |
| GET | `/api/account-strategy/assignments` | Read account, asset-class, or symbol-level research strategy bindings |
| PUT | `/api/account-strategy/assignments` | Save one research strategy binding; different symbols can use different backtest strategies without creating orders or ledger entries |
| GET | `/api/account-strategy/attribution` | Summarize signals, actions, risk decisions, orders, and fills linked to the current strategy |
| GET | `/api/account-strategy/contribution` | Estimate strategy contribution from linked fills and latest local valuation |

Account and symbol strategy assignments are research and audit context only;
they do not mutate orders, fills, positions, or ledger entries. The contribution report
estimates realized/unrealized P/L, commission, slippage, and net contribution
only from fills that can be linked to the assigned strategy. Manual trades,
cash flows, and market movement without evidence are not attributed to strategy
returns by default.

#### Settings — /api/settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Read current configuration |
| PUT | `/api/settings` | Update in-memory runtime settings; business state remains in SQLite |
| POST | `/api/settings/live/start` | Start live monitoring |
| POST | `/api/settings/live/stop` | Stop live monitoring |
| GET | `/api/settings/live/status` | Query live monitoring status |
| POST | `/api/settings/notification/test` | Send test notification |

### WebSocket — /ws

Streams EventBus events in real-time after connection. Each message includes an `event_type` field:

| event_type | Fields |
|------------|--------|
| `MarketEvent` | timestamp, symbol, open, high, low, close, volume, frequency, asset_class |
| `SignalEvent` | timestamp, strategy_id, symbol, target_weight, price |
| `OrderEvent` | timestamp, order_id, symbol, side, order_type, quantity, price |
| `FillEvent` | timestamp, fill_id, order_id, symbol, side, fill_price, fill_quantity, commission, slippage |
| `RiskAlertEvent` | timestamp, alert_id, rule_name, severity, message, symbol, order_id |

## Docker Deployment

### Dockerfile (Multi-Stage Build)

- The project's canonical Node.js runtime is **Node 24 LTS**; `.nvmrc`, the
  strict npm engine, CI, and the Docker build stage all target 24.x.
- **Stage 1** (`node:24-alpine`): Builds the React frontend with
  `npm ci && npm run build`, output to `web/dist/`
- **Stage 2** (`python:3.14-slim`): Copies source + frontend dist, installs server dependencies, sets `KARKINOS_CONFIG_PATH=/app/config.json` and `KARKINOS_DATA_DIR=/app/data/store`, then starts with `python -m server`

### docker-compose.yml

```yaml
services:
  karkinos:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - karkinos-data:/app/data/store
      - ./config.json:/app/config.json:ro
    environment:
      - TZ=Asia/Shanghai
      - TUSHARE_TOKEN=${TUSHARE_TOKEN:-}
      - KARKINOS_HOST=0.0.0.0
      - KARKINOS_PORT=8000
      - KARKINOS_CONFIG_PATH=/app/config.json
      - KARKINOS_DATA_DIR=/app/data/store
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/settings', timeout=5).read()"]
      interval: 30s
```

### Usage

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Override Port

```bash
# Use port 9000
KARKINOS_PORT=9000 docker compose up -d
# Or modify ports in docker-compose.yml to "9000:9000"
```

### Data Volumes

- `karkinos-data`: Mounted at `/app/data/store`, stores Parquet files and SQLite database. Data persists across container rebuilds.

## Web Frontend

### Tech Stack

React 19 + TypeScript + TanStack Router + TanStack Query + ECharts/Recharts + Vite

### Views

| View | Path | Description |
|------|------|-------------|
| DashboardView | `/` | Today’s to-dos and asset overview with today’s conclusion, execution state, account truth, risk blockers, candidate pool, manual-confirmation queue, asset status, position contributors, market pulse, equity, and return summaries |
| PortfolioView | `/portfolio` | Position details + allocation pie chart |
| ActivityView | `/activity` | Trades, dividends, cash flows, and manual adjustments |
| DecisionView | `/decision` | Daily / intraday candidate actions, risk state, evidence, and manual-confirmation entry point |
| MarketView | `/market` | Market quotes + K-line chart |
| SignalsView | `/signals` | Signal history + signal badges |
| BacktestView | `/backtest` | Run backtest + equity curve |
| SettingsView | `/settings` | Config management + live control + notification test |

Initial screens do not seed effective user assets, trades, or fund names.
Portfolio assets, holdings, and ledger activity come from the local database or
explicit private runtime configuration; Activity batch fund candidates are
derived from held fund positions instead of frontend defaults.

### Development

```bash
cd web
npm install
npm run dev       # Dev server, proxies /api → localhost:8000
npm run build     # Build production bundle to dist/
```

## Strategy Development

Extend the `Strategy` base class and implement `on_init` and `on_data`:

```python
from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy

class MyStrategy(Strategy):
    def __init__(self, event_bus: EventBus):
        super().__init__("my_strategy", event_bus)

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        # Your trading logic here
        if event.close > 1850:
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))
        else:
            self.emit_signal(event.symbol, target_weight=0.0, price=float(event.close))
```

`emit_signal(symbol, target_weight, price)` publishes a `SignalEvent` to the EventBus. Portfolio converts the target weight to specific share counts.

## Notification System

Three notification channels:

| Channel | type value | Description |
|---------|-----------|-------------|
| Console | `console` | Terminal output (default) |
| Telegram | `telegram` | Push via Bot API |
| WeChat | `wechat` | Push via ServerChan |

### Configuration Examples

```json
{
    "notification": {
        "type": "telegram",
        "telegram_bot_token": "<telegram-bot-token>",
        "telegram_chat_id": "<telegram-chat-id>"
    }
}
```

```json
{
    "notification": {
        "type": "wechat",
        "wechat_sendkey": "<serverchan-sendkey>"
    }
}
```

Signal push message format:

```
📈 Trading Signal
Symbol: SYNTH001
Direction: LONG
Target Weight: 100.0%
Price: 18.5050
Strategy: dual_ma
Time: 2025-06-15 14:30:00
```

## Technical Indicators

`FeatureEngine` supports the following indicators:

| Indicator | Method | Output Columns |
|-----------|--------|---------------|
| SMA | `sma(df, col, period)` | `sma_5`, `sma_20`, `sma_60` |
| EMA | `ema(df, col, period)` | `ema_12`, `ema_26` |
| RSI | `rsi(df, col, period)` | `rsi` |
| ATR | `atr(df, period)` | `atr` |
| Bollinger Bands | `bollinger(df, col, period)` | `boll_mid`, `boll_upper`, `boll_lower` |

Usage example:

```python
from data.features import FeatureEngine

engine = FeatureEngine()
df_with_features = engine.add_all_features(df)
# Includes columns: sma_5, sma_20, sma_60, ema_12, ema_26, rsi, atr, boll_mid, boll_upper, boll_lower
```

## Risk Management

The legacy `RiskManager` subscribes to `OrderEvent` at `priority=-10`, so it can audit orders and publish risk alerts before Execution (priority=0). The synchronous EventBus does not let one handler consume an event, so this class cannot stop later handlers by itself.

The current Live safety path is `OrderIntentEvent` → `PreTradeRiskManager` → `RiskDecisionEvent`/`OrderEvent` → `ManualConfirmGateway`. Backtests use deterministic compatibility wiring inside `BacktestEngine` to approve `OrderIntentEvent` without depending on Live state.

Three built-in rules:

| Rule | Class | Description |
|------|-------|-------------|
| Position Limit | `PositionLimitRule(max_quantity)` | Rejects buys that would exceed max quantity per symbol |
| Max Drawdown | `MaxDrawdownRule(max_drawdown_pct)` | Rejects buys when portfolio drawdown exceeds threshold |
| Concentration | `ConcentrationRule(max_concentration)` | Rejects buys that would make a single symbol exceed max portfolio weight |

Usage example:

```python
from risk.manager import RiskManager
from risk.limits import PositionLimitRule, MaxDrawdownRule, ConcentrationRule
from decimal import Decimal

risk_mgr = RiskManager(event_bus)
risk_mgr.add_rule(PositionLimitRule(max_quantity=Decimal("1000")))
risk_mgr.add_rule(MaxDrawdownRule(max_drawdown_pct=Decimal("0.15")))
risk_mgr.add_rule(ConcentrationRule(max_concentration=Decimal("0.30")))
```

In the `PreTradeRiskManager` path, rejected orders publish `RiskDecisionEvent` / `RiskAlertEvent` and do not produce an `OrderEvent`. The legacy `RiskManager` requires cooperation from the execution layer to block an order.

## Commission Models

| Asset Type | Commission | Stamp Tax | Transfer Fee |
|-----------|-----------|-----------|-------------|
| A-Share | max(amount x 0.03‰, ¥5) | Sell 0.05‰ | 0.01‰ |
| ETF | max(amount x 0.03‰, ¥5) | None | 0.01‰ |
| Gold Spot | amount x 0.08% | — | — |
| Exchange Bond | max(amount x 0.004‰, ¥1) | — | — |

`MultiAssetCommission` auto-routes to the correct calculator based on `CommissionType`.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event Bus | Synchronous + Priority | Backtest determinism; risk checks before execution |
| Signal Model | Target Weight | Strategy doesn't need to care about lot sizes |
| Instrument | Frozen Dataclass | Immutable + field values carry asset differences |
| Money Type | Decimal | Avoid floating-point precision issues |
| Time Advance | SimulatedClock | Externally controlled, reproducible |
| Data Storage | Parquet + SQLite | Columnar storage efficiency + flexible metadata queries |
| Event Bridge | EventBusBridge | Lossless sync EventBus → async WebSocket conversion |
| Live Scheduling | TradingScheduler | Daemon thread + Event.wait() for instant stop |

## License

MIT
