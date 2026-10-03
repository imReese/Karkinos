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
- Automatic capture, per-source quality, cross-source agreement, historical availability, and return basis are separate claims. Research consumers admit inputs according to their use; a verified source pair does not imply historical PIT or total return.
- Trading calendars, historical universe membership, corporate actions, suspensions, price limits, and lot rules are shared market semantics.

The stock master observation binds its adapter call's actual start, completion
and availability times. Its `trade_date` selects the daily-bar history window;
it is not a historical membership effective date. New observations preserve
revisions under separate content-addressed IDs, including within the same day.
Research replay uses the frozen universe ID, while current scan freshness still
checks whether the latest universe has changed. Legacy v1 observations retain
their exact identity but have unknown availability and cannot satisfy an as-of
read. Capturing today's active stock list never establishes survivorship-free
historical membership or provider raw-response provenance.

Stock dividend and bonus-share observations use the existing ProviderCapture and
content-addressed object store. The source facts have an identity separate from
the capture observation: a repeated response can share facts while retaining its
new observation time. Announcement, implementation announcement, record, ex-date,
payment and bonus-share listing dates remain distinct. A current provider response
does not establish when all its fields became historically available; its admitted
availability is the capture completion time.

An explicit collection for an existing daily Dataset publishes a new DatasetRef
with bound corporate-action observations; it retains the original daily-bar
partitions. Dataset and report reads replay those exact objects offline. The
observations cover provider-reported stock distributions only. An empty response
does not prove that no corporate actions occurred. Neither attaching these facts
nor finding zero matching events models dividend receivables, payment cash,
bonus-share availability, taxes or total return.

Explicit gross research replay may consume implemented cash-only or cash-and-share
distributions from that binding. Portfolio owns dividend receivables, recognized
gross income, cash payment and idempotent share awards. Position keeps unlisted
awards separate from T+1 purchases; the accounting functions spread existing cost
over the additional shares. The backtest schedules record-date entitlements,
ex-date recognition, payment and share listing without creating trade fills or
real-account ledger entries. Fractional share allocations are rejected rather
than rounded. Account-specific withholding, payment rounding, adjusted strategy
features and complete source coverage remain unverified claims. Ex-date orders
are blocked when their authoritative price-limit reference is unavailable.

Both receipt-bound automated research and formal Dataset research retain this
exploratory return boundary. Their reports can replay and research can continue,
but a new qualification or publication cannot treat their raw-price return as
complete economic-return evidence, including when a historical receipt report
omitted the limitation label.

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
- Publication binds the intended consumer and financial book. A forecast published
  for research simulation is not eligible for actual-account recommendations.

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

The daily-bar backtest engine queues completed-bar targets for a strictly later
bar of the same instrument and sizes them at that later close. A final-bar signal
without a later price cannot fill. Baselines, Formula DSL candidates and parameter
variants share this execution rule, including execution-time trading constraints.
Each queued target gets one execution attempt; a blocked target is not a standing
order. Same-time instruments are processed in deterministic symbol order rather
than as a simultaneous portfolio rebalance.
Saved results identify the timing policy; missing metadata on an older result
does not establish its execution timing.

The `next_bar_close.v2` policy also checks each final buy fill against available
cash, including its simulated price and complete fees. Quantity reductions use
instrument lots and recompute costs; dividend receivables cannot fund purchases.
Each accepted fill updates the canonical portfolio before another queued order
is evaluated. Historical `v1` results retain their original identity and do not
establish these buying-power guarantees.

Execution delay and information availability are separate constraints. The
default historical-snapshot replay assumes information at the modeled bar close
and does not establish historical PIT performance. The engine's strict observed
mode rejects missing or later `available_at` values before initializing the
strategy. Neither mode alone verifies historical universe membership or
corporate-action returns.

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

The Research Intelligence lifecycle separates simulation observation from
actual-account publication:

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
   -> Simulation-scoped Forecast (under a standing simulation policy)
      -> Simulated Portfolio Target / Risk Decision / Rebalance Plan
      -> Independent Paper / Shadow Observation
      -> Attribution / Alpha Health -> continue / pause / retire / research feedback
   -> Final Qualification Evidence (independent holdout or forward observation)
      -> Account Qualification
      -> Human Account Publication Review
      -> Account-scoped Forecast
      -> Current Portfolio / Risk / Rebalance Plan
      -> Human Trade Review
```

Research selection, simulation admission, account qualification, account publication,
and trade approval are distinct decisions. An AI-generated candidate never
authorizes its own publication. Deterministic platform code may admit it to
simulation under an explicit owner-authorized policy; this records an automated
decision, not human confirmation.

### Research, simulation, and account publication

| Decision | Inputs and owner | Effect |
| --- | --- | --- |
| Research selection | Frozen datasets, formulas, costs, evaluation; Research | Selects an experiment for further work |
| Simulation admission | Research evidence and standing simulation policy; Research / Simulation | Activates one frozen version for a specified hypothetical book |
| Account qualification | Frozen strategy, current Account Truth, valuation, reviewed fees and account-sized replay; deterministic qualification | Establishes account applicability for those exact inputs |
| Account publication | Qualification and observation evidence plus human review; Research publication | Allows the exact version to supply account recommendations |
| Trade approval | Current account, market, portfolio and risk evidence plus human decision | Remains separate from research and simulation |

Keep research disposition, observation lifecycle, account applicability, and
account publication as separate decisions. A single strategy stage cannot stand
in for all four. Their identities bind the frozen strategy version and applicable
book/account, policy and evidence. A new experiment does not replace a published
incumbent merely because it wins that day's ranking.

Human account publication approves a specific version and bounded account use,
with explicit validity and revocation conditions. Daily recommendation generation
then runs deterministically inside that scope, checking current account, market
and risk facts each time. Ordinary snapshot refresh is not a new strategy approval;
changed formulas, cost rules or approved limits require a new applicable decision.
Refreshing evidence does not widen an existing publication's scope.

Research and simulation do not depend on actual-account completeness. Missing or
stale account facts block qualification and account recommendations. Shared market
data, replay, cost-model, or policy failures block the research or simulation that
uses those inputs. Provider failure does not disable deterministic observation or
account scans of previously published versions.

Simulation policy is default-off and binds universe, permitted formulas, costs,
allocation/risk limits, observation start, concurrent candidate limits, and compute
budgets. Enabling research alone does not authorize simulation. Enabling simulation
does not authorize account publication. Existing authorizations retain their
original scope; migration must not silently add permissions.

Paper observation uses its own cash, positions, fills, fees and equity history.
Shadow observation may compare forecasts or targets with subsequent outcomes
without inventing fills. Both bind a frozen strategy version, policy version,
dataset/as-of boundaries and observation dates. Evaluating today's signal or
rerunning its backtest is not forward observation. Replacing a candidate starts a
new observation identity; it does not rewrite the incumbent's history or book.
Actual-account movements are never imported into a simulation book as its fills.

The independent target shadow journey freezes an ordinary saved dual-MA strategy
or validated Formula definition under an explicit observation policy. A Formula
source retains its original analytics snapshot and canonical sizing evidence;
new publications bind formal verified Datasets without upgrading the source's
historical PIT or code-verification claims. Forecasts contain directional rule
decisions; Portfolio constructs capped targets, Risk independently checks them,
and rebalance intent records target-weight differences. No quantities, orders,
fills, cash or NAV are invented. Warmup decisions and skipped sessions are never
backfilled as forecasts.

Each explicit advance binds calculation time, frozen code and library versions,
the complete fixed-start Dataset prefix, verified calendar information times,
and the first session opening strictly after actual publication. Its outcome
window compares that session's close with the close a configured number of
trading sessions later. These price responses exclude costs and corporate-action
returns and are not paper-account performance. Missing exact endpoints remain
unavailable. Publication and measurement timestamps are obtained after acquiring
the database write lock; a clock reversal or crossing the selected opening
aborts publication. Stored request receipts, version checks and immutable history
protect retries and concurrent commands. Pausing stops new publications while
allowing explicit measurement of previously published targets after restart.

Selection feedback may use time-ordered validation and rolling OOS results.
Once those results guide later iterations they are validation evidence, not an
untouched final test. Final qualification requires an independent frozen holdout
or subsequent forward observation. The AI iteration inputs must exclude the
reserved final holdout. Baseline and candidate share cost, market, sizing and
timing rules. Minimum observation and performance thresholds are explicit policy,
not invented universal constants. Being best among today's candidates is not
evidence that a candidate passed admission.

For the automated normalized-research path, explicit research and sealed end dates
freeze one validation-selected champion before the sealed interval starts. The
reservation binds the input snapshot, formula, baseline, costs and recorded trial
family. The provider-free final evaluator checks the frozen research prefix and
binds the observed holdout snapshot. Overlapping consumed/reserved intervals cannot
be reused to choose another champion; retries retain the original evaluation.
New qualification and publication read this persisted evidence. Existing research
results without it remain available as exploratory results.

Trial correction uses actual adjacent-period equity returns and distinct recorded
formula/parameter trials. Its nominal-count DSR estimate assumes independent trials
and estimates trial dispersion from the candidate's return moments; correlation
and unrecorded searches remain limitations. It does not establish historical PIT
validity or replace independent final evaluation.

Health decisions distinguish unavailable evidence from measured deterioration.
Missing data suspends the affected evaluation; deterministic policy may pause an
affected observation, but missing data alone does not establish alpha decay.
Automatic pause or retirement binds the measured outcome, observation interval,
policy rule and expected current version. Retirement is terminal for that version
in the affected scope; an improvement is a new candidate. Restarting a worker or
retrying admission never reactivates a paused or retired version. Any resume
requires fresh evidence and an explicit decision under the applicable policy.
No health action creates a real trade or closes actual holdings.

If a configured rule also suspends account publication, it names the exact
affected version/account scope; it neither replaces another published strategy
nor disables unrelated recommendations.

Admission and health writes must be atomic and idempotent against their frozen
inputs and current state. Events identify human versus automated decisions and
their evidence. Automated decisions never fill `human_review`,
`human_approval_id`, or `manual_confirmation_recorded` with fabricated confirmation.

The current legacy runtime has a narrower contract: `strategy_promotion_states`
with `stage=paper_shadow` means a human-reviewed account-recommendation source.
`promoted_strategy_universe_scan` consumes it through the existing qualification,
artifact and human-review gates. Preserve those persisted records and readers;
do not reinterpret this stage as automatic research-simulation admission.
Normalized research already publishes a read-only operation preview, which is
research evidence rather than a simulation run. The current paper/shadow runner
consumes account trading plans and does not supply an independent research book.
Implement independent observation before adding automatic simulation admission,
and keep its inputs outside the account scan. Delivery sequence belongs to
[PLAN.md](PLAN.md).

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
