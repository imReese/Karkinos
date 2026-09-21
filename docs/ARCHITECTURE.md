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
- Research views bind exact daily receipts and a versioned units conversion. Original receipts and prior experiments retain their original values; unknown historical units block normalization.
- Replaying captured historical prices does not establish historical availability or point-in-time universe membership. Those limitations remain explicit in the dataset.
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

Baseline and candidate comparisons use the same frozen research window, cost assumptions, position allocation, signal delay, and market trading constraints. Choosing a new research window creates a new baseline; it does not rewrite an existing experiment.

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

AI is a **Research Intelligence Layer**, not an investment or capital authority.

Karkinos separates four authority layers:

| Layer | Canonical owner | AI role |
| --- | --- | --- |
| Financial / Market Truth | Market Data, Dataset, Accounting, persisted evidence | read and explain |
| Research Intelligence | Research domain + AI runtime | investigate, propose, critique, orchestrate bounded research |
| Evaluation & Gates | deterministic Research, Risk, Simulation, Accounting code | consume and explain results; never override |
| Capital Authority | explicit human-supervised execution controls | none |

AI may:

```text
observe approved persisted evidence
explain canonical facts and deterministic results
investigate a research question
propose falsifiable hypotheses and structured candidate specs
critique evidence and identify contradictions / missing tests
orchestrate bounded typed research workflows
```

AI does not own or change:

```text
Market Data facts
Dataset identity
canonical quantitative metrics
deterministic evaluation gates
Published Forecast publication authority
Portfolio state
Risk decisions
Accounting state
research promotion authority
capital or broker execution authority
```

The product capability levels are:

```text
L0 Observe
L1 Explain
L2 Investigate
L3 Propose
L4 Orchestrate Research
```

There is deliberately no AI capital-execution level.

The Research Intelligence lifecycle is:

```text
Research Task
-> Research Run
-> Hypothesis
-> Claim / Evidence
-> Candidate
-> Deterministic Evaluation
   -> rejected
   -> needs revision
   -> selected for further research
-> Account Qualification (when applicable)
-> Human Promotion Review
-> Paper / Shadow
```

Research selection, account qualification, and promotion are distinct decisions.
An AI-generated candidate never promotes itself.

New research contracts should prefer provider-neutral entities:

```text
ResearchTask
ResearchRun
ResearchHypothesis
ResearchClaim
EvidenceRef
ResearchCandidate
EvaluationBundle
CritiqueBundle
ResearchSelection
QualificationRun
PromotionDecision
AITrace
```

Model providers are adapters, not domain authorities.

AI-generated claims are research artifacts, not facts. External websites, papers,
PDFs, notes, and provider responses are untrusted evidence data; they never become
runtime instructions merely because they appear in model context.

Candidate generation should prefer typed DSL / AST output:

```text
AI candidate
-> schema validation
-> operator allowlist
-> semantic / leakage validation
-> deterministic compilation
-> deterministic evaluation
```

Canonical evaluation remains deterministic and may include OOS, after-cost,
walk-forward, sensitivity, regime robustness, leakage checks, turnover, and
drawdown evidence.

Research workflows must be bounded by explicit budgets such as candidate count,
iteration count, backtest count, parameter variants, provider calls, and external
searches. Repeated experimentation is recorded as overfitting evidence rather than
hidden as model iteration.

Every AI invocation or workflow stage must be traceable to provider/model identity,
prompt/instruction version, input artifact identities, evidence references, tool
calls, timing, usage, and output fingerprints where available.

Humans, schedulers, CLI, Web, and AI invoke the same platform capabilities. AI gets
no privileged path around normal Research, Risk, Portfolio, Execution, or Accounting
boundaries.

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
