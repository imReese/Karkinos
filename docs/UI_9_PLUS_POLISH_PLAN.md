# Karkinos UI 9+ Polish Plan

## Objective

Raise every public and private Karkinos route above a 9/10 visual-product bar
without weakening the evidence-first product contract. The result must remain a
calm, precise, high-density financial workbench built from canonical persisted
projections, explicit human authority, and truthful lifecycle states.

This plan extends `design.md`; it does not replace it. The score is an
acceptance tool, not permission to introduce decorative UI, mock financial
values, provider-backed reads, or new financial calculations.

## Non-negotiable boundaries

- GET views remain provider-free, write-free, and refresh-free.
- The UI formats and arranges canonical values; it does not recompute prices,
  cost, P&L, allocation, risk, configuration, or authority.
- Valuation snapshot, ledger cutoff, accounting identity, and evidence status
  stay intact across every projection.
- Strategy and AI surfaces never gain broker access or trading authority.
- Submit, cancel, recovery, capital expansion, and automatic resume remain
  absent by default.
- Missing, stale, estimated, partial, conflicting, and unreconciled evidence
  remain visible and fail closed.
- Public product proof contains no private account data and no mock financial
  performance.
- Routine card nesting remains prohibited.

## 9+ scorecard

Every dimension is scored independently. A route passes only when every
dimension is at least 9.0 and the hard gates below pass. A strong average cannot
hide a weak dimension.

| Dimension                 | 9+ acceptance evidence                                                                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Professional trust        | The first viewport exposes the authoritative state, evidence time, and authority boundary without marketing ambiguity.                                           |
| Information hierarchy     | A three-second scan identifies the route purpose, visual owner, highest-priority state, and next safe action. No more than two regions compete at the top level. |
| Brand identity            | The page is recognizably Karkinos without relying only on the purple accent, logo, or repeated shell chrome.                                                     |
| Visual craft              | Typography, spacing, dividers, alignment, selected states, and surface hierarchy remain deliberate in Latte and Mocha at every target width.                     |
| Data and chart expression | Tables and charts answer a named question, own sufficient canvas, preserve evidence identity, and remain readable without decorative filler.                     |
| Interaction and state     | Loading, empty, missing, stale, partial, blocked, error, and controlled actions are distinct, stable, and appropriately weighted.                                |
| Responsive composition    | Desktop, laptop, tablet, and mobile reorder by operator priority with no document overflow; wide content uses local overflow.                                    |
| Accessibility             | Keyboard reachability, focus visibility, ARIA names, touch targets, reduced motion, and contrast pass the changed contract.                                      |

### Hard gates

- One route-level visual owner is evident in the first relevant viewport.
- Blockers outrank healthy telemetry; prohibited actions are never hidden.
- Body text is normally 14-16px; 12-13px is reserved for verified dense data
  and metadata.
- No unresolved `--app-*` token, raw semantic text color, routine shadow,
  routine glass, decorative gradient, or oversized default radius is added.
- No public or private page uses fabricated account, return, order, risk, or
  execution data to appear complete.
- All changed routes pass deterministic tests and browser geometry checks.

## Reference matrix

References are used for composition principles rather than visual imitation.

| Reference            | Karkinos application                                                                                |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| Apple / Apple Stocks | Strong identity, quiet chrome, list-detail continuity, and a chart that owns the analytical canvas. |
| Google Finance       | Search-first orientation, compact summaries, and comparable watchlists.                             |
| Cursor / Linear      | One dominant task, explicit state, restrained interaction, and low-noise operational chrome.        |
| Stripe / Vercel      | Editorial public-home hierarchy, credible product proof, and disciplined calls to action.           |
| Bloomberg            | Stable information architecture, tabular precision, and professional density.                       |
| Koyfin / TradingView | Contextual analytical workspaces, local chart controls, and sufficient chart area.                  |

## Route art direction

| Route                | Visual owner                             | Required 9+ composition                                                                                                       |
| -------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `/`                  | Evidence-to-action product proof         | Editorial hero plus a realistic, non-financial workbench preview; concise proof, workflow, and a non-repeated closing action. |
| `/overview`          | Account truth and today's priority       | Account metrics first, evidence state adjacent, one ranked action queue, current holdings before secondary analysis.          |
| `/portfolio`         | Current holdings table                   | Compact summary and filters lead directly into the primary table; historical and secondary analysis remain downstream.        |
| `/portfolio/:symbol` | Instrument identity and price evidence   | Instrument facts and evidence state lead into a chart-first position workspace with stable tabs.                              |
| `/activity`          | Immutable ledger history                 | Audit timeline/table owns the page; append-only entry is explicit and secondary.                                              |
| `/account-truth`     | Reconciliation result                    | Score and unresolved difference lead; matched detail stays quiet and progressively disclosed.                                 |
| `/market`            | Watchlist-detail chart workspace         | Persistent list-detail relationship, strong instrument identity, and chart-owned detail canvas.                               |
| `/backtest`          | Reproducible result evidence             | Result, cost/OOS limitations, and equity/drawdown evidence dominate configuration chrome.                                     |
| `/ai-research`       | Cited human research task                | Frozen canonical context, cited artifact, human conclusion, and zero-authority boundary form one workspace.                   |
| `/decision`          | Gate matrix                              | Highest blocker and safe next step lead into the evidence gate matrix and candidate detail.                                   |
| `/risk`              | Active exceptions and thresholds         | Risk metric strip, exception list, threshold table, and isolated controlled action zone.                                      |
| `/operations`        | Priority queue versus immutable timeline | Operator priority and chronological evidence remain visually and structurally distinct.                                       |
| `/trading`           | Persisted-only review queue              | Order evidence and human review status lead; kill switch and signed controls stay isolated and collapsed.                     |
| `/settings`          | Control-center index                     | Data, runtime, research, ingestion, and safety sections are navigable without one uninterrupted form wall.                    |

## Delivery sequence

### Batch A — scorecard and public product identity

- Record this scorecard and route art direction.
- Polish the public header, hero, non-financial workbench proof, closing action,
  and footer rhythm.
- Preserve the zero-API public route contract.

### Batch B — Overview visual owner

- Make account truth and today's highest-priority action the unmistakable first
  viewport hierarchy.
- Keep current holdings ahead of secondary charts and history.
- Reduce repeated state copy and same-level visual competition.

### Batch C — analytical benchmark

- Use Market and Holding Detail as the chart, identity, and responsive quality
  benchmark.
- Align Backtest result evidence, chart controls, and typography with that bar.

### Batch D — decision and operations identity

- Refine Decision, Risk, Operations, and Trading around their distinct visual
  owners rather than one repeated row-and-divider template.
- Keep sensitive actions isolated and default-closed.

### Batch E — remaining routes and system polish

- Complete Activity, Account Truth, AI Research, and Settings.
- Remove remaining route-specific visual drift and unused legacy styles.

## Verification matrix

For every batch:

1. Inspect the current rendered baseline before editing.
2. Run GitNexus query/context and upstream impact for each modified function,
   class, or method; warn before HIGH or CRITICAL changes.
3. Add deterministic tests for changed presentation and interaction contracts.
4. Run focused Vitest, format check, and production build under Node 24 LTS.
5. Verify Latte and Mocha at 1440x900, 1280x800, 1024x768, 834x1112,
   768x1024, and 390x844 as relevant.
6. Check keyboard navigation, focus, ARIA, contrast, reduced motion, and local
   overflow.
7. Confirm public/GET views made no provider contact and performed no write.
8. Run GitNexus change detection when available; otherwise inspect staged and
   unstaged diffs plus direct consumers.
9. Stage only the batch files, commit, push `main`, and monitor CI before
   beginning the next batch.

## Completion rule

The 9+ goal is complete only when all routes satisfy every scorecard dimension,
all hard gates pass, the six-viewport Latte/Mocha evidence is recorded, all
required local checks and CI pass, and no unrelated user change is staged or
modified.

## Batch A validation record — 2026-07-28

### Assumptions and scope

- The public route proves the product structure without pretending to be a
  live financial dashboard; no private data or fabricated performance is used.
- The editorial hero and workbench proof become a two-column composition only
  from 1280px. Narrow laptops and tablets use a calmer vertical composition.
- The existing private workbench route remains the only destination of the
  public call to action.

### Validation

- Runtime: Node `v24.18.0`.
- `npm test`: 66 files and 562 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- `npm run test:e2e -- e2e/public-home.spec.ts`: 3 tests passed against the
  rebuilt production bundle.
- The Playwright matrix covered Latte and Mocha at 1440x900, 1280x800,
  1024x768, 834x1112, 768x1024, and 390x844.

### Visual result

- The first viewport now has one editorial statement and one realistic,
  non-financial workbench proof rather than a generic concept trace.
- The workbench proof exposes account-fact provenance, evidence quality,
  authority, highest blocker, safe next step, and the review boundary.
- The English 1440px product section begins at 882px; the evidence proof is
  visible above it and begins at 117px.
- All six target widths had zero document overflow and zero measured local
  overflow in the header, hero, evidence frame, proof grid, workflow, and
  footer.
- The 390px header now presents a named `Workbench` / `工作台` destination
  instead of an icon-only arrow, and Chinese phrase wrapping avoids splitting
  `投资决定` or `都有`.

### Limits and risk impact

- This batch visually validates only the public home. Private routes remain in
  later batches and are not yet claimed to meet the 9+ scorecard.
- GitNexus reported `PublicHomePage` upstream impact as LOW with no graph-level
  incoming callers; direct source consumers are the root route and its unit and
  browser contracts.
- The public route still emits no financial API request. The batch changes no
  valuation, ledger, risk, OMS, kill-switch, broker, capital, or authorization
  behavior and therefore adds no trading authority or financial-calculation
  risk.

## Batch B validation record — 2026-07-28

### Assumptions and scope

- Account metrics, valuation evidence, the highest-priority exception, and
  current holdings remain the Overview reading path; secondary analysis stays
  below it.
- Additional actionable exceptions remain fully available but no longer carry
  the same initial visual weight as the highest-priority blocker.
- The queue keeps its existing persisted inputs, deduplication, ordering,
  priority, tone, evidence, resolution condition, and safe-action links.

### Validation

- Runtime: Node `v24.18.0`.
- Focused `overview-page.test.tsx`: 39 tests passed.
- `npm test`: 66 files and 562 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- The existing nine-test exemplar Playwright suite completed with
  `test-results/.last-run.json` reporting `passed` and no failed tests.
- The new focused Overview acceptance-viewport Playwright contract passed
  separately against the production bundle.

### Visual result

- Desktop keeps current holdings wider and to the left of the review queue;
  the queue now shows one primary blocker plus a named count of additional
  review items.
- Additional blockers use native `details` disclosure and preserve keyboard,
  focus, evidence, unblock conditions, and safe next actions.
- The 390px current-holdings start moved from approximately 1467px to 977px.
- Holdings begin at approximately 363px, 363px, 735px, 871px, 871px, and 977px
  at 1440x900, 1280x800, 1024x768, 834x1112, 768x1024, and 390x844.
- All six viewports had zero document overflow and zero app-content overflow.
  Latte and Mocha were visually checked at desktop and mobile endpoints.

### Limits and risk impact

- This batch does not change which item is highest priority; it displays the
  first item from the already sorted canonical queue.
- GitNexus reported both `OverviewPage` and `DashboardTodayQueue` upstream
  impact as LOW with no graph-level callers or affected processes. The direct
  source consumer remains the `/overview` route.
- No query, provider behavior, data refresh, financial calculation, valuation
  identity, ledger cutoff, OMS, broker bridge, kill switch, or authorization
  behavior changed. Trading authority remains unchanged and default-closed.

## Batch C1 validation record — 2026-07-28

### Assumptions and scope

- Market and Holding Detail establish the analytical-workspace benchmark before
  Backtest and the remaining research routes are aligned to it.
- Price, OHLC, volume, trades, and cost-reference lines remain persisted inputs;
  the chart only scales and renders them and does not derive a new financial
  fact.
- On a locally overflowing mobile chart, the latest saved bar is the initial
  reading position. Older saved history remains available by horizontal scroll.

### Validation

- Runtime: Node `v24.18.0`.
- Focused Market, chart, Holding Detail, and route-contract Vitest: 4 files and
  50 tests passed.
- `npm test`: 66 files and 562 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- Focused Market Playwright acceptance passed in 1.6 minutes across Latte and
  Mocha at 1440x900, 1280x800, 1024x768, 834x1112, 768x1024, and 390x844.
- The complete ten-test exemplar Playwright suite passed in 4.9 minutes,
  including reduced motion and the remaining-route Latte/Mocha overflow audit.
- Holding Detail was inspected in Latte and Mocha at desktop and mobile, then
  measured at all six acceptance viewports.

### Visual result

- Market now gives the selected instrument name and price greater visual
  authority while preserving the persistent watchlist-detail relationship.
- The shared K-line canvas places range controls on the chart header, renders
  persisted volume below price, and keeps cost references in a quieter legend
  instead of duplicating labels over trade markers.
- At 1440px the Market chart measured about 857x361px; the Holding Detail chart
  measured about 1169px wide and began near 417px in the 900px viewport.
- Holding Detail now carries canonical quantity into the instrument identity
  line, while the existing evidence state remains adjacent to the summary.
- At 390px the 720px analytical canvas measured 369px of intentional local
  overflow and automatically settled at that latest-data edge. The tab rail
  retained 193px of intentional local overflow with a right-edge scroll cue.
- Holding Detail had zero document and app-content overflow at all six target
  viewports. Its chart began near 417px, 437px, 557px, 553px, 553px, and 659px
  respectively from desktop through mobile.

### Limits and risk impact

- This record covers Market and Holding Detail only. Backtest still needs to be
  aligned to the same chart and evidence typography benchmark before Batch C is
  complete.
- GitNexus reported `MarketInstrumentWorkspace`, `PriceStructureChart`, and
  `HoldingDetailPage` upstream impact as LOW with no graph-level callers or
  affected processes. Direct source consumers are `MarketPage`,
  `HoldingDetailRoutePage`, and the two shared chart call sites.
- No query, refresh mutation, provider action, price, cost, P&L, risk,
  valuation identity, ledger cutoff, OMS, broker, kill-switch, capital, or
  authorization contract changed. The browser checks triggered no refresh or
  controlled action, and the UI remains read-only and default-closed.

## Batch C2 validation record — 2026-07-28

### Assumptions and scope

- Backtest already had the correct large-screen composition: setup stays left,
  saved result evidence stays wider on the right, and mobile defaults to result
  evidence when a saved report exists.
- The remaining 9+ blocker was loss of exact evidence through ellipsis, not the
  simulation, result, validation, or promotion model.
- Route-scoped wrapping is preferable to changing the shared `MetricStrip`
  contract for every route.

### Validation

- Runtime: Node `v24.18.0`.
- Focused Backtest and route-contract Vitest: 2 files and 53 tests passed.
- `npm test`: 66 files and 562 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- The focused six-viewport Backtest Playwright contract passed in 8.3 seconds.
- The mobile route-order and overflow Playwright contract passed in Latte and
  Mocha in 41.1 seconds.

### Visual result

- Strategy identity, current-run state, review status, and their details now
  wrap only inside the Backtest evidence strips instead of ending in ellipsis.
- Saved-result metrics preserve exact initial/final equity, fee descriptions,
  and execution-drift descriptions on 390px screens.
- Desktop retains the 0.68/1.32 setup-to-result composition; the result panel
  begins at x=645px at 1440px and x=616px at 1280px.
- At narrower widths the result panel begins near y=403px, 415px, 431px, and
  626px at 1024px, 834px, 768px, and 390px. All six viewports had zero document
  and app-content overflow.
- The mobile results tab remains the default when saved evidence exists, and
  the equity/drawdown chart follows the complete headline metrics directly.

### Limits and risk impact

- GitNexus reported `BacktestPage` and `MetricsGrid` upstream impact as LOW with
  no graph-level callers or affected processes. Direct source consumers are the
  `/backtest` route and `BacktestReportView`.
- This batch changes only route-scoped text overflow. It does not change
  datasets, parameters, simulations, costs, fills, OOS evidence, validation
  gates, promotion readiness, research assignment, paper/shadow previews, or
  any broker/authorization behavior.
- Batch C is now complete. Decision, Risk, Operations, and Trading remain the
  next distinct visual-owner batch and are not yet claimed complete.

## Batch D validation record — 2026-07-28

### Assumptions and scope

- Decision, Operations, and Trading already had a clear evidence-first visual
  owner. They were audited before editing and were not rewritten merely to
  create churn.
- Risk alert titles, dynamic details, and the account-state next step are
  canonical persisted facts. The English UI may translate those known natural
  language templates, but it must preserve their instruments, percentages,
  timestamps, severity, and meaning.
- A portfolio summary that is still loading, unavailable, or missing must stay
  explicit. The UI must not hide the region, infer totals from independently
  loaded holdings, or use placeholder financial values.

### Validation

- Runtime: Node `v24.18.0`.
- Focused Risk and copy Vitest: 2 files and 17 tests passed.
- `npm test`: 66 files and 563 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- The complete exemplar plus Trading-mobile Playwright set passed: 12 tests in
  5.8 minutes. It covered six acceptance viewports, Latte and Mocha, mobile
  route ordering, closed audit drill-downs, reduced motion, and local overflow.
- An initial full Playwright run exposed the Portfolio summary disappearing
  while its canonical snapshot GET was pending. The loading/error/missing state
  fix passed the focused regression, a four-test route subset, and the final
  complete 12-test run.

### Visual result

- Risk now translates the persisted Chinese concentration, cash-buffer, quote
  age, and next-step templates in the English UI without changing any numeric
  fact. No Chinese system sentence remains in the English priority register.
- Risk keeps active blocked and warning evidence first. The shared unblock
  condition and safe next step remain adjacent to that list, followed by the
  metric strip and persisted threshold table.
- Decision retains a single next action, a compact gate matrix, and quieter
  audit drill-downs. Operations retains the review queue before health totals
  and the immutable-history empty state. Trading retains the manual-order queue
  before collapsed kill-switch and broker-boundary controls.
- Portfolio now reserves the canonical summary region immediately. Its loading
  state measured about 74px high and the settled metric strip about 80px, so the
  page no longer silently loses or later inserts a major first-screen region.
- Manual browser review covered Decision and Operations in Latte desktop, Risk
  in Latte desktop and Mocha mobile, Trading in Latte and Mocha at desktop and
  mobile, and Portfolio loading-to-settled behavior. Measured document and app
  content overflow remained zero.

### Limits and risk impact

- This completes the Decision, Risk, Operations, and Trading visual-owner
  batch. It does not complete the all-route 9+ goal; Activity, AI Research,
  Settings, and the final system-wide accessibility/token cleanup remain.
- GitNexus reported `RiskPage`, `formatRiskAlertDetail`, and `PortfolioPage`
  upstream impact as LOW. `formatRiskAlertDetail` has one direct caller,
  `RiskPage`; the two route components have no graph-level callers or affected
  processes.
- No risk score, threshold, price, cost, P&L, valuation identity, ledger cutoff,
  OMS, broker adapter, kill switch, capital, execution, or authorization
  contract changed. Retry is the existing read-only GET; it does not refresh a
  provider or write the database.

## Batch E1 validation record — 2026-07-28

### Assumptions and scope

- Frozen persisted tasks, exact evidence bindings, and their human-review state
  are the AI Research visual owner. Task capture is a secondary human action,
  not the default page canvas.
- Opening a draft may reveal the existing capture form, but it must stay after
  the review queue on narrow screens and beside it only on wide desktops.
- Recording a task still freezes the existing explicitly selected evidence and
  starts no model, provider, broker, order, or capital action.

### Validation

- Runtime: Node `v24.18.0`.
- Focused AI Research Vitest: 2 files and 10 tests passed.
- `npm test`: 66 files and 563 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- A new six-viewport AI Research Playwright contract passed, and the existing
  remaining-route Latte/Mocha mobile audit passed after being updated for the
  progressive capture form: 2 tests in 52 seconds.
- Manual browser inspection covered Mocha mobile and desktop plus Latte desktop;
  the default and open-draft states were both inspected.

### Visual result

- AI Research now opens on a named frozen-evidence review queue with an honest
  loading/error/empty state. The capture form is absent until the operator
  explicitly chooses `Draft research task`.
- The ambiguous `Close` action is now `Collapse research workspace`, while the
  independent capture state uses `Close task draft` and `aria-expanded`.
- On 1440x900 the open-draft queue begins near x=252px at 510px wide and the
  capture surface begins near x=782px at 599px wide. On 390x844 the queue begins
  near y=509px and the composer follows near y=826px.
- All six acceptance viewports preserved queue-before-capture order and zero
  document/app-content overflow. Latte and Mocha kept the same hierarchy.

### Limits and risk impact

- This completes the AI Research visual-owner sub-batch only. Activity and the
  final Settings/accessibility/token cleanup remain before Batch E and the
  all-route 9+ goal can be complete.
- GitNexus reported `ResearchTaskPanel` and `ResearchTaskCard` upstream impact
  as LOW with no graph-level callers or affected processes. Direct source
  consumers are `AiResearchPage` and the default-closed Backtest research
  boundary in `BacktestPage`.
- No query, payload, evidence type, valuation snapshot, ledger cutoff, fixture,
  review decision, provider, strategy, OMS, broker, kill switch, capital, or
  authorization contract changed. AI output remains non-authorizing and all
  execution remains human-started and default-closed.

## Batch E2 validation record — 2026-07-28

### Assumptions and scope

- The immutable persisted ledger table remains the Activity visual owner. Entry
  tools are an explicit secondary action and stay closed until requested.
- The route must not synthesize a net-cash total from visible rows. An absent
  canonical aggregate remains a named missing fact rather than a placeholder
  amount.
- Mobile category controls may use intentional local horizontal overflow while
  the table keeps its existing local overflow and the document remains fixed.

### Validation

- Runtime: Node `v24.18.0`.
- Focused Activity Vitest: 2 files and 21 tests passed.
- `npm test`: 66 files and 563 tests passed.
- `npm run format:check`: passed.
- `npm run build`: production build passed.
- The new six-viewport Activity hierarchy contract passed in 3.5 seconds. The
  remaining-route Latte/Mocha mobile audit, including the entry drawer and new
  density limits, passed in 58 seconds.
- The first clean-data CI run exposed a test-only assumption that ledger history
  was non-empty. The browser contracts now branch on the canonical
  `/api/ledger/entries` response and validate either the persisted table or the
  explicit empty state; no fixture or mock financial data was added.
- Manual browser inspection covered Latte and Mocha at 1440x900 and 390x844.

### Visual result

- The header entry action now uses the secondary hierarchy. Persisted history,
  not the write affordance, is the strongest first-screen surface.
- Metric labels, values, and details wrap inside the Activity strip. The missing
  aggregate is now the concise `Not exposed` / `未提供`, with the canonical
  no-browser-summing boundary still visible.
- Visual filter counts are compact while their ARIA labels retain the localized
  full count. At 390px the category rail changed from a 184px wrapped block to
  a 44px local-scroll rail; the ledger table moved from about y=802px to y=710px.
- At 1440px the filters changed from two rows to one and the table moved from
  about y=503px to y=473px. All six viewports had zero document and app-content
  overflow; only the named filter rail and wide ledger table overflow locally.

### Limits and risk impact

- This completes the Activity visual-owner sub-batch. Settings and the final
  cross-route accessibility/token/legacy-style audit remain before the all-route
  9+ goal can be complete.
- GitNexus reported `ActivityPage` and `ActivityFeed` upstream impact as LOW
  with no graph-level callers or affected processes. The direct production path
  is the Activity route into `ActivityPage`, then `ActivityFeed`.
- No query, ledger entry, trade preview, mutation payload, amount, fee, P&L,
  classification, timestamp, provider, OMS, broker, kill switch, capital, or
  authorization behavior changed. The missing aggregate remains fail-closed.
