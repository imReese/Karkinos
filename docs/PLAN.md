# Karkinos Plan

## Current focus

**Deployment-scope research, full-portfolio validation and policy-authorized recommendations**

Deliver a reproducible decision loop where the user supplies objectives and risk
boundaries without writing strategies. The version evaluated must be the version
that runs: the same universe rule, forecast/portfolio decisions, financial
constraints and timing. Full-market recommendations require full-deployment-scope
evidence; a 40-stock research result cannot grant that authority.

The bounded first implementation now connects full declared-market discovery,
verified dated datasets, shared-capital formula decisions, reserved forward books,
independent final evaluation, current account qualification and policy publication.
The delivery sequence below remains the scope and design checklist; it does not
claim that a runtime experiment has matured or a strategy is profitable. Durable
semantics are owned by
[Architecture](ARCHITECTURE.md#deployment-scope-and-full-market-validation) and
presentation by [Product Design](../DESIGN.md#6-research).

```text
Objective / Risk Boundaries / Explicit Automation Grants
-> Declared Deployment Universe / Data Diagnosis / Executable Baseline
-> Bounded Research and Full-Scope Portfolio Validation
-> Frozen Candidate, Comparators and Final-Test Budget
-> Independent Full-Scope Final / Forward Evidence
-> Current Account Qualification
-> Policy-Authorized Recommendation Publication / Scoped Replacement
-> Health / Continue, Pause or Retire
```

## Current implementation and operating limits

New experiments use the full eligible declared market; the old 40-stock policy
remains available only to replay its frozen historical identity. Provider chunks
remain acquisition batches. Verified datasets compose complete daily shards and
bind real dated master observations. Missing market metadata, a rank-changing
member, source agreement or corporate-action evidence leaves the affected action
waiting or blocked instead of silently narrowing the market.

The initial deployable formula policy ranks simultaneous entries by observed
liquidity, allows four actual holdings, targets at most 25% per symbol and 97%
gross, and reserves complete fees/slippage from shared cash. Failed exits retain
their slots and capital. Hold sessions preserve actual share quantity; the 25%
cap sizes new entries. Replay, independent paper and recommendation adapters use
that same allocation. The grant's observed concentration bound is separate from
the target, allowing fees and price changes without redefining the formula.

An independent simulation authorization reserves a frozen future checkpoint,
hypothetical capital and research costs, starts an isolated book and coordinates
data/targets/settlement without requiring account publication authority. An
account-bound grant retains its actual capital and reviewed-fee constraints.
No overlapping AI iteration consumes the reserved interval. Final evaluation
requires actual timely targets and settled sessions, independently replays those
outcomes and compares the candidate with frozen executable alternatives. Default
statistical admission needs at least 60 observations at the configured checkpoint;
new grants/generations do not erase consumed related final-test budget. Replacement
also quotes reviewed fees and slippage for modeled exit/re-entry, rather than
assuming free switching. Unknown distribution tax or share-entitlement effects
block this first automatic path; provider-reported action coverage is shown as
such, not upgraded to an exchange-complete total-return claim.
Prospective dividend supply uses four all-market provider queries per calendar
day through the existing worker and call budget, from the cash book's start;
missing, truncated or conflicting evidence blocks settlement.
Cold warmup uses actual range captures per stock shard and retains per-session
dual-source verification. It does not repeat every historical request by day or
claim historical availability. Current forward jobs take priority over ordinary
backfills; budget deferrals expose their retry time without raising the limit.
External source unavailability defers the same task with bounded exponential
backoff; it does not exhaust the allowance for malformed or conflicting data.
Single-day collection uses up to 100 instruments per batch; historical ranges
remain bounded to 40. This keeps one complete declared-market input round within
the canonical daily attempt budget for the current market size, including
same-upstream dividend queries. A canonical attempt can contain several actual
SDK calls; this budget does not establish provider rate-limit compliance or a
next-opening completion guarantee. The initial historical warmup can span budget
days. Concurrent books share that capacity. Actual completion must be monitored;
network or provider failures can miss the next-opening deadline;
late data never repairs an already missed point-in-time observation.

Publication is default-off and affects account recommendations. Inside a current
standing grant, successful final evidence plus fresh account qualification can
publish without another candidate confirmation. Publication/replacement is atomic
and idempotent; revocation/expiry invalidates dependent sources at consumption.
Independent validation is controlled separately in the research policy. Its
evidence can support later account qualification only when the exact frozen
scope, portfolio and actual reviewed-cost replay are compatible; it cannot grant
account authority by itself.
Code, scope, fee or authorization changes invalidate the affected experiment.
A settlement retains the current verified dataset and one prior prefix at a time.
Identical immutable prefix references can reuse bars verified during that same
settlement, while reopening the original manifest, membership, time boundaries
and action captures; a different lineage takes the full reader path. This does
not create persistent trust in cached datasets or weaken cold verification.
Within one daily recommendation read, preparation, quote freezing, the persisted
scan and current-input checks share fully verified immutable Dataset reads.
Independent scans and the next daily read verify them cold again, while mutable
account, grant, fee, publication and risk state is rechecked before writing any task.
Actual account holdings that exceed its risk bounds block additional buys while
preserving exit maintenance. These changes create no broker execution authority.
Account entry-board constraints are frozen before ranking and shared by research,
all comparators, forward paper and recommendations while retaining full-market
data coverage. Permission loss blocks policy buys. Recommendation formulas use
their frozen forward seed's initialization boundary, not a mutable runtime date.

A local synthetic sizing run processed 5,000 symbols × 61 sessions (305,000 rows)
with the real shared-capital engine in about 75 seconds including preparation,
with roughly 614 MiB peak RSS. This measures one replay on this machine; a complete
research cycle includes additional stress/parameter/comparator replays and must
fit its existing provider admission window. New datasets retain explicit 2,000
session/20 million row budgets and surface over-budget input before capture.
These measurements and deterministic integration tests are engineering evidence;
actual dated forward observations still have to accrue in calendar time.

A separate offline synthetic Dataset exercise used 5,000 symbols × 240 sessions
(1.2 million rows in 30,000 dual-source shards), with real capture, revision,
reconciliation, verification and dated membership objects. A complete canonical
read took 194.312 seconds with 1,518.2 MiB peak RSS; a new call independently
revalidated the same Dataset in 170.294 seconds. Each full read decoded both
sources exactly once per shard (60,000 decodes). Reuse within the first call took
0.000683 seconds without additional decodes. The OS file cache was partly warm
after construction. This measures strict Dataset reading and request-local reuse
on this machine, not a complete daily recommendation or research-cycle SLA.

## Delivery sequence

1. **Restore truthful presentation and publication authority.**
   - Remove fixed Gen 1-5 histories, champion metrics, formulas, model guesses,
     PASS counts and fingerprints from the live UI. Use saved candidate lineage,
     gate results, actual books and publication decisions; missing evidence stays
     unknown.
   - Remove qualification's ungranted auto-publication and fabricated human
     confirmation. Preserve automatic qualification evaluation. Legacy automatic
     approvals without a standing grant remain audit history, not usable account
     authority; preserve valid unrelated sources and never revive retired sources
     automatically. Account automation returns no applicable source when needed.
   - Remove blanket retirement of every other paper_shadow source from both
     publication paths. Replacement must identify its authorized incumbent.

2. **Unify the deployable strategy and its daily decision behavior.**
   - Bind formula/parameters, as-of universe policy, feature/return basis, ranking,
     actual-book position semantics, total slots, allocation/cash policy, market
     constraints, costs and timing as one deployable version. Reuse existing
     candidate/source bindings rather than creating a parallel strategy registry.
   - Extract one session-level forecast/selection path and reuse Portfolio, Risk,
     simulation and accounting calculations. Research, final replay, forward paper
     and recommendation adapters must produce the same targets for the same
     session data, policy and book state. Target-only shadow remains a separately
     labeled diagnostic, not a substitute for fill-dependent portfolio validation.
   - Cover simultaneous entries, existing holdings, failed exits, partial fills,
     full allocation costs and restricted boards. A four-position limit includes
     existing positions; symbol traversal order cannot choose the portfolio.

3. **Support deployment-scope data and measure local cost.**
   - Remove 40 as a product-universe requirement. Keep provider batch limits and
     explicit resource budgets; prefer full-scope development after measuring
     runtime/memory. An optional fixed stratified panel is development-only.
   - Fix exchange-aware provider routing, including unsupported BSE source pairs.
     Declare exactly which market and account permissions are supported. Do not
     call a restricted or incompletely observed market full A-share coverage.
   - Extend the existing Dataset manifest/reader for dated membership and complete
     daily shard composition; preserve old manifests, captures, datasets and
     settled prefixes. Use existing jobs/object storage, stream/cache reusable
     features, and perform global selection and capital allocation only once.
     Replace the global fixed-row product bound with measured resource budgets
     for the new path; existing experiments retain their frozen bounds.
   - Record expected membership, known exclusions, missing evidence, actual
     evaluations and source coverage. Sync's existing 80%/90% thresholds remain
     operational diagnostics, not qualification. Maintain positions outside the
     new-buy universe; a missing rank-changing member blocks affected new targets.
   - Historical current-master replays stay exploratory. Begin collecting actual
     dated membership, availability and corporate-action inputs now, so lack of
     historical PIT does not prevent a new prospective experiment. Missing final
     economic-return evidence still blocks automatic account publication.

4. **Validate the full portfolio, then freeze an independent final experiment.**
   - Run candidate and baseline over the whole declared historical deployment
     universe with the canonical daily loop, shared capital, instrument-specific
     lots, liquidity, fees/taxes, distributions, risk and fill constraints.
     Inspect forward time splits and sector/size/liquidity/board attribution;
     cross-stock checks supplement rather than replace time separation.
   - Prefer the actual intended capital tier for qualification. Reuse the same
     target rules at additional capital tiers when needed to measure feasibility;
     never infer small-account behavior from normalized CNY 1m research alone.
   - Freeze an executable low-complexity primary comparator and a bounded
     simple/random family before final testing. A huge equal-weight index unable
     to buy lots at that capital is diagnostic only. All comparators share data,
     return basis, timing, risks and costs; compare the incumbent on the same
     future interval and include transition costs.
   - Keep five candidates per run as the present search-budget ceiling, not as
     strategy generations. Freeze the total cycle's calls, variants, spend and
     final checkpoints. Include linked prior panels and scope changes in its
     trial history instead of resetting multiplicity at a new universe tuple.
   - Reuse and extend final reservations/evaluation with deployment-scope and
     portfolio-code bindings. Once the champion is frozen, its final interval
     does not feed revisions or repeated candidate selection. The existing
     global holdout-exposure guard remains: overlapping model research keeps the
     frozen cutoff or waits, while capture, settlement and monitoring continue.
     Do not concurrently feed that interval's latest data to AI and expect its
     final test to remain sealed. Parallel current-market research needs explicit
     experiment isolation and testing-budget support before changing the guard.
     Use a genuinely future interval when the data have already been consumed.
   - Add a narrowly scoped net-excess uncertainty calculation in Analytics. The
     initial design uses paired portfolio returns with a preregistered block
     resampling method, block-length rule fixed from development data, and a
     fixed final decision checkpoint. The lower confidence bound must exceed
     the preregistered economically useful margin, alongside risk/cost rules.
     An initial grant may allocate a one-sided nominal 5% total error budget
     across a finite preregistered set of related final candidates, cycles and
     checkpoints, conservatively dividing it across the planned tests. A first
     release can allow one final cycle/checkpoint. New runs, samples or grant
     renewals do not reset consumed related tests. Record cumulative allocation;
     exhaustion stops new automatic admission under that budget. Block resampling
     assumptions and finite-sample limitations stay visible; insufficient
     observations for the method return insufficient evidence.
     This is a policy choice, not a guarantee or a universal horizon threshold.
   - Retain DSR/PBO as diagnostics with their stated assumptions; improve aligned
     trial-return inputs where justified. Do not treat the current research-period
     DSR flag or a short positive final excess as sufficient automatic admission.

5. **Run a continuous, independent full-scope forward experiment.**
   - A preregistered forward interval can itself supply final evidence, bound to
     the exact book version, outcomes and scope. Do not require two successive
     waiting periods merely to label the same valid future evidence twice.
   - Reuse observation/book/automation owners with the extended scope and shared
     decision path. Freeze inputs and create the book before accepting targets;
     configure data preparation, targets and settlement together, with individual
     revocation and safe retry after partial startup failure.
   - Daily membership may evolve only under the frozen rule and real availability
     cutoffs. Preserve source/cost/code versions and settled prefixes; changes
     that alter decisions create a new applicable experiment rather than rewriting
     the old one. Preserve legacy fixed-basket observations as fixed-basket.
   - Separate continuous operational monitoring from final statistical decisions.
     Monitor target gaps, last settlement, net returns/excess, costs, drawdown,
     cash, concentration, capacity and thesis invalidation. Keep candidate and
     comparator books isolated and on comparable intervals.

6. **Enable bounded automatic publication and scoped replacement.**
   - The user may explicitly enable automatic simulation and, separately,
     automatic account-recommendation publication. Reuse policy storage and
     publication events; bind allowed scope, risk/capital/resource limits,
     full-scope evidence, statistical method/checkpoints, replacement rules,
     expiry and revocation. No per-candidate human confirmation is required
     inside that grant. Simulation-only evidence cannot activate the account scan.
   - Immediately before publication, revalidate the active grant, frozen strategy,
     scope-matched final evidence, current account qualification and expected
     incumbent. Commit an idempotent policy-sourced decision and only the
     designated replacement atomically. Do not populate human-review fields.
     Daily consumption also verifies publication and grant validity. Grant expiry
     or revocation suspends dependent sources; pausing only future automatic
     admission/replacement may retain a valid incumbent under its active grant.
     Expose these as distinct controls and preserve valuation/exit maintenance.
   - Require net improvement after switching costs and policy risk bounds before
     replacement; apply a frozen minimum improvement and cooldown. Insufficient
     evidence keeps a healthy incumbent. An unhealthy incumbent can be paused
     without forcing admission of an unqualified replacement. Continue valuation
     and exit planning; no health or publication event creates a real trade.
   - Show preliminary edge, insufficient evidence or no edge, with actual coverage,
     tested scope, last target/settlement, capital/cost assumptions and the real
     automation decision source. A completed scan or running worker is not edge.

## Verification for this delivery

Use the commands and layers in [Engineering](ENGINEERING.md#4-tests-ci-promotion-and-governance).
The highest-value checks are identical targets across replay/forward/recommendation
adapters given identical inputs; dynamic membership and no future leakage; shard
composition invariant to order; shared-cash and failed-fill behavior; final-window
isolation across linked research trials; insufficient-evidence and multiplicity
handling; automatic publication only under an active exact-scope grant; scoped
atomic replacement, restart/retry and revocation; and preservation of legacy
datasets, books and approvals. Validate the real candidate-to-forward-to-publication
journey with deterministic fixtures, then measure real local full-market workloads.
No fixed runtime or investment-performance target is claimed before measurement.

## In scope

- Make data acquisition, normalization, PIT publication, freshness, revision handling, and replay reliable.
- Strengthen strategy research with reproducible datasets, realistic costs, out-of-sample evaluation, and robustness evidence.
- Deliver cross-sectional research and factor evaluation capabilities: curated multi-asset/ETF universes, cross-sectional ranking and transforms, factor IC/ICIR/quantile metrics, and cross-sectional ETF rotation strategies.
- Liberate Formula DSL operators (including rank and rolling percentile) to support relative strength without governance lock-in.
- Make Research -> Published Forecast -> Portfolio Target -> Risk Decision -> Rebalance Plan explicit and traceable end to end.
- Connect backtest, paper, and shadow outcomes to accounting, attribution, and Alpha / Model health without mixing financial books.
- Improve a small set of high-value local product journeys before adding new platform surface area.
- Keep core platform capabilities usable without AI providers or AI orchestration.
- Support explicitly authorized automatic account-recommendation publication and scoped replacement after full-deployment-scope evidence; this does not authorize capital execution.
- Keep runtime, CI, promotion, and release behavior predictable; engineering machinery should remain smaller than the product value it protects.

## Existing capabilities and limits

The following describes the retained exploratory and legacy paths. The
deployment-scope path above adds separate validation and standing-policy account
publication; it does not upgrade evidence from these older paths.

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
and, for the legacy fixed-basket path, admits at most 40 instruments, appending at
most 366 calendar days per batch within the observation's frozen total row budget. Missing,
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
- The exact deployable universe, decision/portfolio rules and timing are validated before automatic recommendation publication; sampled evidence never silently broadens authority.
- Automatic decisions bind a real, active grant and preserve their policy source; existing records never become fabricated human approval or retroactive authorization.
- Tests and CI protect behavior and financial/research semantics rather than repository structure or project-management milestones.
