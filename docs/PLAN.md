# Karkinos Plan

## Current focus

**Zero-manual-strategy automated research to forward simulation decision loop**

Deliver an end-to-end, reproducible pipeline where a user provides target constraints and risk boundaries—without writing code or inventing strategy formulas—to obtain candidates, forward paper simulation, and a definitive decision report on whether capital allocation is justified.

```text
Target / Risk Constraints
-> Built-in Baseline / Missing-Data Diagnosis
-> Automated Formula Research (Pre-registered Budget)
-> Frozen Candidate Selection (40-Stock Unified Panel)
-> Continuous Verified Observation & Data Prep
-> Multi-Tier Paper Settlement (Round-Lot & Cost Drag)
-> Decision-Ready Evidence (Preliminary Edge / Insufficient / No Edge)
```

## Four-step delivery sequence

1. **Zero-prior-knowledge research pipeline cold-start**:
   - Reuse existing Stock Formula Auto-Research -> Candidate Screening -> Independent Paper Book.
   - Remove the requirement for prior manual backtests: platform initializes with a built-in baseline on the research universe.
   - Clear diagnostic feedback when data or configuration is missing (market daily bars, trading calendar, or provider credentials) instead of dumping errors or expecting manual strategy construction.
   - Acceptance: From a clean workspace without user code or manual strategy definitions, produce an evidence-backed candidate report or an explicit "no qualified candidate" explanation.

2. **Bridge research-to-forward-simulation breakpoints**:
   - Unify universe boundaries: align observation automatic data preparation to admit up to 40 instruments (matching the 40-stock research universe panel), preventing silent dropping of candidate universe members.
   - Ensure strict 1:1 binding between candidate code, parameters, immutable dataset, cost assumptions, and paper book records. Missing data waits (fails closed); modifications create distinct versions.
   - Close minor remaining edges in cache invalidation, plan identity, and receipt association.
   - Acceptance: A frozen 40-stock candidate continuously receives verified daily data, publishes targets, and completes paper settlement; deterministic results across restarts, fail-closed on anomalies without false success.

3. **Answer 'Does automated research add value?' using existing verification**:
   - Reuse frozen candidates, future holdout intervals, simple & random challenge baselines, and independent paper books (no new validation framework).
   - Pre-register research scope, candidate count, model call / token budget, benchmark, fees, slippage, and round-lot (100-share) trading constraints before experiments start.
   - Log all trials and rejections to guard against backtesting / multiple-testing overfitting (Bailey et al.).
   - Evaluate across paper capital tiers (e.g. 50k, 100k, 500k RMB) to measure round-lot cash drag and concentration without risking real money.
   - Distinct acceptance gates: engineering workflow completion vs out-of-sample investment edge.

4. **Deliver a decision-ready homepage / overview**:
   - Clearly explain whether any candidate merits continued observation and why.
   - Net return after fees, alpha over simple benchmark (capped equal-weight buy & hold).
   - Max drawdown, longest underwater period, and explicit risks taken.
   - Thesis invalidation tracking: reasons for pause or retirement.
   - Incurred data and model expenses, plus remaining missing evidence.
   - Three canonical decision outcomes:
     * *Preliminary edge*: continue accumulating forward evidence, decide on small live validation.
     * *Insufficient evidence*: maintain paper observation, limit research budget.
     * *No edge across pre-registered cycles*: adjust methodology, narrow scope, or retain simple baseline; pause expansion.

## In scope

- Make data acquisition, normalization, PIT publication, freshness, revision handling, and replay reliable.
- Strengthen strategy research with reproducible datasets, realistic costs, out-of-sample evaluation, and robustness evidence.
- Deliver cross-sectional research and factor evaluation capabilities: curated multi-asset/ETF universes, cross-sectional ranking and transforms, factor IC/ICIR/quantile metrics, and cross-sectional ETF rotation strategies.
- Liberate Formula DSL operators (including rank and rolling percentile) to support relative strength without governance lock-in.
- Make Research -> Published Forecast -> Portfolio Target -> Risk Decision -> Rebalance Plan explicit and traceable end to end.
- Connect backtest, paper, and shadow outcomes to accounting, attribution, and Alpha / Model health without mixing financial books.
- Improve a small set of high-value local product journeys before adding new platform surface area.
- Keep core platform capabilities usable without AI providers or AI orchestration.
- Keep runtime, CI, promotion, and release behavior predictable; engineering machinery should remain smaller than the product value it protects.

## Research and simulation delivery sequence

Apply the authority and book boundaries in
[Architecture](ARCHITECTURE.md#research-simulation-and-account-publication) in this
order:

1. Keep normalized research admission independent of account qualification and
   pending human publication review. Preserve research policy, provider budgets,
   data validation and legacy account-bound admission. Extend the Formula DSL
   through bounded deterministic operators with explicit units and timing.
2. Build one useful forward-observation journey from a frozen research candidate
   to an independent paper book or target-only shadow observation. Reuse the
   existing simulation, market-rule, risk and accounting calculations. Persist the
   book identity and observation evidence needed for replay; add storage only
   where this real consumer requires it. Introduce separately authorized,
   deterministic simulation admission only with that journey. The existing
   normalized operation preview and account-plan paper runner are not substitutes.
3. Feed observation outcomes into deterministic Alpha health, then qualification
   and human account publication. Add automatic pause/retirement only with bound
   evidence and configured rules. Keep the existing account scan's evidence gates
   throughout migration; simulation admission alone never activates that scan.

Exact, clean exploratory Dataset snapshots can support normalized research
selection and simulation after replay checks. This admission preserves their
historical-availability and economic-return limitations; account publication
still requires its separate evidence. Ordinary, Formula and baseline research
use explicit cost and daily-volume participation assumptions. Default research
slippage is 5 bps and participation is 1%; adverse cost scenarios reuse the same
data and rules. These values are assumptions, not calibrated execution evidence.
New normalized candidate recommendations rank comparable complete 10/25 bps
cost-stress evidence first, then the worst net excess over their bound baseline,
before the existing research metrics. Missing evidence remains unknown; neither
completeness nor a winning rank is a profitability gate. Saved older rankings
retain their original identity and order.
The final normalized-research test freezes the champion, baseline and a bounded
simple/random challenger family before the future interval. They use fresh
equal-notional books, common data and costs; research-period wealth does not
carry into that comparison. Winning this experiment does not upgrade PIT or
account-publication evidence.

Independent target-only research observation supports explicit start, publish /
measure, and pause commands. It freezes a saved dual-MA, ETF-rotation or Formula
candidate, publishes only the latest closed session from a verified immutable Dataset, and
measures exact future price endpoints in a separate observation history. It
does not simulate fills or account returns. An optional rule frozen at start
monitors subsequent raw-price responses during explicit measurement, with a
configured minimum sample count and threshold. It can report a breach or pause
that observation; missing or unresolved evidence cannot trigger a performance
pause. Per-observation scheduling is an explicit opt-in that consumes local
verified Datasets within the next-opening publication deadline. Missing data waits;
target scheduling does not request providers or backfill missed targets. A separate,
default-off observation data-preparation opt-in lets the existing data worker
verify the frozen basket and append subsequent closed sessions to its original
immutable Dataset. It preserves original partitions, uses existing provider budgets,
and admits at most 40 instruments, appending at most 366 calendar days per batch
within the observation's frozen total row budget. Missing,
conflicting or incomplete sessions do not publish an interval. A new observation may explicitly bind a separate verified warmup Dataset with the
same typed universe, adequate history and latest closed session. This preserves the
original report and freezes a new forward experiment; it does not certify historical
inputs or continue the historical strategy state. Observations without a verified
immutable input prefix cannot use automatic preparation.
Normalized candidates and human qualification review
show observations from the exact source report as supplementary evidence. The
candidate view reuses the observation and paper controls so current net performance,
benchmark, costs and health are available at the research decision point. Raw
price responses do not replace independent final evaluation or change account
qualification. Human review may separately bind an exact simulated paper-book
version and interval; later settlement preserves that reviewed financial prefix.

An observation may separately start an independent stock/ETF paper book, with
its own initial cash, positions, modeled fills, costs and equity history. Explicit
settlement consumes only targets published after the book started, binds immutable
daily inputs and preserves previously settled results across restart and replay.
Reported stock distributions reuse the existing gross accounting model. ETF
books currently use explicit price-only returns because their distributions are
not verified; empty provider responses never prove complete coverage.
New stock distribution settlements require every bound report to have been
captured after the settlement session closed. Refreshing those reports creates
a new Dataset while preserving the frozen bar prefix and previous settlement
inputs; revisions that change settled financial results remain blocked.
The paper view derives net return, drawdown, fees, slippage, cash and position
contributions from its existing accounting. A frozen same-universe, capped
equal-weight buy-and-hold comparator uses the same cash, instruments and costs,
and starts at the first genuinely accepted target session. Waiting cash before
that session cannot manufacture relative performance. A separately configured
paper-health rule may report or pause acceptance of new paper targets; it does
not qualify or publish an account strategy. Pausing retains holdings for later
settlement. Paper settlement has its own default-off per-observation scheduling
opt-in, consumes verified local Datasets, and never backfills missing targets.
The target shadow health rule continues to measure raw-price responses.

Do not expand this work into live trading, broker adapters, capital authorization
or a general workflow framework.

The ordinary Dataset backtest also supports the bounded `risk_parity_macro`
research baseline. Complete aligned daily baskets and a converged risk-budget
calculation are required; capital-weight bounds may change risk contributions.
This strategy is not yet an independent forward-observation source. Small Python
research helpers provide explicitly timed, scoped financial-statement selection
and aligned benchmark-relative metrics; they do not publish PIT Datasets or
change account evaluation. The local order-export command projects existing
manual-order snapshots to review-only CSV, without generating orders or claiming
broker-format compatibility. Usage is in the [strategy library](strategies/README.md).

## Frozen

- new live-trading or broker integrations;
- automatic capital-authority infrastructure;
- autonomous AI trading;
- new AI orchestration frameworks;
- new acceptance or conformance frameworks;
- hosted accounts, cloud control planes, or cloud sync;
- unrelated product features;
- architecture-driven microservice or language rewrites.

Maintenance fixes remain allowed for user data, security, financial correctness, persisted compatibility, and currently supported behavior.

## Exit criteria

- Data -> PIT Dataset is reliable, observable, identifiable, and replayable.
- Research results bind reproducible data, assumptions, parameters, costs, and evaluation evidence.
- Published Forecast, Portfolio Target, Risk Decision, and Rebalance Plan have clear ownership and traceability.
- Backtest, paper, shadow, accounting, and attribution preserve distinct financial semantics while supporting useful comparison and feedback.
- Core product workflows work without AI orchestration.
- Local development and runtime behavior remain predictable.
- A small set of real product journeys passes reliably end to end.
- Tests and CI protect behavior and financial/research semantics rather than repository structure or project-management milestones.
