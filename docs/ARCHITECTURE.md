# Karkinos Architecture

## 1. System overview

Karkinos is a **local-first quantitative research and investing platform for the
China market**.

Its core is a continuous evidence flywheel:

```text
                         Human / Scheduler / AI
                                  |
                                  v
External Data -> Market Data -> PIT Dataset -> Research -> Published Forecast
                                                       ^              |
                                                       |              v
                                                Alpha / Model      Portfolio
                                                   Health             |
                                                       ^              v
                                                       |        Risk Guardrails
                                                       |              |
                                                       |              v
                                                Attribution <- Outcomes
                                                       ^          /       \
                                                       |         /         \
                                                Accounting   Simulation   Execution
                                                       ^         |           |
                                                       |         v           v
                                                       +------ Fills / Financial Events
```

New market information becomes point-in-time research input. Research produces
validated forecasts. Portfolio construction turns forecasts into desired capital
allocation. Risk controls whether proposed actions may proceed. Simulation and
execution produce outcomes. Accounting and attribution turn those outcomes into
new evidence for research.

## 2. Domain ownership

| Domain | Canonical responsibility |
| --- | --- |
| **Market Data** | Normalized observations, source identity, market/event time, availability time, capture time, source revision history, and China-market data semantics |
| **Dataset** | Point-in-time composition, universe and time selection, dataset identity, and reproducible research inputs |
| **Research** | Features, experiments, evaluation, research evidence, and publication of forecasts |
| **Portfolio** | Desired capital allocation, portfolio targets, and rebalance planning |
| **Risk** | Independent hard constraints and decisions that allow, block, or require recalculation of portfolio actions |
| **Simulation** | Historical or forward-time market replay, clocks, matching models, slippage models, and hypothetical execution |
| **Execution** | Canonical order/fill lifecycle and external execution boundary |
| **Accounting** | Isolated financial books containing cash, lots, positions, booked fees and taxes, PnL, and valuation state |
| **Attribution / Alpha Health** | Outcome decomposition and evidence used to promote, degrade, isolate, or retire research edge |

Ownership is semantic. A domain may have multiple representations, but only one
canonical calculation or write owner for each fact.

## 3. Data and point-in-time datasets

External providers produce observations. Market Data normalizes those
observations and owns their source, time, and revision semantics.

Research data must distinguish:

```text
what happened
when it happened
when it became knowable
when Karkinos captured it
where it came from
which source revision it belongs to
```

Dataset publication selects a point-in-time-consistent view of Market Data and
assigns it a stable identity.

A Dataset owns the composition of research input, not the revision history of
its underlying market facts.

An experiment binds an identifiable Dataset. Later corrections or provider
revisions do not silently change the input of an existing experiment.

Dataset identity must be reproducible; it does not require a physical full copy
of all underlying data.

Trading calendars, historical universe membership, corporate actions,
suspensions, price limits, lot rules, and other China-market constraints are
shared market semantics rather than strategy-local logic.

## 4. Research and forecasts

Research turns Datasets into predictive evidence:

```text
Dataset
-> Features
-> Alpha / Model
-> Experiment
-> Evaluation
-> Research Evidence
-> Published Forecast
```

Experiments may produce scores, rankings, probabilities, expected returns,
confidence estimates, or other predictive outputs.

Experiment output is research evidence by default. It does not automatically
become portfolio input.

A Published Forecast is the Research -> Portfolio contract. It identifies the
investment view together with the dataset/research identity, as-of boundary,
universe, and forecast horizon required to interpret it.

Canonical research metrics and evaluation results are produced by deterministic
platform code.

## 5. Portfolio and risk

Portfolio construction combines published forecasts with the current financial
book, portfolio policy, exposures, liquidity, expected costs, and other
allocation inputs:

```text
Published Forecasts
+ Financial Book
+ Portfolio Policy
+ Risk / Exposure Estimates
+ Liquidity / Expected Costs
-> Portfolio Target
```

A `Portfolio Target` is the desired allocation owned by Portfolio.

Risk applies independent hard guardrails:

```text
Portfolio Target
-> Risk Decision
   -> allowed
   -> blocked
   -> recalculate with explicit constraints
```

Risk does not silently rewrite a Portfolio Target. When a target must change,
Portfolio remains responsible for producing the new target.

A Rebalance Plan is generated from an allowed Portfolio Target and the current
financial book:

```text
Allowed Portfolio Target
+ Current Financial Book
-> Rebalance Plan
```

A Rebalance Plan describes intended portfolio changes. It is not an Order.

## 6. Simulation, execution, and accounting

Simulation and Execution are separate boundaries.

Simulation provides an evaluation environment for hypothetical outcomes. It may
model clocks, market replay, matching, slippage, transaction costs, and
simulated fills.

Execution owns the canonical Order / Fill lifecycle and the interaction with an
external execution venue.

```text
Rebalance Plan
-> Pre-trade Risk
-> Order Intent
-> Order
-> Fill
```

Backtest and paper workflows may reuse the same Order / Fill semantics through a
simulated venue. Future live workflows use an external execution adapter.

Shadow evaluation may observe a target or rebalance plan without requiring a
simulated Order / Fill lifecycle.

Expected, simulated, and booked costs are distinct:

```text
Portfolio  -> expected transaction cost
Simulation -> simulated execution cost
Execution  -> venue/broker execution evidence
Accounting -> booked financial effect
```

Accounting consumes confirmed financial events and maintains isolated financial
books.

```text
Financial Book
  cash
  lots
  positions
  booked fees / taxes
  realized / unrealized PnL
  valuation state
```

Backtest, paper, shadow, and actual-account state do not share mutable financial
state. Where they maintain financial books, they share accounting semantics but
remain isolated books.

Execution reconciliation compares local Order / Fill state with external order
and trade evidence. Accounting reconciliation compares local financial state
with external cash, position, fee, and account evidence.

China-market rules such as T+1, board lots, commissions, taxes, price limits,
and suspensions are shared wherever they materially affect portfolio,
simulation, execution, or accounting results.

## 7. Outcomes, attribution, and Alpha health

Outcomes feed the research loop:

```text
Forecast / Portfolio Intent
-> Simulated or Observed Outcome
-> Attribution
-> Alpha / Model Health
-> Research
```

Attribution decomposes outcomes where evidence permits, including:

```text
market / factor exposure
Alpha / Model
portfolio construction
turnover and costs
execution
unexplained residual
```

Alpha / Model Health tracks whether the evidence supporting an edge remains
valid over time.

Promotion, weighting, degradation, isolation, and retirement produce new
research decisions. They do not rewrite historical experiment identity.

## 8. AI and orchestration

Humans, schedulers, CLI tools, the Web application, and AI invoke the same
platform capabilities.

AI may:

```text
propose hypotheses
submit experiments
inspect evidence
critique results
select follow-up research
```

AI does not own Market Data, Dataset identity, quantitative metrics, Published
Forecasts, Portfolio state, Risk decisions, Accounting state, or capital
authority.

The platform capabilities used by AI remain independently invokable and
verifiable without an AI provider.

## 9. Sources of truth

A canonical fact may have multiple derived representations:

```text
API responses
database read models
caches
reports
materialized views
analytics
UI models
```

Derived representations do not gain independent calculation or write authority.

Provider responses, broker APIs, AI output, HTTP delivery, Web UI, storage
engines, and schedulers do not become canonical domain owners by carrying,
persisting, or presenting information.

## 10. Core invariants

- **Point-in-time before prediction.** Research only uses information available
  at the modeled decision time.
- **Reproducibility.** Research and simulation results bind enough data,
  code/model, parameters, time boundaries, and financial assumptions to be
  reconstructed.
- **One canonical owner per fact.** Multiple representations do not create
  competing sources of truth.
- **Experiment evidence is not portfolio input.** Portfolio consumes explicitly
  published forecasts.
- **Forecast is not portfolio intent. Portfolio intent is not execution.**
- **Portfolio owns targets. Risk owns guardrails.** Risk never silently becomes a
  second portfolio constructor.
- **Simulation is not Execution. Execution is not Accounting.** Shared financial
  semantics do not imply shared runtime state.
- **Financial books are isolated.** Backtest, paper, shadow, and actual-account
  state never leak mutable state across books.
- **Failed attempts do not destroy valid state.** Failed refreshes,
  calculations, or publications do not silently replace the last known valid
  result.
- **Uncertainty blocks the affected action.** Missing, stale, conflicting, or
  unverified evidence blocks dependent actions without unnecessarily disabling
  unrelated capabilities.
- **AI drives iteration; Karkinos owns truth.**
- **Local-first ownership.** Core research and financial workflows do not depend
  on a hosted account or cloud control plane.
- **Capital authority is explicit.** Real-money authority is bounded,
  human-supervised by default, and never granted implicitly by research, AI,
  providers, or UI state.
