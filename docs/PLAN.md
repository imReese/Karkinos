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
