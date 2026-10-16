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

### Deployment scope and full-market validation

The validation subject is a deployable strategy version: formula and parameters,
universe eligibility and timing rules, feature/return basis, signal-state rules,
candidate ranking, total position limits, allocation and cash policy, market
constraints, costs, decision/execution clock, and deterministic implementation.
Formula equality alone does not establish strategy equality.

The same versioned universe rule applies in research, final evaluation, forward
simulation and recommendations. Membership is resolved with facts available at
each decision cutoff; the rule may admit new listings and remove ineligible
members without silently changing the strategy. Held instruments retain their
valuation and exit-maintenance lane after leaving the buy universe. Unknown
listing, trading or availability facts are not known exclusions.

Full-market means the explicitly declared eligible market, not every security
irrespective of exchange support, liquidity, listing history or account
permissions. A restricted scope must be named and validated as such. Deployment
cannot exceed its validated scope; adding exchanges or changing eligibility,
ranking, feature basis or execution rules requires a new applicable evaluation.
The legacy 40-stock research panel preserves its frozen replay identity; new
full-scope experiments do not inherit that sample bound. Sampled development is permitted for bounded early
screening, with selection fixed before inspecting outcomes. It never supplies
full-market qualification. Full-scope development is preferred when measured
local runtime and resource budgets permit it.

Historical universe reconstruction includes the securities and states known at
the historical cutoff, including subsequently delisted members. Today's active
master cannot certify historical membership. When historical PIT or economic
return inputs are unavailable, historical results remain exploratory. A new
preregistered full-scope prospective experiment can accumulate independently
valid evidence from actual captures; it does not repair the historical claim.

Provider batch size and dataset scope are separate. Existing capture, verified
jobs, object storage and Dataset readers remain the data path. Dataset
manifest v4 references daily membership and disjoint collection shards;
previous versions and their frozen budgets retain their original meaning. A
complete section validates expected membership, duplicate/missing rows, source
identities, verification and decision availability before publication. Separate
captures remain separate provenance. Features may be computed by shard, but
global ranking, portfolio allocation and the financial book are not sharded into
independent portfolios whose equity curves are later combined.

The reader verifies original capture hashes and both source materializations,
and reuses the canonical bars already decoded during that verification. One
daily recommendation read may reuse fully verified immutable Dataset reads with
the same object-store root and DatasetRef through preparation, quote freezing,
the persisted scan and current-input checks. Nested consumers explicitly join
that call's scope; independent scans and the next daily read verify the bytes
again. Grant, publication, account, fees, health and risk
checks still run at consumption and before atomic task publication. Data reuse
never caches an authority decision.

Coverage is measured against the declared universe before provider failures are
removed. Operational sync thresholds do not prove full validation coverage.
Known policy exclusions, unavailable evidence and actually evaluated members
remain separately countable. Missing members that could change a global ranking
block that strategy's affected new targets; they do not disable unrelated books
or excuse missing valuation of an existing position. A narrower available-data
scope is admissible only when explicitly declared in advance and used throughout
the experiment and publication.

Research, historical validation, forward paper and recommendation adapters use
one deterministic session-level decision path. It evaluates the admitted cross
section, emits forecasts, then invokes the existing Portfolio and Risk owners.
The path uses the relevant book's actual positions and available cash: held
positions consume total slots, unfilled targets are not positions, an unfilled
exit does not free a slot or cash, and new allocations reserve their full modeled
cost. Positions outside a strategy's approved scope are constraints, not implicit
authority for that strategy to sell them. Stable tie-breaking removes dependence
on bar, symbol or shard traversal order. Accounting and execution retain their
own calculations and isolated books.

The initial formula policy uses entry and exit intents. A hold preserves actual
share quantity as prices move; its observed weight remains book metadata. The
25% symbol target sizes a new entry, while the separately authorized observed
concentration bound governs the resulting book.

Signal features use a frozen, as-of-valid treatment of corporate actions;
execution and accounting use raw tradable prices and explicit distributions.
Adjusted features must not book distributions a second time. Cost, tax, lot,
suspension, price-limit and participation assumptions apply consistently across
candidate and comparators. A next-session-close simulation establishes evidence
for that explicit model only; an intraday recommendation/execution window needs
its corresponding timing and price evidence.

Validation is portfolio-level, with shared capital, simultaneous opportunities,
cash drag, actual slot limits, modeled fills and costs. Per-stock success rates
or the average of independent stock backtests cannot replace it. The primary
simple comparator must be executable at the tested capital and have the same
return basis; a thousands-name equal-weight index can be a diagnostic but cannot
be presented as an executable small-account baseline. Frozen simple/random
challengers share the universe, clock, risk/capital limits and costs. Market,
sector, size and liquidity attribution expose concentrated explanations without
requiring every stock or subgroup to make money.

Full-scope development and rolling validation may guide revisions. Final evidence
starts after the formula, universe rule, portfolio/execution implementation,
comparators, cost scenarios, search budget and evaluation checkpoints are frozen.
It consists of an untouched, correctly timed final interval or a genuinely new
prospective interval over that same deployment scope. A viewed historical tail
does not become untouched by changing its label. All related trials, parameter
variants and development panels remain in the research history when scope
changes; changing a sample does not reset the search count.

Final evaluation uses the full portfolio's net outcomes, uncertainty and risk
constraints. Thousands of correlated stocks do not create thousands of
independent time observations. Autocorrelation and overlapping holding periods
must be reflected in the chosen inference method; DSR/PBO are supplementary
diagnostics under their stated assumptions, not substitutes for independent
evidence. Observation horizon, effective sample requirements, minimum useful
improvement, risk limits and statistical error budget are explicit preregistered
policy. They are not universal Sharpe or day-count constants. Repeated candidate
tests, related research cycles and repeated looks at accumulating performance
consume the standing grant's preregistered nominal error budget. New run IDs,
development samples or policy renewal do not erase already consumed related
tests. Finite cycles/checkpoints may share a conservatively allocated budget;
inference assumptions and finite-sample limitations remain explicit.
Checking worker health daily does not create permission to test for admission
daily until a candidate happens to pass.

The simplest research schedule is a bounded development cycle, one frozen
champion and comparator family, then a fixed final observation and decision.
That candidate's development cutoff stays frozen throughout the final interval.
Capture, settlement and operational monitoring continue. With the current global
holdout-exposure guard, overlapping model research that would consume final dates
must keep the frozen cutoff or wait. Concurrent current-market research requires
explicit experiment isolation and bounded cross-candidate testing before that
guard can be changed. Consumed data are never reused as an untouched test to
select another version. Concurrent final candidates or checkpoints must be bounded
and accounted for before their results are inspected.
Insufficient evidence remains a supported outcome; a final failure is retained
instead of triggering unlimited optimization on the same final interval.

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

The existing bounded daily-bar backtest engine queues completed-bar targets for a strictly later
bar of the same instrument and sizes them at that later close. A final-bar signal
without a later price cannot fill. Baselines, Formula DSL candidates and parameter
variants share this execution rule, including execution-time trading constraints.
Each queued target gets one execution attempt; a blocked target is not a standing
order. Same-time instruments are processed in deterministic symbol order rather
than as a simultaneous portfolio rebalance.
Saved results identify the timing policy; missing metadata on an older result
does not establish its execution timing.
These are preserved legacy replay semantics. The full-deployment-scope path must
first complete the session's cross-sectional decisions and shared-capital
allocation; it cannot inherit symbol-order portfolio selection and call it the
same validated strategy. Existing matching/accounting may be reused behind that
path without changing previously saved results or their timing-policy identity.

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
      -> Account Publication (human decision or standing publication policy)
      -> Account-scoped Forecast
      -> Current Portfolio / Risk / Rebalance Plan
      -> Human Trade Review
```

Research selection, simulation admission, account qualification, account publication,
and trade approval are distinct decisions. An AI-generated candidate never
authorizes its own publication. Deterministic platform code may admit it to
simulation, or publish a qualified version for bounded account recommendations,
under the corresponding explicit owner-authorized policy. These record automated
decisions, not per-candidate human confirmation. Research, simulation and account
publication permissions remain separate grants.

An exact exploratory Dataset snapshot with complete content identities and clean
consumed rows can support research selection and hypothetical simulation. Its
bytes must still replay before use. This admission does not infer historical
information availability, corporate-action coverage or economic-return validity,
and never admits account publication. Default research execution assumptions
include 5 bps proportional slippage and a cumulative 1% share-volume cap per bar;
explicit overrides remain frozen in each report. Unfilled residuals are cancelled
after the attempt. Adverse cost replays use fresh books over the same inputs and
rules. These assumptions do not prove venue liquidity or executable returns.

### Research, simulation, and account publication

| Decision | Inputs and owner | Effect |
| --- | --- | --- |
| Research selection | Frozen datasets, formulas, costs, evaluation; Research | Selects an experiment for further work |
| Simulation admission | Research evidence and standing simulation policy; Research / Simulation | Activates one frozen version for a specified hypothetical book |
| Account qualification | Frozen strategy, current Account Truth, valuation, reviewed fees and account-sized replay; deterministic qualification | Establishes account applicability for those exact inputs |
| Account publication | Scope-matched final evidence, current qualification and either human review or an active standing publication grant; Research publication | Allows the exact version to supply bounded account recommendations |
| Trade approval | Current account, market, portfolio and risk evidence plus human decision | Remains separate from research and simulation |

Keep research disposition, observation lifecycle, account applicability, and
account publication as separate decisions. A single strategy stage cannot stand
in for all four. Their identities bind the frozen strategy version and applicable
book/account, policy and evidence. A new experiment does not replace a published
incumbent merely because it wins that day's ranking.

An owner may approve one version or explicitly enable automatic publication under
a standing policy. The latter binds the account/strategy allocation scope,
permitted market and strategy family, capital/risk and resource bounds, required
full-scope validation, evaluation checkpoints, replacement/health rules, expiry
and revocation. It is default-off and cannot be inferred from an enabled research
or simulation policy. It authorizes recommendation publication only, not orders,
broker access or increased capital authority. No per-candidate human click is
required inside that grant.

The grant freezes the account's permitted entry boards before ranking. Research
data and features still cover the full declared universe; baseline, candidate,
comparators, forward paper and account recommendations apply the same entry
constraint. Unsupported trade units remain excluded. A later permission loss
blocks new policy buys rather than silently substituting a narrower portfolio;
exit maintenance remains available. Daily formula initialization uses the frozen
forward seed's history boundary, independent of mutable runtime start dates.

An automated publication decision binds the policy identity/generation, exact
candidate and deployment rules, final-evidence interval, current qualification,
and expected incumbent version. The publication command revalidates all of them
and the grant immediately before an atomic, idempotent write. Changing a formula,
scope, cost rule or approved limit requires a new applicable decision; the policy
may authorize that new decision but cannot reuse incompatible evidence. Ordinary
snapshot refresh does not widen an existing publication's scope.

Daily recommendations run deterministically inside the approved scope, checking
publication validity, the bound grant's expiry/revocation, and current account,
market and risk facts each time. Revoking or expiring a grant invalidates the
sources whose authority depends on it; it does not erase their history or stop
valuation and exit maintenance. Pausing future automatic admission/replacement
is a separate scheduling control and may retain a currently valid publication
under its still-active grant. The UI distinguishes these effects explicitly.
A replacement must satisfy the
preregistered absolute admission requirements and its net benefit over a
comparable incumbent, after transition costs. Comparison uses a common interval,
capital, data, timing and cost basis; the incumbent's original lifetime return
is not compared directly with a new book. Replacement frequency and minimum
improvement prevent daily winner churn. Only the specifically authorized source
is superseded; other strategies and books are unaffected. Switching publication
does not liquidate actual holdings, inherit simulated fills, or reset performance.
Existing holdings retain explicit ownership and a transition/exit plan.

Research and simulation do not depend on actual-account completeness. Missing or
stale account facts block qualification and account recommendations. Shared market
data, replay, cost-model, or policy failures block the research or simulation that
uses those inputs. Provider failure does not disable deterministic observation or
account scans of previously published versions.

The research policy may separately authorize independent full-scope validation.
It freezes hypothetical capital, research costs, entry-board rules, risk limits,
a finite final-test budget and future statistical checkpoint. It reuses the
existing verified-seed, sealed-reservation, observation and paper-book owners;
no account publication grant, private balance or reviewed account fee schedule is
required to collect this evidence. The future interval starts only after the
verified seed is ready. Revocation fences that simulation's observation inputs,
new targets and settlements without erasing its history. Shared market-data
collection retains its separate lifecycle.

An independent simulation final retains its own validation provenance. A later
account publication needs its own active grant and current qualification. Reuse
requires compatible strategy, code, scope, entry rules, capital, statistical and
risk requirements. Qualification replays the original candidate and its frozen
comparison family over the same data and interval under current reviewed fees,
then applies the account's statistical and risk requirements to those curves.
The completed qualification stores that assessment immutably; subsequent
consumers reopen it and revalidate the current fee and publication bindings.
The original simulation, modeled costs and paper fills retain their identities.
Missing or incompatible evidence blocks account publication.

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

The independent target shadow journey freezes an ordinary saved dual-MA or
ETF-rotation strategy, or a validated Formula definition, under an explicit
observation policy. A Formula source retains its original analytics snapshot
and canonical sizing evidence;
new publications bind formal verified Datasets without upgrading the source's
historical PIT or code-verification claims. Forecasts contain directional rule
decisions; Portfolio constructs capped targets, Risk independently checks them,
and rebalance intent records target-weight differences. No quantities, orders,
fills, cash or NAV are invented. Warmup decisions and skipped sessions are never
backfilled as forecasts.

Each advance binds calculation time, frozen code and library versions,
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

An observation can also explicitly start a separate stock/ETF paper book with
initial cash, empty holdings and frozen instrument, cost and implementation assumptions.
It accepts only targets actually published after that book started and before
their designated session opened. Settlement models one attempt at that session's
close, using the existing simulation, risk, Portfolio and distribution calculations;
it never reruns the strategy to invent historical targets. Simulation fill time
and actual settlement-record time remain distinct. This is a daily-close model,
not proof of historical PIT availability, liquidity or actual execution.

Each settled session binds its immutable Dataset and saved financial projection.
Further settlement replays those original inputs and requires the already settled
financial prefix to agree before appending any new sessions atomically. A newer
Dataset cannot replace previously used prices. Late or conflicting corporate
actions that change that prefix block settlement; source revisions cannot grant
the same economic entitlement twice. The gross reported-distribution model retains
its coverage, tax and rounding limitations. Pausing the book stops acceptance of
newly published targets; it does not liquidate holdings or prevent their subsequent
valuation and settlement. Paper facts stay outside actual-account ledgers and
shared execution tables. Observation scheduling does not authorize paper settlement.

Stock paper books default to the existing gross reported-distribution model;
ETF books currently use explicit price-only returns because ETF distributions
are not covered by that owner. Both preserve provider coverage, tax, timing and
instrument-model limitations. Trading identity remains stock or ETF even when an
ETF's investment exposure is gold or bonds.

Paper performance is derived from the recorded equity, fills, positions and
attempts. Net equity already includes fees and slipped prices; diagnostics never
subtract those costs again. The return and drawdown series includes initial cash.
A frozen, capped equal-weight same-universe buy-and-hold comparator shares the
book's initial cash, instruments, cost and distribution assumptions. Its first
single execution attempt is synchronized to the earliest genuinely accepted
published target session by a rule frozen at book start. Waiting sessions remain
visible and both simulated books retain cash until that session. This comparison
is modeled net excess return, not factor-neutral alpha or proof of execution.

An optional paper-health policy freezes minimum evaluated sessions and net-excess
and drawdown thresholds at book start. Sessions before any accepted target do
not satisfy its sample requirement. A breach may report a review or atomically
pause only that paper book's acceptance of new targets; holdings continue to be
valued. Its decision identifies the financial version, interval and comparison
basis. Missing evaluation inputs cannot trigger a new performance action. Reads
derive paper diagnostics from the preserved book version. Human publication
review may bind a supplementary paper version and outcome fingerprint; later
ordinary settlement preserves the reviewed immutable prefix. This evidence never
replaces independent final evaluation or account qualification.

Local scheduling is a separate, default-off opt-in for an exact observation.
It reuses these same commands and receipts, with a persisted configuration
generation rechecked under the publication write lock. It consumes existing
verified Datasets; it does not authorize provider requests or account actions.
Automatic publication uses the just-closed session's window and cannot retarget
a missed opening after a restart. Pause, configuration replacement, shutdown and
release activation fence automatic writes. Missing inputs only update operational
status; they do not create empty observation versions or performance evidence.
An unidentified unreadable discovery candidate is reported separately; a selected
matching Dataset that fails verification blocks instead of falling back to an
older matching version.

Observation data preparation is a third, separate default-off permission. The
existing data worker submits one two-source verification job per subsequent closed
session for the entire frozen stock/ETF basket. It appends successful verified
daily partitions to the exact original immutable Dataset; it cannot replace that
prefix or synthesize a multi-asset revision from unrelated single-asset receipts.
The complete interval retains calendar, source, capture and verification evidence.
When this supply permission is enabled, automatic target and paper consumers also
check the selected Dataset against the original prefix. A newer catalog entry
with revised history blocks the action; it cannot silently substitute that history
or cause fallback to an older matching entry.
Legacy fixed-basket observations retain their frozen instrument/row budgets and
configured provider budgets. Full-scope formula observations compose complete
dated shards, bounded by 10,000 instruments, 2,000 sessions and 20 million rows. Each appended batch spans at most 366 calendar days; successful
batches extend the preserved prefix and serve as the next batch's cursor. Pending
or failed jobs cannot advance that cursor. Long-lived observations do not lose data
supply merely because their original start is more than a year old.

Full-scope cash books also collect prospective corporate actions through the
existing leased data queue. Four actual all-market dividend queries per calendar
day bind their raw captures and availability to the Dataset, beginning at the
cash book's observation start. Collection waits for the provider's 21:00 update
window and consumes the existing daily call budget. Truncated responses,
incomplete implemented terms, conflicting revisions or missing days block the
affected settlement. This is provider-reported coverage, not a historical warmup
or exchange-completeness guarantee. Heavy immutable composition and replay run
outside the account write lock; final catalog acceptance rechecks the current
permission and generation in a short transaction.

At observation creation, an explicit forward Dataset may supply a separate warmup
history. The source report identity, original research dates and parameters stay
unchanged. This Dataset binds the same typed universe, complete verified sessions,
minimum warmup and latest closed session at creation. Its availability must precede
creation. Strategy state is recomputed from that seed, not claimed to continue the
old backtest state. Subsequent manual and automatic observation/paper inputs must
preserve its exact partitions. Existing observations without this binding retain
their original source history. A verified prefix is still required for automatic
preparation; a new seed does not certify historical research or account publication.

Cold full-scope warmup collects each stock shard over its complete required date
range, rather than fetching the same stock separately for every historical day.
Historical range jobs retain at most 40 instruments per capture, while single-day
jobs allow 100. One complete input round at the declared 10,000-instrument limit
therefore needs at most 100 daily batches per upstream, within the existing
Shanghai-calendar-day budget of
100 canonical fetch attempts. The next midnight can supply the small remainder
when that upstream also performs the four prospective dividend queries; continuous
trading-week admission is tested against each next-opening deadline, rather than
only comparing weekly totals. Concurrent books share this capacity; the bound
does not guarantee arbitrary concurrent workloads or provider completion times.
Existing 40-instrument jobs and immutable Dataset identities remain readable.
Each source retains one genuine range capture; normalization, revisions, quality
and independent reconciliation remain dated per session. The capture's actual
completion time remains its conservative availability boundary. Missing sessions,
duplicate rows, incomplete membership or a conflicting source block acceptance.
The forward interval is frozen only after the seed is ready; late historical
collection cannot become an already elapsed forward sample.

Opted-in current forward input jobs take precedence over ordinary historical
watchlist collection. The existing daily provider-attempt budget remains bounded;
its status exposes the next Shanghai-midnight reset and deferred jobs retain their
actual retry time. A transport batch may contain multiple real SDK requests, so
the attempt count is not a count of individual network requests or a completion
time guarantee. Source failures or insufficient supply can still miss a target's
next-opening deadline; those targets remain missed. While full-scope preparation
is enabled, ordinary historical jobs yield their allowance on verified trading
days, including before the close; non-trading days can use remaining capacity.
One book's bounded preparation batch shares its already verified immutable reads
across collection guards. The first cold read occurs before an individual job's
execution timeout. Each provider entry still rereads mutable permission, lease
and calendar state; another book or the next batch verifies its Dataset cold.

This permission never enables target publication or paper settlement. Queued jobs
bind the configuration generation. Revocation is checked at provider entry, visible
daily/interval publication and job completion; queue and publication checks hold
the existing policy write lock. An already executing provider call may leave
immutable capture evidence, but cannot proceed to another request or visible
publication after revocation. Successful prior jobs may be reused offline without
granting their old generation new provider authority. Paused observations receive
data only when their separate paper-settlement permission remains enabled, to
value retained holdings. These inputs establish cross-source agreement, not
historical availability, total-return coverage or account authority.

Paper settlement requires a separate default-off opt-in on that observation;
enabling target publication alone grants no settlement permission. It runs the
same replay and append checks using verified local Datasets after the close,
including valuation of existing holdings when target publication is paused.
Its configuration generation and stop request are rechecked under the paper
write lock. It never requests providers or reconstructs unpublished targets.

An optional price-monitoring rule is frozen when starting an observation; it has
no default performance threshold. Measurement evaluates stable,
chronologically selected non-overlapping intervals before checking eligibility.
Missing, zero-exposure and known ex-date-confounded intervals keep their slots;
the evaluator cannot replace them with more favorable samples. The rule compares
the arithmetic mean of target-weighted raw-price changes minus the fully invested
equal-weight frozen universe with a configured threshold. Cash exposure affects
this comparison; it is not risk-adjusted alpha, total return or a significance test.
Provider-reported corporate-action evidence does not establish complete coverage.
Unresolved or missing matured evidence prevents performance action. An explicitly
configured pause commits the measured outcomes, bound decision, lifecycle change
and retry receipt atomically. Reads return the saved decision without recomputing;
old observations acquire no new rule. This scope cannot qualify or publish an
actual-account recommendation or reactivate a paused observation.

Selection feedback may use time-ordered validation and rolling OOS results.
Once those results guide later iterations they are validation evidence, not an
untouched final test. Final qualification requires an independent frozen holdout
or subsequent forward observation. The AI iteration inputs must exclude the
reserved final holdout. Baseline and candidate share cost, market, sizing and
timing rules. Minimum observation and performance thresholds are explicit policy,
not invented universal constants. Being best among today's candidates is not
evidence that a candidate passed admission.

Ordinary dual-MA parameter sweeps can explicitly select on a training prefix and
then evaluate the single chosen parameter set in a fresh test book. Normalized
parameters are deduplicated and ties use their canonical ordering. Test prices
never participate in ranking. The full immutable Dataset and its replay identity
remain unchanged; an explicit execution window records the actual metric dates.
Earlier bars warm the canonical crossover state and previous close only: orders,
positions, cash, costs and distribution eligibility do not carry into the test.
An already bullish warmup state does not manufacture an entry at the split.
Training and test reports retain the same cost and corporate-action assumptions,
plus the recorded choice and its provenance. This ordinary workflow is usable
without AI and remains exploratory validation, not sealed final qualification.

For the automated normalized-research path, explicit research and sealed end dates
freeze one validation-selected champion before the sealed interval starts. The
reservation binds the input snapshot, formula, baseline, costs, recorded trial
family and bounded simple/random challengers. The provider-free final evaluator
checks the frozen research prefix and
binds the observed holdout snapshot. Overlapping consumed/reserved intervals cannot
be reused to choose another champion; retries retain the original evaluation.
New qualification and publication read this persisted evidence. Existing research
results without it remain available as exploratory results.

The champion, baseline and challenger replays begin their sealed interval with
the same initial notional and empty positions. Earlier bars supply formula
history and the last known pre-sealed rule decision, without carrying research
cash, holdings, profits or costs. That last decision may execute only on a
strictly later sealed bar. Each replay uses the same frozen costs, participation
cap, universe and observed holdout snapshot. The final comparison requires
positive net excess over the strongest frozen comparator, without selecting a
replacement champion from the holdout. This counterfactual test does not prove
historical PIT availability or actual execution.

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

Legacy `strategy_promotion_states` with `stage=paper_shadow` identify an
account-recommendation publication, not an independent research simulation.
Preserve existing human-reviewed records and their validation. Policy-authorized
publication needs an explicit decision-source and grant/evidence binding in the
existing publication contract; a stage flag or nonempty actor name is never
sufficient. Do not reinterpret legacy records as a new grant or manufacture
human confirmation for automated decisions.

Historical qualification auto-switch records and static frontend PASS/champion
presentation did not implement this authority model. Historical automated approval
records without a bound publication grant remain inspectable but cannot acquire
authority retroactively. Exclude such sources from the usable publication set
without disabling valid unrelated sources; if none remain, report no applicable
source. Never rewrite immutable approvals or automatically revive retired
incumbents. A fresh applicable publication decision needs a real grant or human
review and freshly validated evidence; recovery of a qualification with an
existing immutable approval must not overwrite that approval.

Reuse the existing observation, paper book, policy storage, publication commands
and events. The account-plan paper runner is not an independent full-market
experiment. The existing fixed-basket observation cannot be relabeled as
full-market validation. New data composition and decision-source bindings belong
in these existing owners, with versioned persistence only where their actual
consumers require it. Delivery sequence and implementation gaps belong to
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
