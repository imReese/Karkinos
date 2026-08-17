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
   approval fingerprints, and keep provider contact and live-like authority off.
2. The sanitized Account Truth promotion evidence is `clear`, `pass`, fresh,
   ledger-covered, has zero unresolved mismatches, and binds current cash and
   position snapshots captured on the plan's Shanghai market date and no later
   than the final Decision. Capture is the earlier of those latest snapshot
   timestamps; the later local file-ingestion time is only `imported_at` and
   cannot refresh old evidence. Snapshot age at Decision must remain inside the
   reviewed maximum. The evidence also binds its source fingerprint, valuation
   snapshot, and positive ledger cutoff.
3. The final Decision and plan are generated only from 09:35 through 09:44
   Asia/Shanghai. Every order intent uses its current persisted market quote
   rather than the historical signal price, and binds that quote's positive
   price, source, aware timestamp, and age at decision. The quote must be on the
   same market date and no more than 300 seconds old.
4. The account-specific reviewed fee schedule covers the action date and every
   order intent resolves a non-negative fee from that schedule.
5. Pre-trade risk is passed and bound by one exact risk decision per intent.
6. Kill Switch and automation policy permit paper/shadow only; broker
   submission remains disabled.

Missing, stale, conflicting, estimated, partial, future-dated, or
unreproducible evidence produces `no_action`.

## Daily operator sequence

1. Before the decision cutoff, explicitly ingest or review current market and
   Account Truth evidence. Read pages do not refresh providers.
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
4. Karkinos rebuilds Decision and the trading plan, runs the canonical batch
   risk gate, persists one deterministic paper/shadow simulation, then rebuilds
   the plan again before resolving the production outcome.
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

When live monitoring is owner-enabled, the background loop reads the persisted,
officially verified SSE calendar and may call the same service only from 09:35
through 09:44 Asia/Shanghai. It skips closed or unverified days and atomically
claims one background attempt for the market date before invoking the service.
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

The claimed background attempt persists one privacy-minimized Operations alert
for `no_action`, read-only ticket review, interruption, or fail-closed failure.
When notification is configured, a `no_action` message contains only the market
date and at most eight named blockers, and delivery is bounded to ten seconds.
The attempt records alert/notification status; delivery or alert-store failure cannot trigger a retry, create an OMS
order, contact a broker, mutate the ledger, or change capital authority.

Decision → Automation also shows `karkinos.daily_candidate_runtime_status.v1`.
It separately proves whether owner configuration enabled the background monitor
and whether the exact in-process monitor task is still running. A disabled,
missing, completed, cancelled, or failed task is an operational blocker for the
automatic attempt even when the decision window itself is open. The manual
window remains a separate fact. Runtime-task liveness never claims that Account
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

On an owner-operated Mac, a terminal background process is not durable service
evidence. Before relying on the next decision window, first inspect the local
user-level definition with `./scripts/manage_launch_agent.sh print-plist`, then
explicitly install it with `./scripts/manage_launch_agent.sh install`. Verify
`./scripts/manage_launch_agent.sh status` reports both a loaded LaunchAgent and
process liveness. The service binds only `127.0.0.1`, restarts after an
unexpected exit, and is fully reversible with `uninstall`. Installation does
not edit `config.json` or `.env`, enable `live_auto_start`, contact a provider,
or establish financial readiness. If another listener owns the backend port,
installation fails without stopping it. The operator must resolve that exact
process explicitly; never run two daily-candidate services against one local
runtime database.

## Forward operating trial

The production panel counts a date only when all of the following are true:

- the official SSE calendar snapshot is verified and marks it as a trading
  day;
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
  frozen baseline/candidate dataset identities, and dataset replay fingerprint;
- each ticket and daily snapshot contain the exact same privacy-minimized
  Account Truth binding: source fingerprint, capture/derived age, reviewed age
  maximum, valuation snapshot, ledger cutoff, reconciliation, and coverage;
- same-day Account Truth source identity, capture-before-Decision ordering,
  derived age inside the reviewed maximum, and complete ledger coverage remain
  bound, and every prior non-simulation order is currently reconciled;
- the persisted paper/shadow run has matching date and fingerprint, exact
  candidate/order counts, and `within_expectations` status and divergence;
- the same non-empty strategy-advancement and reviewed-fee fingerprint bundles
  remain frozen within the current trial epoch.

A strategy-advancement or reviewed-fee binding change deterministically starts
a new trial epoch at its first observed daily record. Older qualifying days are
kept as superseded evidence and never merged into the new 20-day / 50-order
count. If a previously used binding later returns, it still starts a new epoch.

The minimum review threshold is 20 qualifying trading days and 50 simulated
orders. Meeting it permits only an exact human GO/NO-GO review:

- `continue_paper_shadow` keeps collecting evidence;
- `no_go` records that the strategy should not advance;
- `go_to_bounded_manual_trial` records a research conclusion for a separately
  authorized, small, reversible manual trial.

The review binds the current trial fingerprint, reviewer, note, and exact
confirmation phrase. It does not issue an order, authorization, or capital
limit. Later evidence drift produces a new fingerprint and requires a new
review.

## Failure and recovery

| Evidence state | Required result | Safe recovery |
| --- | --- | --- |
| Account Truth missing, stale, or mismatched | `no_action` | Explicitly ingest and reconcile newer evidence |
| Account Truth was not captured on the plan's Shanghai date or its ledger coverage is not `covered` | `no_action` | Import and review the current account snapshot |
| Account Truth was captured after the Decision or exceeds its reviewed age at Decision | `no_action`; date excluded | Wait for a new reviewed snapshot and the next clean Decision |
| Prior non-simulation order lacks current reconciliation or its plan/paper/actual source changed | `no_action` | Complete exact execution reconciliation; do not bypass or edit evidence |
| Quote timestamp absent or not on the plan date | `no_action` | Persist current-date trusted market evidence |
| Decision/plan generated outside 09:35-09:45 or quote age exceeds 300 seconds | `no_action`; date excluded | Wait for the next verified window and refresh persisted quotes before running |
| Intent price differs from its bound current quote, or quote source is absent | `no_action` | Rebuild Decision and plan from current persisted quotes |
| Strategy advancement or fee binding missing | `no_action` | Return to Strategy Lab or fee-schedule review |
| Frozen dataset replay, comparison, human approval, or ticket/snapshot strategy binding drifts | `no_action`; latest day blocks GO review | Rebuild and human-review the canonical strategy advancement evidence; never edit the daily record |
| Risk gate incomplete or blocked | `no_action` | Inspect the named risk or data-quality blocker |
| Paper/shadow failed, diverged, missing, or count-mismatched | `no_action` | Inspect the persisted simulation; do not hand-edit it |
| Two input fingerprints on one market date | Trial date excluded | Review the drift and continue on a later clean date |
| Stored daily input identity cannot be replayed | Trial date excluded | Preserve the record, investigate source drift or tampering, and continue on a later clean date |
| Background alert or notification fails | Candidate result remains unchanged and no retry occurs | Inspect the attempt's sanitized `operator_alert` / `notification` status before the next window |
| Background monitor is disabled, missing, completed, cancelled, or failed | No automatic attempt; runtime status fails closed | Keep the process stopped or restart only after explicit owner enablement, then verify `background_monitor_running=true` before the next window |
| macOS LaunchAgent is unloaded or process liveness is unavailable | No durable automatic-monitor claim | Explicitly inspect or reinstall the exact user-level service; do not infer financial readiness from launchd state |
| Background window passes without a record | `missed_decision_window`; no backfill | Prepare current evidence before the next verified trading-day window |
| Strategy or reviewed-fee fingerprint changes | New trial epoch starts | Keep old samples as superseded evidence; do not merge them |
| Kill Switch unavailable or active | `no_action` | Restore or explicitly review trading controls |

## What this evidence does not prove

Twenty days and 50 simulated orders test reproducibility, execution assumptions,
and operating discipline. They do not establish that future returns will be
positive. Backtest advancement evidence, the forward operating trial, small
manual outcomes, after-cost performance, drawdown, and plan/paper/actual drift
must remain separate evidence layers. Capital changes continue through the
existing evidence-based capital review and a new explicit human authorization.
