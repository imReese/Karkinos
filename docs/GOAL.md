# Karkinos Goal

## Product

Karkinos is a **local-first quantitative research and investing platform for the China market**.

Primary objective:

> Discover, validate, combine, deploy, monitor, and retire investment edge with enough rigor to support real capital decisions.

Core question:

> Given the information available at the time, does this investment idea produce robust value after realistic costs and constraints, and how should that evidence affect the portfolio today?

## Core loop

```text
Market Data
-> Point-in-time Dataset
-> Research
-> Published Forecast
-> Portfolio Target
-> Risk Decision
-> Rebalance Plan
-> Simulation / Paper / Shadow
-> Accounting / Outcomes
-> Attribution / Alpha Health
-> Research
```

## Product priorities

| Priority | Requirement |
| --- | --- |
| **Edge quality** | PIT evaluation, OOS validation, realistic costs, relevant market constraints |
| **Reproducibility** | Traceable data, assumptions, parameters, code/model, and time boundaries |
| **Financial correctness** | Unambiguous positions, costs, orders, fills, valuation, and accounting |
| **Capital safety** | Explicit, bounded, observable, human-supervised real-money actions |
| **Operator clarity** | Visible state, uncertainty, blockers, and reasons for actions |
| **Engineering simplicity** | Complexity only when it improves product capability, correctness, reliability, or safety |

## Research standard

Core research requires:

- point-in-time information availability;
- historical universe membership and China-market trading constraints;
- reproducible dataset and experiment identity;
- out-of-sample evaluation;
- realistic fees, taxes, turnover, liquidity, and execution assumptions when material;
- comparison against simple baselines;
- explicit uncertainty and limitations.

Alpha, models, scores, rankings, probabilities, and expected returns are investment views, not orders.

## Boundaries

| Area | Boundary |
| --- | --- |
| **Local-first** | Core user state, research artifacts, portfolio state, financial state, and primary calculations remain locally owned by default |
| **External services** | May provide data, models, notifications, remote computation, backup, or sync; they do not become core authority |
| **AI** | May generate hypotheses, run research workflows, critique evidence, and assist the user; it does not own canonical facts, metrics, portfolio state, accounting, risk results, or capital authority |
| **Capital** | Real-money automation is not the default mode; authority is explicit and human-supervised |
| **Broker integration** | Outer capability, not the product center |

Karkinos must not:

- allow research or AI code to grant itself capital authority;
- allow strategy code to bypass Portfolio, Risk, Execution, or Accounting boundaries;
- store broker passwords as part of the normal product model;
- treat broker connectivity as evidence of investment quality;
- expand capital authority implicitly from prior success.

## Success

A mature Karkinos can:

- reconstruct why a research result existed;
- distinguish predictive evidence from leakage, overfitting, and cost illusion;
- compare Alpha, model, and portfolio approaches on consistent evidence;
- trace Forecast -> Portfolio -> Risk -> Rebalance decisions;
- explain contributions from Alpha, portfolio construction, risk, turnover, costs, and execution;
- detect weakening edge;
- reduce, isolate, or retire weak research;
- preserve financial meaning across research, simulation, paper, shadow, and real decisions;
- keep real-capital actions bounded and understandable.

## Non-goals

Karkinos is not:

- an investment-advice or guaranteed-return product;
- a high-frequency or exchange-grade low-latency trading system;
- an unattended full-account autonomous trading bot;
- an institutional multi-account OMS in the near term;
- a strategy marketplace or social trading network;
- a generic broker terminal;
- an AI agent platform disguised as a quantitative product;
- a cloud platform that requires hosted identity for the core workflow;
- a showcase for microservices, distributed systems, language rewrites, or architecture patterns without demonstrated product need.
