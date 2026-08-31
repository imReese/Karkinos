# Daily Candidate Production Runbook

[中文](DAILY_CANDIDATE_PRODUCTION_RUNBOOK.zh.md) | [Goal](KARKINOS_GOAL.md) | [Architecture](ARCHITECTURE.md) | [Controlled execution](CONTROLLED_EXECUTION_PLAN.md) | [Roadmap](ROADMAP.md)

## Production boundary

This runbook operates Karkinos as a supervised daily decision system. A run
produces exactly one of these outcomes:

- `manual_order_ticket_candidate`: current persisted evidence permits a human
  to continue into the separate manual-ticket workflow;
- `no_action`: one or more named blockers remain, or no strategy action exists.

Neither outcome creates or submits a broker order, changes the production
ledger, grants execution authority, changes a strategy assignment, or expands
capital authority. A candidate is not a promise of profit.

## Required evidence before a qualifying run

1. The strategy has an active, human-reviewed `paper_shadow` promotion bound
   to a complete `karkinos.strategy_advancement_gate.v2` artifact. The current
   order-generation gate must replay the persisted frozen dataset, prove the
   baseline/candidate manifests match, retain the reviewed comparison and human
   approval fingerprints, rehash the exact verified daily selection and
   content-addressed strategy backup bound at promotion, and keep provider
   contact and live-like authority off. That exact backup must also freeze a
   non-empty economic hypothesis, risk impact, failure conditions, limitations,
   and anti-lookahead assumptions. Their content fingerprint is reviewed
   evidence, not an automatic stop or execution rule.
2. The sanitized Account Truth promotion evidence is `clear`, `pass`, fresh,
   ledger-covered, has zero unresolved mismatches, and binds current cash and
   position snapshots captured on the plan's Shanghai market date and no later
   than the final Decision. Capture is the earlier of those latest snapshot
   timestamps; the later local file-ingestion time is only `imported_at` and
   cannot refresh old evidence. Snapshot age at Decision must remain inside the
   reviewed maximum. The evidence also binds its source fingerprint, valuation
   snapshot, and positive ledger cutoff.
   Owner-enabled daily roll-forward may carry an existing scope review through
   materially continuous canonical history: superseded state snapshots,
   historical non-decision metadata, and chronological append-only activity.
   Newly appended stock trades automatically revalidate the fee review only
   when every component matches the approved terms, without expanding its
   reviewed notional envelope. Every intervening import is checked; changed or
   removed economic activity, back-dated additions, fee mismatches, or asset-
   scope drift require exception review, and byte restoration cannot hide them.
3. The final Decision and plan are generated only from 09:35 through 09:44
   Asia/Shanghai. Every order intent uses its current persisted market quote
   rather than the historical signal price, and binds that quote's positive
   price, source, aware timestamp, and age at decision. The quote must be on the
   same market date and no more than 300 seconds old.
   Before recommendation tasks are written, the promoted strategy must also
   replay the complete receipt-bound stock universe on the previous verified
   close. Current stock holdings use a separate exit lane; funds and ETFs never
   become strategy candidates. The run refreshes only selected new-buy symbols,
   rebuilds Account Truth, and repeats the scan. The two signal-selection
   fingerprints must match exactly.
4. The account-specific reviewed fee schedule covers the action date and every
   order intent resolves a non-negative fee from that schedule.
5. Pre-trade risk is passed and bound by one exact risk decision per intent.
6. Kill Switch and automation policy permit paper/shadow only; broker
   submission remains disabled.

Missing, stale, conflicting, estimated, partial, future-dated, or
unreproducible evidence produces `no_action`.

## Daily operator sequence

1. Before the decision cutoff, let the collector and daily snapshot roll-
   forward prepare current Account Truth, and explicitly ingest or review
   current market evidence. Read pages do not refresh providers. Materially
   continuous canonical history carries the account scope automatically.
   Appended stock trades also revalidate automatically when all fee components
   match the approved terms, while the reviewed notional envelope stays fixed.
   Changed/removed economic activity, back-dated additions, fee mismatches, or
   asset-scope changes enter exception review.
2. If any prior non-simulation OMS order exists, run execution reconciliation
   and finish its current plan → paper → actual or no-fill terminal closure.
   Open Decision → Automation and inspect the Account Truth, execution-closure,
   market, strategy, risk, and fee blockers.
3. During the displayed 09:35-09:45 decision window, start the canonical run
   from the application or call
   `POST /api/automation/run/daily-candidate`. The endpoint accepts no caller-
   supplied plan, price, quantity, account balance, or strategy fingerprint.
   The Web disables its manual run control outside that window; a direct API
   call outside it persists only a named `no_action` result and cannot qualify.
4. Karkinos previews the promoted strategy over the complete frozen stock pool
   without writing signals, refreshes and audits selected buy quotes, rebuilds
   Account Truth, and repeats the scan. Only an unchanged selection may become
   persisted recommendation tasks. It then rebuilds Decision and the trading
   plan, runs the canonical batch risk gate, persists one deterministic
   paper/shadow simulation, and rebuilds the plan again before resolving the
   production outcome. A complete scan with no entry or exit signal is a normal
   deterministic `no_action`, not a missing-strategy blocker.
5. If the result is `no_action`, resolve only the named evidence source for the
   next clean market date. A manual same-day rerun remains auditable; if its
   input fingerprint differs, that date is excluded from the trial. Do not edit
   runtime records or copy values around a gate.
6. If the result is `manual_order_ticket_candidate`, inspect the simulated
   order, current quote, costs, risk/constraint checks, evidence fingerprint,
   divergence, invalidation conditions, and current Kill Switch. The returned
   artifact is read-only and does not create an OMS order. Continue only
   through the existing per-order human-confirmation workflow.
7. After any manually entered broker order, import exact broker evidence and
   complete plan → paper → actual reconciliation before the next batch.

The always-on live scheduler's background loop reads the persisted,
officially verified SSE calendar and may call the same service only from 09:35
through 09:44 Asia/Shanghai. It skips closed or unverified days and atomically
claims one background attempt for the market date before invoking the service.
That claimed date is passed into every Decision/plan read. If either persisted
date differs at any stage, the service records a current-claim-date
`NO-ACTION`, stops before the next risk or paper/shadow step, and never links or
notifies a stale-date result. A final caller-side date check converts any
contract regression into a sanitized `failed_closed` attempt.
The claim remains fail-closed after a stale plan, failure, interruption, or app
restart, so none of those paths can create a later automatic retry with newer
information. The loop reports a missed window after 09:45 instead of
backfilling. Repeated identical manual inputs remain idempotent; a different
same-date input fingerprint is retained as conflict evidence and the date does
not qualify. `karkinos.daily_candidate_input_identity.v2` deliberately ignores
only the changing current-age counter when the underlying evidence and gate
outcome are unchanged. It binds production blockers, the sanitized risk-error
fingerprint, frozen strategy replay, the exact paper/shadow result, and prior-
execution closure, so a same-day repair or drift cannot overwrite the earlier
record.

`karkinos.daily_candidate_background_schedule.v3` also projects the current or
next `karkinos.daily_candidate_next_reviewed_window.v1` from the same persisted,
officially verified SSE calendar. The projection includes exact Shanghai start
and end timestamps and remains read-only: it performs no provider contact or
database write, cannot reopen an attempted date, cannot permit retry or
backfill, and cannot change attempt, execution, or capital eligibility. If the
next year is required, its separately persisted calendar must also be
officially verified; otherwise the next window remains explicitly unavailable.
Use this date only to prepare Account Truth, fees, strategy review, and market
ingestion before the window.

From 08:45 through 09:34 Asia/Shanghai, the always-on monitor may atomically
claim one `karkinos.daily_candidate_preparation_check.v1` record for the verified
market date. The check reads only durable gates that should be ready before the
decision window: safe paper/shadow policy, same-date Account Truth, the active
account-specific fee review, a currently replay-valid human-promoted strategy,
and prior plan → paper → actual closure. It deliberately defers current quotes,
the final Decision/plan, and the runtime window. A blocked check persists and
notifies only sanitized blocker codes and the first safe action; a passing check
means only that window-time evidence can be prepared next. The claim is once per
date, never retries or backfills, does not consume the formal daily attempt or
forward-trial eligibility, and never contacts a provider or broker, runs risk or
paper/shadow, creates an OMS order, mutates the ledger, changes capital authority,
or establishes profitability.

The claimed background attempt persists one privacy-minimized Operations alert
for `no_action`, read-only ticket review, interruption, or fail-closed failure.
When notification is configured, a `no_action` message contains only the market
date and at most eight named blockers, and delivery is bounded to ten seconds.
The attempt records alert/notification status; delivery or alert-store failure cannot trigger a retry, create an OMS
order, contact a broker, mutate the ledger, or change capital authority.

Decision → Automation also shows `karkinos.daily_candidate_runtime_status.v1`.
It proves whether the exact in-process monitor task is still running. The
monitor is not configurable: a missing, completed, cancelled, or failed task is
a service failure and blocks the automatic attempt even when the decision
window itself is open. The manual window remains a separate fact. Runtime-task liveness never claims that Account
Truth, market, strategy, fees, risk, or reconciliation are financially ready,
and the status read performs no provider call, database write, broker action,
or authority change.

Automation Cockpit v4 also shows
`karkinos.daily_candidate_financial_preflight.v1`. This read-only projection
rebuilds the current Decision and plan from persisted facts, then checks the
same-date Account Truth capture, trusted persisted quotes, exact promoted
strategy and frozen-dataset replay, current reviewed-fee/date binding, safe
automation policy, and prior-execution closure. A green preflight means only
that one canonical risk plus paper/shadow attempt may start inside the reviewed
window. It does not run risk, simulate an order, create a ticket, touch OMS or
the production ledger, contact a provider or broker, expand capital, or prove
profitability. The post-shadow production gate still decides whether a
read-only manual ticket candidate exists. Any missing or drifted source is
shown as a named `NO-ACTION` reason.

The preflight also returns a read-only `operator_checklist` in dependency order:
Account Truth, account-specific fees, and strategy review come before prior
execution closure, current quotes, the Decision/plan, and the runtime window.
Each step carries its exact blockers, the
`karkinos.daily_candidate_operator_evidence.v1` evidence contract, completion
criteria, and review surface. Account Truth explicitly requires same-current-
Shanghai-date cash and position snapshots, itemized
`quantity/price/gross_amount/fee/tax/transfer_fee/net_amount`, reviewed source
hash/window/scope/completeness metadata, latest-ledger-cutoff coverage, and zero
unresolved cash/position/fee/cost-basis mismatches. Raw XLS rows and private
account identifiers are not required to be stored, and an owner statement is
not accepted as a financial fact. The strategy step requires five dependent
sequential iterations and ten calls, not five parallel calls. Its saved policy
must use `unbounded_daily`: Karkinos applies no daily aggregate token budget,
while provider per-request/context limits and token-usage accounting remain.
The checklist performs no
repair, evidence write, strategy approval, ticket creation, execution grant, or
capital change. When every gate passes, it still points only to one canonical
paper/shadow attempt.

Run `uv run python scripts/service/audit_daily_candidate_production.py --pretty` from
the repository root to verify the current machine rather than only the code
manifest. The command accepts only an explicit loopback HTTP base URL and reads
the live Automation Cockpit plus shadow-research status. It returns a sanitized,
fingerprinted `karkinos.daily_candidate_production_readiness.v2` report with the
current financial preflight, exact monitor liveness, five-sequential-iteration
and unbounded-daily-token policy, and forward-trial counts. It also carries the
canonical dependency-ordered operator checklist. Repeated per-candidate blockers
are grouped by blocker code with occurrence and affected-candidate counts, while
the exact first gate, safe action, required persisted evidence, and completion
criteria remain visible. Invalid, missing, authority-granting, or non-canonical
checklist input fails the report closed instead of being accepted as operator
guidance. Exit `0` means the running service is ready to
continue bounded paper/shadow evidence collection; it does not mean the 20-day /
50-order threshold has been reached. Exit `2` means fail-closed non-readiness,
including an unreachable service. Repository tests or a static acceptance
manifest cannot make this live report green. The report contains no XLS rows,
account identifiers, broker action, database write, execution grant, capital
change, or profitability claim.

On an owner-operated Mac, a terminal background process is not durable service
evidence. Production must already have a verified immutable `current` release;
start or repair its supervised service only with
`./scripts/start_server.sh prod`. A successful command verifies the running
version, commit SHA, artifact fingerprint, process health, and live scheduler
against `current`. Then run
`uv run python scripts/service/audit_daily_candidate_production.py --pretty` to
check the application-level production gates. Stop the exact supervised service
with `./scripts/stop_server.sh prod`. `scripts/service/manage_launch_agent.sh` is an
internal locked backend and must not be invoked directly for installation,
restart, or removal. The service binds only `127.0.0.1`, restarts after process
exit while loaded, and always starts the scheduler, which may contact the
configured market-data provider; none of this establishes financial readiness
or broker authority. If another listener owns port 8000, startup fails without
stopping it. Resolve that exact process explicitly; never run two daily-
candidate services against one local runtime database.

## Forward operating trial

The production panel counts a date only when all of the following are true:

- the official SSE calendar snapshot is verified and marks it as a trading
  day;
- the run date is not later than the projection's Shanghai as-of date, and
  both persisted run timestamps are timezone-aware and no later than that
  single captured as-of time;
- exactly one daily-candidate input fingerprint exists for the date;
- that input fingerprint replays from the persisted Decision/plan identity,
  production blockers, sanitized risk failure, frozen strategy binding,
  paper/shadow result, and prior-execution closure;
- the production gate passed and emitted a manual ticket candidate;
- every emitted read-only ticket has a replay-valid fingerprint, exact date,
  final Decision/plan timestamps inside the reviewed window, a current quote no
  more than 300 seconds old, paper/shadow identity, prior-execution closure,
  and explicit no-OMS/no-broker/no-capital-authority boundaries;
- each ticket and daily snapshot contain the exact same strategy-gate binding:
  strategy advancement, reviewed fee schedule, comparison, human approval,
  frozen baseline/candidate dataset identities, dataset replay fingerprint,
  current verified daily-selection/strategy-backup fingerprints, and the exact
  strategy operating constraints copied from that backup;
- those strategy operating constraints have a replay-valid content fingerprint,
  non-empty hypothesis, risk impact, failure conditions, limitations, and
  anti-lookahead assumptions, while retaining explicit human-review-only,
  no-execution, and no-capital-change boundaries;
- each ticket and daily snapshot contain the exact same privacy-minimized
  Account Truth binding: source fingerprint, capture/derived age, reviewed age
  maximum, valuation snapshot, ledger cutoff, reconciliation, coverage, and a
  content fingerprint over the referenced import events, human reviews,
  immutable valuation, and historical ledger rows; no broker rows, account
  identifiers, or balances are copied into the binding;
- same-day Account Truth source identity, capture-before-Decision ordering,
  derived age inside the reviewed maximum, and complete ledger coverage remain
  bound, and every prior non-simulation order is currently reconciled;
- the trial re-resolves that historical Account Truth reference and recomputes
  its privacy-minimized replay fingerprint at the stored ledger cutoff. Later
  append-only ledger rows are a safe continuation, while a missing import,
  changed review, modified source event, valuation drift, or changed/deleted
  ledger row at or below the cutoff excludes the day;
- the trial recomputes the current execution closure: every order already
  present in the historical closure must remain clear with the same
  plan/paper/actual fingerprint, while later fully reconciled orders may form a
  safe superset; any current unresolved order or historical-source drift
  excludes the day;
- trial v2 separately summarizes the complete current non-paper/shadow OMS
  population as reconciled actual orders or terminal no-fills. The summary is
  privacy-minimized, fingerprinted, and derived only from the canonical closure;
  these real outcomes are not attributed to the trial strategy and never count
  toward the 50 simulated-order threshold;
- the persisted paper/shadow run has matching date and fingerprint, exact
  candidate/order counts, and `within_expectations` status and divergence;
- the same non-empty strategy-advancement, reviewed-fee, and strategy-operating-
  constraint fingerprint bundles remain frozen within the current trial epoch.
- for every stored strategy reference, the trial re-resolves the current
  persisted order-generation gate and compares its full binding with the
  snapshot and ticket; an AI strategy's missing legacy selection/backup
  binding, deleted backup, fingerprint drift, pause, or current promotion
  blocker excludes the day and blocks GO review.

A strategy-advancement, reviewed-fee, or reviewed strategy-operating-constraint
binding change deterministically starts a new trial epoch at its first observed
daily record. Older qualifying days are kept as superseded evidence and never
merged into the new 20-day / 50-order count. If a previously used binding later
returns, it still starts a new epoch.

The minimum review threshold is 20 qualifying trading days and 50 simulated
orders. Meeting it permits only an exact human GO/NO-GO review:

- `continue_paper_shadow` keeps collecting evidence;
- `no_go` records that the strategy should not advance;
- `go_to_bounded_manual_trial` records a research conclusion for a separately
  authorized, small, reversible manual trial.

The review binds the current trial fingerprint, current execution-evidence
fingerprint, reviewer, note, and exact confirmation phrase. It does not issue
an order, authorization, or capital limit. A later reconciled fill, terminal
no-fill, unresolved order, or other evidence drift produces a new fingerprint
and requires a new review.

## Failure and recovery

| Evidence state | Required result | Safe recovery |
| --- | --- | --- |
| Account Truth missing, stale, or mismatched | `no_action` | Explicitly ingest and reconcile newer evidence |
| Account Truth was not captured on the plan's Shanghai date or its ledger coverage is not `covered` | `no_action` | Import and review the current account snapshot |
| Account Truth was captured after the Decision or exceeds its reviewed age at Decision | `no_action`; date excluded | Wait for a new reviewed snapshot and the next clean Decision |
| Referenced Account Truth import/review/valuation/historical ledger cannot be replayed exactly | `no_action`; date excluded | Restore or re-import canonical evidence; never edit the daily record or bypass the cutoff |
| Prior non-simulation order lacks current reconciliation or its plan/paper/actual source changed | `no_action` | Complete exact execution reconciliation; do not bypass or edit evidence |
| Current real-order closure changes after a trial review | Old review is no longer current | Inspect the new plan/paper/actual or terminal-no-fill summary and record a new bounded human review; do not count it toward the simulated sample |
| Quote timestamp absent or not on the plan date | `no_action` | Persist current-date trusted market evidence |
| Decision/plan generated outside 09:35-09:45 or quote age exceeds 300 seconds | `no_action`; date excluded | Wait for the next verified window and refresh persisted quotes before running |
| Intent price differs from its bound current quote, or quote source is absent | `no_action` | Rebuild Decision and plan from current persisted quotes |
| Strategy advancement or fee binding missing | `no_action` | Return to Strategy Lab or fee-schedule review |
| Strategy hypothesis, risk impact, failure conditions, limitations, or anti-lookahead assumptions are missing or drifted | `no_action`; latest day blocks GO review | Rebuild the verified backup and obtain a new explicit human paper/shadow promotion; never infer or patch constraints in a ticket |
| Frozen dataset replay, comparison, human approval, or ticket/snapshot strategy binding drifts | `no_action`; latest day blocks GO review | Rebuild and human-review the canonical strategy advancement evidence; never edit the daily record |
| Risk gate incomplete or blocked | `no_action` | Inspect the named risk or data-quality blocker |
| Paper/shadow failed, diverged, missing, or count-mismatched | `no_action` | Inspect the persisted simulation; do not hand-edit it |
| Two input fingerprints on one market date | Trial date excluded | Review the drift and continue on a later clean date |
| Stored daily input identity cannot be replayed | Trial date excluded | Preserve the record, investigate source drift or tampering, and continue on a later clean date |
| Background alert or notification fails | Candidate result remains unchanged and no retry occurs | Inspect the attempt's sanitized `operator_alert` / `notification` status before the next window |
| Pre-window preparation record is blocked, invalid, interrupted, or missing | Formal attempt remains untouched; no retry or backfill is granted | Review the sanitized first gate before a later clean window; never treat preparation as a trading result |
| Background monitor is missing, completed, cancelled, or failed | No automatic attempt; runtime status fails closed | Restart the service, investigate the task failure, and verify `background_monitor_running=true` before the next window |
| macOS LaunchAgent is unloaded or service readiness is unavailable | No durable automatic-monitor claim | Run `./scripts/start_server.sh prod`, then the production-readiness audit; do not invoke the internal LaunchAgent manager or infer financial readiness from launchd state |
| Background window passes without a record | `missed_decision_window`; no backfill | Prepare current evidence before the next verified trading-day window |
| Strategy, reviewed-fee, or strategy-operating-constraint fingerprint changes | New trial epoch starts | Keep old samples as superseded evidence; do not merge them |
| Kill Switch unavailable or active | `no_action` | Restore or explicitly review trading controls |

## What this evidence does not prove

Twenty days and 50 simulated orders test reproducibility, execution assumptions,
and operating discipline. They do not establish that future returns will be
positive. Backtest advancement evidence, the forward operating trial, small
manual outcomes, after-cost performance, drawdown, and plan/paper/actual drift
must remain separate evidence layers. Capital changes continue through the
existing evidence-based capital review and a new explicit human authorization.
