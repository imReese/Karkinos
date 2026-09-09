# Karkinos Goal

This document defines the long-term product goal and hard boundaries of
Karkinos.

Durable system design belongs to [ARCHITECTURE.md](ARCHITECTURE.md). Current
development scope belongs to [PLAN.md](PLAN.md). This document should change
rarely.

## Product

Karkinos is a **local-first quantitative research and investing platform for
the China market**.

Its purpose is to help the user discover, validate, combine, deploy, monitor,
and retire investment edge with enough rigor that research can support real
capital decisions.

Karkinos is not judged by lines of code, number of strategies, test count,
infrastructure sophistication, AI features, or broker integrations.

Its value comes from answering a harder question well:

> Given the information that was actually available at the time, does this
> investment idea produce robust value after realistic costs and constraints,
> and how should that evidence affect the portfolio today?

Karkinos does not promise investment returns. It exists to make investment
reasoning more disciplined, reproducible, and falsifiable.

## Core loop

The long-term product loop is:

```text
Market Data
-> Point-in-time Dataset
-> Research
-> Forecast
-> Portfolio Target
-> Rebalance Plan
-> Risk
-> Simulation / Paper / Shadow
-> Human-supervised Action
-> Accounting / Reconciliation
-> Attribution
-> Edge Monitoring / Retirement
```

The center of the product is the loop from **data to evidence to portfolio
decision**, not automated trading.

Research should make it cheap to propose an idea, test it honestly, compare it
with alternatives, understand why it works or fails, and discard it when the
evidence is weak.

## Product priorities

When priorities conflict, Karkinos prefers:

1. **Edge quality**
   Evidence must survive point-in-time evaluation, out-of-sample testing,
   realistic costs, and relevant market constraints.

2. **Reproducibility**
   A meaningful result should be traceable to the data, assumptions, parameters,
   and implementation that produced it.

3. **Financial correctness**
   Portfolio state, costs, positions, orders, fills, valuation, and accounting
   must have unambiguous financial meaning.

4. **Capital safety**
   Real-money actions remain bounded, explicit, observable, and
   human-supervised by default.

5. **Operator clarity**
   The user should be able to understand what the system knows, what it is
   uncertain about, why an action is suggested or blocked, and what changed.

6. **Engineering simplicity**
   Complexity is justified only when it improves research quality, financial
   correctness, reliability, safety, or meaningful product capability.

## Research standard

Karkinos should make weak research difficult to mistake for strong research.

Core research must respect:

* point-in-time information availability;
* historical universe membership and China-market trading constraints;
* reproducible data and experiment identity;
* out-of-sample evaluation;
* realistic fees, taxes, turnover, liquidity, and execution assumptions where
  they materially affect results;
* comparison against simple baselines;
* explicit limitations and uncertainty.

Alpha, models, scores, rankings, probabilities, or expected returns express
investment views. They are not automatically BUY or SELL commands.

A strategy abstraction must not become the center of the product if it hides
the distinction between research evidence, portfolio construction, risk, and
execution.

## Local-first boundary

The core Karkinos workflow must not depend on a hosted account or cloud control
plane.

Core user state, research artifacts, portfolio state, and primary calculations
are owned locally by default.

External services may provide data, models, notifications, remote computation,
backup, synchronization, or other optional capabilities, but using such
services must not silently transfer authority over the core workflow.

Local-first does not mean offline-only. It means the local product remains the
owner of its core state and decisions.

## AI boundary

AI can assist with:

* hypothesis generation;
* research exploration;
* experiment design;
* explanation and critique;
* workflow assistance.

AI does not become the authority for canonical market facts, quantitative
metrics, portfolio state, financial accounting, risk results, or capital
permission.

Canonical quantitative and financial results must remain reproducible by
deterministic application code.

AI may help the user reason about a decision. It does not receive independent
authority to make that decision real.

## Capital and execution boundary

Real-money automation is not the default product mode.

Live-like workflows are human-supervised unless the user explicitly adopts a
more permissive mode supported by deliberate safety boundaries.

Karkinos must not:

* allow research or AI code to grant itself capital authority;
* allow strategies to bypass portfolio, risk, or execution boundaries;
* store broker passwords as part of the normal product model;
* treat a broker connection as proof that an investment process is sound;
* expand capital authority implicitly because a previous action succeeded.

Broker integration is an outer capability, not the product center.

## Success

Karkinos succeeds when it materially improves the quality of the user's
investment process.

A mature Karkinos should make it possible to:

* reconstruct why a research result existed;
* distinguish genuine predictive evidence from leakage, overfitting, and cost
  illusion;
* compare competing Alpha, model, and portfolio approaches on consistent
  evidence;
* understand how forecasts become portfolio decisions;
* explain the contribution of Alpha, portfolio construction, risk, turnover,
  costs, and execution to realized outcomes;
* detect when an edge is weakening or no longer justified;
* reduce, isolate, or retire weak research rather than preserving it because it
  once performed well;
* move from research to simulated or real decisions without changing the
  financial meaning of the system;
* keep real-capital actions understandable, bounded, and reversible where the
  external system permits.

The product should become more useful as evidence accumulates, not merely more
complex.

## Non-goals

Karkinos is not intended to be:

* an investment-advice or guaranteed-return product;
* a high-frequency or exchange-grade low-latency trading system;
* an unattended full-account autonomous trading bot;
* an institutional multi-account OMS in the near term;
* a strategy marketplace or social trading network;
* a generic broker terminal;
* an AI agent platform disguised as a quantitative product;
* a cloud platform that requires hosted identity to access the core workflow;
* a showcase for microservices, distributed systems, language rewrites, or
  architecture patterns without demonstrated product need.

Features are successful only when they strengthen the path from trustworthy
data to trustworthy investment decisions.
