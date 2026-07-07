# Karkinos Architecture

Karkinos is a China-market personal quant research and trading platform. Its
purpose is to improve after-cost trading outcomes through disciplined,
auditable, risk-gated decisions. Automatic broker submission is a future
execution capability, not the source of edge and not the default product mode.

The core architectural rule is:

```text
prove the decision first
-> simulate and reconcile the execution path
-> require explicit human authority by default
-> only then consider a tightly gated broker bridge
```

This keeps Karkinos focused on process quality instead of turning a
possibly weak or unverified signal into a faster real-money mistake.

## North-Star Workflow

The platform should answer the daily operating question:

> Given my portfolio, market data, risk limits, account truth, and validated
> strategies, what should I do today -- buy, sell, hold, rebalance, or do
> nothing -- and why?

The end-to-end workflow is:

```text
market data and account facts
-> reproducible research dataset
-> strategy runtime / backtest / replay
-> research evidence bundle
-> strategy promotion gate
-> daily decision
-> daily trading plan
-> pre-trade risk gate
-> paper/shadow run
-> divergence review
-> manual confirmation
-> manual ticket or controlled broker bridge
-> broker evidence import
-> execution/account reconciliation
-> journal and post-decision review
```

Each step produces evidence. Later steps consume that evidence; they do not
overwrite it or silently bypass it.

## Layered Architecture

```text
Web cockpit
  Overview / Decision / Operations / Trading / Account Truth / Market
    |
    v
Application services
  Decision, daily trading plan, operations, automation, OMS, gateway,
  execution reconciliation, strategy promotion, account truth
    |
    v
Domain and engine layer
  EventBus, Strategy Runtime, Portfolio, Risk, Paper Broker, Backtest
    |
    v
Local evidence and state
  SQLite facts, market bars, broker evidence, run records, reports
    |
    v
External adapters
  Market data providers, read-only broker connectors, future gateway
```

The service layer owns workflow authority. Strategy code can propose signals
and candidate actions, but it cannot submit broker orders. Broker connectors
can contribute evidence, but they cannot mutate production ledger state without
review and reconciliation.

## Current Core Flows

### Research and Strategy Runtime

Karkinos learns from PTrade-style strategy ergonomics through lifecycle hooks,
strategy context, parameter schemas, and one strategy API that can be reused
across backtest, replay, paper, and shadow modes.

The safe translation is:

```text
strategy hook
-> StrategyRuntimeOutput
-> StrategyRuntimeAuditRecord
-> evidence/risk/account/paper/manual gates
```

The strategy runtime context is read-oriented. It should expose market data,
portfolio facts, parameters, account facts, risk limits, and run metadata. It
must not expose direct broker-order authority.

### Daily Decision and Trading Plan

`build_daily_trading_plan` is the high-risk aggregation point that converts
decision evidence into manual-confirmation order intents. It consumes decision
payloads, account-truth status, market health, portfolio controls, candidate
actions, fees, cash impact, T+1 constraints, limit/suspension/ST checks, and
drawdown/concentration controls.

Its outputs are previews:

* `order_intents` are evidence-linked order candidates.
* `blockers` explain why an action cannot proceed.
* `submission_status` defaults to manual confirmation or blocked states.
* `broker_bridge_status` remains disabled by default.

Changing this flow has a broad blast radius because it feeds Decision,
Operations, and paper/shadow runs. Treat it as a platform contract.

### Operations and Paper/Shadow

Operations Center is the daily runbook. It answers:

```text
what ran
what failed
what is blocked
what is ready for review
what evidence is safe to rely on
what the operator should do next
```

`run_paper_shadow_from_trading_plan` creates or reuses a deterministic
paper/shadow run from the daily trading plan. It records simulated orders and
fills as evidence only. It must not create production ledger entries, mutate
cash or positions, store broker credentials, or submit broker orders.

The paper/shadow run should be the first place where execution assumptions meet
the current plan:

```text
daily trading plan
-> deterministic input fingerprint
-> paper/shadow order request
-> simulated OMS transitions
-> simulated fills / rejects / cancels / expirations
-> divergence status
-> next manual review step
```

### OMS and Gateway Boundary

OMS is the production-facing order lifecycle boundary. Its near-term role is
not "send orders"; its role is to make order authority explicit.

The safe lifecycle is:

```text
awaiting_manual_confirmation
-> manually_confirmed
-> manual_ticket_created
-> broker evidence imported
-> reconciled or exception review
```

Any future broker gateway must remain capability-based:

* manual-ticket gateway: copyable ticket, no broker API submission;
* dry-run gateway: validates payloads and records rejected/accepted previews;
* read-only connector: account/cash/position/order/fill evidence only;
* controlled live gateway: future, disabled by default, gated per account,
  strategy, symbol, order, risk state, account truth, and kill switch.

### Account Truth and Reconciliation

Account truth is the platform's reality check. Broker statements and connector
snapshots are staged as evidence before they influence decisions.

Execution reconciliation compares:

```text
OMS order state
-> broker gateway event
-> imported broker trade/fill evidence
-> local ledger/cash/position expectations
```

No automation path should directly mutate production ledger state just because
broker evidence exists. Matching evidence can recommend review actions; ledger
mutation remains explicit and auditable.

## Authority Boundaries

| Layer | May do | Must not do |
| --- | --- | --- |
| Strategy | Emit signals, candidates, warnings, explanations | Submit broker orders or bypass gates |
| Backtest/research | Produce reproducible evidence and assumptions | Claim deployability without OOS/after-cost/risk review |
| Daily plan | Create order-intent previews and blockers | Create broker orders or ledger entries |
| Risk gate | Pass/block with reasons and policy snapshots | Be optional for actionable candidates |
| Paper/shadow | Simulate order/fill outcomes and divergence | Mutate production cash, positions, or ledger |
| OMS | Track explicit order authority and transitions | Submit while broker submission is disabled |
| Broker gateway | Export tickets or future gated bridge actions | Store passwords or enable live submission by default |
| Account truth | Stage/import/reconcile broker evidence | Silently rewrite production ledger |
| UI | Explain next actions and evidence | Hide data-quality gaps or imply guaranteed returns |

## Automation Maturity

Karkinos is built to become more automated, but automation matures in layers:

| Level | Name | Meaning |
| --- | --- | --- |
| L0 | Research evidence | Backtests, sweeps, OOS, after-cost evidence, limitations |
| L1 | Daily trading plan | Candidate pool, blockers, risk, account truth, costs |
| L2 | Paper/shadow operating loop | Scheduled simulated execution and divergence review |
| L3 | Manual execution assist | OMS, manual tickets, broker evidence import, reconciliation |
| L4 | Controlled broker bridge | Per-order gated broker adapter, disabled by default |
| L5 | Small-capital auto pilot | Explicitly enabled, capped, monitored, reversible pilot |
| L6 | Unattended real-money automation | Deferred until every upstream layer is mature |

This ladder preserves the money-making goal: the system should automate the
parts that increase discipline and evidence quality first. Broker submission
comes only after the system proves it can decide, simulate, reconcile, and stop.

## Controlled Live Bridge Requirements

A future real broker submission path is acceptable only if all gates below are
true for the specific account, strategy, symbol, and order:

* strategy stage allows controlled bridge pilot;
* latest research evidence is after-cost and OOS acceptable;
* Account Truth gate is fresh and pass or explicitly policy-accepted degraded;
* pre-trade risk passes with a stored policy snapshot;
* paper/shadow divergence is clear or manually accepted;
* kill switch is off;
* gateway capability and health checks pass;
* order is inside account, strategy, symbol, cash, turnover, and loss limits;
* user has explicitly enabled the account and strategy for the bridge;
* per-order confirmation is required until a later small-capital pilot policy
  explicitly permits limited automation;
* all transitions, broker responses, fills, rejects, cancels, and reconciliation
  outcomes are written as immutable evidence.

No strategy should call a broker adapter directly. The only allowed path is
through policy, risk, OMS, gateway, and reconciliation services. The current
strategy tree is covered by a static broker-boundary guard so adapter imports
and direct broker-style calls fail deterministic tests before future connector
work can rely on them.

## Design Implications

* The architecture optimizes for decision and execution quality, not for the
  fastest order submission.
* The default UI should surface "what to review next" before "what to buy".
* Runtime data, broker evidence, reports, logs, and screenshots remain local
  and out of source control.
* Tests should be deterministic and use synthetic fixtures for live-like paths.
* Every trading-related feature should state what it assumes, what it blocks,
  what evidence it records, and what it refuses to automate.
