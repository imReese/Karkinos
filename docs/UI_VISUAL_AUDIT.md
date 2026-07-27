# Full-route Visual Audit

Audit date: 2026-07-27

This audit records the settled visual state of the Karkinos public surface and
workbench after the route-level redesign batches. `design.md` remains the UI
source of truth. This document is an acceptance snapshot and prioritization
boundary, not a second design system.

## Scope and method

The audit used the running application with the local persisted development
database. It did not inject mock financial values, contact a market-data
provider, or exercise broker, OMS, capital, or order-submission authority.

The following surfaces were reviewed as complete pages:

- public home: `/`;
- overview, portfolio, activity, risk, Account Truth, decision, operations,
  market, trading, backtest, AI research, and settings;
- representative holding detail: `/portfolio/603659`.

The visual baseline covered 1440 x 900, 1280 x 800, 1024 x 768, 834 x 1112,
768 x 1024, and 390 x 844. Latte and Mocha were exercised across desktop,
tablet, and mobile checks. Every route was allowed to reach its settled
evidence state before its visual hierarchy was judged. The audit checked:

1. first-screen focal point and five-second comprehension;
2. page composition and task order;
3. chart weight and chart-to-evidence relationship;
4. list-to-detail behavior;
5. desktop, tablet, and mobile reflow;
6. single-H1 structure, local overflow, disclosure defaults, and authority
   boundaries;
7. missing, stale, degraded, blocked, and reconciled evidence language.

## Second-pass closure

The second pass corrected composition and state-semantics drift found after the
first full-route audit:

- Overview, Risk, and Market now keep transient loading distinct from empty,
  missing, stale, and error evidence. A delayed persisted GET no longer appears
  to prove that evidence is absent.
- Activity leads with immutable ledger history and opens entry controls only on
  demand. Operations leads with the priority queue, opens queue evidence in a
  stable detail drawer, and keeps technical identity in drill-down.
- Holding detail keeps canonical position facts visible when the persisted
  price series is missing. The evidence rail stacks below the summary from
  768-1024 px and returns to the desktop split only at 1280 px.
- The public home replaces a large, static concept card with a compact product
  trace. It identifies the public `/` to private `/overview` transition, shows
  the evidence-to-human-review path, and states the default read-and-review-only
  authority without inventing account, return, order, or execution values.

No second-pass change introduced a provider-backed read, UI financial
recalculation, broker capability, or a new design system.

## Reference matrix

The references are sources of interaction principles, not themes to copy.

| Reference                                                                                 | Principle retained                                                                                   | Karkinos adaptation                                                                                                      | Explicit non-goal                                                                   |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| [Apple Stocks](https://support.apple.com/guide/stocks/welcome/mac)                        | Watchlist-to-detail composition, strong instrument identity, and a chart that owns the detail canvas | Market and holding detail keep the selected instrument, persisted quote state, time range, and chart in one reading path | Copying Apple chrome or hiding provenance behind visual calm                        |
| [Google Finance](https://www.google.com/finance/)                                         | Search-led orientation, compact market summaries, and comparable lists                               | Search remains global while holdings and market lists use concise, comparable rows                                       | Blending broad market movement with personal contribution                           |
| [Cursor](https://cursor.com/) and [Linear](https://linear.app/)                           | One dominant task, quiet chrome, explicit status, and reduced noise                                  | Decision, Risk, Operations, and Trading lead with the current human task or blocker                                      | Turning every subsystem into an equally weighted dashboard card                     |
| [Stripe](https://stripe.com/) and [Vercel](https://vercel.com/)                           | Editorial public-home hierarchy, disciplined proof, and restrained calls to action                   | The public home explains Karkinos before entering the workbench                                                          | Applying marketing-page spacing, gradients, or hero scale inside operating routes   |
| [Bloomberg Terminal](https://www.bloomberg.com/professional/products/bloomberg-terminal/) | Stable information architecture and professional domain density                                      | Desktop navigation and tables preserve predictable placement and high information yield                                  | Reproducing terminal clutter, proprietary conventions, or density without hierarchy |
| [Koyfin](https://www.koyfin.com/)                                                         | Context-rich dashboards, advanced graphing, and workspace continuity                                 | Charts appear where they answer the route's primary question and retain surrounding evidence                             | User-composed widgets that allow canonical concepts to diverge across routes        |
| [TradingView](https://www.tradingview.com/)                                               | Chart-first instrument analysis, local range controls, and clear market context                      | Market, holding detail, and backtest give charts sufficient canvas and local controls                                    | Direct broker connectivity, visual trading prompts, or a second charting system     |

The combined target is therefore not a collage. Public pages borrow editorial
clarity from Cursor, Linear, Stripe, and Vercel. Operating pages borrow
master-detail discipline from Apple and Google plus chart and data density from
Bloomberg, Koyfin, and TradingView. Karkinos keeps its own evidence-first state
language, Catppuccin themes, human authorization boundary, and canonical
persisted projections.

## Route results

| Route                | Audit state       | First-screen owner                            | Result and remaining observation                                                                                                                                                                            |
| -------------------- | ----------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/`                  | Accepted exemplar | Brand proposition and product trace           | The compact first screen pairs the proposition with a structural evidence path, explicit public/private route identity, and read-and-review-only authority without fake financial data.                     |
| `/overview`          | Accepted          | Account truth, holdings, and next safe action | Account metrics and evidence lead; loading remains distinct from missing evidence, and holdings and action priority stay legible without routine card nesting.                                              |
| `/portfolio`         | Accepted          | Current holdings table                        | Holdings remain ahead of secondary analysis while realized history, closed assets, and ledger drill-down stay available.                                                                                    |
| `/portfolio/$symbol` | Accepted exemplar | Instrument identity and price canvas          | Apple-like list/detail discipline is translated into a persisted-evidence view; canonical position facts survive a missing price series, and tablet composition stacks without shrinking the chart.         |
| `/activity`          | Accepted          | Immutable activity timeline                   | History leads; the controlled entry tool opens on demand instead of competing with the audit path.                                                                                                          |
| `/risk`              | Accepted exemplar | Current blockers and clearing conditions      | Exception priority, risk metrics, threshold evidence, and the kill-switch boundary are distinct; transient loading is not labeled as missing evidence.                                                      |
| `/account-truth`     | Accepted          | Current reconciliation report                 | The settled report, score, exceptions, and matched-detail disclosure agree. A transient load state cleared normally and was not treated as a persistent defect.                                             |
| `/decision`          | Accepted exemplar | Next decision and gate matrix                 | Account facts, research, risk, paper/shadow, and human review are readable as one staged decision.                                                                                                          |
| `/operations`        | Accepted          | Priority evidence queue                       | Actionable exceptions lead into a stable evidence drawer; immutable history remains quieter and technical fingerprints stay in drill-down.                                                                  |
| `/market`            | Accepted exemplar | Instrument list and selected chart            | The watchlist-to-chart relationship survives desktop, tablet, and horizontal mobile rail layouts; delayed persisted quotes remain loading rather than false missing evidence.                               |
| `/trading`           | Accepted          | Manual-confirmation queue                     | Empty pending state is honest and broker authority remains disabled. Monitor whether repeated real use justifies a whole-route empty-state compression; do not reorder it from screenshot preference alone. |
| `/backtest`          | Accepted exemplar | Persisted report and equity/drawdown evidence | Saved evidence, after-cost metrics, chart, reproducibility identity, and promotion gates now outrank setup controls when results exist.                                                                     |
| `/ai-research`       | Accepted          | Evidence-freezing human task                  | The empty review state remains honest rather than filled with invented research. Large input space is appropriate only while the task form is the primary action.                                           |
| `/settings`          | Accepted          | Persisted configuration                       | The route is intentionally long but progressively disclosed; refresh and authority-affecting controls remain separated from configuration facts.                                                            |

## Cross-viewport results

| Baseline          | Settled result                                                                                                                            |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1440 x 900, Mocha | All audited routes retained one visible H1, zero document/shell horizontal overflow, and a stable desktop information hierarchy.          |
| 1280 x 800, Latte | Navigation, command bar, content canvas, charts, tables, and controlled zones remained usable without first-fold collisions.              |
| 1024/768, mixed   | The shell uses the tablet canvas and bottom navigation; holding summary and evidence stack in one reading path without document overflow. |
| 834 x 1112, Latte | Master-detail routes rebalanced without shrinking the chart into a decorative thumbnail; task routes stacked in reading order.            |
| 390 x 844, Mocha  | Mobile navigation did not cover the active task, local rails contained intentional overflow, and low-priority disclosures stayed closed.  |

Theme symmetry, mobile touch targets, reduced motion, and disclosure defaults
also remain covered by deterministic frontend and Playwright contracts. A route
that initially displays loading or missing evidence must be judged after the
canonical GET settles; missing or stale final evidence must remain visible and
fail closed.

## Validation evidence

Validation used Node.js 24.18.0 and a no-live local application server:

- `web/node_modules/.bin/prettier --check docs/UI_VISUAL_AUDIT.md docs/UI_VISUAL_AUDIT.zh.md`
  passed;
- `cd web && npm test` passed 66 files and 562 tests;
- `cd web && npm run build` completed the TypeScript and production Vite build;
- `cd web && npm run test:e2e` passed all 18 Playwright tests in 5.0 minutes;
- the in-app browser audit reached settled states on all 14 audited routes and
  found no document or app-shell horizontal overflow at the sampled widths.

The first sandboxed Playwright launch could not bind its localhost test port;
the same no-live command was rerun with scoped localhost permission. One final
full-suite attempt then reached the completed Trading mobile DOM but exhausted
the generic 30-second test budget; its isolated rerun passed in 0.662 seconds.
Aligning that test-only budget with the existing cross-viewport specs produced
the complete 18-test pass above without changing an assertion or production
behavior. No provider or broker connection was enabled for any run.

## Priority decision

No P0 or P1 whole-page visual defect was found in this audit.

The following are observation triggers, not authorized patch work:

- Trading: revisit the empty queue only if usage evidence shows that a stable
  zero-pending state repeatedly blocks access to the audit task. Preserve the
  queue as the first owner whenever pending confirmation exists.
- AI Research: revisit the desktop empty-state balance only when persisted
  review tasks exist. Do not add illustrative or mock research to fill space.
- Settings: split navigation only if operator testing shows that progressive
  disclosure is insufficient; do not create more routine panels merely to
  shorten the page.

Button sizing, borders, timestamp wording, badge polish, and similar local
details remain below this threshold. Resume UI implementation only when there
is evidence of a first-screen hierarchy failure, hidden blocker, chart/list
relationship failure, cross-viewport inconsistency, authority ambiguity,
canonical-state disagreement, accessibility regression, or overflow.

## Integrity and authority result

The audit found no UI path that needs a financial-contract change. The reviewed
surfaces continue to consume canonical persisted projections; read paths remain
provider-free and write-free; the UI does not recompute price, cost, P&L, risk,
configuration, or authority. Missing and stale evidence remains explicit.
Strategy and AI stay disconnected from broker authority, and trading remains
manual-confirmation-first with no default submit, cancel, automatic recovery,
or capital-expansion capability.
