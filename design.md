# Karkinos Product Design System

Karkinos is a financial operating workbench for one serious China-market
investor. The interface must make account truth, evidence quality, risk, and the
next safe human action faster to understand than the surrounding software.

This document is the source of truth for product UI direction. It defines the
visual system, information hierarchy, interaction primitives, page patterns,
and implementation guardrails. If implementation and this document disagree,
update the implementation or record the drift explicitly before extending the
conflicting pattern.

## Product Design North Star

The first screen should answer, in order:

1. What is the account worth, and which persisted snapshot proves it?
2. What changed, and how much of the change is explained?
3. Is the data complete, fresh, reconciled, and suitable for interpretation?
4. What requires human attention before any action?
5. Where is the instrument-, strategy-, or order-level evidence?

Karkinos should feel like a calm, precise financial workstation: dense enough
for daily operation, approachable enough for one operator, and explicit enough
that missing evidence or disabled authority cannot be mistaken for success.

It is not:

- a brokerage clone;
- a marketing dashboard;
- a collection of decorative metric cards;
- a terminal that maximizes density at the cost of comprehension;
- a UI that turns research, AI output, or a review into trading authority.

## Design Principles

### 1. Evidence before atmosphere

Visual atmosphere may help orientation, but it must not compete with values,
timestamps, evidence state, or the next operator action. Persisted financial
facts and their identity always receive higher visual priority than decoration.

### 2. Tasks before modules

Organize surfaces around operator questions and workflow stages, not around the
number of backend subsystems. The operator should see what is blocked, why it is
blocked, and the one safe next step without reading every healthy subsystem.

### 3. Tables and workflows before cards

Use tables for comparable records, gate matrices for staged evidence, timelines
for ordered facts, and inline metric strips for small sets of account values.
Use cards only when an object genuinely needs isolation.

### 4. One concept, one visual owner

Overview, Portfolio, Decision, Risk, Operations, and Trading may project a
canonical concept but must not present competing calculations or status
languages. Reuse the same value formatting, state taxonomy, snapshot identity,
and evidence affordance.

### 5. Progressive disclosure without hidden risk

Show the decision-critical summary first. Secondary evidence may live in a
drawer, expandable row, tab, or detail page. A blocker, stale fact, unresolved
residual, or authority boundary must never be hidden by default.

### 6. Semantic color, not decorative color

Accent identifies selection and interaction. Success, danger, warning, info,
and teal explain financial or operational meaning. Large background gradients,
glows, and translucent color washes are not product structure.

### 7. Authority must look different from analysis

Read-only navigation, explicit ingestion, append-only audit actions, and
authority-affecting controls are different interaction classes. Their location,
labeling, confirmation, and visual treatment must make that distinction clear.

## Current Implementation Audit

Audited on 2026-07-18 against the running Overview, Portfolio, Risk, and
Decision routes, the frontend dependency manifest, and the token layer.

### Foundations worth keeping

- Catppuccin Latte and Mocha already have a centralized `--app-*` token
  mechanism. The mechanism and palette direction are worth keeping; the current
  token inventory is not yet accepted as the target contract.
- Account, portfolio, valuation, risk, and evidence surfaces already use
  canonical backend projections rather than mock financial values.
- TanStack Query, Router, and Table provide suitable data and table foundations.
- Recharts, Lucide, React Hook Form, Tailwind CSS, `clsx`, and
  `tailwind-merge` are sufficient for the current product scale.
- Tables use tabular numerals and most colors are tokenized.
- The product exposes data freshness, manual confirmation, broker-disabled,
  and persisted-facts-only boundaries in the UI.

### Drift to correct

- The token inventory contains 52 declared names and 48 referenced names, but 6
  referenced tokens are undefined and 10 declared tokens have no consumer.
- `--app-focus`, `--app-accent-bg`, `--app-positive`, `--app-negative`,
  `--app-profit`, and `--app-subtext-1` are referenced without definitions.
  Focus visibility and financial/status color can therefore fall back or
  silently lose their intended meaning.
- Latte semantic and secondary text colors do not consistently meet the 4.5:1
  contrast target on panel surfaces. Raw success, warning, and danger colors are
  widely used as text even though text-specific tokens exist.
- Shape tokens do not govern the product: `--app-radius-lg` has one consumer,
  `--app-radius-xl` has none, while components contain hundreds of
  `rounded-2xl`, `rounded-3xl`, and 27-32px declarations.
- The component layer still contains hard-coded Catppuccin colors and shadows,
  concentrated in Backtest and chart surfaces.
- Cards and rounded panels have become the default layout mechanism, including
  cards nested inside cards.
- Account metrics, workflow stages, normal states, warnings, and actions often
  receive similar visual weight.
- The floating toolbar, large page headings, wide gutters, 18-24px radii,
  gradients, glow, and translucent layers consume attention and vertical space.
- Icon-only desktop navigation hides the product information architecture.
- Risk and Decision surfaces require scanning many repeated status blocks before
  the current blocker and next action become clear.
- Portfolio filtering and summary surfaces push the primary holdings table too
  far down the page.
- Mobile layouts too often stack desktop containers instead of reordering
  information by operational priority.

The redesign must correct this drift without replacing canonical projections,
changing financial calculations, or introducing provider calls into reads.

## Reference Strategy

Karkinos may learn interaction patterns from mature libraries and financial
products without inheriting a vendor theme.

### Existing foundations

- **TanStack Table:** canonical table engine for holdings, risk boundaries,
  decision gates, evidence registers, and order histories.
- **Recharts:** current chart foundation; do not add a second chart library for
  a visual effect already supported here.
- **Lucide:** canonical icon family.
- **Tailwind CSS:** implementation utility layer, constrained by `--app-*`
  tokens and the primitives in this document.

### Patterns to learn from

- **Radix UI / React Aria:** accessible behavior for dialogs, tabs, popovers,
  tooltips, selects, and disclosure controls.
- **shadcn/ui:** composable component APIs and code ownership, not its default
  theme or card-heavy examples.
- **Ant Design Pro / IBM Carbon:** dense enterprise tables, filter bars,
  exception lists, master-detail layouts, and operational state handling.
- **Fluent 2:** compact command bars, navigation hierarchy, and clear focus
  treatment.
- **OpenBB:** modular research workspace and discoverable, explicit data
  operations.
- **Ghostfolio, rotki, and Portfolio Performance:** portfolio accounting,
  history, allocation, import, and reconciliation UX.

Do not install a full opinionated component suite merely to copy its appearance.
Any new runtime dependency requires a concrete missing capability, accessibility
review, bundle-impact review, license review, and deterministic tests. Prefer a
small Karkinos-owned primitive over parallel UI systems.

## Information Architecture

Desktop navigation should expose labels and group routes by operator intent:

```text
Portfolio
  Overview
  Holdings
  Activity
  Market

Research
  Strategy Lab
  AI Research

Decision & Risk
  Decision
  Risk

Execution & Operations
  Operations
  Trading Review

System
  Settings
```

The desktop sidebar may collapse to icons, but labels are the default at common
laptop and desktop widths. The collapsed state must preserve accessible names,
tooltips, section separation, and a clear active route.

Mobile uses a navigation drawer or compact primary navigation. It must not
shrink the desktop sidebar into an unlabeled permanent strip.

## Application Shell

### Desktop

- Default labeled sidebar: 200-224px.
- Collapsed sidebar: 56-64px.
- Top command/status bar: 44-52px.
- Main workspace owns the remaining width and scrolls independently where
  practical.
- Page content should normally use the available workspace width; avoid a
  marketing-style narrow maximum width.

### Top command/status bar

The top bar is a flat shell region, not a floating capsule. It may contain:

- current account or workspace identity;
- valuation status and as-of time;
- market-data status and as-of time;
- global search or command entry;
- theme and language controls;
- an explicit route to detailed data health.

Do not display redundant labels such as “global toolbar.” Status controls should
be compact and should not dominate the page. A status is expressed with label,
state, and time; color alone is insufficient.

### Workspace header

Each route begins with one compact workspace header:

- section label, when useful;
- concise page title;
- one-sentence operational purpose;
- at most one primary route-level action and a small number of secondary
  controls.

Recommended title size is 28-32px on desktop and 24-28px on mobile. Avoid large
display typography and excessive top padding.

## Layout System

Use a 12-column desktop grid, an 8-column tablet grid, and a 4-column mobile
grid. Content relationships determine spans; the existence of a component does
not automatically justify a new panel.

### Surface hierarchy

1. **Canvas:** application background.
2. **Workspace:** route-level content region.
3. **Section:** titled content separated by spacing or a rule.
4. **Repeated item:** row, compact card, table record, or timeline entry.
5. **Controlled action zone:** visually isolated mutation or authority boundary.

Do not insert an additional framed surface when spacing and a section divider
already express the hierarchy.

### Spacing

Use an 8px foundation with a compact supporting scale:

- 4px: icon/text adjustment and dense metadata;
- 8px: related inline elements;
- 12px: compact control padding;
- 16px: standard row and component spacing;
- 24px: section separation;
- 32px: major workspace separation;
- 48px: exceptional page-level separation only.

### Radius and elevation

- Controls and small badges: 4-6px.
- Standard framed tools and repeated items: 6-8px.
- Dialogs and controlled action zones: up to 12px.
- Avoid 18-24px default radii.
- Default surfaces have no drop shadow.
- Use elevation only for overlays, menus, drawers, dialogs, and sticky elements.
- Blur and glass effects are not permitted on routine workspace surfaces.

### Card budget

A card is appropriate for:

- a genuine repeated entity;
- an exception requiring isolation;
- a modal, drawer, or framed tool;
- a dangerous or explicitly controlled action;
- a compact mobile replacement for a table row.

A card is not appropriate for:

- every individual metric;
- each healthy workflow stage;
- a section that already sits inside a framed parent;
- descriptive copy that can be a row or note;
- decoration around a table, chart, or filter bar without functional need.

Routine card nesting depth is zero. A repeated object may contain unframed
subsections, but not another decorative card.

## Visual System and Token Contract

Karkinos uses Catppuccin **Latte** for light mode and **Mocha** for dark mode.
Use Catppuccin names in design discussion and semantic `--app-*` variables in
product code. Raw palette values are foundations; components consume semantic
roles, not raw colors.

| Role | Mocha | Latte | Token |
| --- | --- | --- | --- |
| Base canvas | `#1e1e2e` | `#eff1f5` | `--app-base`, `--app-bg` |
| Mantle | `#181825` | `#e6e9ef` | `--app-mantle` |
| Crust | `#11111b` | `#dce0e8` | `--app-crust` |
| Panel | `#313244` | `#ccd0da` | `--app-panel`, `--app-surface-0` |
| Surface | `#45475a` | `#bcc0cc` | `--app-surface-1`, `--app-border` |
| Primary text | `#cdd6f4` | `#4c4f69` | `--app-text`, `--app-foreground` |
| Muted text | `#a6adc8` | `#6c6f85` | `--app-muted`, `--app-subtext-0` |
| Accent | `#cba6f7` | `#8839ef` | `--app-accent` |
| Information | `#89b4fa` | `#1e66f5` | `--app-accent-secondary` |
| Success | `#a6e3a1` | `#40a02b` | `--app-success` |
| Danger | `#f38ba8` | `#d20f39` | `--app-danger` |
| Warning | `#f9e2af` | `#df8e1d` | `--app-warning` |
| Teal | `#94e2d5` | `#179299` | `--app-teal` |

Palette rules:

- Do not introduce generic Tailwind colors when an `--app-*` token exists.
- Accent purple is for selection, focus, and platform emphasis, not large
  backgrounds or atmospheric glow.
- Semantic colors must explain P&L, evidence, risk, or action state.
- Financial direction must use the project-wide China-market convention
  consistently. Sign and text remain mandatory; color is supplementary.
- Use text-specific semantic tokens when raw palette colors fail contrast.
- Latte must not become pure white paper; Mocha must not become pure black.
- Remove decorative grid backgrounds and radial glows from primary reading
  surfaces unless a documented usability test proves an orientation benefit.

### Audited token health

The 2026-07-18 static audit produced the following baseline:

| Check | Result | Required disposition |
| --- | ---: | --- |
| Unique declared `--app-*` tokens | 52 | Rationalize by role |
| Unique referenced `--app-*` tokens | 48 | Must all resolve |
| Referenced but undefined | 6 | Replace or define before shell migration |
| Defined but unused | 10 | Remove or document a scheduled consumer |
| Component lines with hard-coded colors | 48 | Replace unless explicitly justified |
| `rounded-2xl` occurrences | 487 | Migrate by primitive, not global search/replace |
| `rounded-3xl` occurrences | 22 | Review as likely surface drift |
| Explicit 27-32px radius occurrences | 81 | Remove from routine surfaces |

The undefined references are:

| Current reference | Target disposition |
| --- | --- |
| `--app-focus` | Replace with canonical `--app-focus-ring` |
| `--app-accent-bg` | Define as the canonical selected/active background |
| `--app-positive` | Replace with `--app-pnl-positive` or an operational state token according to meaning |
| `--app-negative` | Replace with `--app-pnl-negative` or an operational state token according to meaning |
| `--app-profit` | Replace with `--app-pnl-positive` |
| `--app-subtext-1` | Replace with contrast-checked `--app-text-tertiary` |

Do not fix these by assigning every missing name to a visually similar existing
color. Each call site must first be classified as financial direction,
operational state, interaction, or text hierarchy.

### Contrast baseline

Measured against the current Latte panel (`#ccd0da`), the following ratios do
not satisfy the 4.5:1 target for small text:

| Token/value | Contrast on Latte panel |
| --- | ---: |
| `--app-muted` | 3.20:1 |
| `--app-soft` | 4.05:1 |
| raw success | 2.17:1 |
| `--app-success-text` | 3.20:1 |
| raw danger | 3.52:1 |
| `--app-danger-text` | 4.34:1 |
| raw warning | 1.70:1 |
| `--app-warning-text` | 2.59:1 |

These measurements are evidence of a systemic contract gap, not a universal
claim about every rendered component. Effective contrast must be tested against
the actual background, including transparent mixes.

Rules:

- Small body, table, metadata, badge, and financial text requires at least
  4.5:1 against every allowed parent surface.
- Large display values may use 3:1 only when they meet the WCAG large-text size
  and weight definition.
- Raw Catppuccin semantic colors are permitted for icons, chart strokes, dots,
  borders, and non-text fills. They are not text colors by default.
- Semantic text tokens have independently selected Latte and Mocha values; they
  do not have to equal the palette hue.
- `color-mix()` may derive quiet backgrounds and borders. Critical text colors
  must be explicit, testable tokens rather than arbitrary mixes.
- Focus rings require at least 3:1 contrast against adjacent surfaces and must
  remain visible in both themes.

### Target token layers

Use three deliberate layers:

1. **Palette foundations:** Catppuccin values owned in the theme root. Product
   components do not consume these values directly.
2. **Semantic application tokens:** stable roles for surface, text,
   interaction, P&L, evidence, and operational state.
3. **Component tokens:** rare values for a shared primitive when no semantic
   application token expresses the requirement.

Component tokens must not encode page-specific business meaning. A Portfolio
page must not introduce its own version of “warning text,” “positive P&L,” or
“panel border.”

### Canonical semantic roles

The target semantic inventory includes:

| Group | Canonical roles |
| --- | --- |
| Canvas and surfaces | `--app-bg`, `--app-surface`, `--app-surface-raised`, `--app-surface-overlay` |
| Structure | `--app-border`, `--app-divider` |
| Text | `--app-text`, `--app-text-secondary`, `--app-text-tertiary`, `--app-text-inverse` |
| Interaction | `--app-accent`, `--app-accent-hover`, `--app-accent-bg`, `--app-accent-border`, `--app-focus-ring` |
| Operational success | `--app-success-text`, `--app-success-bg`, `--app-success-border` |
| Operational warning | `--app-warning-text`, `--app-warning-bg`, `--app-warning-border` |
| Operational danger | `--app-danger-text`, `--app-danger-bg`, `--app-danger-border` |
| Information | `--app-info-text`, `--app-info-bg`, `--app-info-border` |
| Financial direction | `--app-pnl-positive`, `--app-pnl-negative`, `--app-pnl-neutral` |
| Shape | `--app-radius-control`, `--app-radius-surface`, `--app-radius-overlay` |
| Elevation | `--app-shadow-overlay`, `--app-shadow-sticky` |
| Charts | `--app-chart-grid`, `--app-chart-label`, and named series tokens |

Financial-direction tokens and operational-state tokens are intentionally
separate. A profitable value is not a system success, and a negative return is
not an application error. The `pnl` token mapping follows the project-wide
China-market direction convention while the semantic names remain stable.

### Shape contract

Target values are:

```css
--app-radius-control: 6px;
--app-radius-surface: 8px;
--app-radius-overlay: 12px;
```

Pills use `9999px` only for compact segmented controls, binary states, tags, or
avatars where the shape communicates component type. A pill is not the default
button or status-container shape.

Do not mass-replace every existing radius. Migrate one shared primitive or one
bounded page flow at a time so repeated items, tables, dialogs, and controlled
action zones keep their intended hierarchy.

### Legacy aliases and removal

Current aliases such as `--app-bg`/`--app-base`,
`--app-text`/`--app-foreground`, `--app-muted`/`--app-subtext-0`, and
`--app-panel`/`--app-surface-0` obscure ownership.

During Phase 1, a legacy name may temporarily point to a canonical role only
when all of the following are true:

- the mapping is semantically exact;
- the alias is marked deprecated next to its definition;
- remaining consumers are counted by a deterministic test;
- the phase that removes the final consumer is recorded.

Do not preserve ambiguous aliases indefinitely. `--app-soft`, raw semantic
colors used as text, and financial direction expressed through success/danger
must be classified call site by call site rather than globally aliased.

### Token validation

The frontend must gain deterministic checks for:

- every referenced `var(--app-*)` resolves in both Latte and Mocha;
- both themes define the same canonical semantic token set;
- the approved text/surface contrast matrix passes its threshold;
- routine components do not introduce raw hex, RGB, or generic Tailwind palette
  colors without an allowlisted reason;
- deprecated token consumer counts only decrease;
- new routine surfaces use the canonical radius tokens;
- financial P&L and operational-state tokens are not interchanged.

## Typography and Numbers

Use system-native readability over decorative branding.

Sans stack:

```text
-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "PingFang SC",
"Microsoft YaHei", "Noto Sans CJK SC", sans-serif
```

Rules:

- Body text is normally 14-16px; dense table and metadata text may use 12-13px
  only with verified contrast and line height.
- Chinese UI copy is concise and operational.
- Monospace is reserved for codes, IDs, hashes, fingerprints, and machine
  artifacts. It is not the default financial-value font.
- Comparable values use `font-variant-numeric: tabular-nums`.
- Currency, decimal precision, percentage precision, and signs are stable within
  a column or metric group.
- Do not scale type with viewport width.
- Do not use reduced opacity for important values.

## Core UI Primitives

New product surfaces should be composed from a small Karkinos-owned primitive
layer. Primitive APIs encode layout and accessibility, not financial
calculations.

### `WorkspaceHeader`

Compact route identity, purpose, evidence time, and route-level controls.

### `MetricStrip`

Three to six comparable account or risk metrics separated by spacing or rules.
It replaces grids of one-metric cards. Each metric supports label, value,
optional comparison, state, and evidence time.

### `FilterBar`

Search, primary filters, sorting, result count, and a “more filters” disclosure.
It is a toolbar, not a large panel. Filter state is local/read-only unless the
surface explicitly documents persistence.

### `DataTable`

TanStack-based table with local horizontal scrolling, sticky headers where
useful, stable numeric alignment, keyboard navigation, empty/loading/error
states, and expandable evidence rows.

### `StatusBadge`

Compact label for a known state. It always has visible text and an accessible
name. Critical meaning must not be truncated into ambiguity.

### `EvidenceState`

Displays state, reason, as-of time, source, snapshot/cutoff identity when
needed, and the safe next step. Use this instead of a colored dot plus prose in
another region.

### `ExceptionList`

Priority-ordered operational items with severity, affected scope, reason,
fingerprint, clearing condition, and one safe navigation or review action.

### `GateMatrix`

Rows represent workflow gates; columns represent state, evidence, blocker, and
next action. Healthy rows may collapse. Blocked and review-required rows remain
visible.

### `Timeline`

Chronological immutable facts with event type, source, financial impact,
environment, and evidence identity. Production ledger, paper/shadow, backtest,
and broker evidence must be visually distinguishable.

### `EvidenceDrawer`

Right-side or modal detail for long provenance, raw identifiers, cost-basis
differences, reconciliation details, and audit history. Opening it is read-only.

### `ControlledActionZone`

Isolated area for kill switch, explicit ingestion, signed audit mutations, or
other sensitive actions. It states side effects, required authority, expected
result, and what it cannot do. Dangerous controls never share styling with
ordinary navigation.

## State Language

Use one product-wide state taxonomy:

- **available:** complete enough for the stated interpretation;
- **healthy:** operating within known bounds;
- **attention:** usable but requires timely review;
- **review required:** a human conclusion or acknowledgement is missing;
- **blocked:** a required gate failed or evidence is insufficient;
- **partial:** a known batch or projection is incomplete;
- **stale:** evidence is older than its contract permits;
- **estimated:** explicitly non-authoritative evidence;
- **unreconciled:** persisted sources disagree or coverage is incomplete;
- **unavailable:** the product has no suitable persisted fact;
- **disabled:** capability is intentionally not enabled;
- **loading, empty, error:** view lifecycle states, not financial conclusions.

Every non-healthy financial or operational state should answer:

1. What is affected?
2. Why is it in this state?
3. Which persisted evidence and time support the conclusion?
4. What is the safe next human step?
5. What action remains prohibited?

Do not use internal reason codes without localized explanation. Do not label a
disabled or unconfigured capability as an error merely to attract attention.

## Financial Presentation Integrity

- Persisted ledger facts and bound valuation snapshots are the only authority
  for account, holdings, allocation, P&L, risk, and reconciliation displays.
- Runtime cache and provider responses are ingestion inputs, not account facts.
- GET pages do not contact providers or silently refresh evidence.
- The UI may format and arrange canonical values; it must not independently
  recalculate prices, costs, P&L, allocation, risk decisions, or authority.
- Relevant financial surfaces expose valuation snapshot, ledger cutoff, and
  evidence time without forcing users to inspect developer tooling.
- Snapshot or cutoff mismatch produces a blocked or explicitly non-authoritative
  view, never a silently reconciled number.
- Current holdings use the canonical economic-zero quantity contract. Closed
  positions remain in history and realized results.
- Missing, stale, estimated, partial, or unreconciled evidence remains visible.
- Cash flows, fees, realized P&L, unrealized P&L, and market movement retain
  distinct presentation identities.

## Page Patterns

### Overview

The first desktop viewport should contain:

1. a compact account metric strip;
2. current evidence/data health;
3. the prioritized action queue;
4. enough portfolio context to understand today’s change.

Recommended composition:

```text
Account metric strip
Portfolio performance / attribution       Today action queue
Current holdings table
Performance | Allocation | Attribution | Calendar
Market context and recent activity
```

- Do not wrap every metric in a card.
- The action queue is a ranked list, not a grid of status cards.
- Current holdings should appear before long historical analysis on common
  desktop viewports.
- Market heatmaps represent persisted broad-market or industry breadth only.
  A personal-holdings contribution view must be named as portfolio contribution,
  never market heatmap. If breadth evidence is unavailable, show that boundary.
- Performance, allocation, attribution, and calendar may share a tabbed analysis
  region instead of stacking every large module.

### Portfolio

- `FilterBar` sits immediately above the primary holdings `DataTable`.
- Default desktop additions prioritize weight and realized P&L; secondary
  fields use expandable rows or the detail drawer.
- Current, pending settlement/reconciliation, and historical closed positions
  are distinct views.
- A sticky summary row may show current count, market value, cash, and exposure.
- Clicking a row opens the existing instrument detail route or an evidence
  drawer; do not create duplicate financial calculations.

### Holding detail

- Header: instrument identity, asset class, quantity state, quote/evidence state.
- Metric strip: quantity, available quantity, market value, weight, today P&L,
  realized/unrealized P&L.
- Primary tabs: Position, P&L & Costs, Transactions, Evidence, Reconciliation.
- Cost-basis differences are a labeled comparison, not competing headline
  values.
- Historical transactions remain accessible after a position closes.

### Market

- Separate market context, watchlist, and current-holding evidence review.
- Index tables/cards show point, point change, percentage only when supported,
  as-of time, and state.
- Refresh is an explicit audited ingestion action with stated side effects; page
  reads remain provider-free.
- Never fabricate breadth, previous close, percentage change, or heatmap data.

### Research and Backtest

- Treat an experiment as a reproducible evidence record, not a performance
  advertisement.
- Keep dataset, parameters, costs, OOS status, benchmark, limitations, and
  promotion state adjacent to headline metrics.
- Comparisons use aligned tables and small multiples rather than independent
  cards for each result.
- AI claims are cited research artifacts and visually distinct from deterministic
  calculations and human conclusions.

### Decision

Use a gate-first workspace:

| Gate | State | Evidence | Blocker | Next action |
| --- | --- | --- | --- | --- |
| Account Truth | ... | ... | ... | ... |
| Research evidence | ... | ... | ... | ... |
| Deterministic risk | ... | ... | ... | ... |
| Paper/shadow | ... | ... | ... | ... |
| Human review | ... | ... | ... | ... |

- Show the single highest-priority blocker and safe next step at the top.
- Healthy gates may collapse; blockers and review requirements remain expanded.
- Candidate actions appear in a sortable table or compact master-detail list.
- Order-intent previews state that they do not submit broker orders.
- Decision Quality measures process evidence, not predicted return or authority.

### Risk

- Lead with active blockers and breached/near-boundary items.
- Present drawdown, exposure, liquidity, concentration, and cash in a compact
  risk metric strip.
- Use a threshold table with current value, warning threshold, hard limit,
  state, evidence time, and affected workflow.
- Keep normal boundaries collapsed or visually quiet.
- Place kill switch controls in a separate `ControlledActionZone` with current
  state, reason requirement, scope, and explicit side effects.

### Operations

- Separate chronological history from operator priority.
- Use `ExceptionList` for unresolved journeys and `Timeline` for immutable
  evidence history.
- Each item shows fingerprint, source, safe next action, exact clearing
  condition, and prohibited actions.
- Healthy subsystem telemetry belongs below the attention queue or behind a
  disclosure.

### Trading review

- The default surface is a persisted-only review queue.
- Order intent, risk decision, capital boundary, evidence identity, and operator
  review status remain adjacent.
- Submit and cancel controls do not appear unless a separately reviewed future
  stage explicitly authorizes and implements them.
- Disabled broker or authority state is neutral and explicit, not a broken-state
  visual alarm.

### Settings

- Group configuration by runtime, data, AI research, evidence ingestion, and
  safety boundaries.
- Distinguish environment-owned secrets from persisted non-secret settings.
- Unknown or ineffective fields must be explained before save or startup, not
  silently ignored.

## Tables

- Wide tables scroll inside their own container and never stretch the app shell.
- Prefer sticky headers and a sticky identity column when they materially aid
  comparison.
- Numeric columns align right; text and state columns align left.
- Currency, percentage, quantity, and price columns use consistent precision.
- Long fund names truncate reliably and expose the full accessible name.
- Row actions are compact and ordered by safety; navigation precedes mutation.
- Secondary provenance belongs in an expandable row or `EvidenceDrawer`.
- Filtering and sorting are read-only unless the surface explicitly states
  otherwise.

## Charts, Calendar, and Heatmaps

- Charts answer a named analytical question; they are not decorative filler.
- Axes, grid lines, legends, tooltips, and selected markers must be readable in
  both Latte and Mocha.
- Tooltips show exact values, time, unit, and evidence context where relevant.
- Comparable series use stable colors and ordering across routes.
- Calendar cells prioritize date, period, and signed amount. Color intensity is
  supplementary.
- Desktop treemaps require a clear area metric and signed value labels. Mobile
  uses an ordered list when a treemap would become illegible.
- No chart may silently combine mismatched valuation snapshots or ledger cutoffs.

## Actions and Side Effects

Use explicit action classes:

1. **Navigate/read:** opens another persisted-only view.
2. **Ingest/refresh:** explicitly contacts a provider or reads a local source and
   persists an audited run.
3. **Audit mutation:** appends review, acknowledgement, or evidence without
   changing financial facts or authority.
4. **Controlled financial/authority action:** requires its own reviewed contract,
   authorization, preview, confirmation, and recovery design.

Rules:

- Do not label provider ingestion simply “Refresh” without scope and side-effect
  context.
- Buttons state the object and action: “Refresh confirmed NAV,” “Record review,”
  or “Open trading review.”
- Mutation controls show pending, success, idempotent replay, partial, conflict,
  and failure states deterministically.
- A UI action cannot imply that viewing or acknowledging clears a blocker when
  only newer persisted evidence can clear it.

## Loading, Empty, Partial, Blocked, and Error States

- Loading preserves approximate layout without displaying fake financial data.
- Empty describes the valid absence and the next safe step.
- Partial identifies the missing scope and prevents authoritative totals.
- Blocked explains the failed gate and clearing condition.
- Error explains what failed to load without relabeling account truth.
- Retrying a GET remains read-only. Provider contact requires an explicit
  ingestion action.
- Avoid large rounded error banners when a compact inline state or section-level
  exception communicates the scope more precisely.

## Responsive Behavior

### Desktop: 1280px and above

- Labeled sidebar and two-column workbench where a secondary rail is useful.
- Primary data table or analytical workspace receives the larger span.
- First viewport prioritizes account truth and actions, not decorative chrome.

### Tablet: 768-1279px

- Single-column or 8-column layouts based on task priority.
- Secondary rails move below the primary task, not above it.
- Filters may collapse into a “more filters” disclosure.

### Mobile: below 768px

- Reorder content: blockers/actions, account summary, current positions, then
  analysis and history.
- Replace wide comparison tables with local horizontal scrolling or compact
  master-detail rows; do not shrink the whole page.
- Use drawers and disclosures for provenance.
- Avoid repeating the same status in a page header, card, and row.
- No horizontal page overflow; long codes and names wrap or truncate safely.

## Accessibility and Input

- Body, table, status, and small financial text target WCAG AA contrast of
  4.5:1 or better.
- Large financial values may use 3:1 only when their size and weight qualify.
- All functionality is keyboard reachable with a visible focus state.
- Icon-only controls have accessible names and tooltips where discovery matters.
- Status and P&L never rely on color alone.
- Dialogs and drawers manage focus and restore it on close.
- Touch targets are at least 40px in compact mobile layouts unless a denser
  control has an accessible alternative.
- Reduced-motion preferences disable non-essential transitions.

## Copy

The UI sounds like an operating instrument, not a marketing page.

Use concise state and action language such as:

- `估值可用`
- `行情缓存`
- `待人工复核`
- `风险阻断`
- `证据不完整`
- `打开交易复核`
- `刷新确认净值`
- `不会提交券商订单`

Avoid:

- internal reason codes without localization;
- English fallback in Chinese mode;
- repeated safety paragraphs when one canonical boundary notice is enough;
- vague actions such as `处理`, `同步`, or `继续` without an object;
- phrases implying guaranteed profit, investment advice, or granted authority.

## Implementation Guardrails

Before merging visible frontend changes:

- confirm the component uses a Karkinos primitive or documents why it cannot;
- confirm no referenced `--app-*` token is undefined in either theme;
- use text-safe semantic tokens rather than raw success, warning, danger, or
  financial-direction palette values;
- check Catppuccin Latte and Mocha;
- check a common desktop viewport, a laptop/tablet width, and mobile when layout
  changes;
- scan for hard-coded colors, large radii, blur, shadows, gradient surfaces, and
  nested cards;
- verify local overflow for tables and charts;
- verify loading, empty, partial, blocked, and error states;
- verify keyboard navigation, focus, accessible names, and status contrast;
- confirm GET paths remain provider-free and write-free;
- confirm canonical snapshot, ledger cutoff, accounting, and permission
  boundaries remain unchanged;
- run relevant Vitest, format check, and production build under Node 24 LTS;
- add deterministic regression tests for changed interaction or presentation
  contracts.

## Incremental Migration Plan

The redesign is incremental. Do not rewrite all routes at once.

### Phase 1: foundations and shell

- Replace or define the six unresolved token references according to their
  actual semantic role.
- Introduce the canonical surface, text, interaction, operational-state, P&L,
  radius, and elevation token groups.
- Add theme-parity, unresolved-token, contrast-matrix, hard-coded-color, and
  deprecated-consumer checks.
- Migrate the shell and new primitives to compact radius, flat surface, divider,
  focus-ring, and overlay-only elevation tokens.
- Remove unused tokens and legacy aliases only after their consumers reach zero.
- Introduce `WorkspaceHeader`, `MetricStrip`, `FilterBar`, `StatusBadge`, and
  `EvidenceState`.
- Flatten the app shell and toolbar; make desktop navigation labels discoverable.
- Remove routine glow, glass, decorative grids, and oversized page spacing.

### Phase 2: Overview and Portfolio

- Replace nested account cards with a metric strip and sections.
- Convert the action queue into a ranked `ExceptionList`.
- Move current holdings earlier and make the table the primary Portfolio surface.
- Consolidate performance, allocation, attribution, and calendar into a coherent
  analysis workspace.

### Phase 3: Decision, Risk, and Operations

- Introduce `GateMatrix`, threshold tables, and evidence drawers.
- Prioritize blockers and safe next actions; quiet healthy telemetry.
- Isolate kill switch and sensitive mutations in `ControlledActionZone`.
- Separate priority queues from immutable timelines.

### Phase 4: remaining routes and responsive polish

- Apply the primitives to Research, Backtest, Market, Trading, Activity, and
  Settings.
- Reorder tablet and mobile surfaces by operator priority.
- Complete contrast, keyboard, local-overflow, and reduced-motion audits.

Each phase preserves APIs and canonical financial contracts by default. Any
backend field, dependency, or financial presentation contract added for the
redesign requires a separate explicit review.

## Definition of Done

A redesigned surface is complete only when:

- its primary operator question is answerable in the first relevant viewport;
- blockers are more prominent than healthy telemetry;
- comparable facts use tables, metric strips, or aligned rows instead of card
  grids;
- no routine card is nested inside another routine card;
- every referenced application token resolves in both themes;
- critical text/surface pairs pass their documented contrast threshold;
- financial direction does not reuse operational success or danger tokens;
- routine controls and surfaces use the canonical shape contract;
- all financial values retain canonical evidence identity and state;
- read-only, ingestion, audit, and authority actions are visually distinct;
- Latte, Mocha, desktop, tablet, and mobile behavior are verified;
- accessibility and deterministic tests cover the changed contract;
- no strategy, AI, GET, or presentation component gains broker, ledger, risk,
  kill-switch, or capital-authority capability.
