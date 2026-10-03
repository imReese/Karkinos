# Karkinos Plan

## Current focus

**Evidence-bound research and portfolio decision loop**

The engineering reset is complete. Further cleanup is maintenance, not a separate product track.

```text
Market Data
-> PIT Dataset
-> Research / Evaluation
-> Published Forecast
-> Portfolio Target
-> Risk Decision
-> Rebalance Plan
-> Simulation / Shadow
-> Accounting / Attribution
-> Evidence / Feedback
```

## In scope

- Make data acquisition, normalization, PIT publication, freshness, revision handling, and replay reliable.
- Strengthen strategy research with reproducible datasets, realistic costs, out-of-sample evaluation, and robustness evidence.
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

Independent target-only research observation supports explicit start, publish /
measure, and pause commands. It freezes a saved dual-MA or Formula candidate,
publishes only the latest closed session from a verified immutable Dataset, and
measures exact future price endpoints in a separate observation history. It
does not simulate fills or account returns. An optional rule frozen at start
monitors subsequent raw-price responses during explicit measurement, with a
configured minimum sample count and threshold. It can report a breach or pause
that observation; missing or unresolved evidence cannot trigger a performance
pause. Automatic observation scheduling and the subsequent qualification linkage
remain delivery work. Do not expand this work into live trading, broker adapters,
capital authorization or a general workflow framework.

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
