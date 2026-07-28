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

| Dimension | 9+ acceptance evidence |
| --- | --- |
| Professional trust | The first viewport exposes the authoritative state, evidence time, and authority boundary without marketing ambiguity. |
| Information hierarchy | A three-second scan identifies the route purpose, visual owner, highest-priority state, and next safe action. No more than two regions compete at the top level. |
| Brand identity | The page is recognizably Karkinos without relying only on the purple accent, logo, or repeated shell chrome. |
| Visual craft | Typography, spacing, dividers, alignment, selected states, and surface hierarchy remain deliberate in Latte and Mocha at every target width. |
| Data and chart expression | Tables and charts answer a named question, own sufficient canvas, preserve evidence identity, and remain readable without decorative filler. |
| Interaction and state | Loading, empty, missing, stale, partial, blocked, error, and controlled actions are distinct, stable, and appropriately weighted. |
| Responsive composition | Desktop, laptop, tablet, and mobile reorder by operator priority with no document overflow; wide content uses local overflow. |
| Accessibility | Keyboard reachability, focus visibility, ARIA names, touch targets, reduced motion, and contrast pass the changed contract. |

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

| Reference | Karkinos application |
| --- | --- |
| Apple / Apple Stocks | Strong identity, quiet chrome, list-detail continuity, and a chart that owns the analytical canvas. |
| Google Finance | Search-first orientation, compact summaries, and comparable watchlists. |
| Cursor / Linear | One dominant task, explicit state, restrained interaction, and low-noise operational chrome. |
| Stripe / Vercel | Editorial public-home hierarchy, credible product proof, and disciplined calls to action. |
| Bloomberg | Stable information architecture, tabular precision, and professional density. |
| Koyfin / TradingView | Contextual analytical workspaces, local chart controls, and sufficient chart area. |

## Route art direction

| Route | Visual owner | Required 9+ composition |
| --- | --- | --- |
| `/` | Evidence-to-action product proof | Editorial hero plus a realistic, non-financial workbench preview; concise proof, workflow, and a non-repeated closing action. |
| `/overview` | Account truth and today's priority | Account metrics first, evidence state adjacent, one ranked action queue, current holdings before secondary analysis. |
| `/portfolio` | Current holdings table | Compact summary and filters lead directly into the primary table; historical and secondary analysis remain downstream. |
| `/portfolio/:symbol` | Instrument identity and price evidence | Instrument facts and evidence state lead into a chart-first position workspace with stable tabs. |
| `/activity` | Immutable ledger history | Audit timeline/table owns the page; append-only entry is explicit and secondary. |
| `/account-truth` | Reconciliation result | Score and unresolved difference lead; matched detail stays quiet and progressively disclosed. |
| `/market` | Watchlist-detail chart workspace | Persistent list-detail relationship, strong instrument identity, and chart-owned detail canvas. |
| `/backtest` | Reproducible result evidence | Result, cost/OOS limitations, and equity/drawdown evidence dominate configuration chrome. |
| `/ai-research` | Cited human research task | Frozen canonical context, cited artifact, human conclusion, and zero-authority boundary form one workspace. |
| `/decision` | Gate matrix | Highest blocker and safe next step lead into the evidence gate matrix and candidate detail. |
| `/risk` | Active exceptions and thresholds | Risk metric strip, exception list, threshold table, and isolated controlled action zone. |
| `/operations` | Priority queue versus immutable timeline | Operator priority and chronological evidence remain visually and structurally distinct. |
| `/trading` | Persisted-only review queue | Order evidence and human review status lead; kill switch and signed controls stay isolated and collapsed. |
| `/settings` | Control-center index | Data, runtime, research, ingestion, and safety sections are navigable without one uninterrupted form wall. |

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
