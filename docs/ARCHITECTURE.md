# Karkinos Architecture

## 1. System

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

## 2. Domain ownership

| Domain | Canonical responsibility |
| --- | --- |
| **Market Data** | Normalized observations, source identity, event time, availability time, capture time, source revision history, China-market data semantics |
| **Dataset** | PIT composition, universe/time selection, dataset identity, reproducible research input |
| **Research** | Features, experiments, evaluation, research evidence, Published Forecasts |
| **Portfolio** | Desired allocation, Portfolio Targets, Rebalance Plans |
| **Risk** | Hard constraints and allow/block/recalculate decisions |
| **Simulation** | Historical/forward replay, clocks, matching, slippage, hypothetical execution |
| **Execution** | Order/Fill lifecycle and external execution boundary |
| **Accounting** | Isolated financial books: cash, lots, positions, booked fees/taxes, PnL, valuation |
| **Attribution / Alpha Health** | Outcome decomposition and evidence for promotion, degradation, isolation, retirement |

One canonical calculation/write owner per fact. Derived representations may exist without becoming new owners.

## 3. Data and PIT datasets

Market Data records:

```text
observation
source
market/event time
availability time
capture time
source revision
```

Dataset records:

```text
as-of boundary
universe
selection
research input composition
dataset identity
materialization provenance
```

Rules:

- Market Data owns source revision history.
- Dataset owns PIT composition, not underlying fact revisions.
- Experiments bind an identifiable Dataset.
- Later provider corrections do not mutate prior experiment input.
- Dataset identity must be reproducible; a full physical copy is not required.
- Trading calendars, historical universe membership, corporate actions, suspensions, price limits, and lot rules are shared market semantics.

## 4. Research and forecasts

```text
Dataset
-> Features
-> Alpha / Model
-> Experiment
-> Evaluation
-> Research Evidence
-> Published Forecast
```

Published Forecast is the Research -> Portfolio contract.

It binds the predictive view to the required research identity, dataset identity, as-of boundary, universe, and forecast horizon.

Rules:

- Experiment output is evidence by default.
- Evidence does not become Portfolio input until explicitly published.
- Canonical research metrics are produced by deterministic platform code.
- Forecast is not Portfolio intent.

## 5. Portfolio and risk

```text
Published Forecasts
+ Financial Book
+ Portfolio Policy
+ Exposure / Risk Estimates
+ Liquidity / Expected Costs
-> Portfolio Target
-> Risk Decision
   -> allowed
   -> blocked
   -> recalculate with explicit constraints
-> Rebalance Plan
```

Rules:

- Portfolio owns Portfolio Targets.
- Risk owns independent guardrails.
- Risk does not silently rewrite a Portfolio Target.
- Rebalance Plan is generated from an allowed target and the current financial book.
- Rebalance Plan is not an Order.

## 6. Simulation, execution, and accounting

```text
Rebalance Plan
-> Pre-trade Risk
-> Order Intent
-> Order
-> Fill
-> Financial Event
-> Accounting Book
```

| Boundary | Owns |
| --- | --- |
| **Simulation** | Replay, simulated venue, matching, slippage, simulated fills |
| **Execution** | Canonical Order/Fill lifecycle and external venue interaction |
| **Accounting** | Booked financial effects and financial-book state |

Backtest and paper may use simulated Order/Fill semantics. Shadow may evaluate a target or plan without an Order/Fill lifecycle.

Cost semantics:

| Stage | Cost |
| --- | --- |
| Portfolio | expected transaction cost |
| Simulation | simulated execution cost |
| Execution | venue/broker execution evidence |
| Accounting | booked financial effect |

Financial books are isolated across backtest, paper, shadow, and actual-account contexts.

Reconciliation:

- Execution: local Order/Fill vs external order/trade evidence.
- Accounting: local financial state vs external cash/position/fee/account evidence.

China-market rules are shared wherever they materially affect Portfolio, Simulation, Execution, or Accounting.

## 7. Outcomes and Alpha health

```text
Forecast / Portfolio Intent
-> Simulated or Observed Outcome
-> Attribution
-> Alpha / Model Health
-> Research
```

Attribution may separate:

```text
market / factor exposure
Alpha / Model
portfolio construction
turnover and costs
execution
unexplained residual
```

Historical experiment identity is immutable. Promotion, weighting, degradation, isolation, and retirement create new research decisions.

## 8. AI and orchestration

AI may:

```text
propose hypotheses
submit experiments
inspect evidence
critique results
select follow-up research
```

AI does not own:

```text
Market Data
Dataset identity
quantitative metrics
Published Forecasts
Portfolio state
Risk decisions
Accounting state
capital authority
```

Humans, schedulers, CLI, Web, and AI invoke the same platform capabilities.

## 9. Invariants

- **Point-in-time before prediction.**
- **Reproducible research and simulation.**
- **One canonical owner per fact.**
- **Experiment evidence is not Portfolio input.**
- **Forecast is not Portfolio intent.**
- **Portfolio intent is not execution.**
- **Portfolio owns targets; Risk owns guardrails.**
- **Simulation is not Execution; Execution is not Accounting.**
- **Financial books are isolated.**
- **Derived views never become competing truth owners.**
- **Failed updates do not replace last-known valid state.**
- **Uncertainty blocks only dependent actions.**
- **AI drives iteration; Karkinos owns truth.**
- **Core workflows remain local-first.**
- **Capital authority is explicit and human-supervised by default.**
