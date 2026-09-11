# Karkinos Architecture

This document defines the durable architecture of Karkinos: the core system
flow, domain ownership, sources of truth, and boundaries that should remain
stable as the implementation evolves.

Current priorities belong to [PLAN.md](PLAN.md), current repository reality to
[ENGINEERING.md](ENGINEERING.md), and external design references to
[REFERENCES.md](REFERENCES.md).

## 1. System overview

Karkinos is a **local-first quantitative research and investing platform for the
China market**.

Its core is a continuous evidence flywheel. New market information becomes
point-in-time research input; research produces forecasts; forecasts inform
portfolio decisions; simulation and observed outcomes produce new evidence that
feeds back into research.

```text
                         Human / Scheduler / AI
                                  |
                                  v
External Data -> Market Data -> PIT Dataset -> Research -> Forecast
                                                   ^           |
                                                   |           v
                                           Alpha / Model    Portfolio
                                              Health           |
                                                   ^           v
                                                   |      Risk / Rebalance
                                                   |           |
                                                   |           v
                                           Attribution <- Outcome
                                                           ^
                                                           |
                                            Simulation / Paper / Shadow
                                                           |
                                             Human-supervised Execution
```

The platform owns quantitative and financial truth. Humans, schedulers, the Web
application, CLI tools, and AI may invoke platform capabilities, but they do not
redefine their semantics.

## 2. Platform capabilities and orchestration

Core capabilities must be usable and verifiable independently of AI:

```text
acquire and normalize market data
publish point-in-time datasets
run reproducible experiments
publish forecasts and evaluation results
construct portfolio targets and rebalance plans
apply risk constraints
simulate orders, fills, costs, and portfolio changes
maintain canonical financial state
calculate attribution and Alpha / Model health
```

AI may propose hypotheses, submit experiments, inspect evidence, critique
results, and choose follow-up research. Replacing or disabling an AI provider
must not change the quantitative or financial meaning of these capabilities.

## 3. Domain ownership

| Domain | Owns |
| --- | --- |
| **Market Data** | Normalized market observations, source identity, market/event time, availability time, capture time, and China-market data semantics |
| **Dataset** | Point-in-time selection, reproducible research inputs, dataset identity, and revision lineage |
| **Research** | Features, experiments, Alpha / Model evaluation, forecasts, and research evidence |
| **Portfolio** | Desired capital allocation, portfolio targets, rebalance intent, and allocation trade-offs |
| **Risk** | Financial constraints and decisions that reduce, modify, or block portfolio actions |
| **Simulation / Execution** | Order and fill lifecycle, matching/execution semantics, and financially relevant execution costs |
| **Accounting / Reconciliation** | Cash, lots, positions, fees, taxes, PnL, valuation state, and reconciliation with external account evidence |
| **Attribution / Alpha Health** | Outcome decomposition, research-performance feedback, and evidence used to promote, degrade, isolate, or retire edge |

Ownership is semantic. It does not require one package, class, table, process, or
service per domain.

## 4. Data and point-in-time datasets

External providers produce observations. They are inputs, not canonical
research datasets.

Market data used for research must preserve enough identity and time information
to distinguish:

```text
what happened
when it happened
when it became knowable
when Karkinos captured it
where it came from
which revision it belongs to
```

Normalization and validation turn provider observations into Karkinos market
data. Dataset publication then selects a point-in-time-consistent research view
with a stable identity.

An experiment binds an identifiable dataset. Corrections and revisions produce a
distinguishable dataset state rather than silently changing the historical input
of an existing result.

Trading calendars, historical universe membership, corporate actions,
suspensions, price limits, lot rules, and other China-market constraints belong
to shared market semantics rather than individual strategies.

## 5. Research, forecasts, and portfolio construction

Research turns datasets into predictive evidence:

```text
Dataset
-> Features
-> Alpha / Model
-> Forecast
-> Evaluation
```

Research outputs investment views such as scores, rankings, probabilities,
expected returns, or equivalent forecasts. A forecast is not an order.

Portfolio construction combines forecasts with current portfolio state,
constraints, exposures, liquidity, and expected costs to produce desired capital
allocation:

```text
Forecasts
+ Current Portfolio
+ Constraints / Exposures / Costs
-> Portfolio Target
-> Rebalance Plan
```

A `Portfolio Target` describes desired state. A `Rebalance Plan` describes the
intended change from current state toward that target. Neither defines how an
order is submitted or filled.

Simple portfolio policies must remain possible without requiring optimizer or
framework machinery.

## 6. Risk, simulation, execution, and accounting

Risk evaluates portfolio intent and capital-affecting actions. It may constrain,
modify, or block a rebalance, but it does not generate Alpha or own accounting.

The financial lifecycle is:

```text
Rebalance Plan
-> Risk-approved Intent
-> Order
-> Fill
-> Accounting
```

Simulation and execution own the canonical order/fill lifecycle and the
financial semantics of matching and execution. Backtest, paper, shadow, and
future live workflows may use different clocks, data sources, and execution
adapters, but they must not independently redefine orders, fills, fees, or
market constraints.

Accounting consumes confirmed fills and other financial events. It owns cash,
lots, positions, fees, taxes, realized and unrealized PnL, and related valuation
state.

External broker statements, snapshots, and imports are evidence about an
external account. Reconciliation compares that evidence with Karkinos state;
it does not invent missing financial facts to force agreement.

China-market rules such as T+1, board lots, commissions, taxes, price limits,
and suspensions must be shared wherever they materially affect simulation or
execution results.

## 7. Outcomes and the research feedback loop

Research does not end when a forecast or portfolio target is produced.

```text
Forecast / Portfolio Intent
-> Simulation or Observed Outcome
-> Attribution
-> Alpha / Model Health
-> Research
```

Attribution separates effects such as market or factor exposure, Alpha,
portfolio construction, turnover, costs, and execution where the available
evidence permits.

Alpha / Model Health evaluates whether the evidence supporting an edge remains
valid. Promotion, weighting, degradation, isolation, and retirement create new
research decisions; they do not rewrite the historical identity of earlier
experiments.

## 8. Sources of truth and derived representations

A financial or research concept has one canonical calculation or write owner,
but it may have many derived representations.

Examples include API responses, database read models, caches, reports,
materialized views, analytics, and UI models. These may be optimized for their
consumers, but they must not become competing sources of truth.

External providers, broker APIs, AI output, HTTP delivery, Web UI, storage
engines, schedulers, and optional hosted services are adapters or orchestration
boundaries. They do not own Karkinos domain semantics merely because they carry,
persist, or present the data.

## 9. Cross-cutting invariants

- **Point-in-time before prediction.** Research only uses information available
  at the modeled decision time.
- **Reproducibility.** Meaningful results bind enough data, code/model,
  parameters, time boundaries, and financial assumptions to be reconstructed.
- **One canonical owner per concept.** Derived representations do not gain
  independent calculation or write authority.
- **Forecast is not portfolio intent. Portfolio intent is not execution.** These
  boundaries remain distinct even when implemented in the same process.
- **Failed attempts do not destroy valid state.** A failed refresh, calculation,
  or publication does not silently replace the last known valid result.
- **Uncertainty blocks the affected action.** Missing, stale, conflicting, or
  unverified evidence blocks dependent actions without unnecessarily disabling
  unrelated capabilities.
- **Financial semantics are shared where they matter.** Simulation and execution
  use consistent market, cost, order, fill, and accounting concepts.
- **AI drives iteration; Karkinos owns truth.** AI can direct research but cannot
  become the authority for market facts, quantitative metrics, portfolio state,
  accounting, risk results, or capital permission.
- **Local-first ownership.** Core research and financial workflows do not depend
  on a hosted account or cloud control plane.
- **Capital authority is explicit.** Real-money authority is bounded,
  human-supervised by default, and never granted implicitly by research, AI,
  providers, or UI state.

## 10. Implementation freedom

This architecture deliberately does not prescribe:

- Python package layout;
- process or worker topology;
- database count or storage engine;
- SQLite, Parquet, Arrow, DuckDB, Polars, Rust, or other technology choices;
- queue or scheduler implementation;
- HTTP route structure;
- release or deployment machinery;
- current migration sequence or feature priority.

Use the simplest implementation that preserves the boundaries above. Introduce
stronger physical separation only when correctness, isolation, lifecycle,
performance, or a real external boundary requires it.

If a decision is about what Karkinos should build now, it belongs in
[PLAN.md](PLAN.md). If it describes how the repository works today, it belongs
in [ENGINEERING.md](ENGINEERING.md).