# Karkinos Financial Workbench

Karkinos private routes use one professional financial-workstation language.
The goal is fast scanning, explicit evidence authority, and dense analytical
workflows—not a SaaS card dashboard.

## Design principles

- Prefer flat sections, registers, tables, charts, and split panes over card walls.
- Use typography, dividers, alignment, and whitespace to establish hierarchy.
- Reserve semantic color for P&L, evidence quality, risk, blockers, and authority.
- Keep neutral information surfaces transparent. Avoid decorative shadows.
- Controls may use compact rounding; large content surfaces stay square and flat.
- Never fill unavailable financial facts for visual completeness.
- `--`, unavailable, stale, estimated, blocked, and review-required are different states.
- Evidence and authority remain separate: a recommendation never implies execution.

## Reference patterns

The workbench borrows interaction patterns—not branding—from professional tools:

- Bloomberg PORT: positions, performance, attribution, and risk in one workflow.
- TradingView Holdings: dense holdings tables, multiple analytical views, summaries.
- Koyfin: watchlists/tables as primary analytical surfaces with configurable context.
- IBKR PortfolioAnalyst: portfolio performance, holdings, allocation, activity, and risk.

## Global private-route shell

Private workbench routes use `app-workbench-route` and a 1560px maximum canvas.
Account Truth is intentionally narrower at 1440px because it is an audit workflow.

Standard reading order:

1. Workspace header and authoritative context.
2. Evidence/status strip when needed.
3. Compact metric strip or quote register.
4. Primary chart/table/queue.
5. Secondary analysis or safety rail.
6. Evidence identity and deep diagnostics on demand.

Large neutral surfaces must not use rounded cards or decorative shadows.

## Route information architecture

### Overview

Account state -> daily strategy recommendation -> performance -> holdings ->
market/data status -> operator attention. Strategy recommendations are read-only,
require human confirmation, and never imply broker submission.

### Portfolio

Portfolio facts -> holdings table -> account/strategy analysis -> closed history.
Holdings are primary. Allocation and construction guidance are supporting analysis.

### Market

Instrument universe/watchlist -> selected instrument chart -> quote evidence ->
market-data operations -> research notes. The instrument table/rail is the navigator.

### Activity

Audit history first. Manual financial-entry tools remain controlled actions rather
than dashboard shortcuts.

### Backtest / Strategy Lab

Left: strategy, dataset, parameters, run controls. Right: current result, curves,
metrics, validation, fills, and evidence. Governance, promotion, and research archive
remain disclosures below the primary research canvas.

### AI Research

Cited research is primary. Backtest and account-strategy context are supporting facts.
AI output is never presented as deterministic account truth or execution authority.

### Decision

Decision posture -> gates -> daily trading plan -> workflow -> signal queue ->
evidence register -> lane details. Registers and gate tables replace summary tiles.

### Risk

Blocking register -> risk metrics/safety rail -> decision handoff -> threshold table ->
structural analysis -> history. Current blockers stay above retrospective analysis.

### Trading

Manual-review queue first -> safety/authority rail -> execution audit -> history.
Broker automation and release evidence remain explicit, bounded, and secondary.

### Operations

Attention queue first -> readiness/health -> subsystem register -> evidence history.
Viewing evidence never clears a blocker or changes authority.

### Settings

Persisted configuration is primary; operations/safety/preferences are secondary.
Use registers and disclosures, not settings cards.

### Account Truth

Readiness -> reconciliation -> evidence sources. This route favors audit readability
and a narrower canvas over trading-terminal density.

### Holding Detail

Instrument identity -> valuation/evidence state -> metric strip -> tabbed position,
P&L, transactions, evidence, and reconciliation details.

## Responsive behavior

- Desktop favors split panes, fixed evidence rails, dense tables, and sticky identifiers.
- Tablet collapses secondary rails below primary content.
- Mobile uses local horizontal overflow only for data that cannot be responsibly stacked.
- Touch targets remain accessible; density must not reduce control hit areas.

## Visual acceptance

A route is not complete if:

- the first viewport is dominated by empty chart/card space;
- unavailable values appear without a reason or evidence state;
- equal-size tiles obscure the primary workflow;
- a secondary panel visually outweighs a holdings/table/queue surface;
- a recommendation looks like an executable instruction;
- neutral content uses decorative shadows or large rounded containers;
- the route invents a new typography, spacing, or status system instead of workbench primitives.
