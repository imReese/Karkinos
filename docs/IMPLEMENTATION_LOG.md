# Karkinos Implementation Log

This file keeps historical implementation progress out of the strategic goal
page and roadmap. Entries are factual implementation notes, not user-facing
roadmap promises.

## v1.4 Progress

* 2026-06-26: Decision candidate cards now include a localized, symbol-scoped
  handoff to the holding attribution review section. This lets a daily
  candidate continue into the same holding-level attribution boundary used by
  Backtest paper/shadow evidence. It is navigation-only and does not create
  orders, fills, ledger entries, broker submissions, or automatic real-money
  trading.
* 2026-06-26: Web Backtest attribution preview now links directly to the
  matching holding's strategy-attribution review section after paper/shadow
  evidence is generated. The link is localized, symbol-scoped, and anchored to
  the holding attribution boundary so users can continue the single-instrument
  loop without hunting through pages. This is navigation-only: it does not
  create orders, fills, ledger entries, broker submissions, or automatic
  real-money trading.
* 2026-06-26: The `single_instrument_strategy_loop` acceptance audit now
  includes holding-level attribution review readiness. The manifest points to
  the read-only holding attribution API, localized evidence-chain display, and
  deterministic backend/frontend tests that prove symbol-filtered evidence is
  visible before any strategy P/L claim. This does not mutate ledger records,
  submit broker orders, or enable automatic real-money trading.
* 2026-06-25: Web strategy-contribution surfaces now include a stable
  localized explanation that only linked signal, review, order, and fill
  evidence is counted while manual trades and cash flows remain separate.
  Decision summaries also keep contribution status user-readable in English
  and Chinese. Internal strategy identifiers remain secondary audit labels.
  This is display-only and does not change contribution math, attribution
  gates, ledger records, broker submission, or automatic trading behavior.
* 2026-06-25: Added a read-only acceptance audit API surface for
  `single_instrument_strategy_loop` and moved the audit registry / JSON export
  builder into shared analytics code. The Backtest readiness card now fetches
  live audit manifest metadata instead of hardcoding the 8/8 coverage count.
  The API is review-only: it writes no report artifact, does not mutate the
  ledger, does not submit broker orders, and does not enable automatic
  real-money trading.
* 2026-06-25: Web Backtest now surfaces the
  `single_instrument_strategy_loop` acceptance audit coverage directly inside
  the single-instrument readiness card. Users can see the verified
  product-readiness criteria without reading CLI JSON, with explicit wording
  that the audit does not enable broker execution and is not investment advice.
* 2026-06-25: The Data-Trusted Single-Instrument Strategy Loop acceptance
  audit now includes an explicit Web boundary criterion for the post-risk
  paper/shadow next step and the rule that strategy P/L attribution stays
  blocked when production fills are not linked. The capability-based
  `single_instrument_strategy_loop` CLI export covers this evidence without
  introducing broker submission, ledger mutation, or automatic real-money
  trading.
* 2026-06-25: Web Backtest now makes the post-risk paper/shadow step and
  attribution boundary more explicit in the single-instrument research loop.
  Once a risk preview passes, the UI tells users to run paper/shadow simulation
  before any manual step, and attribution preview highlights that strategy P/L
  stays unavailable when no production fill facts are linked. This is
  explanatory UI only; it does not create broker orders, mutate the production
  ledger, or enable automatic real-money trading.
* 2026-06-25: Web Backtest single-instrument loop readiness now includes a
  localized next-review-step guide. After a run produces signal evidence, the
  card tells the user whether to inspect after-cost evidence, wait for signal
  preview, run risk preview, run paper/shadow simulation, or review the
  attribution boundary, without exposing internal reason codes or triggering
  broker execution.
* 2026-06-25: Web Backtest now shows a localized Decision handoff context
  panel when opened from a candidate action with `symbol`, `assetClass`, or
  `strategy` query parameters. The panel summarizes the carried instrument,
  asset class, and strategy and explicitly marks the flow as research-only so
  users can continue from daily candidate review into reproducible after-cost
  research without mistaking it for broker execution.
* 2026-06-25: Decision candidate Backtest evidence links now carry
  single-instrument context through `symbol`, `assetClass`, and `strategy`
  query parameters, and the Web Backtest page reads those values as initial
  form defaults. This lets a daily candidate hand off to a reproducible
  after-cost research run for the same instrument and strategy without manual
  re-entry. It is UI/default-state plumbing only; it does not create signals,
  orders, fills, ledger entries, broker submissions, or change
  automatic-trading defaults.
* 2026-06-25: Decision candidate cards now provide localized handoff links
  from each candidate to Backtest evidence, the single-instrument holding
  detail page, and Trading approvals when manual confirmation is ready. This
  makes the single-instrument strategy loop easier to follow from a daily
  candidate back to research evidence and position context. It is navigation
  only; it does not create signals, orders, fills, ledger entries, broker
  submissions, or change automatic-trading defaults.
* 2026-06-25: Decision workflow task cards now include localized handoff
  links to existing review surfaces for market data, risk review, Strategy
  Lab/backtest evidence, paper/shadow review, and trading approvals. This
  helps the single-instrument strategy loop move from daily decision review
  back to the relevant evidence surface without exposing internal workflow
  codes. It is navigation only; it does not create signals, orders, fills,
  ledger entries, broker submissions, or change automatic-trading defaults.
* 2026-06-25: Web Backtest now renders a localized single-instrument loop
  readiness card for the current result. The card summarizes dataset snapshot,
  strategy registry, after-cost backtest, signal preview, risk gate,
  paper/shadow simulation, and attribution-boundary evidence as user-readable
  review states without exposing internal reason codes. It is display and
  review guidance only; it does not mutate ledger entries, create orders or
  fills, submit broker orders, claim strategy P/L, or change automatic-trading
  defaults.
* 2026-06-25: Added a capability-based acceptance audit manifest and CLI
  registry entry for the data-trusted single-instrument strategy loop. The
  audit covers dataset snapshot and strategy registry evidence, one-symbol
  after-cost backtest, signal preview, risk preview, paper/shadow preview,
  attribution-preview boundary, and localized Web Backtest surfaces. This is
  deterministic audit coverage for the read-only preview chain; it does not
  claim production strategy P/L, mutate ledger entries, submit broker orders,
  or change automatic-trading defaults.
* 2026-06-25: Backtest now exposes a read-only attribution evidence preview
  after the single-symbol signal, risk, and paper/shadow preview chain. The
  backend reports preview evidence counts, production order/fill fact counts,
  evidence refs, next review action, and keeps `can_attribute_pnl=false` until
  real signal, review, order, and fill facts are linked. Web Backtest renders
  the preview boundary after paper/shadow simulation with localized copy. This
  does not write order facts, fill facts, ledger entries, broker submissions,
  or claim strategy P/L.
* 2026-06-25: Backtest now exposes a read-only paper/shadow preview after a
  passed single-symbol risk preview. The backend route builds paper order/fill
  simulation evidence with structured fee breakdown and a shadow-review
  summary without passing a database handle to the paper broker. Web Backtest
  renders the simulated fill, estimated fee, and no-ledger-mutation boundary
  after the user sizes a candidate and runs risk preview. This does not write
  order facts, fill facts, ledger entries, broker submissions, or change
  automatic-trading defaults.
* 2026-06-25: Backtest now exposes a read-only pre-trade risk preview for
  sized single-symbol strategy candidates. The backend route reuses
  `PreTradeRiskManager` rule inputs through a pure preview function and the
  Web Backtest page lets users enter a quantity, run the preview, and see
  localized pass/blocked reasons such as kill-switch status. The response
  explicitly requires manual confirmation and does not create orders, persist
  risk decisions, create fills, mutate ledger entries, submit broker orders,
  or change automatic-trading defaults.
* 2026-06-25: Strategy signal-preview audit records now include a structured
  review-gate chain for data readiness, account truth, pre-trade risk,
  paper/shadow preview, and manual review. Web Backtest renders those gates as
  localized user-facing review states after a single-symbol run, without
  exposing internal reason codes. This is audit and review guidance only; it
  does not run a sized pre-trade order intent, create paper or live orders,
  persist signals, mutate ledger entries, submit broker orders, or change
  automatic-trading defaults.
* 2026-06-25: Added a research-only Backtest signal-preview path that runs a
  registered strategy over explicit single-symbol bars or server-side
  single-symbol date ranges, validates the same parameter schema as backtests,
  and returns strategy-runtime audit records with dataset snapshot and
  data-quality context. Web Backtest now shows the preview after a
  single-symbol research run. Candidate records require downstream risk,
  account-truth, paper/shadow, and manual-review gates and explicitly do not
  enable execution. This preview does not persist signals, create action tasks,
  create paper or live orders, create fills, mutate ledger entries, submit
  broker orders, or change automatic-trading defaults.
* 2026-06-25: Web Backtest equity/drawdown charts now consume saved fill
  records, overlay buy/sell markers, and show a compact marker summary with
  localized side labels, symbol, price, time, and quantity. The markers are
  report display evidence only and do not change strategy math, fills,
  attribution, broker behavior, order submission, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
* 2026-06-24: Backtest validation evidence now shows localized strategy names
  as the primary OOS strategy value and keeps raw strategy ids in a separate
  audit-id field. Backtest strategy snapshot cards follow the same convention:
  primary strategy text is localized and the raw id remains audit metadata.
  Web surfaces no longer consume the combined strategy audit-label helper
  directly, so internal ids stay secondary in Backtest and Decision review
  text. This is display formatting only; it does not change research evidence,
  OOS calculations, strategy ids, broker behavior, order submission, risk
  gates, automatic trading defaults, or manual-confirmation requirements.
* 2026-06-24: Decision candidate cards, candidate evidence chains, and signal
  journal rows now keep localized strategy names as the primary user-facing
  text and show raw strategy ids only as secondary audit ids. This removes
  combined labels such as "strategy name · strategy id" from the main
  decision workflow while preserving traceability. This is display formatting
  only; it does not change decision evidence, signal records, strategy ids,
  broker behavior, order submission, risk gates, automatic trading defaults,
  or manual-confirmation requirements.
* 2026-06-24: Decision strategy-attribution gate summaries now show the
  localized strategy name in the primary status value and move the raw
  strategy id into the detail line as an audit id. This keeps decision
  summaries readable while preserving the review key. This is display
  formatting only; it does not change decision evidence, attribution math,
  strategy ids, broker behavior, order submission, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
* 2026-06-24: Strategy contribution cards now show localized strategy names as
  the primary label and move the raw strategy id into a smaller audit-id line.
  This keeps contribution evidence user-readable while preserving the
  underlying strategy key for review. This is display formatting only; it does
  not change strategy attribution math, evidence gating, strategy ids, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-24: Activity manual-trade preview now keeps generated fee-rule
  notes out of the visible panel once gross amount, commission, stamp tax,
  transfer fee, total fee, net cash impact, fee-rule label, and cost-basis
  method are already shown as structured fields. This is display formatting
  only; it does not change fee calculation, ledger persistence, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-24: Backtest account-strategy and strategy-review tables now use
  localized strategy names as the primary display even when registry metadata
  is incomplete, while strategy ids remain visible only as secondary audit
  keys where needed. This is display formatting only; it does not change
  strategy assignment, strategy ids, attribution math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-24: Public ledger notes now localize raw internal note-code
  segments through the shared ledger formatter instead of rendering backend
  reason-code text in Activity, Overview dashboard, explainability, and
  holding ledger traces. User-authored free-text notes remain unchanged. This
  is display formatting only; it does not change ledger persistence, fee
  calculation, cost-basis math, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
* 2026-06-24: Portfolio positions and holding-detail cost-basis method labels
  now use the shared ledger formatter. Unknown future broker cost-basis method
  ids fall back to localized review copy instead of leaking raw backend codes
  in portfolio cost views, while existing broker displayed cost, projected
  ledger cost, local moving-average cost, difference, and status display stay
  unchanged. This is display formatting only; it does not change cost-basis
  math, ledger projection, broker evidence, fee calculation, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
* 2026-06-24: Shared Web ledger formatting now owns public labels for manual
  fee-rule ids and cost-basis method ids. The Activity manual-trade preview
  consumes those shared labels instead of carrying its own local mapping, so
  configured account fee rules, manual fee overrides, moving-average cost,
  broker displayed remaining cost, and unknown future ids use the same
  localized public fallback path as other ledger evidence. This is display
  formatting only; it does not change fee calculation, cost-basis math,
  ledger persistence, broker behavior, risk gates, automatic trading defaults,
  or manual-confirmation requirements.
* 2026-06-24: Activity manual-trade entry now previews the same configured
  fee contract used by ledger persistence before the user saves a trade. The
  preview shows gross amount, commission, stamp tax, transfer fee, total fee,
  net cash impact, fee-rule label, and cost-basis method while the backend
  preview route deliberately avoids writing trades, ledger entries, or broker
  orders. This is pre-save evidence surfacing only; it does not change ledger
  persistence, broker behavior, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-24: Backtest run-configuration and strategy snapshot copy now
  describes the backend boundary as a user-facing interface boundary and
  labels strategy ids as audit metadata instead of internal implementation
  identifiers. Chinese strategy metadata uses the same audit-id framing. This
  is copy-only and does not change backtest payloads, strategy ids, report
  persistence, strategy math, broker behavior, risk gates, automatic-trading
  defaults, or manual-confirmation requirements.
* 2026-06-24: Shared public-note formatting now localizes Account Truth
  evidence limitation phrases about staged broker evidence and unresolved
  reconciliation review in both English and Chinese. Decision, Backtest,
  Risk, and Account Truth surfaces that consume `formatPublicNote` can reuse
  the same user-readable text instead of leaking backend limitation wording.
  This is display formatting only; it does not change account-truth scoring,
  reconciliation math, broker evidence persistence, API paths, trading
  behavior, risk gates, automatic-trading defaults, or manual-confirmation
  requirements.
* 2026-06-24: Backtest asset-class controls now display localized asset labels
  such as Stock/Fund or 股票/基金 while preserving the backend enum payload for
  API compatibility. Adjacent Backtest asset-entry helper copy was also updated
  to avoid exposing raw `asset_class` field names in user-facing guidance. This
  is display/input guidance only; it does not change strategy math, backtest
  API paths, broker behavior, order submission, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
* 2026-06-24: Saved Backtest dataset-snapshot tables now reuse the shared
  asset-class formatter so report rows display localized labels instead of raw
  backend enum values. The underlying dataset snapshot schema, API payloads,
  report persistence, strategy math, broker behavior, risk gates, and
  manual-confirmation defaults are unchanged.
* 2026-06-24: Backtest Chinese run-configuration copy now describes the
  backend contract as a user-readable interface boundary instead of leaking the
  English implementation term `contract`. This is copy-only and does not change
  request payloads, API paths, strategy math, broker behavior, risk gates,
  automatic-trading defaults, or manual-confirmation requirements.
* 2026-06-24: Shared Web submit-error copy now avoids developer-facing
  payload/server-log wording in both English and Chinese. The router fallback
  uses the same user-readable form/service-status language. This is copy-only
  and does not change form validation, request payloads, API paths, broker
  behavior, risk gates, automatic-trading defaults, or manual-confirmation
  requirements.
* 2026-06-24: Account strategy contribution cards and the Backtest account
  strategy panel now format missing-valuation warnings with readable
  instrument labels from current holdings when available, keeping the symbol
  as secondary audit context and falling back to the raw symbol only when no
  local name is known. This is display-only evidence surfacing; it does not
  change strategy contribution math, valuation data, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-24: Backtest strategy evidence gates now merge promotion-review
  rows with validation-matrix rows, so readiness-only strategies remain
  visible with display names first and internal strategy ids as secondary
  audit labels. This is display-only evidence surfacing; it does not change
  strategy promotion rules, attribution math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-24: Account strategy contribution cards now surface backend
  limitation notes through the shared public-note formatter, so strategy
  contribution estimates explain linked-fill, quote, manual-trade, and
  cash-flow boundaries in user-facing language instead of raw backend
  wording. This is display formatting only; it does not change attribution
  math, strategy assignment, broker behavior, order submission, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
* 2026-06-24: Trading execution audit fill facts now parse structured
  fill metadata and reuse the shared public ledger execution-detail formatter
  for gross amount, net cash impact, quantity, price, commission, stamp tax,
  transfer fee, and other fee display. Internal fee-rule identifiers remain
  hidden from user-facing fill cards. This is display formatting only; it does
  not change fill persistence, order submission, broker behavior, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
* 2026-06-24: Shared dashboard ledger presentation now uses signed structured
  net cash impact as the primary amount when fee evidence is available, while
  preserving gross amount, quantity, price, commission, stamp tax, and
  transfer fee as detail fields. This prevents buy-side ledger cards from
  presenting pre-fee gross amount as the cash movement. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-24: Shared public ledger notes now suppress generated account
  commission configuration remarks when structured fee breakdown or fee-rule
  evidence is already present. This keeps generated fee assumptions out of
  free-text user notes while preserving structured commission, stamp tax,
  transfer fee, other fee, and cash-impact details. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-24: Portfolio position tables now show broker-displayed unit cost
  beside the local moving-average cost when broker cost-basis evidence exists,
  with localized method/status context on both desktop rows and mobile
  metrics. This is a read-only presentation slice; it does not change ledger
  math, cost-basis computation, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
* 2026-06-23: Manual trade fee calculation was extracted into a shared backend
  fee-contract service used by both Portfolio trade creation and direct Ledger
  trade creation. Stock/ETF omitted-fee entries now share the same configured
  commission, stamp-tax, transfer-fee, other-fee, total-fee, fee-rule, and
  note formatting behavior, while explicit user-entered fees are marked with
  the `manual_fee_input` audit rule. This keeps manual trade accounting
  metadata consistent without changing broker behavior, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
* 2026-06-23: Manual ledger trade creation now uses the same structured
  configured fee contract as the Portfolio manual trade path when the caller
  omits an explicit fee. The route preserves commission, stamp tax, transfer
  fee, other fees, total fee, fee-rule id, and net cash impact for stock/ETF
  manual ledger entries, while explicit user-supplied fees continue to use the
  `manual_fee_input` audit marker. This is accounting metadata only; it does
  not submit broker orders, change risk gates, enable automatic trading, or
  bypass manual confirmation.
* 2026-06-23: Shared public ledger notes now suppress generated trade-note
  segments that start with a buy/sell/subscription/redemption action and only
  repeat structured quantity, price, amount, commission, or fee facts. Activity,
  Portfolio holding traces, Overview, and Risk explainability tests cover the
  formatter path so public notes stay reserved for user-authored context while
  core accounting facts remain structured fields. This is display formatting
  only; it does not change ledger storage, accounting math, broker behavior,
  order submission, risk gates, or manual-confirmation defaults.
* 2026-06-23: Shared public ledger explainability titles now treat generated
  Chinese trade titles such as local buy/sell labels followed by a symbol the
  same way as generated English `Bought/Sold` titles. Risk explainability
  events rebuild those titles through the shared ledger formatter, so
  user-facing cards show localized action + instrument name + symbol instead
  of symbol-only generated titles. This is display formatting only; it does
  not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, or manual-confirmation defaults.
* 2026-06-23: Decision strategy-attribution summary tiles now surface
  component-level strategy contribution evidence when the backend provides it:
  net contribution, realized P/L, unrealized P/L, commission, slippage, tax,
  manual movement, cash-flow movement, and excluded movement. Frontend
  coverage pins the user-facing component labels in the decision summary.
  This is display formatting only; it does not change attribution math,
  decision generation, broker behavior, order handling, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Aligned the standalone Account Strategy contribution card with
  the Backtest contribution report by showing realized P/L, unrealized P/L,
  commission, slippage, tax, manual movement, cash-flow movement,
  unattributed movement, and net contribution as localized component fields.
  Frontend coverage verifies the contribution card does not collapse
  strategy performance into a single net value when linked-fill evidence is
  available. This is display formatting only; it does not change attribution
  math, strategy assignment, broker behavior, order handling, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Expanded the Backtest account-strategy contribution report to
  show component-level realized P/L, unrealized P/L, commission, slippage, tax,
  manual movement, cash-flow movement, unattributed movement, and net
  contribution instead of only a compressed net summary. Frontend coverage
  verifies the user-facing contribution breakdown. This is display formatting
  only; it does not change attribution math, strategy assignment, broker
  behavior, order handling, risk gates, or manual-confirmation defaults.
* 2026-06-23: Updated the Backtest strategy snapshot surface so saved reports
  show the localized strategy name before the internal strategy id, while the
  internal id remains available as a secondary audit identifier. The same
  snapshot now localizes asset-universe and frequency codes such as stock and
  daily, and validation notes now fall back to the shared public-note formatter.
  Frontend coverage verifies the Chinese strategy snapshot no longer presents
  "strategy id" as the primary user-facing field or leaks those raw metadata
  codes or raw English validation notes. This is display formatting only; it
  does not mutate persisted reports, strategy metadata, trading behavior, risk
  gates, broker behavior, or manual-confirmation defaults.
* 2026-06-23: Routed Backtest validation-evidence OOS strategy labels through
  the shared strategy audit formatter, so research evidence panels show the
  localized strategy name before the internal strategy id, and added localized
  benchmark-role copy for generic trend-following evidence. The same panel now
  renders assumption and limitation notes through the shared public-note
  formatter. Frontend coverage verifies the OOS evidence panel no longer
  renders a bare strategy id, raw benchmark role, or raw English investment
  advice limitation as the public evidence value. This is display formatting
  only; it does not mutate strategy metadata, research evidence, trading
  behavior, risk gates, broker behavior, or manual-confirmation defaults.
* 2026-06-23: Routed Decision strategy-attribution gate summaries through the
  shared strategy display-name map, so strategy names appear before internal
  ids in user-facing decision evidence. Frontend coverage verifies the gate
  shows the localized strategy label with the internal id secondary. This is
  display formatting only; it does not mutate strategy assignment, broker
  behavior, risk gates, order handling, or manual-confirmation defaults.
* 2026-06-23: Routed Account Truth latest-review notes through the shared
  public operational-note formatter and displayed the localized note under the
  latest review status. Historical backend review notes such as Account Truth
  center audit remarks no longer need to appear as raw English operational
  text in the Chinese review surface. Frontend coverage verifies the localized
  note rendering. This is display formatting only; it does not mutate manual
  review decisions, broker evidence, production ledger entries, trading
  behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Added broker-evidence instrument names to Account Truth
  reconciliation detail responses and routed the review item title through the
  shared instrument display helper, so review cards show the instrument name
  before the symbol when broker evidence provides it. Backend and frontend
  tests cover the detail payload and Account Truth review rendering. This is
  display evidence only; it does not mutate reconciliation math, broker
  evidence, production ledger entries, trading behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Tightened user-facing strategy assignment and simulation-review
  labels across shared public notes, Backtest, and Decision surfaces. Raw
  backend phrases about strategy assignment now render as localized product
  language that explains when strategy contribution can be calculated, and
  paper/shadow evidence labels are presented as simulation-review evidence for
  users. Frontend tests cover the shared formatter plus Backtest and Decision
  rendering. This is display wording only; it does not mutate strategy
  assignment, broker behavior, risk gates, order handling, or
  manual-confirmation defaults.
* 2026-06-23: Added structured trade fields to portfolio explainability
  drivers and timeline events, including quantity, price, commission, gross
  amount, net cash impact, fee rule metadata, and optional fee breakdown.
  Risk explainability now prefers the shared public ledger formatter for these
  structured fields, so generated quantity/price/fee facts are displayed as
  localized execution details instead of being carried as free-text notes.
  Backend and frontend tests cover the API fields and Risk page rendering.
  This is evidence/display formatting only; it does not mutate ledger entries,
  broker evidence, fee models, trading behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Routed Decision signal-queue action details through the shared
  public note formatter so backend research or review phrases are localized
  before being shown in the manual-order handoff surface. Frontend coverage
  verifies the `/api/signals/actions` path in Chinese and keeps the original
  English evidence phrase out of the public UI. This is display formatting
  only; it does not mutate candidate actions, manual-order payloads, broker
  evidence, trading behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Tightened the shared public ledger note formatter so generated
  trade notes that only repeat structured amount, quantity, price, commission,
  or fee facts are suppressed from public note fields while user-authored notes
  remain visible. Overview and Activity tests cover the shared behavior so
  generated ledger remarks do not duplicate structured columns. This is
  display formatting only; it does not mutate ledger entries, broker evidence,
  fee models, trading behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Routed Activity ledger instrument cells through the shared public
  ledger instrument formatter so the audit table shows one consistent
  name-plus-symbol label and keeps the asset-class chip separate, instead of
  rendering a standalone secondary symbol line. Frontend coverage verifies the
  ActivityFeed path for fund and stock rows. This is display formatting only;
  it does not mutate ledger entries, broker evidence, fee models, trading
  behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Added shared localized fallbacks for unknown public status,
  action, and note codes so future backend snake-case values render as generic
  review labels instead of leaking internal names, title-cased raw codes, or
  "unmapped" placeholders into Decision workflow cards and other public
  surfaces. Tests cover the shared formatter and the Decision workflow path in
  Chinese and English. This is display formatting only; it does not mutate
  ledger entries, broker evidence, trading behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Moved Risk/Overview explainability event title and detail
  formatting into the shared public ledger formatter. Generated event titles
  such as buy/sell/cash movement now use the same localized ledger labels,
  instrument-name resolution, and legacy-note suppression as Activity,
  Portfolio, and Account Truth review surfaces. This is display formatting
  only; it does not mutate ledger entries, broker evidence, trading behavior,
  risk gates, or manual-confirmation defaults.
* 2026-06-23: Moved broker trade evidence-reference formatting into the shared
  public ledger formatter and routed the Account Truth review surface through
  it. Broker trade evidence now uses the same localized buy/sell labels as
  ledger activity, while non-trade broker evidence still uses the public
  evidence formatter. This is display formatting only; it does not mutate
  broker evidence, production ledger entries, trading behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Extended the Account Truth review surface to format broker
  trade evidence references with the shared public ledger trade labels instead
  of page-local broker event labels. Review evidence now renders buy/sell
  trade references as the same localized ledger actions used by Activity,
  Overview, Portfolio, Risk, and holding detail, while non-trade broker
  evidence keeps the existing public evidence formatter. The shared ledger
  execution details also accept the full ledger-row shape and suppress zero
  stock-specific fee rows for open-end fund purchases. This is display
  formatting only; it does not mutate broker evidence, production ledger
  entries, trading behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Routed manual Portfolio trade ledger writes through the
  configured stock/ETF fee model when commission is omitted. Ledger entries now
  store structured commission, stamp tax, transfer fee, other fee, total fee,
  and net cash impact while the API response continues to expose the legacy
  commission component for compatibility. Tests cover buy-side transfer fees
  and sell-side tax/fee cash impact. This is ledger evidence alignment only; it
  does not submit broker orders, bypass risk gates, or alter
  manual-confirmation defaults.
* 2026-06-23: Surfaced ledger-projected remaining cost-basis evidence in the
  Web holding-detail valuation panel with separate labels from broker-confirmed
  cost evidence. Holding detail now labels projected values as local
  ledger-derived evidence, keeps broker-confirmed `available` evidence as the
  only state that can trigger a broker cost-basis review warning, and continues
  to show moving-average local cost separately. Frontend tests cover the
  `projected_from_ledger` state and assert it is not rendered as broker
  displayed cost. This is display evidence only; it does not mutate ledger
  entries, submit broker orders, change risk gates, or alter
  manual-confirmation defaults.
* 2026-06-23: Added broker-style remaining cost-basis evidence to deterministic
  portfolio ledger projections. Partial sells now reduce projected
  broker-display-style remaining cost by net proceeds after commission, stamp
  tax, transfer fees, and other structured trade fees, while realized P/L and
  cash continue to use the same net cash impact math. The projected
  cost-basis status is `projected_from_ledger`, not broker-confirmed
  `available`, so UI surfaces can keep imported broker evidence distinct from
  local ledger-derived estimates. This is projection evidence only; it does not
  mutate ledger entries, submit broker orders, change risk gates, or alter
  manual-confirmation defaults.
* 2026-06-23: Added a shared Web instrument display helper and applied it to
  the Decision page's candidate cards, signal action queue, and signal journal
  rows. When backend evidence provides a display name, Decision surfaces now
  show the instrument name before the symbol instead of relying on raw symbols
  or legacy candidate titles. Trading execution-audit order and fill facts now
  reuse the same name-plus-symbol helper and prefer display names carried by
  the execution facts before falling back to current holdings. Activity and
  holding-detail execution details also avoid duplicating net cash impact after
  it has already been shown as the primary signed amount, while keeping gross
  amount, quantity, price, and fee breakdowns structured. Frontend tests cover
  that the user-visible Decision surface renders name-plus-symbol labels and
  does not expose the old internal candidate title as the primary audit label,
  that Trading audit rows use fact-level instrument names, and that public
  execution details avoid repeating cash-impact fields. This is display
  formatting only; it does not submit broker orders, mutate account facts,
  change API paths, or change live-like manual-confirmation defaults.
* 2026-06-22: Started the shared public ledger formatter migration by moving
  ledger instrument, note, amount, and entry-type formatting into a shared Web
  module. Overview, Risk explainability conversion, Activity compatibility
  imports, and holding-detail ledger traces now use the shared formatter path,
  and holding-detail tests prove raw ledger entry types such as internal trade
  codes are not rendered in that surface. This is display formatting only; it
  does not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Upgraded account strategy contribution attribution so fully
  linked strategy fills remain the only source of strategy net contribution,
  while tax, fee, slippage, manual ledger movement, missing-evidence fills, and
  external cash flow are separated into distinct report fields. Deterministic
  backend coverage proves that metadata-only strategy fills and manual trades
  are excluded from net strategy contribution by default. This is attribution
  evidence only; it does not submit broker orders, mutate broker facts, or
  change live-like manual-confirmation defaults.
* 2026-06-22: Added structured trade-cost fields to persisted ledger entries.
  Buy and sell ledger rows can now preserve gross trade amount, signed net cash
  impact, JSON fee breakdown, fee-rule id, fee-rule version, and cost-basis
  method while keeping the legacy `amount` and `commission` fields compatible.
  Manual Portfolio trades and Ledger trade imports populate these fields for
  audit and reconciliation. This is accounting evidence only; it does not
  submit broker orders, mutate broker facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Started Strategy Attribution 2.0 + Broker Fee & Cost Basis
  Fidelity with a structured local broker fee schedule and deterministic fee
  breakdown contract. Ignored `config.json` can now hold safe fee-rule
  parameters such as commission rates, minimum commissions, stamp tax,
  transfer fee, other fee rate, rule id, and known limitations while rejecting
  credential-like fields. `StockACommission` and `ETFCommission` expose
  component-level fee breakdowns while legacy total-fee `calculate()` calls
  remain compatible. This is accounting evidence only; it does not submit
  broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.

## v1.3 Progress

* 2026-06-22: Completed localized frontend coverage for Decision no-action,
  degraded, blocked, and review-required states. The Web Decision page now
  formats lane summary decisions through the shared public-label formatter, so
  Chinese and English surfaces do not expose raw internal decision codes such
  as no-action or review-required state ids. Tests assert that localized
  no-action, degraded account truth, blocked data quality, review-required
  decision state, and no-action reasons remain user-readable. This is display
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.
* 2026-06-22: Added decision certainty evidence for candidate actions so stale,
  cached, estimated, unknown, missing, or unavailable market/account evidence
  cannot appear as a certain actionable suggestion. Decision summaries now
  degrade stale/estimated data to review-required, block missing/unavailable
  evidence, hide manual approval entry points until review is complete, and
  localize certainty reasons and required actions in the Web Decision page.
  This is review evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
* 2026-06-22: Added candidate-level evidence-chain fields and Web rendering for
  strategy source, market data status, account truth, risk status, research
  evidence, paper/simulation evidence, cost impact, uncertainty, and manual
  confirmation state. The surface localizes user-facing labels and keeps
  internal action codes out of the UI. This is review evidence only; it does
  not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
* 2026-06-22: Connected the decision workflow task surface to the Web Decision
  page with localized task labels, status labels, and next-action labels.
  Decision workflow rendering now places data refresh and account truth before
  strategy evidence, paper/shadow review, and manual confirmation, and tests
  assert that internal action codes are not shown to users. This is display
  and review-order evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
* 2026-06-22: Started Professional Decision Workflow with a stable decision
  summary workflow task surface. Daily and intraday decision summaries now
  order data refresh, account truth, risk review, strategy evidence,
  paper/shadow review, and manual confirmation so data and account-truth
  blockers are visible before strategy opportunities. This is API review
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.

## v1.1 Progress

* 2026-06-22: Added shadow review comparison evidence for strategy candidates,
  paper outcomes, and real account movement. The new
  `analytics.shadow_review` report only attributes a real account movement to a
  strategy when candidate id, paper order id, and strategy id references align;
  unsupported movement remains explicitly unattributed with a review action.
  The report is audit evidence only and does not mutate account facts, ledger
  entries, broker orders, or manual-confirmation defaults.
* 2026-06-22: Added an explicit paper OMS state machine with deterministic
  transitions for staged, submitted, accepted, partially filled, filled,
  rejected, cancelled, expired, and reconciled states. Paper order payloads now
  retain full OMS transition evidence in addition to the compact status
  history, and tests cover idempotent repeated transitions plus invalid path
  rejection. The state machine is paper-only review evidence and does not
  submit broker orders, mutate production ledger entries, or change manual
  confirmation defaults.
* 2026-06-22: Added the first Paper Broker & OMS evidence slice. The new
  `execution.paper_broker` module records paper-only order and fill evidence
  into the existing order/fill fact tables with
  `karkinos.paper_broker.v1` payloads, status history, fee/slippage fields, and
  optional strategy, signal, risk decision, dataset, cost model, and
  account-truth references. Tests verify that paper evidence does not mutate
  production ledger entries. This does not introduce broker submission, broker
  credentials, default real-money automation, or any change to manual
  confirmation defaults.

## v1.0 Progress

* 2026-06-22: Completed the v1.0 documentation and backend coverage acceptance
  evidence. The bilingual strategy primer now explains built-in strategy ids,
  parameter meanings, risk assumptions, custom strategy placement under
  `strategy/extensions/` or `KARKINOS_STRATEGY_EXTENSION_DIR`, sanitized
  extension templates, and the non-investment-advice/manual-confirmation
  boundary. Added deterministic documentation coverage tests, and confirmed
  existing backend tests cover lifecycle ordering, read-only runtime context,
  output normalization, extension discovery, and blocked unsafe extension
  manifests.
* 2026-06-22: Added a shared market-calendar contract for Strategy Runtime and
  the Web return calendar. `data.market_calendar` and the Web shared
  `market-calendar` helper expose the same
  `karkinos.market_calendar.v1` schema semantics for trading days, weekends,
  configured market holidays, and configured closed days. Strategy Runtime
  context now carries the calendar as read-only review context, while the Web
  return calendar explains non-trading blank dates as weekend, holiday, or
  closed instead of rendering them as missing prices or zero-return trading
  days. This is calendar explanation evidence only; it does not fetch broker
  data, submit orders, change risk gates, or change manual-confirmation
  defaults.
* 2026-06-22: Tightened the shared Strategy Registry contract for built-in and
  extension strategies. Registry entries and `/api/backtest/strategies` now
  expose the same capability-based contract version, strategy schema version,
  source type, extension flag, parameter schema, validation metadata, and
  research-only execution boundary for both built-in and local extension
  strategies. The boundary explicitly keeps broker order submission disabled
  and requires risk, account-truth, paper/shadow, and manual confirmation gates
  before any candidate could be reviewed. Existing `params` and
  `parameter_schema` fields remain aligned for compatibility.
* 2026-06-22: Added standardized Strategy Runtime output normalization.
  Lifecycle hooks may now return observation signals, buy candidates, sell
  candidates, rebalance candidates, risk warnings, or no-action explanations.
  `StrategyRuntimeRunner` stamps each output with deterministic audit ids,
  hook/source-event references, strategy/run ids, reason text, evidence, and
  downstream gate requirements. Candidate actions explicitly require risk,
  account-truth, paper/shadow, and manual review gates and set
  `does_not_enable_execution=true`, so this contract does not submit broker
  orders or change live-like manual-confirmation defaults.
* 2026-06-22: Hardened the Strategy Runtime context boundary. Runtime context
  now carries account facts, position facts, risk limits, parameters, and
  metadata as recursively frozen read-only mappings, exposes only a false
  `broker_order_submission_enabled` safety flag, and does not provide broker,
  broker-client, or order-submission methods to strategies. Deterministic tests
  prove context immutability and the absence of broker submit capability. This
  does not change existing backtest behavior, broker submission, real-money
  trading defaults, or live-like manual-confirmation requirements.
* 2026-06-22: Added the capability-based Strategy Runtime lifecycle contract.
  `strategy.runtime` now exposes the canonical initialize, before-market, bar,
  tick, after-market, order-update, and fill-update hooks through a deterministic
  runner and audit trace. The contract is exported from the strategy package and
  covered by backend tests for hook vocabulary and invocation order. This does
  not change existing backtest behavior, broker submission, real-money trading
  defaults, or live-like manual-confirmation requirements.

## v0.9 Progress

* 2026-06-22: Added Market Data Reliability acceptance evidence for frontend
  market-data tests. The audit manifest now groups tests for shared
  data-status rendering, Overview estimated valuation labels, return-calendar
  confirmed versus unconfirmed valuation handling, 1D equity-curve missing and
  stale observation behavior, dashboard next actions, and Backtest unconfirmed
  dataset warnings. This is frontend test and audit evidence only; it does not
  change valuation inputs, broker submission, trading behavior, or manual
  confirmation defaults.
* 2026-06-22: Added Market Data Reliability acceptance evidence for backend
  deterministic tests. The audit manifest now groups the adapter normalization
  contract tests, freshness diagnostics tests, manual and scheduled refresh
  boundary tests, and frozen dataset replay determinism tests under the backend
  coverage criterion. This is test and audit evidence only; it does not change
  market-data inputs, broker submission, trading behavior, or live-like manual
  confirmation defaults.
* 2026-06-22: Added Market Data Reliability acceptance evidence for Web
  data-status surfaces. The audit manifest now ties the shared localized
  market-data status formatter to Overview quick actions, Market selected
  symbol detail, Settings valuation notices, Backtest dataset snapshot warnings,
  and the global app-shell status indicators, with tests proving user-facing
  next actions do not leak internal reason codes. This is display and audit
  evidence only; it does not change valuation inputs, broker submission,
  trading defaults, or manual-confirmation behavior.
* 2026-06-21: Tightened the Overview 1D net-value chart missing-observation
  contract. The Web chart now treats `missing` or `error` quote-status points
  as gaps for quote-dependent series (`total`, stocks, funds, and other
  assets) while preserving the cash series and localized quote status in the
  tooltip. This prevents missing intraday observations from being displayed as
  confirmed total or stock/fund values and keeps the chart from fabricating a
  continuous market-data path. This is a display-safety change only; it does
  not change valuation data, broker submission, trading behavior, or manual
  confirmation defaults.
* 2026-06-21: Tightened the backend 1D equity-series missing-observation
  contract. The portfolio equity-series API can now return `null` for
  quote-dependent buckets on missing or error quote observations while keeping
  cash, public quote status, and missing-symbol evidence intact. This prevents
  the API from materializing average-cost or stale baseline values as if they
  were intraday market observations. This is a data-contract safety change
  only; it does not change broker submission, trading behavior, risk gates, or
  manual confirmation defaults.
* 2026-06-21: Hardened return-calendar and explainability conversion for
  nullable valuation points. Equity-series points with missing quote-dependent
  values are now excluded from numeric equity-curve and component-breakdown
  conversion while their valuation status and missing-symbol evidence remain
  available to downstream diagnostics. This prevents missing valuation points
  from crashing attribution surfaces or being displayed as confirmed returns.
  This is a reporting-safety change only; it does not change valuation source
  data, broker submission, trading behavior, risk gates, or manual confirmation
  defaults.
* 2026-06-21: Documented the v0.9 market-data reliability workflow and privacy
  boundary in the user README set. The docs now explain the shared status
  vocabulary, manual and scheduled refresh boundaries, frozen replay datasets,
  local storage boundaries, and that estimated, cached, stale, missing, or
  confirmed-NAV-missing data is data-quality evidence rather than investment
  advice, return guarantee, or execution approval. The market-data acceptance
  audit manifest now includes this documentation evidence.
* 2026-06-21: Extended the shared Web market-data next-action formatter to
  Overview and Market data-status surfaces. Overview now prefers localized
  cache/stale/estimated/missing/confirmed-NAV-missing guidance before showing
  provider fallback actions, while Market exposes the same guidance in both
  the data-health panel and selected-symbol detail. Provider-specific actions
  such as continuing with local cached data remain intact. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
* 2026-06-20: Added a shared Web market-data next-action formatter for
  unconfirmed statuses and connected Settings valuation notices to it. Cache
  and stale states now guide users to refresh quotes or check the data source,
  estimated states guide users to wait for confirmation or refresh, missing
  states guide users to backfill or run first sync, and confirmed-NAV-missing
  states guide users to wait for or sync fund NAV confirmation. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
* 2026-06-20: Added the capability-based Market Data Reliability acceptance
  audit manifest and CLI registry entry. `build_market_data_reliability_acceptance_audit()`
  maps the completed v0.9 data-plane criteria to deterministic evidence paths
  and validation commands, while `scripts/export_acceptance_audit.py --audit
  market_data_reliability` exports the manifest through the shared CI-friendly
  JSON surface. This is audit/reporting evidence only; it does not change
  trading behavior, broker submission, live-like defaults, or manual
  confirmation requirements.
* 2026-06-20: Connected the shared v0.9 market-data status vocabulary to Web
  public labels and the return calendar valuation guard. The Web formatter now
  localizes `confirmed`, `live`, `cache`, `estimated`, `missing`, `stale`, and
  `confirmed_nav_missing` without leaking internal codes, and the return
  calendar treats estimated, cached, stale, or confirmed-NAV-missing periods as
  valuation gaps instead of confirmed returns. The Overview 1D equity curve now
  uses the same localized status text and marks category changes as needing
  confirmation when the underlying valuation point is estimated, cached,
  missing, or otherwise unconfirmed. Historical market bars and daily closes now
  normalize to the shared public `confirmed` status while keeping their source
  evidence separate. Current valuation points preserve explicit shared
  statuses such as `estimated`, `cache`, and `confirmed_nav_missing` instead of
  collapsing them into `live`. Market data health aggregation now preserves a
  full-cache state as `cache` rather than relabeling it as stale, and the
  Overview data-status card plus global toolbar treat cache, estimated,
  missing, partial, stale, and confirmed-NAV-missing states as unconfirmed
  market data instead of healthy live quotes. This changes display semantics
  only; it does not change portfolio data, broker submission, trading
  defaults, or manual-confirmation behavior. The Overview total-assets rail
  also labels estimated, missing, or confirmed-NAV-missing valuation status
  with localized public text instead of showing those figures as confirmed.
  Market research now counts cache, estimated, missing, stale, and
  confirmed-NAV-missing quotes as data needing review through the shared
  frontend status helper, and the user-facing summary uses review-oriented
  wording instead of calling every unconfirmed quote stale. Settings data
  status now uses the same shared helper so estimated, missing, and
  confirmed-NAV-missing valuations are shown as review-required rather than
  healthy confirmed quotes. Backtest dataset snapshots now surface per-symbol
  data status in the report table and show a research-evidence warning when a
  saved report contains unconfirmed market data, so estimated rows are not
  presented as confirmed inputs for after-cost metrics. Frozen replay datasets
  now provide deterministic replay evidence for Strategy Runtime dry-runs,
  including status counts, unconfirmed statuses, required action, and safety
  flags, so estimated replay inputs cannot be treated as confirmed returns.
* 2026-06-20: Added deterministic frozen market-data replay datasets.
  `data.market_data_replay` freezes normalized `MarketDataRecord` values into
  a stable `karkinos.market_data_dataset.v1` payload, computes a deterministic
  dataset fingerprint, and replays records in canonical order for backtest,
  strategy-runtime dry-run, paper/shadow review, and audit replay consumers.
  The frozen dataset carries explicit safety evidence that it does not change
  trading behavior, enable broker order submission, or alter manual
  confirmation defaults.
* 2026-06-20: Added a capability-based market-data refresh contract for manual
  and scheduled refresh flows. `data.market_data_refresh` builds and runs
  auditable refresh tasks for intraday quotes, close-price bars, and fund NAV
  confirmation through the market-data adapter boundary. Each refresh run
  returns trigger, task, refreshed-symbol, failed-symbol, record-count, and
  safety evidence showing that trading behavior, broker order submission, and
  manual-confirmation defaults were not changed.
* 2026-06-20: Added market-data quality diagnostics to the shared v0.9
  contract. `build_market_data_quality_report()` now detects missing expected
  trading sessions, records that appear on configured non-trading days, stale
  quotes, confirmed fund NAV gaps, mixed adjustment modes, and provider price
  differences. The diagnostics return localized messages, deterministic
  pass/degraded/blocked status, and JSON-safe evidence payloads. This is a
  backend data-quality contract only; it does not change broker submission,
  trading defaults, refresh behavior, or manual-confirmation requirements.
* 2026-06-20: Started Data Plane & Market Reliability with a shared market
  data contract. `data.market_data` defines the capability-based
  `MarketDataAdapter` boundary for daily bars, intraday bars, snapshots, ticks,
  and replay records, plus the shared status vocabulary (`confirmed`, `live`,
  `cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`).
  `MarketDataRecord` and `MarketDataRecordMetadata` preserve source, source
  symbol, timestamp, trading session, adjustment mode, freshness metadata, and
  limitations. Deterministic tests cover status normalization, Chinese labels,
  event-kind serialization, and the adapter contract without changing broker
  submission, trading defaults, or manual-confirmation behavior.

## v0.8 Progress

* 2026-06-18: Added the first account strategy assignment and attribution loop.
  `/api/account-strategy` can read and update a research-only assignment while
  forcing `auto_trade_enabled=false`; attribution and contribution endpoints
  link available signal, risk, order, fill, fee, and valuation evidence without
  mutating ledger, broker, order, fill, or position state. Backtest Web now
  starts with the strategy catalog, shows the current account assignment, and
  surfaces attribution/contribution status as audit evidence rather than a
  profitability claim.
* 2026-06-18: Connected strategy attribution readiness into promotion and
  decision gates. Strategy promotion readiness blocks an assigned strategy when
  attribution evidence is pending; Decision summaries and candidate cards now
  surface the strategy-attribution gate and fall back to review-required when
  a strategy-driven candidate lacks linked contribution evidence. Backend and
  frontend deterministic tests cover the degraded decision state and visible
  gate status without changing broker submission, trading defaults, or manual
  confirmation requirements.
* 2026-06-18: Added Strategy Assignment acceptance audit coverage to the shared
  capability registry. `build_strategy_assignment_acceptance_audit()` and
  `scripts/export_acceptance_audit.py --audit strategy_assignment` map the
  completed v0.8 checklist items to deterministic backend, frontend, and
  documentation evidence while leaving unfinished roadmap items visible in
  `docs/ROADMAP.md`.
* 2026-06-18: Completed account, asset-class, and symbol scope handling for
  account strategy assignment updates. Asset-class assignments now persist the
  selected class and filter attribution evidence by matching signal asset
  class, with deterministic route tests covering the boundary.

## v0.7 Progress

* 2026-06-18: Started Account Truth Review Center with read-only review APIs.
  `/api/account-truth/import-runs` lists staged broker import metadata, while
  `/api/account-truth/reconciliation-reports` and
  `/api/account-truth/reconciliation-reports/{import_run_id}` compute report
  summaries and details against current Karkinos ledger, cash, positions,
  fees, taxes, and cost basis. Reconciliation items include item keys,
  severity, broker value, Karkinos value, difference, suggested review action,
  symbol, detail, and broker evidence references. The routes do not mutate the
  production ledger, holdings, broker state, or credentials.
* 2026-06-18: Added the first manual review action API for Account Truth
  differences. `POST
  /api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`
  records `accepted`, `ignored`, `known_difference`, `ledger_candidate`, or
  `needs_investigation` decisions and returns the persisted audit state. Report
  detail responses include the latest review decision per item. Deterministic
  tests verify that recording a `ledger_candidate` does not create production
  ledger entries.
* 2026-06-18: Added the first Web Account Truth Review Center. `/account-truth`
  shows Account Truth Score component reasons, staged import runs, status
  filters for reconciliation reports, per-item broker/Karkinos differences,
  evidence references, and manual review action buttons. `GET
  /api/account-truth/score` exposes the same component-level score evidence to
  the Web UI. Frontend tests cover rendering, status filtering, review action
  submission, score display, and blocked-state presentation; backend tests
  cover the score endpoint and ledger-candidate non-mutation safety.
* 2026-06-18: Surfaced Account Truth gate evidence in Decision and Strategy
  Promotion review surfaces. Decision summaries and candidates now show pass,
  degraded, blocked, or not-evaluated account-truth state with score and
  unresolved-difference context; Strategy Lab promotion readiness shows the
  same gate status and evidence availability. Frontend tests cover degraded and
  blocked decision states plus promotion-gate rendering without changing broker
  submission, production ledger mutation, or manual-confirmation defaults.
* 2026-06-18: Added Account Truth Review Center acceptance audit coverage.
  `build_account_truth_review_acceptance_audit()` maps the v0.7 review
  workflow checklist to deterministic backend, frontend, documentation, and CLI
  evidence. `scripts/export_acceptance_audit.py --audit account_truth_review`
  exports the manifest through the shared capability registry without using a
  roadmap version in function, file, or CLI names.

## v0.6 Progress

* 2026-06-17: Started Account Truth with a canonical broker statement CSV
  contract and read-only import preview parser. The parser normalizes local CSV
  rows into broker evidence preview events, validates required columns and
  event types, computes file-level and row-level SHA-256 fingerprints, reports
  deterministic duplicate rows, and records limitations that the preview does
  not mutate the production ledger or enable broker submission. README and
  Chinese docs now describe the import workflow, privacy boundary, and safe
  synthetic examples.
* 2026-06-17: Added staged broker evidence persistence for valid import
  previews. `BrokerEvidenceRepository` creates local `broker_import_runs` and
  `broker_evidence_events` tables, stores source type, file fingerprint, row
  counts, validation status, duplicate counts, timestamps, limitations, and
  typed evidence events for trades, dividends, fees, taxes, transfers,
  position snapshots, and cash snapshots. Duplicate files are recorded as
  warning import runs without duplicating evidence rows, and deterministic
  tests verify the production ledger is not mutated.
* 2026-06-17: Added the first deterministic reconciliation report core.
  `build_reconciliation_report()` compares staged broker evidence against
  Karkinos cash, positions, ledger fees, ledger taxes, and position cost basis,
  returning versioned `pass`, `warning`, `mismatch`, or `blocked` reports with
  per-category differences and suggested review actions. The report remains
  evidence only; it does not write ledger entries, change holdings, or submit
  broker orders.
* 2026-06-17: Added manual review persistence for reconciliation items.
  `ManualReviewRepository` records `accepted`, `ignored`, `known_difference`,
  `ledger_candidate`, and `needs_investigation` decisions keyed by import run
  and reconciliation item. Decisions are idempotent audit notes only;
  `ledger_candidate` does not create production ledger entries without a
  future explicit confirmation path.
* 2026-06-17: Added deterministic Account Truth Score generation.
  `build_account_truth_score()` converts reconciliation report status, manual
  review decisions, account/data freshness, and unresolved cash, position, fee,
  tax, and cost-basis differences into a versioned 0-100 score with
  `pass`, `degraded`, or `blocked` gate status, required actions, blocking
  reasons, and limitations. The score is report/gate evidence only and does
  not mutate ledger, holdings, or broker state.
* 2026-06-17: Connected Account Truth Score evidence to strategy promotion
  readiness. `build_strategy_promotion_readiness()` can now consume explicit
  account-truth score evidence; `degraded`, `blocked`, or explicitly missing
  account-truth evidence adds an `account_truth_gate_pass` missing requirement
  while legacy callers that do not pass score evidence remain unchanged.
* 2026-06-17: Connected Account Truth Score evidence to Decision Cockpit.
  `/api/decision/today` and `/api/decision/intraday` now include
  account-truth gate evidence in summaries and candidates. Missing,
  `degraded`, or `blocked` account-truth evidence changes actionable
  candidates to `review_required` and prevents live-like manual-confirm
  readiness without changing broker submission or ledger mutation behavior.
* 2026-06-17: Added Account Truth acceptance audit coverage and CLI registry
  wiring. `build_account_truth_acceptance_audit()` maps all Account Truth and
  reconciliation acceptance criteria to concrete code, docs, deterministic
  tests, and validation commands. `scripts/export_acceptance_audit.py` now
  supports `--audit account_truth` and includes it in `--audit all` without
  using roadmap-version names or writing artifacts by default.

## v0.5 Progress

* 2026-06-17: Added a research evidence acceptance audit manifest.
  `build_research_evidence_acceptance_audit()` maps all completed
  Quant Research Quality & Production Evidence Hardening checkboxes to
  concrete code, docs, deterministic tests, and validation commands without
  changing execution defaults or schema versions.
* 2026-06-17: Started v0.5 by adding target, scope, acceptance criteria, and a
  dedicated progress section for research evidence hardening. The first backend
  implementation slice is a minimal versioned `ResearchEvidenceBundle` and
  analyzer contract for existing backtest runs, without changing Web UI or
  execution behavior.
* 2026-06-17: Implemented the first v0.5 backend evidence slice. Single
  backtest runs now attach `research_evidence_bundle` to `metrics_json` and
  saved report files. The bundle is versioned, includes deterministic analyzer
  outputs for data quality, after-cost evidence, and OOS presence, records
  China-market assumption gaps, and keeps promotion status as human review
  evidence without enabling execution behavior.
* 2026-06-17: Extended the evidence bundle surface to Strategy Lab sweeps and
  comparisons. Each sweep result and comparison item now exposes the same
  `research_evidence_bundle` contract that is persisted in the saved
  `metrics_json`, so multi-run research outputs can be audited without looking
  up each saved result manually.
* 2026-06-17: Connected research evidence gates to promotion readiness.
  Strategy promotion readiness now reads each saved backtest result's
  `research_evidence_bundle.promotion_gate.status`; degraded or blocked
  evidence adds a `research_evidence_gate_pass` missing requirement even when
  after-cost/OOS, risk, paper/shadow, and divergence evidence are otherwise
  present. This keeps shadow/paper eligibility behind the v0.5 evidence gate.
* 2026-06-17: Added explicit evidence references and trade statistics to the
  research evidence bundle. Backtest evidence now records dataset snapshot
  references, strategy metadata availability, after-cost and OOS evidence
  availability, cost-summary availability, fill and trade counts, turnover,
  commission, slippage, and limitation counts so saved reports can be audited
  from one versioned artifact without enabling execution behavior.
* 2026-06-17: Added deterministic rolling OOS evidence for Strategy Lab
  experiments. Backtest requests can now ask for rolling OOS folds over a
  frozen equity curve, producing fold-level train/test evidence, aggregate
  pass rate, worst and mean out-of-sample return, and total OOS cost. The
  research evidence bundle's OOS analyzer summarizes rolling mode, fold count,
  and aggregate fields while explicitly noting that rolling evidence does not
  refit parameters per fold or enable execution behavior.
* 2026-06-17: Added parameter sweep robustness evidence. Sweep responses now
  include a versioned robustness artifact with the best parameter set, local
  neighbor stability, per-parameter sensitivity ranges, grid-grounded
  overfitting warnings, and limitations requiring after-cost, OOS, risk, and
  data-quality review before any promotion consideration.
* 2026-06-17: Exposed research evidence bundles as first-class API and report
  artifacts. Single backtest responses and saved JSON reports now surface the
  same `research_evidence_bundle` at top level while retaining the nested
  `metrics_json` copy for compatibility. README and Chinese docs now explain
  `pass`, `degraded`, and `blocked` gate states, required review evidence, and
  the boundary that evidence does not enable broker order submission.

## Earlier Progress

* 2026-06-17: Added a per-instrument daily PnL entry point. Portfolio positions
  now carry `today_change`, `today_change_pct`, daily baseline price, baseline
  timestamp, and baseline source through the same API used by the holdings
  table and holding detail page. The Web cockpit shows single-stock/fund daily
  PnL beside quote price, market value, since-buy PnL, and baseline evidence,
  so account-level daily movement can be traced back to individual holdings
  without adding broker submission or execution behavior.
* 2026-06-17: Documented portfolio return-accounting semantics. Added a
  Chinese guide for daily PnL, since-buy floating PnL, realized PnL, cash-flow
  treatment, and baseline-price priority so future cockpit and API work can
  keep cost basis, market movement, and external flows separated.
* 2026-06-16: Cleaned Risk explainability notes and top-panel layout. Risk
  recent impact cards and timeline events now route their details through the
  shared Web ledger public-note formatter, suppressing legacy internal notes
  while preserving user-authored English notes elsewhere. The Risk
  explainability top grid now aligns panels at the top and keeps the
  recent-impact list in a local scrollable region.
* 2026-06-16: Fixed Risk explainability event readability so recent impact
  events and timeline trade events use the shared instrument identity metadata
  path instead of rendering raw symbols or internal action strings.
* 2026-06-16: Fixed the Overview 1D equity-curve cash path so same-day ledger
  events are replayed at their ledger timestamp instead of being projected back
  to the market open.
* 2026-06-16: Fixed the Overview 1D equity-curve tooltip path so category
  point-in-time changes are supplied by backend `*_daily_change` fields
  instead of being inferred from the first visible chart point.
* 2026-06-16: Confirmed the v0.2/v0.3/v0.4 acceptance checkboxes had no
  remaining unchecked items, then added a data integrity slice for provider
  reconciliation through deterministic local-cache-vs-provider OHLCV reports.
* 2026-06-16: Made historical OHLCV storage explicitly SQLite-first for local
  audit and query paths while retaining Parquet as a local mirror.
* 2026-06-15: Added a v0.4 Strategy Lab acceptance audit and marked the v0.4
  acceptance criteria complete.
* 2026-06-15: Split Strategy Lab after-cost report assumptions into structured
  cost and slippage evidence.
* 2026-06-15: Reduced raw Strategy Lab parameter-key exposure in the Web
  Backtest comparison panel.
* 2026-06-15: Surfaced persisted Strategy Lab metadata in saved Web Backtest
  reports.
* 2026-06-15: Persisted Strategy Lab strategy metadata snapshots on saved
  backtest reports.
* 2026-06-15: Added Strategy Lab strategy metadata and readable parameter
  labels to the Web Backtest page.
* 2026-06-15: Added the Web Strategy Lab same-dataset comparison review
  surface.
* 2026-06-15: Added a same-dataset Strategy Lab comparison contract.
* 2026-06-15: Added Web Backtest parameter-sweep review.
* 2026-06-15: Added a Web Backtest validation-evidence report panel.
* 2026-06-15: Surfaced Backtest dataset snapshots in the Web report.
* 2026-06-15: Added dataset snapshot metadata to the single Backtest runner.
* 2026-06-15: Refined the Web Backtest strategy-parameter experience for
  Chinese users.
* 2026-06-15: Added the first backend Strategy Lab parameter-sweep API.
* 2026-06-15: Made local Strategy Lab extension scripts runnable through the
  Backtest API path.
* 2026-06-15: Localized Web Backtest strategy parameter labels and
  descriptions while preserving stable API parameter ids.
* 2026-06-15: Fixed the Web Backtest initial-cash control browser validation
  contract.
* 2026-06-15: Added the first local Strategy Lab extension area.
* 2026-06-15: Wired the Web Backtest page to the strategy registry.
* 2026-06-15: Started v0.4 Strategy Lab backend parameter contracts.
* 2026-06-15: Added the v0.4 Strategy Lab Backtesting Engine target to the
  project goal.
* 2026-06-12: Removed the Activity batch fund form's built-in fund candidates.
* 2026-06-12: Exposed latest risk-gate outcomes on signal action cards.
* 2026-06-12: Added a deterministic Profit Discipline smoke path covering
  fixture data cache metadata, feature calculation, after-cost backtest report,
  generated signal, mandatory pre-trade risk gate, action queue risk summary,
  and signal journal audit chain.
* 2026-06-12: Tagged registered strategies with v0.2 benchmark metadata.
* 2026-06-12: Added reusable out-of-sample validation evidence for completed
  backtests.
* 2026-06-12: Wired OOS validation evidence into the backtest run path.
* 2026-06-12: Added a deterministic v0.2 strategy validation matrix.
* 2026-06-12: Added fixture-backed validation backtests for all v0.2 benchmark
  strategies.
* 2026-06-12: Exposed the v0.2 strategy validation matrix through the backtest
  API.
* 2026-06-12: Added a portfolio cockpit API surface.
* 2026-06-12: Made action-card risk gate state explicit.
* 2026-06-12: Added manual-confirmation readiness to action cards.
* 2026-06-12: Added the first action-to-manual-order execution bridge.
* 2026-06-12: Linked manual order decisions back into the signal journal.
* 2026-06-12: Added a deterministic daily paper/shadow run endpoint.
* 2026-06-12: Added a signal journal review/outcome endpoint.
* 2026-06-12: Made the CI contract explicit for Profit Discipline MVP gates.
* 2026-06-12: Added a strategy promotion readiness surface.
* 2026-06-12: Added a paper/shadow divergence review write path.
* 2026-06-12: Added a v0.2 acceptance audit manifest and aligned the goal
  checklist with deterministic evidence.
* 2026-06-12: Started v0.3 shadow-trading reliability work with schema
  versioning and idempotent same-date/action order facts.
* 2026-06-12: Added the first v0.3 data-quality gate to daily shadow runs.
* 2026-06-12: Started the Daily + Intraday Decision Cockpit API surface.
* 2026-06-12: Added the first read-only intraday decision lane.
* 2026-06-12: Attached persisted strategy validation evidence to decision
  candidates.
* 2026-06-12: Added current-state aggregation to decision summaries.
* 2026-06-12: Added the first frontend Decision Cockpit surface.
* 2026-06-12: Added a deterministic v0.3 Decision Cockpit acceptance path.
* 2026-06-12: Completed the v0.3 checklist audit.
* 2026-06-12: Fixed Web cockpit responsive containment.
* 2026-06-14: Improved portfolio analysis responsiveness and audit surfaces.
* 2026-06-14: Moved the return calendar into the Overview cockpit.
* 2026-06-14: Improved the Overview return-calendar empty state.
* 2026-06-14: Consolidated the Overview performance module.
* 2026-06-14: Polished the Overview return-calendar fallback language and
  holdings display.
* 2026-06-14: Connected explainability attribution to deterministic daily
  portfolio valuation when historical price cache is available.
* 2026-06-14: Tightened the return-calendar attribution contract.
* 2026-06-14: Aligned the return calendar with China-market non-trading day
  semantics.
* 2026-06-14: Fixed return-calendar valuation-gap attribution.
* 2026-06-14: Connected return-calendar daily valuation to the authoritative
  local OHLC cache.
* 2026-06-14: Added traceable daily-change breakdowns to the return calendar.
* 2026-06-14: Clarified ledger and holding labels in the web cockpit.
* 2026-06-15: Tightened current-day return attribution and ledger naming.
* 2026-06-15: Separated current valuation from audited return-calendar
  attribution.
* 2026-06-15: Tightened live quote freshness semantics for fund estimates.
* 2026-06-15: Made TuShare fund permission fallback auditable in the cockpit.
* 2026-06-15: Added a Settings data-source operations surface.
* 2026-06-15: Tightened the Settings cockpit density around backend operations.
* 2026-06-15: Added Settings runtime-boundary and safety-register surfaces.
* 2026-06-15: Began cockpit-density cleanup on the Decision page.
* 2026-06-15: Reworked the Risk page summary into boundary and blocking
  registers.
* 2026-06-15: Standardized portfolio return percentages to two decimal places.
* 2026-06-15: Clarified the Portfolio holdings quote board summary cards.
* 2026-06-15: Deduplicated the Portfolio holdings quote board detail surface.
* 2026-06-15: Split Portfolio quote summaries from instrument detail.
* 2026-06-15: Redesigned the Portfolio positions entry affordance.
* 2026-06-15: Upgraded the holding-detail and Market price-structure surface
  from a compact sparkline into a K-line chart with selectable ranges.
* 2026-06-15: Tightened the holding-detail page header.
* 2026-06-15: Added account-level manual trade commission configuration.
* 2026-06-15: Fixed return-calendar detail labels for aggregated periods.
* 2026-06-18: Added research-only account strategy assignment and attribution
  evidence surfaces without enabling automatic trading.
* 2026-06-18: Added a strategy contribution estimate API and Backtest surface
  that separates linked-fill unrealized P/L, commission, slippage, and net
  contribution while excluding manual trades, cash flows, and missing-evidence
  movement by default.
* 2026-06-18: Added five-tier Backtest P/L attribution status copy for account
  strategy evidence: not started, partial, stale, blocked, and complete.
* 2026-06-18: Extended account strategy attribution evidence references across
  signal, action, risk, review, order, and fill records.
* 2026-06-18: Added evidence-gated strategy contribution surfaces to Overview
  and Portfolio while reusing Backtest and Decision attribution gates.
* 2026-06-22: Fixed return-calendar valuation status semantics so live,
  confirmed, and complete periods display returns normally; cache, stale,
  estimated, and confirmed-NAV-missing periods display returns with an
  unconfirmed marker; and only missing or unavailable prices render as
  valuation gaps.
* 2026-06-22: Added acceptance-audit evidence for the 1D net-value chart
  contract. Existing frontend and backend deterministic tests now prove that
  the 1D chart can show intraday market movement, cash-flow changes,
  stock/fund movement, fund confirmation state, stale status, and missing
  quote-dependent observations without fabricating values. This is audit
  wiring only; it does not change broker submission, trading behavior, risk
  gates, or manual-confirmation defaults.
* 2026-06-22: Completed the v1.1 paper broker and OMS backend coverage slice.
  Paper broker tests now cover paper-only fills, partial fills, cancellations,
  rejections, slippage, fee/tax cost modeling, and OMS idempotency without
  mutating the production ledger or introducing broker order submission.
* 2026-06-22: Started v1.2 Broker Evidence Connector with a capability-based
  read-only connector contract and deterministic fake connector fixtures for
  account, cash, position, order, fill, and health facts. The connector surface
  does not expose broker order submission.
* 2026-06-22: Added local read-only broker connector configuration parsing for
  ignored `config.json`. Connector config accepts client path and account alias
  only, rejects password/secret/token/credential fields, and keeps source
  examples synthetic.
* 2026-06-22: Added read-only broker connector evidence normalization. Synthetic
  connector snapshots now convert fills, cash snapshots, and position snapshots
  into staged broker evidence that can feed reconciliation without mutating the
  production ledger or enabling broker order submission.
* 2026-06-22: Wired staged broker evidence into shared Account Truth gate
  construction. Decision summaries and Strategy Lab promotion readiness now
  block when latest read-only broker evidence reconciles to unresolved material
  differences, while preserving manual-confirm-only live-like behavior.
* 2026-06-22: Added deterministic fake connector evidence-state coverage for
  healthy, disconnected, stale, permission-limited, duplicate, and incomplete
  snapshots. Disconnected snapshots now block without emitting stale evidence
  rows, incomplete snapshots surface explicit diagnostics, and duplicate
  connector rows are marked deterministically. This remains read-only broker
  evidence and does not submit broker orders, mutate production ledger entries,
  or change manual-confirmation defaults.
* 2026-06-22: Completed the v1.2 broker evidence reconciliation detail slice.
  Canonical broker statement previews and staged evidence now preserve optional
  transfer-fee and broker cost-basis method fields. Reconciliation reports
  expose trade gross amount, signed net cash impact, fee, tax, transfer-fee,
  and cost-basis differences as reviewable items. This is audit evidence only;
  it does not mutate production ledger entries, submit broker orders, or change
  manual-confirmation defaults.
* 2026-06-22: Added shared public formatting for generated Trading manual-order
  notes. Decision-generated order notes now render as user-readable copy on
  Trading queue and audit surfaces without exposing internal action ids; order
  execution behavior and manual-confirmation defaults are unchanged.
* 2026-06-22: Moved the Overview latest-ledger cards onto the shared public
  ledger formatter for entry titles, instrument labels, and cleaned public
  notes. Legacy note prefixes and technical note segments remain hidden from
  the user-facing ledger cards.
* 2026-06-22: Stopped Decision manual-order preparation from writing internal
  signal action ids into order notes. Prepared manual orders now use the
  shared public queue note from the Trading API hook while preserving manual
  confirmation and broker-submit defaults.
* 2026-06-22: Localized Decision signal-journal audit event labels on
  user-facing candidate and journal surfaces. Dotted internal event keys remain
  backend audit identifiers, while the Web UI now shows public event copy
  without changing signal, journal, risk-gate, or manual-confirm behavior.
* 2026-06-22: Connected Risk explainability recent-driver and timeline titles
  to the shared public ledger formatter for generated ledger kinds. Internal
  ledger kind values such as cash-flow entry types now render as localized
  public titles while existing human-authored titles are preserved. This is UI
  formatting only; it does not change risk computation, ledger facts, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Account Truth review evidence references for
  user-facing reconciliation items. Broker evidence ids now render as readable
  source, subject, event-type, and import-run labels instead of raw
  machine-formatted reference strings. This is review-surface formatting only;
  it does not change import parsing, reconciliation, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Account Truth reconciliation item categories on the
  Web review surface. Difference cards now display public labels such as cash,
  position, fee, and cost basis through the shared public-label formatter
  instead of rendering raw backend category fields. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Replaced Account Truth reconciliation report summary shorthand
  such as raw cash/fee delta labels with localized public labels for cash
  difference and fee difference. This is report-summary display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Localized generated Account Truth reconciliation detail copy on
  the Web review surface. Known backend-generated reconciliation explanations
  now pass through the shared public-note formatter in Chinese locale instead
  of exposing English operational sentences. This is detail-text display
  formatting only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Added stable Account Truth reconciliation detail codes alongside
  the legacy detail text. Reconciliation item generation and the Account Truth
  report API now expose a machine-stable `detail_code`, and the Web review
  surface prefers that code for localized public-note rendering while keeping
  old `detail` payloads as fallback. This is an additive review-surface
  contract change only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Structured dynamic Account Truth reconciliation detail context
  for broker cost-basis method evidence. Cost-basis reconciliation items now
  expose `detail_context` for values such as the broker cost-basis method, and
  the Web review surface renders those context fields as localized labels and
  values instead of exposing raw method codes in generated detail text. This is
  an additive review-surface contract change only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Added category-aware numeric formatting to Account Truth
  reconciliation item values on the Web review surface. Position differences
  now show share units, cost-basis differences show four-decimal CNY price
  values, and cash/fee/tax-like differences use CNY amount formatting instead
  of unqualified raw numbers. This is display formatting only; it does not
  change reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Extended Account Truth report summaries to use the same
  category-aware money formatting for cash and fee differences. Report cards
  now display localized CNY amounts instead of raw decimal strings while the
  reconciliation report payload remains unchanged. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
* 2026-06-22: Added tax-difference visibility to Account Truth reconciliation
  report summary cards. Existing `tax_difference` payload values now render as
  localized CNY amounts alongside cash and fee differences, making fee/tax
  evidence visible without changing the reconciliation payload or accounting
  calculations. This is display formatting only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Extended the shared public ledger formatter to render structured
  trade cost facts on Web ledger surfaces. Activity and Overview ledger rows
  can now show gross trade amount, signed net cash impact, commission, stamp
  tax, transfer fee, and localized cost-basis method labels from structured
  fields instead of hiding those facts in notes. This is display formatting
  only; it does not change ledger persistence, fee calculation, trading,
  broker behavior, or manual-confirmation defaults.
* 2026-06-22: Moved holding-detail ledger traces onto the same structured
  ledger cost formatter used by Activity and Overview. Holding detail now
  exposes gross amount, signed net cash impact, commission, stamp tax,
  transfer fee, and localized cost-basis method labels from structured ledger
  fields while keeping public notes separate. This is display formatting only;
  it does not change ledger persistence, fee calculation, trading, broker
  behavior, or manual-confirmation defaults.
* 2026-06-22: Localized Risk explainability ledger fallback details for
  generated cash-flow and ledger adjustment events. Risk review surfaces now
  use the active Web language for public fallback descriptions after shared
  ledger-note cleanup removes internal import notes. This is display
  formatting only; it does not change risk math, ledger persistence, trading,
  broker behavior, or manual-confirmation defaults.
* 2026-06-23: Moved Backtest strategy validation rows to use localized
  strategy display names as the primary label while keeping strategy ids as
  secondary audit metadata. This makes research-gate status easier to read
  without changing strategy execution, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Moved Decision candidate strategy evidence to the same
  user-facing strategy display-name convention. Candidate cards and evidence
  chains now show localized strategy names first while preserving internal
  strategy ids as secondary audit metadata. This is display formatting only; it
  does not change decision generation, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Added strategy identity to the Web strategy contribution report
  using localized display names first and internal strategy ids as secondary
  audit metadata. This makes contribution evidence attributable to a readable
  strategy without changing attribution math, ledger facts, broker behavior,
  trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Extracted shared Web strategy display formatting for readable
  strategy names and secondary audit ids. Backtest, Decision, and Strategy
  Contribution surfaces now use the same formatter instead of page-local
  copies. This is display formatting only; it does not change strategy
  execution, attribution math, ledger facts, broker behavior, trading, risk
  gates, or manual-confirmation defaults.
* 2026-06-23: Risk explainability events now hydrate shared ledger formatting
  with instrument names from the current account snapshot. Generated broker or
  ledger event titles that only carry a symbol now render readable name +
  symbol labels in recent drivers, timeline events, and position drivers. This
  is display formatting only; it does not change risk math, ledger
  persistence, broker behavior, trading, risk gates, or manual-confirmation
  defaults.
* 2026-06-23: Localized Risk blocking-register alert kinds so user-facing risk
  cards show readable labels such as cash buffer instead of raw internal codes.
  This is display formatting only; it does not change risk calculations,
  trading, broker behavior, risk gates, or manual-confirmation defaults.
* 2026-06-23: Localized Risk blocking-register severity labels so user-facing
  alert badges show review labels such as warning instead of raw severity
  codes. This is display formatting only; it does not change risk
  calculations, trading, broker behavior, risk gates, or manual-confirmation
  defaults.
* 2026-06-23: Promoted cash-interest ledger entries to first-class cash income
  in portfolio projection, explainability timeline flow breakdown, and the
  shared public ledger formatter. Activity now reuses shared action titles,
  short labels, signed amounts, and cash-impact semantics instead of
  page-local ledger type branches. This changes cash-interest classification
  from market movement to income flow where evidence exists; it does not change
  ledger persistence, fee math, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Moved holding-detail ledger traces onto the shared public ledger
  activity summary for action titles, cash-impact wording, and signed primary
  amounts while keeping structured gross amount, net cash impact, fee, tax, and
  transfer-fee lines visible. Cost-basis method is no longer mixed into
  execution detail lines and should remain in dedicated cost-basis views. This
  is presentation alignment only; it does not change ledger persistence, fee
  math, broker behavior, trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Updated portfolio projection cost math to consume structured
  trade fee breakdowns when present, including commission, stamp tax, transfer
  fee, and other fee components. This keeps local moving-average buy cost and
  cash projection aligned with the same ledger fee evidence shown in user
  surfaces. It does not mutate ledger entries, change broker behavior, submit
  orders, bypass risk gates, or alter manual-confirmation defaults.
* 2026-06-23: Added Portfolio holding-detail support for broker-facing
  cost-basis evidence when the position API provides it. The Web detail view
  now distinguishes local moving average cost, broker displayed unit cost,
  broker displayed cost basis, localized cost-basis method, and the difference
  between broker and local cost-basis totals. The positions API can carry these
  optional evidence fields without mutating ledger entries. This is
  presentation and payload-surface work only; it does not change projection
  math, reconciliation decisions, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Hydrated Portfolio position cost-basis fields from staged broker
  evidence when no explicit broker cost-basis fields are already attached to
  the projected position. The positions API now reads the latest imported
  position snapshot cost basis from Account Truth evidence and derives broker
  displayed unit cost, broker displayed total cost basis, local-vs-broker
  difference, method, and availability status. This uses already-imported
  evidence only; it does not read broker credentials, mutate the production
  ledger, submit orders, bypass risk gates, or change manual-confirmation
  defaults.
* 2026-06-23: Added a Portfolio holding-detail cost-basis review prompt when
  broker displayed cost evidence differs from Karkinos local moving-average cost
  by a material display threshold. The prompt is localized and points users back
  to Account Truth evidence before relying on cost-basis P/L. This is
  presentation-only audit guidance; it does not change ledger math, broker
  behavior, trading, risk gates, or manual-confirmation defaults.
* 2026-06-23: Moved the Activity page net-cash-impact summary onto the shared
  public ledger summary formatter. The page now respects structured
  `net_cash_impact` evidence and first-class cash-interest entries instead of
  using a local `entry_type` branch. This is UI summary alignment only; it does
  not mutate ledger entries, change broker behavior, submit orders, bypass risk
  gates, or alter manual-confirmation defaults.
* 2026-06-23: Extended the shared public ledger execution-detail formatter so
  holding details, Activity audit rows, and Risk explainability cards show
  structured net cash impact alongside gross amount, quantity, price, and fee
  evidence. This is display formatting only; it does not mutate ledger entries,
  change fee calculation, change broker behavior, submit orders, bypass risk
  gates, or alter manual-confirmation defaults.
* 2026-06-23: Updated the Risk page manual approval table to resolve
  instrument display names from the same portfolio position evidence used by
  the Trading page, so pending manual approvals show readable name + symbol
  labels instead of symbol-only rows. This is presentation-only; it does not
  change order approval, rejection, broker behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Added explicit public labels for reconciliation fee, tax, gross
  amount, net cash impact, and transfer-fee categories so Account Truth review
  cards show specific user-facing difference types instead of generic fallback
  labels. This is label formatting only; it does not change reconciliation
  math, review decisions, ledger mutation, broker behavior, risk gates, or
  manual-confirmation defaults.
* 2026-06-23: Paper broker fill metadata now records the structured fee
  breakdown produced by the shared commission contract, including commission,
  stamp tax, transfer fee, other fees, fee rule ID, and known limitations while
  preserving the legacy total commission field for compatibility. This is
  paper-only simulation evidence; it does not mutate the production ledger,
  submit broker orders, bypass risk gates, or alter manual-confirmation
  defaults.
* 2026-06-23: Decision candidate cards now pass backend detail notes through
  the shared public-note formatter before rendering, matching the existing
  signal action queue behavior. This prevents internal strategy-assignment
  evidence phrases from leaking into localized user-facing action cards. This
  is display formatting only; it does not change decision generation, risk
  gates, broker behavior, order submission, or manual-confirmation defaults.
* 2026-06-23: Risk blocking-register detail text now uses the shared
  public-note formatter, and Account Truth review tests pin specific
  reconciliation action-code localization. This prevents internal market data
  and review codes from appearing in localized review surfaces. This is
  display formatting and regression coverage only; it does not change risk
  calculations, reconciliation math, broker behavior, order submission, or
  manual-confirmation defaults.
* 2026-06-23: Account strategy contribution reports now expose a derived
  strategy-health status with `healthy`, `degraded`, `stale`, `paused`, and
  `needs_review` states, plus machine-readable reasons. The Web strategy
  contribution card renders the health status with localized labels. This is
  a read-only evidence and display slice; it does not change strategy
  assignment, contribution math, risk gates, broker behavior, order
  submission, or manual-confirmation defaults.
* 2026-06-23: Overview ledger cards now use a shared ledger dashboard
  presentation formatter for action titles, structured details, amounts, and
  public notes instead of local one-off formatting helpers. This continues the
  v1.4 shared public ledger formatter work without changing ledger storage,
  accounting math, broker behavior, order submission, or manual-confirmation
  defaults.
* 2026-06-23: Shared public ledger notes now suppress generated cash and
  dividend remarks when the same amount and entry type are already available
  as structured ledger fields. This keeps core accounting facts such as cash
  interest amounts out of free-text public notes while preserving user-authored
  notes. This is display formatting only; it does not change ledger storage,
  accounting math, broker behavior, order submission, or manual-confirmation
  defaults.
* 2026-06-23: Risk/explainability ledger details now reuse the shared
  execution-detail formatter for non-trade cash and dividend events, so
  generated cash movements expose structured amounts instead of generic
  fallback text or legacy English operational notes. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, or manual-confirmation defaults.
* 2026-06-23: Account Truth review now localizes known broker cost-basis
  mismatch detail text even when the backend only provides the legacy English
  detail string and no `detail_code`. This continues the v1.4 review-surface
  cleanup for public notes and does not change reconciliation math, review
  decisions, ledger mutation, broker behavior, order submission, or
  manual-confirmation defaults.
* 2026-06-24: Extended the shared ledger evidence-reference formatter so
  Account Truth review cards can show instrument display name plus symbol for
  broker evidence references, including trade and position-snapshot evidence.
  This is user-facing formatting only; it does not change reconciliation math,
  review decisions, ledger mutation, broker behavior, order submission, or
  manual-confirmation defaults.
* 2026-06-24: Backtest fill tables now render buy/sell directions through the
  shared public ledger action labels, so saved research reports use localized
  user-facing trade directions instead of raw `BUY` / `SELL` text. This is
  report display formatting only; it does not change backtest fills, cost
  calculation, broker behavior, order submission, risk gates, or
  manual-confirmation defaults.
* 2026-06-24: Manual order approval tables now render order directions through
  shared public labels, including a safe localized fallback for future or
  unknown backend side codes. This is approval-table presentation only; it does
  not change order approval, rejection, broker behavior, order submission,
  risk gates, or manual-confirmation defaults.
* 2026-06-24: Overview pending-approval cards now show instrument display name
  plus symbol and render order directions through shared public labels,
  including a safe fallback for future backend side codes. This is dashboard
  presentation only; it does not change order approval, rejection, broker
  behavior, order submission, risk gates, or manual-confirmation defaults.
* 2026-06-24: Activity ledger source labels now use localized public fallback
  copy for future or unknown non-empty source codes instead of rendering raw
  internal source ids. This is ledger presentation only; it does not change
  ledger storage, accounting calculations, broker behavior, order submission,
  risk gates, or manual-confirmation defaults.
* 2026-06-24: Portfolio positions now show broker-versus-local cost-basis
  differences when broker cost-basis evidence includes a non-zero difference,
  using localized cost-basis copy in both desktop rows and mobile cards. This
  is cost-basis presentation only; it does not recalculate position cost,
  mutate ledger entries, change broker behavior, submit orders, or bypass
  manual confirmation.
* 2026-06-24: Exchange bond / convertible-bond fee modeling now returns the
  same structured fee-breakdown contract as A-share and ETF calculations, and
  manual trade fee resolution can produce bond fee evidence without stock stamp
  tax or transfer-fee assumptions. This is deterministic fee-evidence plumbing
  only; it does not enable broker submission, change default execution, or
  bypass manual confirmation.
* 2026-06-24: Activity manual-trade fee prefill now stays a UI estimate unless
  the user edits the fee field; default trade submissions omit explicit
  commission so the backend configured fee contract can generate structured
  commission, stamp-tax, transfer-fee, other-fee, total-fee, and fee-rule
  evidence. Edited fees still submit as manual fee input. This does not change
  broker behavior, order submission, risk gates, or manual-confirmation
  defaults.
* 2026-06-24: Public operational-note formatting now treats dotted backend
  note identifiers the same as snake-case note identifiers, so Trading order
  rows, Trading audit rows, manual approval risk hints, and Account Truth
  review cards fall back to localized review copy instead of rendering raw
  backend codes. This is display formatting only; it does not change order
  state, review state, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
* 2026-06-24: Shared public ledger-note formatting now splits semicolon and
  multiline note segments before suppressing generated structured trade facts,
  so a user remark can remain visible while repeated quantity, price, amount,
  and fee text stays in structured fields. This is display formatting only; it
  does not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-25: Shared public review labels now cover strategy review promotion
  states and Account Truth manual-review action buttons, so review surfaces
  show localized user actions such as simulation-review readiness and
  ledger-correction candidates instead of backend status nouns or generic
  fallback labels. This is display formatting only; it does not change
  reconciliation math, review persistence semantics, ledger mutation, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-25: Portfolio compact holding cards now label locally projected
  cost-basis evidence as ledger-projected unit cost instead of broker-displayed
  cost when no broker cost-basis evidence has been imported. This is display
  formatting only; it does not change cost-basis math, ledger mutation, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-25: Backtest fills now carry the same structured fee-breakdown
  payload used by paper broker evidence, manual trade previews, and ledger
  projections while preserving the legacy total `commission` field. The v1.4
  broker fee / cost-basis acceptance audit now records this shared fee-contract
  evidence. This is research and simulation evidence only; it does not submit
  broker orders, change live-like defaults, bypass risk gates, or bypass
  manual confirmation.
* 2026-06-25: Account Truth cost-basis reconciliation now compares broker
  reported per-share cost basis against the Karkinos broker/local cost-basis
  method context and exposes comparison unit, precision policy, and rounding /
  fee-allocation limitations to the Web review surface. The v1.4 broker fee /
  cost-basis acceptance audit records this evidence. This is reconciliation
  evidence only; it does not mutate ledger entries, submit broker orders,
  change risk gates, enable automatic trading, or bypass manual confirmation.
* 2026-06-25: The v1.4 broker fee / cost-basis acceptance audit now records
  the shared public ledger formatter contract used across Overview, Activity,
  Portfolio holding detail, Risk explainability, Decision, and Account Truth
  review surfaces. Existing Web tests cover localized action titles, entry
  types, instrument names, timestamps, quantities, prices, amounts, fees, cash
  impact, evidence references, and suppression of internal ledger/action codes.
  This is presentation/audit-manifest evidence only; it does not change ledger
  storage, accounting math, broker behavior, order submission, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
* 2026-06-25: Shared public ledger-note formatting now suppresses dash-prefixed
  legacy manual-trade notes such as generated "manual trade - instrument buy"
  facts when the same quantity, price, amount, fee, and cash-impact values are
  already available as structured fields. The v1.4 acceptance audit now records
  the broader user-facing contract that raw entry types, reason codes, legacy
  prefixes, duplicate symbol/name fragments, and mixed operational notes should
  not leak into public ledger surfaces. This is display cleanup only; it does
  not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-25: Shared public ledger-note formatting now keeps genuine user
  remarks while suppressing generated accounting-fact note segments such as
  cost-basis, net-cash-impact, amount, quantity, price, and fee fragments when
  those facts already have structured fields. The v1.4 acceptance audit records
  the localized public-note contract so future ledger surfaces do not smuggle
  core accounting facts into free-form notes. This is display/audit evidence
  only; it does not change ledger storage, accounting math, broker behavior,
  order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-25: Portfolio cost views now consistently distinguish local moving
  average buy cost from broker displayed cost-basis evidence across the
  positions table and holding detail page. The positions table now prefers the
  explicit broker-displayed unit cost from the API when present instead of
  deriving a unit value from total remaining cost, matching the holding detail
  page and reducing confusion when broker precision or remaining-cost methods
  differ. The v1.4 acceptance audit records the localized Portfolio cost-view
  evidence. This is display/evidence handling only; it does not change cost
  calculation, ledger storage, broker connector behavior, order submission,
  risk gates, automatic trading defaults, or manual-confirmation requirements.
* 2026-06-25: The v1.4 acceptance audit now records the existing sell-side net
  proceeds projection evidence: partial sells reduce broker-display-style
  remaining cost by proceeds after commission, stamp tax, transfer fees, and
  other configured fee components, while realized P/L uses the same net cash
  math. This records existing deterministic projection and ledger-fee evidence;
  it does not change cost calculation, ledger storage, broker connector
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
* 2026-06-25: Manual trade fee resolution now treats `convertible_bond` as an
  exchange-bond fee class for configured ledger and preview fee evidence,
  preserving commission, other-fee, total-fee, fee-rule, and net-cash-impact
  fields without adding stock stamp tax or transfer fees. Deterministic backend
  tests now cover the v1.4 fee/cost-basis contract across A-share fees,
  Shanghai/Shenzhen transfer-fee differences, ETF/fund-style fees,
  convertible-bond fees, broker displayed cost basis, realized P/L, and net
  cash impact. This is fee evidence and ledger projection handling only; it
  does not introduce broker order submission, automatic real-money trading,
  broker password storage, or changes to manual-confirmation requirements.
* 2026-06-25: The v1.4 acceptance audit now records frontend coverage for
  user-facing fee and cost-basis surfaces: Activity, Trading, Portfolio
  positions, holding detail, manual trade preview, and shared ledger formatting
  tests cover fee-breakdown display, cost-basis-method labels, broker/local
  cost-basis difference warnings, and suppression of raw entry types, fee-rule
  ids, backend note codes, and internal reason codes. This is test/audit
  coverage only; it does not change UI behavior, ledger storage, broker
  behavior, order submission, automatic trading defaults, or manual-confirmation
  requirements.
* 2026-06-26: Portfolio cockpit responses now include read-only construction
  recommendation evidence for action-linked positions. A recommendation is
  marked actionable only when account-truth status is `pass` and the matching
  risk gate is `passed`; missing/degraded account truth or blocked/unchecked
  risk returns required review actions and a localized rationale instead. This
  is portfolio-construction evidence only; it does not write production ledger
  entries, submit broker orders, enable automatic trading, or bypass manual
  confirmation.
* 2026-06-26: Portfolio now surfaces cockpit construction recommendations in a
  localized read-only card next to strategy attribution and risk summaries.
  Blocked/degraded items show user-readable review actions instead of raw
  internal action codes, while actionable items are labeled as manual-review
  candidates only after account-truth and risk gates pass. This is UI evidence
  surfacing only; it does not write production ledger entries, submit broker
  orders, enable automatic trading, or bypass manual confirmation.
* 2026-06-26: Portfolio holding detail now links each held instrument directly
  into the Backtest single-instrument strategy research flow with the current
  symbol and asset class prefilled. This improves the user-visible path from a
  specific holding to dataset snapshot, strategy registry, after-cost backtest,
  signal preview, risk preview, paper/shadow simulation, and attribution
  boundary review. It is navigation/context handoff only; it does not run a
  strategy automatically, write ledger entries, submit broker orders, enable
  automatic trading, or bypass manual confirmation.
* 2026-06-26: Portfolio-to-Backtest handoff now carries an explicit
  `source=portfolio` query context, and Backtest displays a localized holding
  research context instead of reusing decision handoff wording. This keeps the
  single-instrument strategy loop user-readable when launched from a holding
  detail page. It remains navigation/context handoff only; it does not run a
  strategy automatically, write ledger entries, submit broker orders, enable
  automatic trading, or bypass manual confirmation.
* 2026-06-26: Backtest run results now keep a localized single-instrument run
  context summary beside the evidence chain, including handoff source, symbol,
  asset class, strategy, and the research-only/no-broker-order boundary. This
  helps users keep the selected holding context visible while reviewing dataset,
  signal, risk, paper/shadow, and attribution evidence. It does not change
  strategy execution, ledger writes, broker order submission, automatic trading,
  or manual-confirmation defaults.
* 2026-06-26: Backtest run context now links back to the current instrument's
  Portfolio holding detail page, closing the user-visible loop from holding
  evidence into strategy research and back to holding/PnL review. The link is a
  read-only navigation affordance; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
* 2026-06-26: Portfolio holding detail now shows a localized strategy
  attribution boundary card whenever holding PnL is still account-level
  evidence. The card explains that PnL is not assigned to a strategy until a
  strategy signal, review decision, order, and fill can all be linked, and it
  points back to the single-instrument strategy research evidence flow. This is
  read-only attribution guidance; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
* 2026-06-26: Portfolio holding detail now upgrades the attribution boundary
  card only when a symbol-level account-strategy assignment matches the current
  holding and linked fill/evidence references exist. The card shows strategy,
  contribution status, linked-fill count, and evidence-reference count, but it
  still withholds strategy P/L amounts until attribution review is complete.
  This is read-only evidence surfacing; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
* 2026-06-26: Account Strategy now exposes a read-only holding-level
  attribution report at `/api/account-strategy/holdings/{symbol}/attribution`.
  The report filters linked signal, action, risk, review, order, and fill
  evidence to the requested symbol, and Portfolio holding detail uses that
  symbol-level report before showing evidence counts. It remains evidence
  indexing only; it does not calculate strategy P/L for the holding, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
* 2026-06-26: Portfolio holding detail now renders the symbol-level
  attribution report as a localized evidence chain. Signal, candidate-action,
  risk, review, order, and fill references are shown as user-readable evidence
  types with audit identifiers instead of raw internal ref strings. This is
  read-only audit surfacing; it does not attribute P/L by default, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
* 2026-06-26: Portfolio holding detail now includes a localized attribution
  review readiness gate. The gate shows whether strategy signal, manual
  review, risk check, order evidence, and fill evidence are linked for the
  current holding, and it keeps the explicit boundary that holding P/L is not
  assigned to the strategy until review is complete. This is explanatory UI
  only; it does not calculate strategy-attributed holding P/L, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
