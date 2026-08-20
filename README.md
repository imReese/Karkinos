# Karkinos

> Investing is a chronic condition. Here is your scalpel.
> 投资是一种慢性病。这是你的手术刀。

Karkinos is a China-market personal quant research and trading platform. It
connects reproducible research, portfolio evidence, risk control, daily plans,
paper/shadow execution, reconciliation, and human-supervised controlled
execution in one local-first application.

Karkinos 是面向中国市场的个人量化投研与交易平台，将可复现研究、组合证据、风控、每日计划、
paper/shadow 执行、对账与人工监督的受控执行连接成一个本地优先的金融应用。

[中文文档](docs/README.zh.md) | [English documentation](docs/README.en.md) |
[Roadmap](docs/ROADMAP.md) | [Architecture](docs/ARCHITECTURE.md)

## What Karkinos provides

- Deterministic backtests with frozen datasets, after-cost metrics, OOS
  evidence, parameter sweeps, comparisons, and strategy extensions.
- A daily decision and trading-plan workflow with explicit buy, sell, hold,
  rebalance, no-action, and review-required outcomes.
- Portfolio, ledger, valuation, Account Truth, broker evidence, and
  reconciliation views built from persisted facts.
- Mandatory risk, data-quality, paper/shadow, reconciliation, and operator
  gates before live-like actions.
- Paper Broker, OMS, manual order tickets, execution reconciliation, and a
  default-closed controlled-execution foundation.
- Evidence-bound AI research workflows, including human-gated allowlisted
  Formula DSL experiments and explicitly selected canonical strategy-outcome
  evidence. Their output remains non-authoritative research and never becomes
  trading authority by itself.
- React/Vite product UI, FastAPI backend, SQLite persistence, Docker runtime,
  deterministic tests, and acceptance-audit evidence.

## Safety boundary

Karkinos is a personal research and trading platform, not investment advice.
Historical results and AI-generated research do not guarantee future returns.

- Strategy code and AI output cannot call a broker directly.
- Real-money submission is disabled by default.
- Controlled execution requires explicit, bounded, expiring human authority
  plus fresh risk, account, market, gateway, and reconciliation evidence.
- Missing, stale, partial, ambiguous, or conflicting financial evidence fails
  closed.
- Broker passwords, API keys, private account exports, runtime databases,
  logs, and screenshots containing private data must not enter source control.

## Current status

Research, daily planning, paper/shadow operations, OMS, Account Truth,
reconciliation, and the non-submitting controlled-execution foundation are
implemented. The active milestone is v1.8. Provider-neutral adapter release,
conformance, persisted-only readiness, and read-only soak-promotion gates are in place; Trading now provides a default-collapsed signed accept/reject/revoke review that binds the exact manifest, newest conformance, current review, and operator approval without database editing.
A separately signed, at-most-12-hour write-edge release binds exact reviewed evidence and one-way revocation through a signed issue/revoke review.
Both block credential-key manifests locally, expose no submit/cancel action, grant no order/capital authority, register no adapter, and do not select or contact a provider. Signed exact-terminal reconciliation now covers full fill, no-fill
cancel, and partial-fill-then-cancel from persisted evidence. A separate final
operator signature can now post the exact cleared fills to the production
ledger once, in one transaction, while zero-fill cancel remains a recorded
no-op. The posting boundary rechecks OMS, lifecycle, broker evidence, Account
Truth, and ledger identity; it cannot submit, cancel, contact a provider, or
change capital authority. A separately signed append-only correction can now
reverse one posting only from canonical replay, preserving the original trades
and requiring a newer Account Truth import afterward. That optional correction
is available from the existing order journey as a reason-selected deterministic
preview, offline-signature verification, and final exactly-once apply; the UI
cannot supply financial deltas. Decision also exposes exact-preview, offline-signed one-way session revocation that closes future admission without submit/cancel. Selecting or implementing one real broker edge
still requires explicit owner confirmation before any read-only soak or
human-confirmed per-order pilot.

Account-strategy contribution is now a persisted-facts-only projection: a fill
must be posted to the production ledger and bound to one exact valuation
snapshot and ledger cutoff before P/L is visible. Missing or drifted evidence
produces an explicit manual review step, while a strategy with no fills creates
no artificial blocker. This projection cannot contact a provider, write the
ledger, or grant execution or capital authority.

From Strategy Lab, a human can bind the exact current strategy id and canonical contribution report into a frozen AI research context. Capture rejects strategy or valuation/ledger drift; incomplete evidence stays blocked, and capture neither recalculates P/L nor invokes a model.

Owner-authorized after-close shadow research runs once per persisted market date: it refreshes the local baseline, binds complete account evidence, atomically claims at most ten DeepSeek calls while recording token usage without a Karkinos daily aggregate token cap, exports the saved backtest plus a strict risk/allocation allowlist with absolute values and valuation/ledger identifiers removed, validates Formula DSL locally, runs canonical after-cost rolling OOS, and sends only normalized results for critique. Every enabled standing run requires exactly five sequential revisions; a legacy, bounded-token, or smaller enabled policy is audited as `blocked_by_policy` before evidence preparation or provider access until the owner explicitly saves the complete unbounded-daily-token policy. Each round performs exactly one hypothesis-generation call, the canonical local backtest and advancement gate, then one critique call; the next round receives a fingerprinted, privacy-minimized parent bundle containing the prior formula, metrics, blockers, and critique. Five rounds therefore require ten sequentially capped provider calls, and an incomplete or mismatched lineage fails closed. Provider per-request output and context-window limits remain technical constraints, not a Karkinos daily token budget. DeepSeek never selects the winner: only candidates that pass every deterministic advancement check enter a fixed lexicographic ranking by after-tax excess, mean/worst OOS excess, drawdown, turnover, and stable candidate identity. An incomplete set, partial evaluation, or zero passing candidates produces no new winner and therefore no new promotion; it does not imply a trading `NO-ACTION`, and the current human-approved strategy remains unchanged until explicitly replaced. The separate daily Decision pipeline still replays current Account Truth, market, fee, strategy, risk, paper/shadow, and reconciliation evidence to decide a ticket candidate or `NO-ACTION`. Each completed daily set is written to a privacy-minimized, content-addressed Formula DSL backup with an immutable database receipt; a missing or fingerprint-drifted backup blocks public paper/shadow approval. The verified selection and backup fingerprints are persisted in the promotion readiness record and re-resolved read-only from disk by every downstream paper/shadow and order-generation check; missing legacy bindings, deleted backups, or post-approval drift fail closed. Stable identities make retries idempotent; Kill Switch, policy/evidence drift, incomplete facts, provider/context-limit exhaustion, or call-count exhaustion fails closed. Web shows the new-candidate winner/backup status plus baseline/candidate metrics, costs, OOS, risks, critique, and sequential round lineage; only the verified new-candidate winner with a complete fingerprint-valid advancement gate and exact human confirmation can promote to canonical `paper_shadow`. Direct generic promotion and legacy generic promotion state are ineligible as ticket evidence. The Web reads canonical promotion state: pause/revoke requires an explicit reason and exact human confirmation, immediately blocks tickets while retaining audit history, and re-entry requires a fresh review note and the exact paper/shadow-only confirmation. Per-order evidence rechecks current promotion and blocks paused/revoked or drifted candidates; neither promotion nor a ticket replaces production strategy, creates/submits an order, or changes capital authority.
Candidate comparison now uses deterministic `karkinos.strategy_advancement_gate.v2`: the snapshot hashes the exact ordered timestamp/OHLCV rows; aligned rolling-OOS folds against the reviewed persisted baseline, a bounded Formula parameter grid, frozen-market regimes, drawdown, turnover, capacity/liquidity, account-specific reconciled fee/tax evidence, a redacted proof that research capital does not exceed current reconciled account equity, positive after-tax excess, and completed critique are mandatory.
The built-in fee model remains an estimate and therefore cannot pass account-specific promotion. Missing, stale, conflicting, drifted, or unreproducible evidence completes as a `research_blocked` no-action candidate; reserved `ai_formula_shadow:*` identities must re-resolve the exact candidate, baseline/candidate backtests, critique, human approval, and paper-shadow state before a ticket, while their next batch additionally requires a fingerprint-valid `plan -> paper -> actual` comparison. Account-specific costs become eligible only through the revocable Account Truth fee-schedule review: a provider-free preview compares safe configured terms with exact persisted buy/sell fee, tax, and transfer-fee components, then an exact human fingerprint approval creates the versioned calculator reference used by both baseline and candidate runs. The current review, Account Truth source identity, effective window, and ticket action date are rechecked downstream; no private broker rows or account identifiers are copied into that review. Order generation is a two-step fail-closed handoff: current promotion permits only a `paper_shadow_required` plan intent; `ready_for_manual_confirmation` additionally requires the same-date persisted run to bind the exact action, input fingerprint, simulated order, and `within_expectations` result. Before legacy Trading creates or confirms a ticket it rechecks Account Truth, market freshness, risk, Kill Switch, promotion, fees, and shadow binding. Its daily-shadow compatibility route rejects caller-supplied equity and delegates to canonical Decision -> Plan -> Paper. No record submits an order or grants execution or capital authority. Production daily-candidate operation is one canonical no-caller-facts run: current Decision and plan -> batch risk -> exact paper/shadow -> current-plan replay -> `manual_order_ticket_candidate` or `no_action`. It binds the valuation snapshot, ledger cutoff, same-market-date Account Truth promotion source, trusted quote, reviewed fee rule, risk decision, strategy-advancement fingerprint, paper/shadow identity, and current prior-execution closure; any gap resolves to named blockers. The owner-enabled background runner is restricted to the verified SSE trading-day 09:35-09:45 Asia/Shanghai window and atomically claims one fail-closed attempt per date before running, including stale-plan, failure, interruption, and restart paths. On that same verified date, a separate once-only 08:45-09:35 preparation check reads persisted policy, same-day Account Truth, reviewed fees, human-promoted strategy, and prior execution closure, then records sanitized blockers without provider access, risk/paper execution, retry, trial credit, or trading authority. A read-only trial consumes the complete persisted history and counts only the newest frozen strategy-and-fee epoch with conflict-free verified days and exact simulation; old epochs remain superseded evidence and never merge into a later 20-day / 50-order threshold. Reaching that threshold permits only a human GO/NO-GO review, with no order, authority, capital change, or profitability claim. See [the production runbook](docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.md).
Final Decision and plan timestamps are themselves replayed against that window, every summary and per-intent quote must be no more than 300 seconds old at the decision time, and Account Truth must have been captured no later than that Decision with its derived age inside the reviewed maximum. Account Truth capture is now the earlier of the latest persisted cash and position snapshot times; file ingestion time is retained separately as `imported_at` and can never refresh an old statement. Missing, mismatched, post-event, future, or stale snapshot evidence blocks readiness and fees. `karkinos.daily_candidate_input_identity.v2` excludes harmless wall-clock age drift but binds the production blockers, sanitized risk-failure identity, frozen strategy replay, exact paper/shadow result, and prior-execution closure; the trial recomputes it so a same-day evidence change is retained as a conflicting record rather than overwriting the first result. Manual Web runs are disabled outside the window; direct out-of-window calls remain auditable `no_action` records and cannot enter the forward trial. The final Decision's canonical order-generation gate is revalidated per intent, and the exact advancement, reviewed fee, comparison, human approval, frozen baseline/candidate dataset, and persisted-only replay identities are shared by the snapshot and fingerprinted ticket. The same privacy-minimized Account Truth binding—source fingerprint, capture/age limit, valuation snapshot, ledger cutoff, reconciliation, and coverage—is also shared and replayed without exposing account identity or balances. It additionally hashes the referenced import events, human reviews, immutable valuation, and ledger rows through the stored cutoff; the trial recomputes that exact historical binding, allowing later append-only rows while excluding source, review, valuation, or pre-cutoff ledger drift. A claimed background attempt persists a privacy-minimized operator alert for NO-ACTION, read-only tickets, interruption, or fail-closed failure; configured notification receives the named NO-ACTION blockers, while alert/notification failure never retries the candidate or grants authority. A latest excluded run prevents GO review even when older counts had reached the numerical threshold. Automation Cockpit v4 keeps `karkinos.daily_candidate_runtime_status.v1` as operational liveness evidence and adds `karkinos.daily_candidate_financial_preflight.v1`, a zero-write/provider-free projection over the current Decision/plan, same-date Account Truth, persisted quotes, exact promoted-strategy replay, active reviewed fees, safe automation policy, and prior-execution closure. A pass permits only one canonical risk plus paper/shadow attempt; it never creates a manual ticket, submits an order, mutates OMS/ledger, changes capital authority, or establishes profitability. The final post-shadow production gate remains authoritative for ticket candidacy.
Decision's signal journal now supports an explicit post-decision review. It
first previews the persisted signal/action/risk/order/fill chain and the same
canonical contribution report, then records a human conclusion only against
that exact fingerprint. Acted outcomes require bound fill, valuation-snapshot,
and ledger-cutoff evidence; unexecuted or risk-blocked signals retain separate non-financial outcomes. Stored rows and their append-only event chains are replay-checked, and evidence drift makes old conclusions visibly non-current. Strategy Lab projects the latest valid human review per signal into deterministic safe next actions; integrity failure blocks learning, while an evidence-not-supported result produces only a copyable, separately human-started research question. The GET path does not invoke AI, create memory, contact a provider, change a strategy or financial fact, or grant trading or capital authority.

Decision also exposes the evidence-bound North Star Decision Quality Score.
The current projection checks data and Account Truth completeness,
deterministic risk, benchmark awareness, journaling, and later reviewability.
An operator may explicitly freeze the exact daily fingerprint into an
append-only, replayable capture; longitudinal coverage includes captured days
only. The score measures process evidence, not return, advice, or authority.

On Overview, the market/NAV review count is scoped to canonical current
non-zero holdings. Watchlist instruments, market indices, and closed-position
quotes remain visible in Market or history but cannot inflate the current
holding review queue. The queue is now projected by
`/api/portfolio/market-evidence-review` from one persisted Portfolio snapshot,
with the exact valuation snapshot, quote-set fingerprint, ledger cutoff, and
ledger fingerprint attached. Market exposes the affected symbols, reasons, and
safe manual next step. The GET path is read-only and provider-free; an explicit
targeted refresh is separately audited; fund NAV uses a request-idempotent confirmation-only command that rejects estimates and previous-day NAV. Neither path clears anything
unless newer confirmed persisted evidence produces a new canonical snapshot.

Trading now provides a default-collapsed, non-submitting per-order evidence
review. It lists only canonical `manually_confirmed` OMS candidates and resolves
the newest exact capital evaluation, same-strategy prior-batch reconciliation, and gateway
verification from persisted facts, then binds the newest exact-scope accepted,
conformance-clear, read-only-observing adapter release. Dossier v5 also resolves the Account Truth, Decision action, risk decision, and paper/shadow references to matching persisted source facts, requires those exact refs in the same capital evaluation, and rejects order/symbol/strategy/quantity drift. The operator does not copy those fingerprints by hand. A three-minute offline signature can append one exact
review fact; it cannot submit/cancel, contact a provider, or change OMS, ledger,
risk, kill switch, or capital authority. Missing, ambiguous, newer blocked, or
bounded-scan-incomplete evidence, release revocation, or scope drift remains blocked.
Automation Cockpit and Decision project the same persisted-only candidates as a
ready/blocked summary and provide only a non-submitting handoff to Trading.
Only an explicit alert scan records idempotent warnings for source or candidate
blockers; review-ready candidates remain normal tasks rather than incidents.

For a reconciled controlled order, the Operations/Decision journey can now
complete both signed terminal clearance and the following reconciled-ledger
posting without database edits. Each step has its own canonical preview,
three-minute offline Ed25519 challenge, detached-proof verification, and final
acknowledgement. Clearance records only exact terminal fills and releases the
cross-order interlock without posting the ledger; posting remains a separate
exactly-once transaction. The private key never enters Karkinos, and neither
path can submit or cancel broker orders or change capital authority.

Operations now keeps chronological history separate from operator priority.
Every bounded persisted controlled-order journey is evaluated, and an older
unknown, prepared, or open-order outcome remains ahead of a newer lower-risk or
closed journey. The dedicated `/operations` read-only workbench and compact Overview queue show the exact safe next action and evidence condition
that clears each item; viewing alone never clears a status. Its final Account Truth stage now closes only from the canonical
fresh, complete, current-ledger-covered reconciliation; partial, degraded,
stale, or pre-correction evidence stays open for review. It is a read-only
projection and cannot contact a provider or perform any trading, ledger, risk,
kill-switch, or authority mutation.

For a controlled order whose latest exact persisted lifecycle is still open or
partially filled, the same journey can prepare a provider-neutral manual
cancellation evidence package. It binds both broker/client order ids and the
latest lifecycle fingerprint, rechecks evidence at export, and remains a
copy-only human handoff. Karkinos does not contact the broker or expose a cancel
action; a newer ingested lifecycle observation is required before cancellation
can be treated as fact.

A separate backend-only, default-closed signed cancellation contract binds the exact open lifecycle, remaining quantity, signed release, cached gateway health,
and a short-lived offline proof before atomically claiming at most one cancel
effect. Recovery only queries and never re-cancels; gateway responses stay
non-authoritative. No real adapter or Web cancel action is registered.

For a rejected controlled submission, the journey can also prepare a sanitized,
fingerprinted rejection-review package. It distinguishes a local pre-gateway
block from a definitive gateway rejection and explicitly forbids retrying the
same intent or client order id. The package remains copy-only; a separate
append-only review records exactly who acknowledged which fingerprint and when,
then closes the journey as no-retry. Duplicate/restart replay is idempotent and
conflicting reviewers or evidence drift fail closed. Only that audit store is
written: no query, retry, submit, cancel, OMS, ledger, risk, Account Truth,
interlock, or authority side effect occurs.

See [the roadmap](docs/ROADMAP.md) for priorities and release gates. Completed
implementation evidence lives in
[the implementation log](docs/IMPLEMENTATION_LOG.md), not in this README.

## Quick start

Requirements:

- Python 3.12+
- Node.js 24.x
- `uv`
- Docker, optionally

Install backend and frontend dependencies:

```bash
uv sync --extra server --extra dev --frozen
npm ci --prefix web
```

Build the product frontend and start the local server without the live
scheduler:

```bash
npm --prefix web run build
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
uv run python -m server --no-live
```

The product entry point is `http://127.0.0.1:8000` unless configured
otherwise.

Run the primary checks:

```bash
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

Docker:

```bash
docker compose up --build
```

Use fake or sanitized data for development. Do not commit `config.json` or
`.env`; credentials are rejected from JSON and belong only in the selected
runtime environment file or process environment.

## Documentation

Choose one documentation index:

- [中文文档](docs/README.zh.md) — 安装、工作流、产品边界和专题参考
- [English documentation](docs/README.en.md) — setup, workflows, product
  boundaries, and topic references
- [Repository agent instructions](AGENTS.md) and [Claude instructions](CLAUDE.md)
  — authoritative AI-agent entry points
- [AI collaboration policy](AI_COLLABORATION.md) — tool-neutral project,
  financial-integrity, authority, and validation rules

Each index organizes the same material into core documents, operational
guides, and references. Individual pages link directly to their translation.

## Repository layout

```text
analytics/       reports, attribution, evidence, and acceptance audit
backtest/        deterministic backtesting and experiment services
core/            events, portfolio primitives, and shared contracts
data/            market-data providers, cache, and reliability evidence
execution/       paper broker, OMS, gateway, and controlled execution
risk/            pre-trade and runtime risk controls
server/          FastAPI application and routes
strategy/        built-in strategies, registry, and runtime
tests/           deterministic backend and safety tests
web/             React/Vite product UI
docs/            durable product, architecture, reference, and runbook docs
```

## License

MIT
