# Karkinos Implementation Log

[中文](IMPLEMENTATION_LOG.zh.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md) | [Goal](KARKINOS_GOAL.md)

This file records release-level outcomes and validation evidence. It is not a commit diary. Detailed code history, intermediate slices, and exact diffs live in Git commits and pull requests.

## Current Baseline

As of 2026-08-23, v0.2.3 is the latest tagged stable baseline. Tags v0.2.4 through v0.3.0 were withdrawn because they represented incremental development snapshots rather than a functionally complete release. `main` now carries an untagged v0.3.0 candidate; it does not become a release until the production acceptance evidence is complete. The v1.8 control-plane foundation and AI-native research foundation through Phase 1.18 are implemented. The active product milestone is the broker-connected controlled per-order pilot in [ROADMAP.md](ROADMAP.md). The latest completed cross-cutting work includes:

- the untagged v0.3.0 candidate replaces holdings-only AI research with `karkinos.market_universe_truth.v2`: one immutable, content-addressed full active A-share stock snapshot per provider/trading date; receipt-bound full-market daily history; full-directory hard filtering; and an exact reproducible 40-stock panel that excludes funds/ETFs and rejects missing, stale, short, invalid, untradable, or one-lot-infeasible data before any model call. Human-promoted formulas scan the complete eligible stock pool while current stock holdings retain a separate exit lane. A two-phase decision-window flow previews prior-close signals, refreshes only selected new-buy quotes, rebuilds Account Truth, requires the exact signal-selection fingerprint to survive, and only then persists recommendation tasks. DeepSeek controls signal logic only; local code owns fixed four-slot sizing, costs, lots, risk, and authority. Candidate tickets survive page reload, while a complete no-signal scan is distinguished from a blocked run. Validation passed 2,532 Python tests, 698 Web tests, Web formatting and production build, documentation health, the strategy/broker boundary guard, target-file formatting/import checks, and low-risk change analysis. No path automatically promotes a strategy, creates or submits a broker order, mutates the account ledger, or expands capital authority;
- v0.2.12 adds an exact same-run partial resume for a fifth-hypothesis `provider_timeout` after four complete persisted rounds. The append-only owner authorization replays and fingerprints all four session/draft/backtest/critique/candidate parent chains, requires eight completed calls on the failed run, exactly twelve real calls for the date, the consumed ceiling-13 lineage, and exactly one unused slot; it raises the ceiling only from 13 to 14 so the existing slot plus the new slot can perform only the fifth hypothesis retry and critique. Rounds one through four are loaded from canonical evidence and are neither regenerated nor re-backtested; the old timeout record stays immutable and any drift fails closed. DeepSeek Strategy Research timeout is 600 seconds while other provider timeouts remain unchanged. The path cannot promote a strategy, create or submit an order, contact a broker outside the explicitly authorized provider calls, or expand capital authority. Validation passed 2,511 Python tests, 697 Web tests, Web formatting and production build, documentation health, the strategy/broker boundary guard, target-file pre-commit, and migration plus exact 12/13/14 ceiling admission against a current database copy with `PRAGMA quick_check=ok`;
- v0.2.11 reserves the full 12,288-token response allowance for the bounded Strategy Research JSON contract by explicitly disabling DeepSeek thinking only for hypothesis and critique requests; other external research and memory workflows retain their reviewed reasoning behavior. A `finish_reason=length` response remains an immutable fail-closed `provider_output_truncated` result and is never silently retried. An owner may append one exact truncation-recovery call only for the persisted zero-candidate failure after the prior retry and citation extension were consumed, only when three real calls have been recorded and raising the ceiling from 12 to 13 restores exactly ten remaining calls. The authorization and consumption use separate append-only tables, migrate all same-market-date retry/extension lineage atomically to the replacement run, and grant no strategy, order, broker, or capital authority. Validation passed 2,508 Python tests, 697 Web tests, Web formatting and production build, documentation health, the broker-authority guard, focused route/runtime tests, and a migration against a private-free copy of the current database with `PRAGMA quick_check=ok`;
- v0.2.10 completes the v0.2.8 DeepSeek citation fix without weakening evidence validation: every hypothesis still builds and validates the complete frozen-path catalog, but exports only a deterministic four-or-five-item `cite_01`…`cite_05` catalog and requires every draft to return the exact ordered ID list before local path resolution. Prompt v11 owns new immutable hypothesis/critique role identities. Provider-free corrected-software re-arm atomically migrates both the existing retry and the same-market-date unique citation-extension consumption to the replacement run, including recovery from an older runtime that left the extension on an ancestor run; migration requires the current retry lineage and cannot cross dates. The append-only extension still raises the exact persisted zero-candidate failure ceiling only from 11 to 12, only when doing so restores ten remaining calls, and grants no strategy, order, broker, or capital authority. Validation passed 2,506 Python tests, 697 Web tests, Web formatting, the production build, documentation health, staged GitNexus impact checks, and pre-commit checks; it contacted no broker, submitted no order, and changed no OMS/ledger/risk/capital fact;
- the v0.2.4 Daily Data Flywheel: immutable Account Truth import history is classified by a privacy-minimized material-continuity contract. Daily cash/position snapshot supersession, historical non-decision settlement metadata normalization, and chronological append-only account activity automatically carry the reviewed account scope while current reconciliation, valuation, ledger cutoff, and same-day promotion evidence are still recomputed. Every intermediate import is checked, so changed/removed economic activity, back-dated additions, malformed evidence, or temporary material drift cannot be hidden by restoring older bytes. Newly appended stock trades automatically revalidate the active fee review only when every component matches the approved terms; the originally reviewed notional envelope remains fixed. ETF/fund facts remain Account Truth, valuation, and risk inputs but cannot enter the stock strategy. The flywheel contacts no provider, places no order, changes no strategy promotion, and expands no capital authority. Validation passed 2,492 Python tests, 696 Web tests, Web formatting, and the production build; a read-only run against the current shared persistent store projected Account Truth `ready`, scope `complete`, materially inherited canonical-state continuity, and reviewed fees `active`, with no Account Truth or fee blockers and no provider contact or database write;
- a stock-only production daily-candidate boundary: ETF and fund facts remain in Account Truth, valuation, and risk, but are excluded from reviewed strategy fees, research/promotion, daily candidates, paper/shadow trial orders, and manual tickets; non-stock candidates fail closed at every direct and replayed order-generation boundary. A reviewed-fee preview records the exact stock scope, excludes non-stock trade counts deterministically, and rejects downstream asset classes outside that scope. Separately, an append-only, revocable CITIC canonical-resolution record can close an exact legacy source set only against a complete fingerprint-bound Account Truth scope review; scope revocation or drift automatically reopens follow-up, and neither transition changes broker evidence, reconciliation, execution, or capital authority; persisted observations remain the authoritative read source;
- immutable valuation snapshots and ledger identity;
- evidence-bound strategy contribution v2, assuming the controlled posting contract's immutable `ledger_entries.source_ref = fill_id` identity; linked fills expose P/L only after exact production-ledger and valuation-snapshot replay, while the read path remains provider-free, write-free, and without trading or capital authority;
- canonical daily performance across Holdings, Equity Curve, Overview, and explainability surfaces;
- provider-neutral evidence-bound AI research, review, and memory lineage, including explicit exact-strategy capture of the canonical posted-fill and valuation-bound contribution report without P/L recomputation or authority;
- an evidence-bound human post-decision review that freezes one persisted signal/action/risk/order/fill chain together
  with the canonical strategy contribution snapshot, rejects drift, records idempotently with a replayable append-only
  audit chain, and cannot mutate financial facts or authority;
- a persisted-only Strategy Lab learning queue that replay-checks the stored review, rebinds current evidence, emits
  deterministic human next actions, and offers only copyable human-started research handoffs with no AI or authority;
- a canonical five-dimension Decision Quality Score over persisted Decision, with idempotent daily capture,
  tamper-evident replay, longitudinal coverage, and no AI, financial, risk, execution, or authority side effects;
- a valuation/ledger-bound canonical current-holding market-evidence review consumed unchanged by Overview, with exact blockers and targeted ingestion in Market;
- persisted valuation v4, which keeps fund estimates visible but non-authoritative
  until a same-day confirmed NAV exists, so Decision and risk fail closed;
- a zero-write fail-closed batch-risk boundary for incomplete valuation or candidate evidence; accepted decisions bind
  the exact snapshot and ledger cutoff without creating orders or touching the ledger;
- human-gated allowlisted Formula DSL research over exact saved datasets, executed by the canonical backtest engine
  with next-bar semantics and no production-strategy or trading-authority side effects;
- owner-authorized after-close AI shadow research over newest persisted bars and complete valuation/ledger identity: one run per market date, atomic capped provider-call claims with token-usage accounting but no Karkinos daily aggregate token budget, DeepSeek Formula DSL hypotheses over a strict sanitized account risk/allocation allowlist, local validation and canonical after-cost rolling OOS, evidence critique, Web comparison/notification, and exact human-only canonical `paper_shadow` promotion; policy/Kill Switch/evidence/OOS/cost/provider-limit/call-limit failures close safely, absolute account values and valuation/ledger identifiers are removed before export, and no production-strategy, OMS, ledger, or broker authority exists; the supervised production daily-candidate v3 run then accepts no caller-owned financial facts, replays current Decision/plan after risk and exact paper/shadow, requires same-market-date Account Truth promotion and current prior-execution closure, and emits only a fully bound manual-ticket candidate or named `no_action`; its owner-enabled background caller is limited to a verified SSE trading-day 09:35-09:45 window and skips dates with an existing record, while the read-only 20-day / 50-order trial reads complete history, separates frozen strategy-and-fee epochs without merging old samples, and records exact human GO/continue/NO-GO evidence without creating orders, granting authority, changing capital, or claiming profitability;
- five-round sequential after-close selection and daily backup: every enabled production run requires exactly five rounds and ten calls, without a Karkinos daily aggregate token cap; legacy bounded-token or smaller enabled policies are retained for audit but fail closed before evidence preparation or provider access until the owner explicitly saves the complete policy. Each round performs one DeepSeek generation, one canonical local backtest/gate evaluation, and one DeepSeek critique, then binds the fingerprinted prior formula, metrics, blockers, and critique into the next round. Provider per-request output and context limits still apply and usage remains recorded. The final selector requires an exact candidate/draft/formula lineage; incomplete, mismatched, partial, or all-blocked chains have no new-candidate winner and no new promotion. That research outcome explicitly leaves the current human-approved strategy unchanged and does not imply a trading `NO-ACTION`; the independent daily Decision path remains authoritative for ticket candidacy. The immutable selection and allowlisted Formula DSL snapshots are stored in content-addressed atomic JSON plus database receipts, status rehashes them, and public paper/shadow approval requires the exact verified new-candidate winner and untampered backup. Promotion readiness persists only privacy-minimized selection/backup identities and fingerprints; every downstream promotion and order gate reopens and rehashes the canonical backup, so missing legacy bindings, deletion, or post-approval drift fail closed. Broker rows, private account identifiers, credentials, automatic strategy replacement, broker submission, and capital changes remain excluded;
- production daily-candidate input identity v2 now ignores only harmless current-age counter drift while binding sanitized risk failures, production blockers, frozen strategy replay, exact paper/shadow outcome, and prior-execution closure. Account Truth capture must precede the Decision and its age is recomputed during both production gating and trial replay; same-day source or result drift is retained as conflict evidence instead of overwriting the first result. Account Truth promotion and readiness derive effective capture from persisted cash and position snapshot timestamps rather than repository ingestion time: `imported_at` remains visible for audit, while missing, cross-date, post-event, future, or stale snapshots fail closed across Decision, reviewed fees, research, tickets, and controlled execution. The atomically claimed background market date is now passed through every Decision/plan read: any initial, post-risk, or post-shadow mismatch records current-claim-date NO-ACTION and closes the next side effect, while a final caller-side result-date mismatch is sanitized as `failed_closed` without notification or stale-run linkage. Each claimed background attempt also persists a bounded, privacy-minimized operator alert and sanitized notification status for NO-ACTION, ticket review, interruption, or fail-closed failure; alert/delivery failure never retries the candidate or changes authority. Automation Cockpit v3 introduced `karkinos.daily_candidate_runtime_status.v1`, binding owner startup configuration to the exact in-process daily-candidate monitor task. Disabled, missing, completed, cancelled, or failed task state blocks automatic attempts independently of the manual decision window; the projection is read-only, provider-free, non-authorizing, and explicitly does not claim financial readiness or add broker or capital authority. Automation Cockpit v4 adds `karkinos.daily_candidate_financial_preflight.v1`: one zero-write/provider-free projection now aggregates current Decision/plan identity, same-date Account Truth and quotes, exact frozen strategy replay, action-date-covered reviewed fees, safe automation policy, prior-execution closure, runtime task state, and decision-window status into a named simulation-attempt readiness or `NO-ACTION` result. A pass opens only the existing risk plus paper/shadow attempt; the projection performs neither step, creates no ticket, touches no OMS/ledger/broker path, changes no capital authority, and makes no profitability claim. The existing post-shadow production gate remains authoritative for ticket candidacy;
- the daily Account Truth binding now carries only a privacy-minimized replay contract over the referenced import file/events, current human review decisions, immutable valuation snapshot, and historical ledger rows through the stored cutoff. Trial projection re-resolves that exact historical contract: later append-only ledger facts are safe, while a missing or changed import, review, valuation, or pre-cutoff ledger fact excludes the date. The contract copies no broker rows, private account identifiers, or balances and grants no execution or capital authority;
- a loopback-only live production-readiness audit now combines the running Automation Cockpit financial preflight, exact in-process daily monitor, five-sequential-iteration research policy, and complete forward-trial projection into one sanitized fingerprinted report. Its v2 projection preserves the canonical dependency-ordered operator checklist, compresses repeated per-candidate blockers into code/count summaries, and exposes the first gate, safe action, required persisted evidence, and completion criteria; missing, malformed, non-canonical, or authority-granting checklist input fails closed. An unreachable service, invalid contract, stale or unreconciled financial evidence, missing monitor, legacy 1-round/2-call policy, truncated trial scan, or non-authority boundary drift remains non-ready with exit code 2; exit 0 permits only continued bounded paper/shadow evidence collection and cannot be manufactured by a green static acceptance manifest, submit an order, change capital, or claim profit;
- the background schedule now derives an exact current-or-next reviewed Shanghai window from the same persisted, officially verified SSE calendar, including separately verified next-year evidence at year boundaries. The schedule, readiness audit, and Decision trial panel expose it only as evidence-preparation timing; missing verification remains unavailable, and the projection cannot contact a provider, write the database, reopen an attempted date, retry/backfill a run, or change attempt, execution, or capital eligibility;
- a versioned deterministic strategy-advancement gate for after-close candidates: frozen dataset IDs now hash exact ordered timestamp/OHLCV content; aligned after-cost rolling-OOS folds, a bounded AST-bound parameter grid, frozen-market regimes, non-worsening drawdown/turnover, daily-bar capacity/liquidity, account-specific broker-reconciled fee/tax evidence, a redacted real-account capital constraint, positive after-tax excess, and completed critique are mandatory. The capital constraint binds the exact valuation/ledger identity and blocks unbound or above-equity research before provider export without granting capital authority. Nested fingerprints are recomputed; the built-in fee estimate is ineligible; reserved promotion/tickets re-resolve candidate, source backtests, critique, human approval, and paper state; exact-identity reconciliation persists plan/paper/actual comparison and blocks the next reserved batch unless it passes. Gaps remain `research_blocked` no-action and none of these records grants execution or capital authority;
- a revocable Account Truth fee-schedule review and Web operator workflow that compares configured safe terms with exact persisted buy/sell commission, tax, and transfer-fee components, stores only aggregate results and fingerprints, and creates the versioned calculator reference used by both baseline and candidate backtests. Acceptance requires the exact recomputed preview, reviewer, and full confirmation phrase; the read surface downgrades an accepted record to blocked on current evidence drift. Component rounding and exchange overrides are applied in calculation; critique, promotion, and tickets recheck active review identity and date coverage, while missing/revoked/drifted/tampered evidence remains provider-free no-action with no order or capital authority;
- fail-fast grouped runtime configuration, environment-only TuShare/AI and
  notification credentials, validated Settings write contracts, and one
  dotenv-selection path shared by server and legacy CLI entrypoints;
- a deterministic process-liveness-only endpoint and health-aware startup preflight distinguish a responding Karkinos instance from an unresponsive or foreign listener before build/launch, report without terminating it, and make no financial-readiness, provider, database-write, broker-action, ledger, execution, or capital-authority claim;
- an explicit macOS user-level LaunchAgent operations entry point renders its local definition before installation, runs the production backend with direct arguments on `127.0.0.1`, remains supervised after any process exit while loaded, verifies process liveness, refuses to replace an existing listener, and supports exact reversible uninstall. It does not edit runtime configuration, enable live monitoring, contact a provider or broker, or establish financial, execution, or capital readiness;
- an opt-in local broker-statement collector stages stable CSV evidence
  idempotently across polling/restarts, preserving prior evidence and exposing
  provider-free, non-authorizing Account Truth status;
- privacy-minimized CITIC legacy-XLS preview and source-review intake, including a default-disabled explicit local-directory scan that rejects symlinks, changing or over-limit files, returns no path/name/event details, persists nothing before a second fingerprint-bound review, keeps every GET/list path schema-initialization-free, and projects pending evidence work into a deterministic Operations attention item without entering canonical health, Account Truth, or authority; its deterministic batch assessment detects cross-file duplicate events and identity conflicts while distinguishing observed event months from unproven query-window coverage, and remains blocked, event-free, non-persisting, and ineligible for Account Truth or reconciliation; a separate runtime-only canonical-lineage assessment compares exact financial semantics, broker-order identity, and event identity against the selected canonical import, returns only sanitized counts/fingerprints, treats semantic similarity without identity as partial evidence, and cannot prove account coverage or promote the XLS batch; an append-only, revocable per-source query-window review now binds explicit owner-entered dates to the current file and sanitized-preview fingerprints, rejects future, over-31-day, or event-inconsistent windows, stores no source/transaction details, and clears only that Operations sub-requirement without proving canonical coverage or gaining authority; canonical broker-evidence, reconciliation-review, and evidence-scope-review reads likewise open existing SQLite strictly read-only, treat absent schema as no evidence, reject partial/incompatible schema and malformed records without repair, and reserve schema creation for explicit commands; Account Truth readiness v2 separates observed event span from complete account/date/asset coverage, permits only an exact-import append-only owner review with a browser-hashed account reference to clear that scope, and fails closed after revocation or drift without provider contact, financial recomputation, reconciliation eligibility, execution, or capital authority; a deterministic broker-soak candidate assessment keeps the XLS evidence blocked until a versioned read-only connector snapshot, reviewed account binding, provider capture/deployment/health evidence, current cash/position/order snapshots, and itemized fill fees and taxes are available, without registering a connector, recording soak, contacting a provider, or granting execution or capital authority;
- one deterministic static broker-authority guard now covers strategy,
  deterministic risk, Decision, and AI code. It rejects direct imports of
  execution, broker connector/gateway, controlled submit/cancel/release, and
  session-authority edges as well as direct submit/cancel/account-snapshot
  calls, while preserving explicit extension scans; the current four domains
  have zero violations.
- signed bounded execution policy, atomic budgets, runtime sessions, live
  gates, pause/replacement, submission interlock, lifecycle evidence, operator
  projection, and capital-scaling review.
- a canonical persisted-only controlled-order journey through reconciliation, terminal clearance, ledger posting, and append-only correction; v4 checks every bounded intent so older critical work stays visible and requires complete Account Truth before closure;
- an explicitly opened ledger-posting review with trusted offline proof and exactly-once apply; deterministic faults roll back every financial/completion fact, restart retry is safe, and private keys, broker actions, and authority stay outside Web;
- a separately signed unknown-submission recovery review that binds the
  persisted intent, exact client order id, prior gateway-result fingerprint,
  operator identity, and a short-lived offline proof before atomically
  admitting one query-only gateway call; duplicate clicks and immediate
  restart retries cannot repeat the query, and submit, cancel, ledger, risk,
  kill-switch, and authority paths remain unavailable; only the existing
  controlled-intent/OMS result status may be resolved from definitive query
  evidence;
- provider-neutral manual open/partial cancellation handoff and terminal rejection review; both recheck drift and perform no broker call, while a separate signed command binds lifecycle/release/gateway health, atomically admits one cancel effect, and permits only query recovery without making gateway responses canonical;
- provider-neutral adapter release manifests with append-only human accept/reject/revoke evidence, exact live collector prepare/commit binding, a default-collapsed signed Web review, and an eight-criterion machine-verifiable acceptance audit; none edits the database directly, selects/registers/contacts a provider, or grants execution authority.
- provider-neutral deterministic conformance fixtures with append-only reports,
  exact manifest/review binding, latest-result precedence, and prepare/commit
  revalidation; this does not claim a real adapter is supported.
- connector-scoped, sequence-qualified soak evidence where only atomically accepted v2 cursor evidence counts toward 20 days or passes daily/replay drills; a two-stage Karkinos restart checkpoint additionally requires a changed runtime-instance fingerprint and exact persisted replay, while readable but unsequenced, legacy-boolean, unscoped, unrelated, mixed, or newer failed evidence cannot satisfy promotion.
  This does not prove broker-terminal or real-adapter restart.
- a read-only Trading projection of exact 20-day soak evidence and signed owner acceptance, plus a default-collapsed, no-database-edit operator review for the separately signed, expiring, one-way-revocable persisted write-edge release that production submit/cancel can resolve only while current; the Web review blocks credential-key manifests locally and exposes no submit/cancel, adapter-registration, or capital-authority action. Operations separately composes persisted adapter, signed soak, expiring release, exact scope, and unresolved-journey evidence into an eight-criterion-audited pilot-admission matrix: unsafe contracts open immediately, safe unmet conditions remain compact, and no state completes v1.8, contacts a provider, mutates financial facts/authority, submits, cancels, or scales capital.

Exact historical test totals are intentionally not maintained here because
they become stale after every change. CI artifacts and the acceptance-audit
export own current counts and evidence.

## Release History

### v1.8 — Capital-Bounded Controlled Execution

Status: provider-neutral foundation implemented; real-provider pilot pending owner approval.

Implemented foundation:

- versioned capital policy and append-only evaluation evidence;
- distinct read-only evidence connector and execution gateway identities;
- signed per-order and session attestations;
- gateway verification and exact evidence binding;
- session-start Account Truth, atomic account/symbol budgets, and rate limits;
- signed expiring runtime sessions, live gates, pause, equal-or-narrower
  replacement, and exact-preview, offline-signed one-way revocation from Decision;
- default-closed one-shot submission, unknown recovery, cross-order interlock, and separately signed exact cancellation with an atomic one-effect claim plus no-recancel query recovery; their production factories can resolve only a current persisted write-edge release, while gateway telemetry stays non-authoritative and cannot mutate OMS, ledger, risk, kill switch, interlock, or capital authority;
- signed exact-terminal clearance for full fill, no-fill cancel, and
  partial-fill-then-cancel, plus broker-neutral lifecycle ingestion; open
  partial fills remain blocked and clearance itself cannot post the ledger;
- separately signed, provider-neutral reconciled-ledger posting with
  transaction-time OMS, intent, lifecycle, broker-evidence, Account Truth,
  valuation, and ledger-identity rechecks; exact fills commit once in one
  transaction, partial-cancel posts only actual fills, and no-fill cancel is an
  explicit zero-entry posting;
- separately signed append-only correction derived only by canonical replay;
  the write transaction re-derives the plan, preserves original trades and
  fees, rejects zero-fill/dependent/drifted/tampered cases, and deterministic
  acceptance binds Ledger, Holdings, Allocation, Equity, Overview, Cockpit,
  Account State, realized P/L, valuation identity, and Account Truth staleness;
- versioned adapter capability/boundary manifests and revocable release review
  gates for live collector ingestion;
- deterministic local read-only adapter conformance bound to release review,
  plus a separate non-authorizing execution-edge protocol fixture matrix;
- connector-scoped, latest-result-wins recovery-drill gates for soak promotion;
- persisted operator projection and evidence-based scale review;
- cross-order operator attention prioritization over the full bounded intent
  set, while retaining the chronological latest journey separately for audit;
- a no-database-edit operator path for the terminal-clearance-to-ledger-posting
  step, with deterministic UI tests for canonical action eligibility, blockers,
  missing identities, exact request bodies, and absence of broker calls; the
  local signer refuses key overwrite, enforces private-file permissions, and
  signs only the supplied challenge payload without network I/O.
- a separate no-database-edit terminal-clearance review that appears only for
  the canonical `preview_terminal_clearance` action, binds the exact persisted
  reconciliation run, Account Truth import, lifecycle and broker-evidence
  fingerprints, terminal quantities, and fills, and requires its own offline
  signature before recording the terminal outcome and releasing the interlock.
- a no-database-edit unknown-outcome recovery review for the canonical
  query-only journey action. The old unsigned naked POST is no longer a route;
  preview is provider-free, apply requires an exact recovery fingerprint,
  matching offline Ed25519 proof and acknowledgement, and the database records
  the atomic query claim before any external call.
- no-database-edit packages for the canonical open-order and rejected-order
  journey actions. They export only fingerprinted persisted-evidence handoffs;
  the rejected journey can separately append one exactly-once reviewer/time/
  fingerprint acknowledgement and then closes as no-retry. Neither path can
  query/retry/submit/cancel, change OMS/ledger/authority, release the interlock,
  or prove a later broker outcome.

M4 current adapter/per-order dossier and write-release assumptions and risk record:

- The adapter reviewer supplies an already reviewed credential-free provider-neutral manifest and stable external refs; its signed acceptance binds the exact newest conformance/current review/approval id but does not mean a provider is selected or deployed. Separately, the newest exact order-matching capital evaluation is authoritative even when blocked; dossier v5 resolves unique prior-batch/gateway plus Account Truth, Decision, risk, paper/shadow, and accepted read-only adapter evidence, while the server owns the strict write-release scope and at-most-12-hour window. Pilot admission additionally requires exactly one persisted observing release, its matching signed soak, one current short-lived `manual_each_order` release, one matching provider/gateway/account/connector/release scope, and no unresolved order attention, truncated queue, current session, or blocked session; ambiguity fails closed.
- Deterministic tests cover adapter strict manifest and nested credential-key rejection, exact signature/retry, accept/reject/revoke, changed conformance/current-review drift, GET-without-schema creation, collapsed Web zero-read/no-broker behavior, plus dossier source drift and write-release issue/revoke, expiry, scope, soak, trusted-key, tamper, zero-financial-write, provider-resolution, and local credential tests. Pilot tests add empty-source closure, coherent ready evidence, scope and source drift, unfinished order/session state, invalid counts, deterministic fingerprinting, Operations GET composition, compact safe readiness, immediate unsafe-contract visibility, exact blocker copy, and no submit/cancel controls.
- Risk is HIGH only where production submit/cancel consumes a separately reviewed persisted write-edge release; adapter review and Web wiring are safety-positive LOW/MEDIUM scope. Missing/drifted/revoked evidence remains default-closed, rejection/revocation can only block, and these UIs select/contact/register no provider, create no order, and change no OMS, ledger, Account Truth, risk, kill switch, lifecycle, per-order, or capital-authority fact. The pilot projection itself is LOW-risk, persisted-only rollout evidence outside Operations health—not an order gate or execution/capital authorization—and its fingerprint excludes request-time drift while changing on evidence identity or gate status.

M4 non-authorizing operator-package assumptions and risk record:

- A posted journey may close from the same Account Truth import only when the
  canonical coverage gate recognizes immutable posting lineage for that exact
  import. A corrected journey requires evidence captured after the correction.
  Complete means fresh, gate-pass, clear reconciliation, zero unresolved
  mismatches, current-ledger coverage, and explicit no-ledger/no-authority/
  no-submission boundaries. Partial or degraded evidence remains actionable
  review even when ledger coverage alone is `covered`.
- Deterministic validation covers same-import posting closure, correction
  evidence ordering, stale coverage, partial canonical evidence, single-read
  behavior, and unchanged provider/ledger/Account Truth/authority flags.
- Risk impact is medium because the read-only Automation Cockpit can remove an
  item from its attention queue once canonical evidence proves completion. No
  financial calculation or transition moved into the UI; the projection cannot
  refresh a provider, mutate account facts, or grant execution or capital
  authority.

- The canonical source list remains newest-first, but operator attention is
  severity-first and oldest-first within the same severity. Unknown, prepared,
  and open-order evidence precedes reconciliation, clearance, posting, and
  Account Truth follow-up; closed rejection reviews are excluded. Tests cover a
  newer rejected journey coexisting with an older unknown outcome and prove
  that the query-only, no-resubmit action remains primary.
- Risk impact is medium because this changes which existing human review is
  shown first across Automation Cockpit and Decision/Operations. It remains a
  read-only projection: no provider query, submission, cancellation, OMS or
  ledger mutation, risk decision, kill-switch change, or authority change is
  introduced.

- The latest exact-identity persisted lifecycle observation is assumed to be
  the only broker-order evidence available to the preview. The operator must
  independently verify broker/client ids and remaining quantity. Rejection
  review assumes only sanitized persisted results are reviewable; its audit
  record binds the exact fingerprint and never becomes permission to retry.
- Deterministic validation covers open/partial and local/definitive rejection,
  blocked or ambiguous evidence, restart-stable fingerprints, duplicate export,
  exactly-once concurrent/restart replay, conflicting reviewer, transaction-time drift,
  strict routes, UI acknowledgement, and no query/submit/cancel/ledger calls.
- Risk impact is low: only the dedicated append-only review audit store is
  written. OMS, ledger, Account Truth, risk, kill switch, capital authority,
  and the unresolved-submission interlock remain unchanged.

M4 query-only recovery assumptions and risk record:

- Broker order query by the persisted idempotent client order id is assumed to
  be read-only and bounded by the registered edge gateway. A failed or unknown
  query remains `submission_unknown`; it never authorizes resubmission. A
  persisted 30-second claim window prevents duplicate clicks and immediate
  restart retries while allowing a later explicitly signed query after a lost
  process or disconnected gateway.
- Deterministic validation covers early preview blocking, exact signature
  domain, duplicate apply, restart, query failure, definitive not-found,
  successful recovery, audit claims, route schemas, Web request bodies, and
  absence of submit/cancel/ledger paths.
- Risk impact is medium: this adds one explicit external read to a previously
  unknown execution state, but cannot alter the production ledger, capital or
  execution authority and never calls broker submit or cancel. The query result
  is sanitized and persisted through the existing controlled-intent/OMS result
  transition; ambiguity continues to fail closed.

M4 terminal-clearance UI assumptions and risk record:

- The operator journey owns the actionable submission and reconciliation
  identities; the Web client neither chooses arbitrary financial facts nor
  recalculates quantities, fees, terminal state, or clearance eligibility.
  Full fill, no-fill cancel, and partial-fill-then-cancel are the only
  clearable outcomes; open or conflicting evidence remains blocked by the
  canonical service.
- Validation uses deterministic component fixtures for the exact preview,
  challenge, proof, and apply sequence plus the full Node 24 Web suite,
  formatting, production build, backend safety suite, and CI.
- Risk impact is high at the execution-evidence layer because clearance records
  real fills, transitions the OMS to the reviewed terminal state, and releases
  the cross-order interlock. The existing write transaction rechecks the latest
  reconciliation, lifecycle, Account Truth, order, intent, signature, and
  fingerprint; the UI cannot supply financial values, post the ledger, contact
  a provider, submit/cancel an order, or change authority.

M3 correction assumptions and risk record:

- A non-empty controlled posting represents actual fills for one instrument;
  the applied zero-entry cancel is an auditable no-op and has no financial fact
  to reverse. A correction is local ledger recovery, not replacement broker
  truth, so a newer Account Truth import is mandatory afterward.
- Validation commands are `uv run python -m pytest`,
  `uv run python -m pytest -m trading_safety`, CI-equivalent coverage, and the
  Node 24 `npm run test`, `npm run format:check`, and `npm run build` commands
  under `web/`.
- Risk impact is high because the canonical ledger projector feeds cash,
  positions, costs, realized P/L, equity, Overview, Cockpit, Account State, and
  risk inputs. The boundary mitigates this by rejecting operator-supplied
  financial values, deriving both buy and sell reversal state from canonical
  replay, binding valuation/ledger/Account Truth identities, re-deriving under
  the write lock, verifying before-state on every replay, preserving history,
  and granting no OMS, broker, risk, kill-switch, AI/strategy, or capital
  capability.

M3/M4 correction operator-journey assumptions and risk record:

- Correction is optional recovery after an applied non-empty posting, never the
  routine next action. The operator must select one server-allowlisted reason;
  the Web client cannot submit cash, quantity, price, cost, fee, or ledger-entry
  deltas. Preview and apply continue to use the canonical replay service.
- The operator flow is preview -> three-minute offline Ed25519 challenge ->
  detached-proof verification -> explicit append-only acknowledgement ->
  exactly-once apply. Missing trusted keys, canonical blockers, changed
  fingerprint, duplicate correction, or stale Account Truth keep apply disabled
  or rejected. Success invalidates all affected persisted projection queries and
  makes the required Account Truth re-import visible.
- Risk impact is high because the final signed action mutates the production
  ledger. Mitigations remain server-owned: transaction-time replay and identity
  rechecks, append-only history, exact posting scope, no arbitrary financial
  input, no provider contact, and no OMS, broker submit/cancel, risk, kill
  switch, strategy/AI, or capital-authority capability.

Market-review remediation assumptions and risk record:

- The configured default data source is not assumed to support every asset
  class. TuShare latest quotes remain limited to stocks and open-end funds;
  index refreshes route directly to the already registered AKShare edge source.
  AKShare's documented Sina index feed is preferred when the Eastmoney feed is
  unavailable, but a persisted close is published only after the same adapter's
  daily feed supplies a completed trading date. Intraday rows without a
  trustworthy as-of remain provisional/stale.
- Deterministic validation covers capability-aware source selection, bounded
  timeouts, Shanghai 15:00 completion, previous-close/change derivation, Sina
  code prefixes, Eastmoney fallback, and explicit quote-source provenance.
  Local acceptance additionally used auditable manual refresh runs for 399001
  and 399006 and verified persisted `2026-07-16T15:00:00+08:00` closes.
- Risk impact is medium at the market-evidence boundary: the change can publish
  valuation inputs, but it never changes ledger, OMS, risk, kill switch,
  capital, or broker permissions. Missing timestamps, incomplete sessions, and
  provider failures continue to fail closed. Intraday fund estimates remain
  provisional; post-close confirmation accepts only same-day confirmed NAV,
  while one persisted request id makes duplicate/restart replay provider-free.
  An older NAV cannot overwrite the current estimate or clear the review gate.
- The evidence-review GET has zero connector contact/writes, uses canonical quantity tolerance, preserves negative positions, excludes closed/history-only assets, and fails closed on identity gaps.
  Acknowledgement cannot clear it; only newer confirmed persisted evidence and a new canonical snapshot can. No migration, dependency, broker adapter, OMS/risk/ledger mutation,
  or authority change was introduced.
- The Overview review queue, Operations tower, and dedicated `/operations` workbench consume the same canonical daily-operations projection; each non-normal subsystem has a deterministic, drift-sensitive attention fingerprint, safe next action, and evidence-based resolution condition that viewing cannot clear. The workbench validates every non-authority flag before safe drill-down, while AI capture receives the same read-only payload. Risk impact is high because the canonical builder feeds the route and AI context, but the Web addition is read-only/provider-free and the fields remain derived-only, backward compatible, write-free, and non-authorizing; the older Overview projection remains only a rolling-upgrade fallback.

Remaining release work is owned by the roadmap: one real adapter, read-only
soak, real cancel/unknown recovery, signed submission UI, broader end-to-end and
provider fault injection, real-evidence acceptance, the rest of the operator
journey, and the controlled per-order pilot.

### v1.7 — Controlled Broker Bridge Foundation

- Added manual ticket preview, export, dry run, and operator evidence.
- Added read-only connector capability and health contracts.
- Added execution reconciliation and broker-evidence handoff.
- Kept production broker submission, cancellation, and automatic ledger
  mutation disabled.

### v1.6 — Operations Center and Paper/Shadow Runbook

- Added persisted scheduled and operator-triggered runs.
- Added deterministic paper/shadow orders, fills, costs, divergence, review,
  retry, and limitations.
- Added Operations, Decision, Overview, and Trading visibility plus alerts and
  recovery tasks.

### v1.5 — Daily Trading Plan and Portfolio Construction

- Added candidate pools, target weights, order intents, costs, batch risk, and
  Today's to-dos.
- Preserved no-action, review-required, and manual-confirmation outcomes.

### v1.4 — Attribution and Cost-Basis Fidelity

- Added strategy contribution evidence across orders, fills, fees, taxes,
  realized/unrealized P/L, and unattributed effects.
- Replaced latest-quote contribution estimates with
  `karkinos.account_strategy_contribution.v2`: only production-ledger-posted
  fills bound to one persisted valuation snapshot can expose P/L; missing,
  stale, drifted, or incomplete inventory evidence fails closed with an
  explicit manual next action.
- Aligned broker fees, cost basis, proceeds, and public ledger formatting.

### v1.3 — Professional Decision Workflow

- Unified portfolio, market, signal, research, risk, Account Truth, and
  operations evidence into daily and intraday decisions.
- Exposed explicit action, blocker, explanation, and next-step states.

### v1.2 — Broker Evidence Connector

- Added broker evidence import, staged facts, capability/health status, and
  reconciliation inputs without broker-write authority.

### v1.1 — Paper Broker and OMS

- Added canonical order identity, transitions, idempotency, paper fills, and
  paper/shadow/manual-ticket modes.

### v1.0 — Strategy Runtime Foundation

- Added registered strategy execution, assignments, evidence binding, and
  production-safe extension boundaries.

### v0.9 — Data Plane and Market Reliability

- Added quote-fetch runs, source/cache metadata, stale reasons, manual refresh,
  and deterministic data-health evidence.

### v0.8 — Strategy Assignment and Attribution

- Added account/symbol strategy assignment, lifecycle state, downstream
  references, and attribution without pretending manual trades are strategic.

### v0.7 — Account Truth Review Center

- Added import/reconciliation listing, item review, score explanations, and
  Decision/promotion degradation or blocking.

### v0.6 — Account Truth and Reconciliation

- Added canonical broker statement import preview, staged evidence, duplicate
  detection, reconciliation, review states, and Account Truth scoring.

### v0.5 — Research Evidence Hardening

- Added versioned evidence bundles, data-quality gates, stronger OOS analysis,
  parameter stability, China-market assumptions, and promotion readiness.

### v0.4 — Strategy Lab

- Added typed strategy registry and extensions, generic parameters, Web
  backtests, frozen datasets, sweeps, comparisons, and after-cost/OOS reports.

### v0.3 — Daily and Intraday Decision Platform

- Added daily/intraday decision APIs and Web surfaces with explicit action and
  evidence bundles.

### v0.2 — Profit Discipline MVP

- Completed the first deterministic data-to-backtest-to-signal-to-risk-to-
  dashboard/journal operating loop.

## Validation Ownership

- Current automated evidence: CI artifacts and
  `scripts/export_acceptance_audit.py`.
- Machine-readable completion source: acceptance-audit registry under
  `analytics/`.
- Detailed change history: Git commits and pull requests.
- Current priorities and release gates: `ROADMAP.md`.

When a milestone completes, add a short release-level outcome here. Do not copy full test output,
implementation diffs, per-phase safety disclaimers, or every intermediate commit into this file.
