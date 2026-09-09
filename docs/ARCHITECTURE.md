# Karkinos Architecture

This document defines the durable architectural boundaries and ownership rules
of Karkinos.

It is not a target package tree, runtime topology, storage plan, migration plan,
or roadmap. Current priorities belong to [PLAN.md](PLAN.md), current repository
reality to [ENGINEERING.md](ENGINEERING.md), and external design references to
[REFERENCES.md](REFERENCES.md).

## 1. Architectural shape

Karkinos is a local-first quantitative research and investing platform for the
China market.

Its core research, portfolio, simulation, and financial state can be owned and
operated locally. External data providers, brokers, AI services, and optional
hosted services are adapters to the system; they do not become its architectural
center or source of authority.

The canonical product flow is:

```text
Market Data
-> Point-in-time Dataset
-> Feature / Alpha / Model
-> Forecast
-> Portfolio Target
-> Rebalance Plan
-> Risk
-> Simulation / Paper / Shadow
-> Human-supervised Execution
-> Orders / Fills
-> Accounting / Reconciliation
-> Attribution
-> Alpha Health / Retirement
```

These are semantic boundaries, not required processes, services, databases, or
packages. Keep them together when that is simpler. Split implementation only
when a real boundary or measured need justifies it.

## 2. Durable invariants

1. **Point-in-time before prediction.** Research may only use information that
   was available at the modeled decision time.

2. **Reproducible inputs before reproducible results.** Research and simulation
   results bind exact data, code/model, parameters, time boundaries, and
   financially relevant assumptions.

3. **One canonical owner per concept.** A financial or research fact has one
   calculation or write authority, even when it has many derived
   representations.

4. **Prediction is not portfolio intent.** Alpha, models, scores, and forecasts
   express investment views; they do not directly create orders.

5. **Portfolio intent is not execution.** Desired holdings, rebalance actions,
   orders, fills, and accounting facts are distinct concepts.

6. **External input is not internal authority.** Provider responses, broker
   snapshots, caches, AI output, and UI state must be validated or reconciled
   before becoming canonical Karkinos state.

7. **Financial semantics are shared where they matter.** Simulation, paper,
   shadow, and future live workflows must not independently redefine market
   rules, fees, orders, fills, or accounting.

8. **Uncertainty blocks the affected action.** Missing or stale evidence may
   prevent a dependent decision or execution without unnecessarily disabling
   unrelated parts of the product.

9. **Failed attempts do not destroy valid state.** A failed refresh,
   calculation, or publication must not silently replace the last known valid
   result.

10. **Capital authority never emerges implicitly.** Research, AI, UI actions,
    providers, or strategy code cannot grant themselves permission to trade
    real capital.

## 3. Market data and point-in-time datasets

External providers produce observations, not canonical research datasets.

Core market and fundamental data must preserve enough identity and time
information to answer:

```text
What happened?
When did it happen?
When could the strategy legally know it?
When did Karkinos obtain it?
Where did it come from?
Which revision is this?
```

This normally requires explicit market/event time, availability time, capture
time, source, and revision identity.

Normalization and validation turn provider observations into Karkinos data.
Research consumes published point-in-time datasets rather than depending on
whatever a provider currently returns.

A dataset used by an experiment has a stable identity. Corrections or revisions
produce a distinguishable dataset state rather than silently changing the
historical input of an existing result.

China-market semantics such as trading calendars, historical universe
membership, corporate actions, suspension, price limits, lot rules, and data
availability belong to this domain rather than being reconstructed ad hoc by
individual strategies.

## 4. Research and forecasts

Research owns the production and evaluation of investment views.

Its conceptual flow is:

```text
Dataset
-> Features
-> Alpha / Model
-> Forecast
-> Evaluation
```

An Alpha or model may produce scores, expected returns, probabilities,
rankings, confidence, or similar predictive outputs.

The canonical output consumed by portfolio construction is a forecast or
equivalent investment view, not a BUY/SELL command.

A reproducible experiment must identify the inputs and assumptions needed to
reconstruct its result. Exact representation is an implementation choice; the
architectural requirement is that meaningful research results are not detached
from their provenance.

Canonical metrics, backtest results, and financial calculations are produced by
deterministic application code. AI may propose hypotheses, generate research
candidates, explain results, or critique experiments, but AI output is not
canonical quantitative evidence by itself.

## 5. Portfolio construction and rebalance planning

Portfolio construction owns the transformation from investment views into
desired capital allocation.

```text
Forecasts
+ portfolio state
+ constraints
+ risk / exposure information
+ expected trading costs
-> Portfolio Target
```

A `Portfolio Target` describes desired portfolio state. It does not describe
how an order should be submitted.

Rebalance planning compares desired state with authoritative current state and
produces the intended portfolio changes required to move toward that target.

The portfolio layer owns allocation decisions and trade-offs between expected
return, risk, diversification, turnover, cost, liquidity, and other portfolio
constraints.

Simple portfolio methods must remain possible without requiring optimizer or
framework machinery.

## 6. Risk

Risk is a policy boundary around portfolio intent and capital-affecting actions.

Risk may constrain, reduce, or block proposed portfolio changes. It may also
prevent an execution when required evidence, freshness, authority, or financial
constraints are not satisfied.

Risk does not generate Alpha, own portfolio accounting, or become an alternative
execution engine.

Financial risk rules and operational readiness are related but distinct.
Implementation should not mix infrastructure health with financial policy
merely because both can block an action.

## 7. Simulation and execution

Simulation and execution consume portfolio intent; they do not decide the
investment thesis.

The durable financial lifecycle is:

```text
Rebalance Plan
-> Risk-approved Intent
-> Order
-> Fill
-> Accounting
```

Backtest, simulation, paper, shadow, and future live operation may use different
clocks, data sources, matching models, or external adapters, but they should
share the financial concepts that describe orders, fills, fees, positions, and
market constraints.

China-market rules such as T+1, board lots, commissions, taxes, price limits,
suspensions, and applicable trading restrictions must not be independently
reimplemented by each execution mode.

Vectorized research is allowed and often desirable. It must not silently replace
financially meaningful order, fill, cost, or accounting semantics when those
semantics affect the result.

Real-money execution is an outer adapter and remains human-supervised by
default. A future broker integration cannot bypass canonical risk, authority,
order, or reconciliation boundaries.

## 8. Accounting and reconciliation

Accounting owns Karkinos's canonical internal financial state.

This includes the authoritative treatment of concepts such as:

* cash;
* positions and lots;
* fees and taxes;
* realized and unrealized PnL;
* orders and fills as accounting inputs;
* valuation state where required by portfolio accounting.

Derived portfolio views, dashboards, analytics, and reports may represent this
state but must not independently recalculate or mutate its canonical facts.

External broker records, statements, imports, and snapshots are evidence about
the external account. They become Karkinos facts only through an explicit
import or reconciliation boundary.

When external evidence conflicts with local state, preserve the discrepancy
until it can be explained or reconciled. Do not invent missing financial facts
to make records agree.

## 9. Attribution and Alpha health

Investment outcomes feed back into research through attribution and Alpha
health rather than rewriting historical research results.

Attribution should make it possible to distinguish, where evidence permits,
effects from:

```text
market / factor exposure
Alpha
portfolio construction
turnover and costs
execution
```

Alpha health evaluates whether evidence supporting an investment edge remains
valid over time.

Promotion, weighting, degradation, isolation, and retirement of research ideas
are downstream decisions based on evidence; they do not mutate the historical
identity of the experiments that produced that evidence.

## 10. Canonical ownership and derived representations

"One canonical owner" does not mean "one representation."

Canonical state may be exposed through:

* API DTOs;
* database read models;
* caches;
* reports;
* materialized views;
* analytics;
* UI state.

These are derived representations and may be optimized for their consumers.

They must not silently acquire independent write authority or duplicate the
financial or research calculation owned elsewhere.

Canonical ownership is a semantic rule, not a requirement for one class, one
table, one file, or one package.

## 11. Freshness, publication, and failure

Read availability and action readiness are different concepts.

A useful last-known result may remain visible with its `as_of`, provenance, and
freshness clearly exposed even when a newer attempt failed.

An action that requires newer evidence must remain blocked until the required
evidence becomes valid.

A failure in one provider or subsystem should degrade the capabilities that
depend on it rather than automatically turning into a global product failure.

Unknown outcomes from external side effects must be reconciled before the
system assumes success or retries an action that may already have occurred.

## 12. Outer adapters

The following are outer concerns rather than canonical domain owners:

```text
data providers
broker APIs
HTTP / API delivery
Web UI
AI providers
storage engines
schedulers and background runners
optional hosted services
```

Adapters translate between external systems and Karkinos concepts.

They may cache, transport, serialize, schedule, or present information, but they
must not redefine the semantics owned by the core domains.

The core workflow must not require a hosted account or cloud control plane.
Optional remote capabilities may be added later without transferring implicit
ownership of core user state away from the local-first system.

## 13. Architectural evolution

Prefer the simplest implementation that preserves these boundaries.

Do not create a service, process, database, repository, protocol, plugin,
worker, or language boundary merely because a conceptual domain exists.

Introduce stronger physical separation only when justified by concrete needs
such as correctness, isolation, independent lifecycle, performance, or a real
external boundary.

Likewise, do not preserve an obsolete internal abstraction merely because it
once represented the architecture.

External projects in [REFERENCES.md](REFERENCES.md) provide design evidence.
They do not prescribe Karkinos's package structure, APIs, technology choices,
or implementation machinery.

## 14. What this document does not define

This architecture intentionally does not prescribe:

* Python package layout;
* process or worker topology;
* database count or storage engine;
* SQLite, Parquet, Arrow, DuckDB, Polars, Rust, or other technology choices;
* queue or scheduler design;
* HTTP route structure;
* release or deployment machinery;
* current implementation ownership;
* migration sequencing;
* current feature priorities.

Those choices may change without changing the architecture.

If a decision is about what Karkinos should build **now**, it belongs in
`PLAN.md`. If it describes how the repository works **today**, it belongs in
`ENGINEERING.md`. If it is a durable financial or research ownership rule, it
belongs here.
