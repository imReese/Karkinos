# Karkinos Product Design

This document defines the long-term product model, information architecture, interaction hierarchy, financial semantics, and UI invariants of Karkinos.

It is intentionally not a record of individual visual audits, component tokens, page-specific redesigns, implementation cleanup, or one-off UI issues. Those belong in code, issues, and pull requests.

The purpose of this document is to define how Karkinos should present investment state, research evidence, financial state, risk, and user authority consistently across the product.

---

## 1. Product Model

Karkinos is organized around a closed investment workflow spanning quantitative research, portfolio management, risk control, execution planning, and outcome evaluation.

The product is not designed around a brokerage account homepage, and it is not an AI-first chat interface.

Its core surfaces must allow the user to answer:

1. What is the current portfolio state and performance?
2. As of when is the underlying data valid, and is the current valuation usable?
3. What research results and Published Forecasts are currently available?
4. How does the Portfolio Target differ from the Current Financial Book?
5. Does Risk allow the current plan to proceed?
6. Why do Backtest, Paper, or Shadow outcomes differ from research expectations?
7. Is there anything the user can or should act on now?

The interface should optimize for answering these questions, not for exposing every subsystem or internal state.

---

## 2. Core Investment Flow

The primary investment lifecycle is:

```text
Experiment
    ↓
Research Evidence
    ↓
Published Forecast
    ↓
Portfolio Target
    ↓
Risk Decision
    ↓
Rebalance Plan
    ↓
Paper / Shadow
    ↓
Attribution / Alpha Health
```

Each stage represents a distinct object or decision boundary.

Downstream state must remain traceable to the upstream evidence and decisions that produced it.

A later stage must not silently rewrite the meaning or identity of an earlier stage.

In particular:

- an Experiment is not a Published Forecast;
- a Forecast is not a Portfolio Target;
- a Portfolio Target is not an approved Rebalance Plan;
- a Rebalance Plan is not execution authority;
- successful Paper or Shadow evaluation does not grant financial authority.

---

## 3. Information Architecture

The target navigation follows the investment workflow rather than backend module boundaries.

```text
Overview

Data
  Health
  Datasets

Research
  Experiments
  Forecasts
  Backtests

Portfolio
  Current Book
  Targets
  Rebalance
  Risk

Evaluate
  Paper / Shadow
  Attribution
  Alpha Health

System
  Operations
  Settings
```

Backtests belong to Research because they are part of the historical evidence used to evaluate an Experiment.

Evaluate is reserved for forward-time or realized outcome evaluation.

Real trading capability, if introduced, must integrate with the existing Portfolio, Risk, Execution, and Accounting boundaries. It must not become the organizing center of the product.

---

## 4. Overview

Overview is an investment-state summary, not a system monitoring dashboard.

### Primary information

```text
Portfolio value
Cumulative P&L
Latest trading-session P&L
Available cash
Portfolio performance
Current holdings
User attention
Valuation usability
```

### Secondary information

```text
Realized / unrealized P&L
Strategy status
Risk summary
Recent activity
Data details
```

The default information hierarchy is:

```text
Portfolio summary
Performance
Holdings
Attention / data status
```

### Invariants

- Total portfolio value is the highest-priority financial figure.
- Performance is the primary chart on the page.
- Holdings are the second major content area.
- Healthy data state should normally be represented by a compact summary.
- Only conditions that materially affect valuation or require user action should become primary warnings.
- System health, refresh attempts, fingerprints, internal state-machine fields, and similar technical evidence belong in Data Details or Operations.
- When there is no user action to take, the product must show an explicit empty state rather than filling the Attention area with system information.
- Overview must not duplicate the full Portfolio, Risk, Data, or Operations workspaces.

Overview should answer:

> What do I own, how is it performing, can I trust the current valuation, and is there anything I need to do?

---

## 5. Data

Data surfaces determine whether available information is suitable for valuation, research, and investment decisions.

Core evidence includes:

```text
as_of
source / identity
coverage
freshness
quality
revision
point-in-time availability
blocker
safe next action
```

Provider-specific request details, retry history, transport errors, and low-level execution logs belong in detailed or operational views by default.

A data source being reachable does not imply that its data is sufficiently fresh, complete, authoritative, or appropriate for a particular decision.

The UI must communicate the decision-relevant state rather than merely exposing infrastructure health.

---

## 6. Research

Research is centered on Experiments and evidence.

The core research model is:

```text
Dataset
Feature / Alpha / Model identity
Parameters
Evaluation
Research Evidence
Published Forecast
```

### Invariants

- Candidate Experiments and Published Forecasts must be visually and semantically distinct.
- AI may assist with research ideation, experiment creation, analysis, and explanation, but it receives no additional financial authority.
- Research results must remain traceable to their Dataset, parameters, model or alpha identity, and Evaluation.
- Historical performance must clearly distinguish in-sample and out-of-sample evidence where applicable.
- After-cost diagnostics must be treated as first-class research evidence.
- Charts consume platform-produced research artifacts and canonical metrics rather than independently recomputing them in the browser.
- Promotion, quarantine, retirement, and other lifecycle states must not erase underlying experiment lineage.

A polished chart is not evidence by itself. The product should make the provenance and quality of the underlying evidence inspectable.

---

## 7. Portfolio

Portfolio management must preserve the distinction between:

```text
Published Forecast
Current Financial Book
Portfolio Target
Risk Decision
Rebalance Plan
```

A **Financial Book** is the canonical accounting boundary for cash, positions, fees, P&L, and valuation within a single execution environment.

Examples of separate environments may include actual, paper, shadow, or other explicitly modeled books.

### Invariants

- A Portfolio Target must be traceable to the Published Forecast, Portfolio Policy, risk exposures, constraints, and cost assumptions that produced it.
- A Risk block must never be hidden, silently overridden, or converted into a Target of unclear provenance.
- Current holdings should normally be presented as comparable tabular records rather than isolated cards.
- Market value, position size, P&L, returns, pricing state, and related financial metrics must use consistent semantics throughout the product.
- Complex portfolio optimization should remain comparable with an appropriate simple baseline.
- The UI must not present an optimizer result as self-evidently correct merely because it is mathematically optimal under one model.

Portfolio is where research intent becomes an explicit financial proposal. It is not where evidence, risk, and accounting boundaries should collapse into one object.

---

## 8. Evaluate

Evaluate covers forward-time and realized outcome analysis.

```text
Paper         Forward-time simulated execution
Shadow        Observation of target / plan outcomes
Attribution   Outcome decomposition
Alpha Health  Evidence persistence or decay
```

Backtest remains part of Research because it is historical simulation evidence.

Outcome evaluation must remain traceable to:

```text
Dataset
Experiment
Published Forecast
Portfolio Target
Risk Decision
Rebalance Plan
```

Evaluation should help explain not only whether an outcome was good or bad, but why it differed from expectation.

Where relevant, the product should distinguish effects attributable to:

```text
Market movement
Factor / exposure drift
Alpha decay
Portfolio construction
Execution cost
Slippage
Tradability constraints
Partial or missing fills
Residual / unexplained effects
```

A loss or underperformance event should be drillable into these contributing layers rather than presented as a single unexplained number.

---

## 9. Financial State

Cash, positions, fees, P&L, and valuation must come from an explicit Financial Book.

### Invariants

- Backtest, Paper, Shadow, and actual account state must never be presented as one account.
- When comparing environments, the relevant book or environment identity must remain visible.
- Canonical financial metrics must not be redefined independently in frontend code.
- When a financial metric lacks a reliable accounting basis, the product should show it as unavailable rather than infer an approximate value and present it as canonical.
- Derived values must remain distinguishable from directly accounted values where that distinction is material.
- Financial identities and cutoffs must survive navigation between surfaces.

Accounting ambiguity must fail closed.

---

## 10. Market, Pricing, and Status Semantics

The following concepts must remain independent:

```text
market_session
pricing_kind
pricing_as_of
pricing_authority
valuation_usability
refresh_health
decision_readiness
user_attention
```

### Market semantics

- Market-session state must be derived from the relevant trading calendar rather than approximated from wall-clock age.
- A closed market with valid data from the latest completed trading session may represent a healthy valuation state.
- Cache describes storage or retrieval origin; it does not imply freshness.
- A failed refresh attempt does not automatically invalidate a previously published valuation that remains valid for its intended use.
- Valuation usability and decision readiness are separate concepts.
- System-only state does not automatically become user attention.
- Missing, conflicting, non-authoritative, or otherwise unsafe data must remain fail-closed.

### Pricing semantics

```text
Stock          Realtime quote / session close
ETF            Exchange quote / session close
Open-end fund  Published NAV / estimated NAV
Manual mark    Explicit manual valuation
```

An open-end fund must not describe a Published NAV as a realtime market quote.

Likewise, estimated values must remain distinguishable from published or authoritative values.

The UI should describe the economic meaning of a price, not merely the API field from which it originated.

---

## 11. Status and Evidence

Summary state should prioritize:

```text
what
as_of
usable or blocked
safe next action
```

Detailed evidence may include:

```text
snapshot identity
ledger cutoff
source identity
fingerprint
refresh history
blocker detail
```

### Invariants

- Each concept should have one primary user-visible status.
- Healthy state should not require large success banners.
- Warning and danger states must correspond to real user or financial impact.
- Status must never depend on color alone.
- Technical evidence should normally be accessible through progressive disclosure, drawers, or detailed views.
- Full fingerprints and low-level identities should not dominate primary views when a human-readable summary is sufficient.

Evidence should be available without turning every surface into an audit console.

---

## 12. User Attention

Only items that the user can or should act on now belong in the Attention Queue.

### Appropriate attention items

```text
Manual confirmation
Risk review
Actionable data repair
Ledger reconciliation
Strategy / forecast review
```

### Items that do not belong in Attention by default

```text
Healthy subsystem status
Zero counters
Broker disabled
Paper / Shadow inactive
Internal audit guarantees
Non-actionable refresh failures
Expected external publication wait
```

If multiple downstream blockers share one root cause, they should normally be consolidated into one actionable user item.

For example, a single missing pricing input should not produce separate top-level warnings for valuation, target generation, risk, rebalance, and decision readiness if the user can resolve all of them through the same underlying action.

Attention represents actionable work, not system verbosity.

---

## 13. Interaction Hierarchy

Product actions belong to distinct authority levels:

```text
read / query
refresh / ingestion
research mutation
portfolio proposal
financial mutation
authority mutation
```

These levels must remain visibly and behaviorally distinct.

### Read / query

Read-only interaction.

No confirmation is required and no side effect should occur.

### Refresh / ingestion

Explicitly requests new or updated data.

The UI should expose execution state and resulting data status.

### Research mutation

Creates or modifies research artifacts such as Experiments.

It does not directly alter financial state.

### Portfolio proposal

Creates or modifies a proposed Target or Rebalance Plan.

It represents financial intent but does not by itself imply financial execution.

### Financial mutation

Changes canonical financial state.

Such actions require explicit preview, confirmation, and auditability.

### Authority mutation

Changes the system's permission to perform financially consequential actions.

Authority changes require an independent, high-friction confirmation boundary and must make scope and expiry visible where applicable.

Controls with materially different authority or side effects must not be presented as equivalent actions merely because they can share a visual component.

Research evidence, AI output, a successful backtest, or successful Paper / Shadow evaluation must never be presented as if it automatically grants execution authority.

---

## 14. Visual System

Karkinos continues to use Catppuccin Latte and Mocha as its visual foundation.

The interface should feel restrained, native, information-dense, and appropriate for a professional financial application.

Visual treatment exists to reinforce information hierarchy and meaning rather than to create decoration.

### Layout

- Prefer a continuous content canvas over a wall of equally weighted cards.
- Desktop layouts should generally favor a dominant primary content area, with a compact secondary rail where supporting status or attention information is useful.
- Portfolio summary, Performance, and Holdings should receive primary visual space on investment-focused surfaces.
- Secondary rails should contain compact Attention, Data Status, or other genuinely supporting information.
- Use spacing, alignment, typography, and dividers as the primary hierarchy tools.
- Avoid unnecessary nested containers and card-in-card layouts.
- Layout choices may vary by workspace when the underlying task requires a wide table, chart, comparison surface, or research environment.

### Typography

- Portfolio value and other primary financial figures receive the highest numerical hierarchy.
- Financial numbers use tabular numerals.
- Heading hierarchy should remain stable and utilitarian rather than promotional.
- Time, code, identities, and other technical metadata should use compact, scannable presentation where appropriate.

### Color

- Catppuccin surface colors provide the primary background hierarchy.
- Mauve should remain a restrained primary accent for selection, emphasis, and key chart elements rather than becoming a decorative fill.
- P&L colors must use one consistent positive / negative semantic system.
- Warning and danger colors are reserved for conditions with actual significance.
- Avoid decorative glow, large gradients, and high-saturation background treatments.

### Components

Use components according to the information they represent:

```text
table                Comparable records and holdings
chart                Time, return, risk, or distribution relationships
timeline             Ordered events
card                 Independent object, action, or bounded supporting module
badge                Short status
disclosure / drawer  Technical evidence and detailed state
```

Do not add decorative components merely to fill space.

In particular, avoid:

```text
Decorative sparklines
Decorative donut charts
Marketing quotes
Motivational slogans
Redundant KPI cards
System-health filler
```

The product should look complete because its information hierarchy is coherent, not because every empty area contains another visualization.

---

## 15. Responsive Behavior

Desktop should retain readable text navigation and comparison-friendly tables where appropriate.

On mobile:

- reorder content according to task priority rather than mechanically stacking the desktop layout;
- prioritize Portfolio Summary, Performance, and Attention in the first viewport;
- present Holdings as a scannable list or compact horizontal table;
- collapse technical evidence by default;
- preserve the same financial, pricing, status, and authority semantics as desktop.

Responsive design may change layout, but it must not change the meaning of financial state.

---

## 16. Performance and Consistency

- Pages should primarily consume persisted canonical or derived state.
- Ordinary reads must not implicitly trigger external providers, AI calls, or financially meaningful side effects.
- The same financial or research concept must use consistent identity, formatting, and status semantics across surfaces.
- Failure of one widget must not erase otherwise usable workspace state.
- Large datasets should use pagination, virtualization, or server-side querying as appropriate.
- Overview must not reimplement domain state machines in React.
- Research charts must consume published artifacts or canonical platform outputs rather than independently recreating authoritative metrics in the browser.
- Presentation-layer convenience must never weaken fail-closed behavior in trading, risk, accounting, or authority paths.
- When one canonical value appears in multiple places, its meaning, formatter, as-of semantics, and status interpretation must remain consistent.

---

## 17. Design Change Rules

This document should change only when the long-term product model, information architecture, interaction hierarchy, financial semantics, authority boundaries, status language, or major visual invariants change.

The following do not belong in this document:

```text
Component token changes
Page-specific pixel adjustments
One-off visual audit findings
Screenshot diffs
Cleanup counts
Temporary migration details
Implementation checklists
Individual bug fixes
```

Those belong in code, issues, pull requests, implementation plans, or focused design notes.

`design.md` is the product-level contract.

It should remain stable enough that developers, contributors, and coding agents can use it to answer:

> Does this implementation reinforce the intended Karkinos product model, or does it accidentally turn the system into something else?
