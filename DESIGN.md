# Karkinos Product Design

This document defines the long-term product model, information architecture,
financial semantics, interaction hierarchy, authority boundaries, and UI
invariants of Karkinos.

It does not define page-specific implementation plans, visual audits, component
tokens, temporary migrations, or individual fixes.

---

## 1. Product Model

Karkinos is a personal quantitative-investment platform organized around:

```text
Research
Portfolio
Risk
Execution Planning
Evaluation
Financial State
````

The product is not organized around:

```text
broker integration
AI chat
backend modules
system diagnostics
```

Core product surfaces must answer:

1. What is the current portfolio state and performance?
2. As of when is the underlying data valid?
3. Is the current valuation usable?
4. What research evidence and Published Forecasts exist?
5. How does the Portfolio Target differ from the Current Financial Book?
6. Does Risk allow the current plan to proceed?
7. Why did observed outcomes differ from research expectations?
8. Is there anything the user can or should act on now?

---

## 2. Core Investment Flow

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

Each stage is a distinct object and authority boundary.

Invariants:

* Experiment is not Published Forecast.
* Published Forecast is not Portfolio Target.
* Portfolio Target is not Risk approval.
* Risk approval is not Rebalance Plan.
* Rebalance Plan is not execution authority.
* Paper / Shadow success does not grant financial authority.
* Downstream state must remain traceable to upstream evidence.
* A downstream stage must not silently rewrite upstream identity or meaning.

---

## 3. Information Architecture

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

Rules:

* Backtests belong to Research.
* Forward-time and realized outcome analysis belongs to Evaluate.
* Operations contains system and workflow diagnostics.
* Real trading capability, if introduced, integrates with Portfolio, Risk,
  Execution, and Accounting boundaries.
* Broker capability must not become the organizing center of the product.

---

## 4. Overview

Overview is the primary investment-state summary.

It is not a system-monitoring dashboard.

Overview answers:

```text
What do I own?
What is it worth?
How is it performing?
What changed in the relevant market session?
Can I trust the current valuation?
What requires my attention?
```

### 4.1 Primary Information

```text
Portfolio value
Session P&L
Cumulative P&L
Available cash
Portfolio performance
Current holdings
Valuation usability
User attention
```

### 4.2 Secondary Information

```text
Net contributions
Realized P&L
Unrealized P&L
Current drawdown
Performance drivers
Risk summary
Recent financial activity
Data details
```

### 4.3 Default Hierarchy

```text
Portfolio Summary
Performance
Holdings
Attention / Data Status
```

### 4.4 Financial Information Density

Visual simplification must reduce:

```text
containers
decoration
duplication
visual noise
```

It must not reduce canonical investment information.

Canonical financial information must not be removed solely to simplify layout.

When available and relevant, Overview should preserve:

```text
Portfolio value
Session P&L
Cumulative P&L
Cash
Net contributions
Realized / unrealized P&L
Holdings performance
Performance drivers
```

A metric may move to a lower information tier when it is secondary.

A metric may be hidden when it is:

```text
unavailable
not canonical
not relevant to the current context
duplicated elsewhere on the same surface
```

Reduce containers, not financial information.

### 4.5 Session P&L

Session-performance presentation follows market context.

During the current trading session:

```text
Today P&L
```

After the current trading session closes:

```text
Today P&L
```

On a non-trading day:

```text
Previous Trading Session P&L
<session date>
```

The label and as-of date must reflect the actual market session.

Generic wording such as “recent P&L” should not replace known session semantics.

### 4.6 Performance Drivers

When canonical attribution is available, Overview should provide a compact
explanation of the current or latest-session P&L.

Examples:

```text
Top contributors
Top detractors
Asset-class contribution
```

Performance-driver information is secondary to the main portfolio value and
performance chart.

### 4.7 Overview Invariants

* Portfolio value is the highest-priority financial figure.
* Performance is the primary chart.
* Holdings are the second major content area.
* Session P&L remains visible when canonical data is available.
* Healthy data state uses a compact summary.
* Only conditions that materially affect valuation or require user action
  become primary warnings.
* System health, refresh attempts, fingerprints, internal state-machine fields,
  and infrastructure diagnostics belong in Data Details or Operations.
* An empty Attention area shows an explicit empty state.
* Overview does not duplicate full Portfolio, Risk, Data, or Operations
  workspaces.
* Overview must not reimplement domain state machines in frontend code.

---

## 5. Data

Data surfaces determine whether information is suitable for:

```text
valuation
research
portfolio construction
risk
decision-making
```

Core evidence:

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

Rules:

* Provider availability is not equivalent to data validity.
* Provider-specific request details belong in detailed or operational views.
* Retry history and transport errors are secondary operational evidence.
* User-facing state should express decision-relevant meaning.
* Data quality and freshness must be evaluated in the context of intended use.

---

## 6. Research

Research is centered on Experiments and evidence.

```text
Dataset
Feature / Alpha / Model Identity
Parameters
Evaluation
Research Evidence
Published Forecast
```

Invariants:

* Candidate Experiment and Published Forecast are distinct.
* Research lineage remains inspectable.
* Research results remain traceable to Dataset, parameters, and model identity.
* In-sample and out-of-sample evidence remain distinct where applicable.
* After-cost diagnostics are first-class evidence.
* Promotion, quarantine, and retirement do not erase lineage.
* AI may assist research but receives no additional financial authority.
* Research charts consume canonical platform outputs.
* Browser code must not independently recreate authoritative research metrics.

---

## 7. Portfolio

Portfolio preserves the distinction between:

```text
Published Forecast
Current Financial Book
Portfolio Target
Risk Decision
Rebalance Plan
```

A Financial Book is the canonical accounting boundary for:

```text
cash
positions
fees
P&L
valuation
```

Different environments must remain distinct.

Examples:

```text
actual
paper
shadow
```

Invariants:

* Portfolio Target is traceable to Forecast, Portfolio Policy, constraints,
  exposures, and cost assumptions.
* Risk blocks are explicit.
* Risk blocks are not silently converted into Targets.
* Current holdings are normally represented as comparable records.
* Market value, weight, P&L, return, and pricing state use consistent semantics.
* Optimization output remains comparable with an appropriate simple baseline.
* Mathematically optimal output is not presented as self-evidently correct.
* Portfolio intent does not collapse research, risk, and accounting boundaries.

---

## 8. Evaluate

Evaluate covers forward-time and realized outcome analysis.

```text
Paper         Forward-time simulated execution
Shadow        Observation of target / plan outcomes
Attribution   Outcome decomposition
Alpha Health  Evidence persistence or decay
```

Backtest remains part of Research.

Outcome evaluation remains traceable to:

```text
Dataset
Experiment
Published Forecast
Portfolio Target
Risk Decision
Rebalance Plan
```

Where relevant, Attribution distinguishes:

```text
Market movement
Factor / exposure drift
Alpha decay
Portfolio construction
Execution cost
Slippage
Tradability constraints
Partial / missing fills
Residual effects
```

Evaluation should explain why observed outcomes differ from expectations.

---

## 9. Financial State

Cash, positions, fees, P&L, and valuation originate from an explicit Financial
Book.

Invariants:

* Actual, Paper, Shadow, and Backtest state are not presented as one account.
* Environment identity remains visible when comparing books.
* Canonical financial metrics are not redefined independently in frontend code.
* Unreliable financial metrics are shown as unavailable.
* Approximate values are not presented as canonical values.
* Derived and directly accounted values remain distinguishable when material.
* Financial identities and cutoffs survive navigation.
* Accounting ambiguity remains fail-closed.

---

## 10. Market Session

Market-session semantics are independent from data transport and storage.

Canonical session concepts include:

```text
pre_open
open
midday_break
after_close
non_trading_day
unknown
```

The authoritative session model must derive from the relevant trading calendar
when verified calendar evidence is available.

Relevant session context includes:

```text
market_date
latest_completed_trading_date
expected_quote_date
next_trading_date
session state
calendar verification state
```

Invariants:

* Weekend logic alone is not a trading calendar.
* Wall-clock age alone is not market freshness.
* Market closed with valid latest-session data may be a healthy valuation state.
* Session semantics remain consistent across Overview, Portfolio, Data, Risk,
  and Decision surfaces.

---

## 11. Pricing Semantics

The following concepts are independent:

```text
pricing_kind
pricing_as_of
pricing_authority
storage provenance
freshness
```

### 11.1 Pricing Kinds

```text
Stock          Realtime quote / session close
ETF            Exchange quote / session close
Open-end fund  Published NAV / estimated NAV
Manual mark    Explicit manual valuation
```

### 11.2 Observation and Valuation Mark

The latest market observation and the authoritative valuation mark are distinct
concepts.

```text
Latest Observation
    newest available market information

Valuation Mark
    authoritative value permitted for Financial Book valuation
```

A newer non-authoritative observation must not replace or invalidate an older
valid authoritative valuation mark.

Example:

```text
Friday:
  Published NAV = 1.8000
  authoritative valuation mark

Monday:
  Estimated NAV = 1.8115
  latest observation
  non-authoritative
```

The Monday estimate may be shown as supplementary market information.

The Financial Book may continue to use the valid Friday Published NAV until the
next authoritative NAV becomes available, subject to the applicable freshness
policy.

### 11.3 Pricing Authority

Possible authority states include:

```text
authoritative
non_authoritative
missing
conflicting
```

Non-authoritative information must remain clearly distinguishable.

### 11.4 Storage Provenance

Examples:

```text
provider
persistent cache
persisted snapshot
market bar
```

Storage provenance does not define freshness.

A cached authoritative latest-session close is not automatically stale.

### 11.5 Pricing Presentation

User-facing presentation describes economic meaning.

Examples:

```text
Realtime · 10:32
Close · 09/11
Published NAV · 09/11
Estimated NAV · non-authoritative
```

Open-end fund Published NAV must not be described as realtime market data.

---

## 12. Valuation, Refresh, and Decision Semantics

The following concepts remain separate:

```text
valuation_usability
refresh_health
decision_readiness
user_attention
```

### 12.1 Valuation Usability

Valuation usability answers:

```text
Can the current Financial Book be valued for display?
```

Typical states:

```text
usable
degraded
unavailable
```

Valuation should consume authoritative valuation marks.

A newer non-authoritative observation does not automatically invalidate an
existing usable valuation mark.

### 12.2 Refresh Health

Refresh health answers:

```text
Did recent ingestion or publication activity succeed?
```

Typical states:

```text
healthy
running
degraded
failed
unknown
```

A failed later refresh does not automatically invalidate an already valid
published valuation.

### 12.3 Decision Readiness

Decision readiness answers:

```text
Can current evidence safely support a new investment decision?
```

Decision readiness may be stricter than valuation usability.

A valuation may remain usable while new decision generation is blocked.

### 12.4 Fail-Closed Boundary

Fail-closed requirements apply to:

```text
trading
risk
financial authority
unsafe accounting
decision evidence
```

Fail-closed behavior must not unnecessarily erase usable historical or current
portfolio information from read-only views.

---

## 13. Status and Evidence

Primary status should communicate:

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

Invariants:

* Each concept has one primary user-visible status.
* Healthy state does not require a large success banner.
* Warning and danger correspond to actual user or financial impact.
* Status never depends on color alone.
* Technical evidence uses progressive disclosure.
* Fingerprints and low-level identities do not dominate primary views.
* Refresh health does not masquerade as valuation usability.
* Storage provenance does not masquerade as freshness.

---

## 14. User Attention

Attention contains work the user can or should perform now.

Appropriate items:

```text
Manual confirmation
Risk review
Actionable data repair
Ledger reconciliation
Strategy / forecast review
```

Excluded by default:

```text
Healthy subsystem status
Zero counters
Broker disabled
Paper / Shadow inactive
Internal audit guarantees
Expected external publication wait
Non-actionable refresh failure
System-maintenance-only diagnostics
```

Rules:

* User attention is not system health.
* Operations state does not automatically become Attention.
* Multiple downstream blockers with one root cause should normally become one
  actionable item.
* An item without a meaningful user action belongs outside Attention.
* Empty Attention state must be explicit.

---

## 15. Interaction Hierarchy

```text
read / query
refresh / ingestion
research mutation
portfolio proposal
financial mutation
authority mutation
```

### Read / Query

Read-only.

No financial side effect.

### Refresh / Ingestion

Requests updated data.

Execution state and resulting evidence are visible.

### Research Mutation

Creates or modifies research artifacts.

Does not alter canonical financial state.

### AI Research Interaction

AI appears inside normal product workflows as contextual research intelligence,
not as a generic chat authority.

The supported interaction modes are:

```text
Explain
Investigate
Propose
Orchestrate Research
```

**Explain** interprets already-authoritative facts, metrics, gates, and provenance.

**Investigate** creates or advances a Research Task using approved evidence and
tools.

**Propose** creates falsifiable hypotheses, candidate specs, experiments,
counter-theses, or missing-evidence requests.

**Orchestrate Research** runs a bounded typed research workflow under explicit
tool allowlists, budgets, and trace capture.

There is no AI **Act on capital** interaction mode.

AI may create research artifacts, but it cannot:

```text
establish financial truth
mark deterministic gates as passed
approve its own research promotion
expand execution authority
submit broker orders
rewrite financial history
```

Research interfaces should expose model/provider details as trace or automation
metadata, not as the primary research object. The primary user objects are the
research question, hypothesis, evidence, evaluation, review state, and promotion
state.

### Portfolio Proposal

Creates or modifies Target or Rebalance intent.

Does not grant execution authority.

### Financial Mutation

Changes canonical financial state.

Requires explicit preview, confirmation, and auditability.

### Authority Mutation

Changes permission for financially consequential actions.

Requires a distinct high-friction confirmation boundary.

Scope and expiry must be explicit where applicable.

Research evidence, AI output, Backtest, Paper, or Shadow success must never
implicitly grant execution authority.

---

## 16. Visual System

Karkinos uses Catppuccin Latte and Mocha as its visual foundation.

The interface should feel:

```text
restrained
native
precise
information-dense
professional
financial
```

Visual treatment reinforces information hierarchy.

### 16.1 Core Principle

Reduce containers, not information.

Prefer:

```text
typography
spacing
alignment
dividers
tables
continuous content surfaces
```

over:

```text
card walls
nested panels
decorative chrome
```

### 16.2 Layout

* Prefer a continuous content canvas.
* Avoid equally weighted dashboard tiles.
* Use a dominant primary content area.
* Use a compact secondary rail only when supporting information benefits from
  persistent visibility.
* Portfolio Summary, Performance, and Holdings receive primary space on
  investment surfaces.
* Attention and Data Status remain supporting information.
* Section hierarchy is primarily expressed through spacing, alignment, type,
  and dividers.
* Avoid unnecessary outer borders.
* Avoid card-in-card composition.
* Avoid excessive corner radius.
* Do not confuse empty space with premium design.
* Professional financial UI may be compact without becoming visually noisy.

### 16.3 Typography

* Primary financial values receive the strongest numerical hierarchy.
* Financial values use tabular numerals.
* Heading hierarchy remains stable and utilitarian.
* Marketing-style oversized headings are avoided.
* Time, symbols, codes, and identities remain compact and scannable.

### 16.4 Color

* Catppuccin surfaces define background hierarchy.
* Mauve is a restrained primary accent.
* Mauve may be used for selection and primary chart emphasis.
* P&L uses one consistent positive / negative color system.
* Warning and danger colors are reserved for meaningful conditions.
* Avoid decorative glow.
* Avoid large decorative gradients.
* Avoid high-saturation panel backgrounds.

### 16.5 Components

```text
table                Comparable records and holdings
chart                Time, performance, risk, distribution
timeline             Ordered events
card                 Independent object or bounded action
badge                Short state
disclosure / drawer  Detailed evidence
```

Card is not the default page-section primitive.

### 16.6 Avoid

```text
Decorative sparkline
Decorative donut chart
Marketing quote
Motivational slogan
Redundant KPI card
System-health filler
Decorative iconography
Unnecessary visual chrome
```

A page looks complete because the information model is coherent.

---

## 17. Responsive Behavior

Desktop:

* retain readable navigation;
* retain comparison-friendly tables where appropriate;
* preserve financial information density;
* maintain clear primary and secondary regions.

Mobile:

* reorder by task priority;
* prioritize Portfolio Summary, Performance, and Attention;
* use a scannable Holdings representation;
* collapse technical evidence by default;
* preserve financial semantics;
* preserve pricing authority and as-of meaning.

Responsive layout may change structure.

It must not change financial meaning.

---

## 18. Performance and Consistency

* Pages primarily consume persisted canonical or derived state.
* Ordinary reads do not implicitly trigger external providers, AI, or
  financially meaningful side effects.
* The same financial concept uses consistent identity, formatting, as-of
  semantics, and status interpretation across surfaces.
* Failure of one secondary widget does not erase otherwise usable financial
  state.
* Large datasets use pagination, virtualization, or server-side querying where
  appropriate.
* Frontend code does not redefine canonical financial metrics.
* Frontend code does not recreate domain state machines.
* Research charts consume canonical platform artifacts.
* Presentation convenience never weakens trading, risk, accounting, or
  authority fail-closed behavior.
* Canonical values displayed in multiple locations preserve identical meaning.

---

## 19. Design Change Rules

This document changes only when long-term product behavior changes in:

```text
product model
information architecture
financial semantics
pricing semantics
authority boundaries
interaction hierarchy
status language
major visual invariants
```

The following do not belong here:

```text
Component token changes
Page-specific pixel adjustments
Screenshot diffs
Temporary migration details
Implementation checklists
Individual bug fixes
One-off visual audits
```

Those belong in code, issues, implementation plans, or focused design notes.

`DESIGN.md` is the product-level contract.

Implementations should be evaluated against one question:

> Does this implementation reinforce the intended Karkinos product model and
> financial semantics, or does it accidentally turn the system into something
> else?
