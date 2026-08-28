"""Acceptance manifests for operations."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def _operations_runbook_criteria_part_1() -> tuple[AcceptanceCriterion, ...]:
    return (
        AcceptanceCriterion(
            key="operations_today_runbook",
            checkbox_text=(
                "* [x] `/api/operations/today` exposes subsystem health, "
                "last run, next action, limitations, and paper/shadow "
                "summary evidence without mutating trading state."
            ),
            evidence_paths=(
                "server/services/operations_today.py",
                "server/routes/operations.py",
                "tests/test_operations_today.py",
                "tests/server/test_operations_routes.py",
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_operations_today.py tests/server/test_operations_routes.py",
                "npm --prefix web test -- overview-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="scheduler_run_persistence",
            checkbox_text=(
                "* [x] Scheduler runs record ids, input snapshots, "
                "fingerprints, idempotency keys, errors, retry state, and "
                "limitations for runbook review."
            ),
            evidence_paths=(
                "server/services/market_session_automation.py",
                "server/services/automation_control.py",
                "tests/test_market_session_automation.py",
                "tests/test_automation_control.py",
                "tests/server/test_automation_routes.py",
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_market_session_automation.py tests/test_automation_control.py tests/server/test_automation_routes.py",
                'npm --prefix web test -- overview-page.test.tsx -t "failed scheduler run recovery"',
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_run_storage",
            checkbox_text=(
                "* [x] Paper/shadow runs persist run ids, plan dates, "
                "fingerprints, counts, evidence refs, limitations, and "
                "payloads for deterministic review."
            ),
            evidence_paths=(
                "server/db.py",
                "server/services/paper_shadow_run.py",
                "tests/test_paper_shadow_runs.py",
                "tests/test_paper_shadow_run_service.py",
            ),
            validation_commands=(
                "uv run pytest tests/test_paper_shadow_runs.py tests/test_paper_shadow_run_service.py",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_oms_state_machine",
            checkbox_text=(
                "* [x] Paper/shadow OMS records use explicit lifecycle "
                "states and record accepted transitions with timestamp, "
                "reason, source, and evidence payloads."
            ),
            evidence_paths=(
                "server/services/oms.py",
                "server/services/paper_shadow_run.py",
                "tests/test_oms_service.py",
                "tests/test_paper_shadow_run_service.py",
            ),
            validation_commands=(
                "uv run pytest tests/test_oms_service.py tests/test_paper_shadow_run_service.py",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_simulation_outcomes",
            checkbox_text=(
                "* [x] Paper/shadow simulation covers filled, partial, "
                "rejected, cancelled, expired, failed, fee/tax projection, "
                "idempotent rerun evidence, OMS transition refs in both "
                "run and simulated order payloads, simulated fill "
                "intent/evidence refs, and terminal reason review evidence "
                "without production ledger mutation."
            ),
            evidence_paths=(
                "execution/paper_broker.py",
                "server/services/paper_shadow_run.py",
                "tests/execution/test_paper_broker.py",
                "tests/test_paper_shadow_run_service.py",
            ),
            validation_commands=(
                "uv run pytest tests/execution/test_paper_broker.py tests/test_paper_shadow_run_service.py",
                "uv run python -m pytest tests/test_paper_shadow_run_service.py -k cancelled_and_expired",
                "uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_creates_simulated_order_and_fill_without_ledger_mutation -q",
                "uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_records_failed_run_when_simulation_errors -q",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_run_review_outcomes",
            checkbox_text=(
                "* [x] Paper/shadow run-level operator reviews are stored "
                "as audit evidence while preserving raw divergence status "
                "and exposing a runbook effective status, while keeping "
                "broker submission disabled."
            ),
            evidence_paths=(
                "server/db.py",
                "server/routes/operations.py",
                "server/services/operations_today.py",
                "tests/test_paper_shadow_runs.py",
                "tests/test_operations_today.py",
                "tests/server/test_operations_routes.py",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_paper_shadow_runs.py tests/test_operations_today.py tests/server/test_operations_routes.py",
                "npm --prefix web test -- trading-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_rich_divergence_report",
            checkbox_text=(
                "* [x] Paper/shadow divergence summaries compare expected "
                "strategy behavior, simulated execution, current account "
                "truth, realized market context, cost evidence, and "
                "explicit non-submission safety evidence, and persisted "
                "runs expose structured operator review queues for "
                "diverged, failed, or missing simulations in Operations, "
                "Decision, and Overview."
            ),
            evidence_paths=(
                "server/services/paper_shadow_run.py",
                "server/services/operations_today.py",
                "tests/test_paper_shadow_run_service.py",
                "tests/test_operations_today.py",
                "tests/server/test_operations_routes.py",
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_paper_shadow_run_service.py",
                "uv run pytest tests/test_operations_today.py",
                "uv run pytest tests/server/test_operations_routes.py -k paper_shadow",
                "npm --prefix web test -- overview-page.test.tsx decision-cockpit-page.test.tsx trading-page.test.tsx",
                "npm --prefix web run build",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_fallback_review_queue",
            checkbox_text=(
                "* [x] Operations Today preserves operator review work "
                "for legacy or partial paper/shadow runs by synthesizing "
                "read-only review-queue evidence, OMS status paths, and "
                "transition refs for diverged, failed, or missing "
                "simulations without broker submission or "
                "production-ledger mutation."
            ),
            evidence_paths=(
                "server/services/operations_today.py",
                "tests/test_operations_today.py",
                "docs/README.en.md",
                "docs/README.zh.md",
                "docs/IMPLEMENTATION_LOG.md",
            ),
            validation_commands=(
                'uv run python -m pytest tests/test_operations_today.py -k "legacy_diverged_run or legacy_review_queue or missing_simulation"',
                "uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_manual_handoff_gate",
            checkbox_text=(
                "* [x] Operations, Decision, and Overview expose an "
                "explicit paper/shadow manual-confirmation handoff gate "
                "with readiness, blockers, review metadata, review-queue "
                "count, and no-broker/no-ledger-mutation safety evidence."
            ),
            evidence_paths=(
                "server/services/operations_today.py",
                "tests/test_operations_today.py",
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "docs/IMPLEMENTATION_LOG.md",
            ),
            validation_commands=(
                'uv run python -m pytest tests/test_operations_today.py -k "manual_handoff or accepted_shadow_divergence"',
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual handoff gate"',
                'npm --prefix web test -- overview-page.test.tsx -t "accepted paper shadow review"',
            ),
        ),
        AcceptanceCriterion(
            key="frontend_paper_shadow_next_actions",
            checkbox_text=(
                "* [x] Decision, Overview, and Trading surfaces show "
                "paper/shadow next actions and structured review-queue "
                "summaries for not-run, running, failed, diverged, "
                "accepted-review, and within-expectations states without "
                "exposing raw state-machine internals; input snapshot "
                "summaries and terminal reasons are rendered as public "
                "review evidence, and accepted reviews display as "
                "manual-confirmation handoffs."
            ),
            evidence_paths=(
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
                "web/src/features/operations/api.ts",
            ),
            validation_commands=(
                "npm --prefix web test -- overview-page.test.tsx decision-cockpit-page.test.tsx trading-page.test.tsx",
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "paper shadow review queue"',
                'npm --prefix web test -- overview-page.test.tsx -t "divergence evidence summary"',
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "terminal paper shadow review reasons"',
                'npm --prefix web test -- overview-page.test.tsx -t "terminal paper shadow review reasons"',
                'npm --prefix web test -- trading-page.test.tsx -t "terminal paper shadow review reasons"',
                'npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"',
            ),
        ),
    )


def _operations_runbook_criteria_part_2() -> tuple[AcceptanceCriterion, ...]:
    return (
        AcceptanceCriterion(
            key="automation_run_failure_alerts",
            checkbox_text=(
                "* [x] Failed paper/shadow automation runs generate "
                "acknowledgeable operations alerts with input snapshots, "
                "rerun keys, retry context, limitations, and explicit "
                "non-submission safety evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/services/automation_cockpit.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "uv run python -m pytest tests/test_automation_alerts.py::test_alert_scan_records_failed_paper_shadow_automation_run -q",
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "failed paper shadow automation recovery"',
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="connector_health_alerts",
            checkbox_text=(
                "* [x] Incomplete read-only broker connector health "
                "generates acknowledgeable operations alerts that preserve "
                "capability scope, read/query capability flags, explicit "
                "preview/export/dry-run/cancel/submit blockers, "
                "credential-storage status, and non-submission evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/services/broker_gateway.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="runtime_connector_degradation_alerts",
            checkbox_text=(
                "* [x] Runtime-degraded read-only broker connector "
                "snapshots are polled through the broker-gateway health "
                "contract, local JSON export adapters can provide runtime "
                "read-only snapshots, and degraded snapshots generate "
                "acknowledgeable operations alerts with heartbeat/error "
                "context, capability scope, read/query capability flags, "
                "explicit preview/export/dry-run/cancel/submit blockers, "
                "manual-review requirement, and explicit non-submission "
                "evidence."
            ),
            evidence_paths=(
                "account_truth/broker_connector.py",
                "server/services/broker_connector_runtime.py",
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/routes/broker_gateway.py",
                "server/services/broker_gateway.py",
                "tests/account_truth/test_broker_connector.py",
                "tests/server/test_broker_gateway_routes.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/account_truth/test_broker_connector.py tests/server/test_broker_gateway_routes.py",
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="daily_plan_risk_blocker_alerts",
            checkbox_text=(
                "* [x] Daily trading-plan risk blockers generate "
                "acknowledgeable operations alerts with blocker counts, "
                "risk reasons, manual-review requirement, and explicit "
                "non-submission evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/services/daily_trading_plan.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "tests/test_daily_trading_plan.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py tests/test_daily_trading_plan.py",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="stale_market_data_alerts",
            checkbox_text=(
                "* [x] Stale market-data health snapshots generate "
                "acknowledgeable operations alerts with source health, "
                "stale-symbol samples, next action, manual-review "
                "requirement, and explicit non-submission evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/routes/market.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "tests/test_server_routes.py",
                "web/src/features/market/api.ts",
                "web/src/features/operations/api.ts",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "uv run pytest tests/test_server_routes.py -k market_data_health",
            ),
        ),
        AcceptanceCriterion(
            key="account_truth_mismatch_alerts",
            checkbox_text=(
                "* [x] Degraded or blocked Account Truth snapshots "
                "generate acknowledgeable operations alerts with gate "
                "status, mismatch counts, review actions, manual-review "
                "requirement, and explicit non-submission/non-ledger "
                "mutation evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "account_truth/score.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "tests/account_truth/test_account_truth_score.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "uv run pytest tests/account_truth/test_account_truth_score.py",
            ),
        ),
        AcceptanceCriterion(
            key="paper_shadow_order_divergence_alerts",
            checkbox_text=(
                "* [x] Paper/shadow diverged or review-required runs "
                "generate acknowledgeable operations alerts with run id, "
                "order/fill counts, divergence counts, next review step, "
                "evidence refs, and explicit non-submission/non-ledger "
                "mutation evidence."
            ),
            evidence_paths=(
                "server/services/automation_alerts.py",
                "server/routes/automation.py",
                "server/services/paper_shadow_run.py",
                "tests/test_automation_alerts.py",
                "tests/server/test_automation_routes.py",
                "tests/test_paper_shadow_run_service.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                "uv run pytest tests/test_paper_shadow_run_service.py",
            ),
        ),
        AcceptanceCriterion(
            key="operations_source_control_hygiene",
            checkbox_text=(
                "* [x] CI repository hygiene blocks tracked runtime "
                "databases, logs, exports, screenshots, generated "
                "reports, local secrets, and agent/plugin state from "
                "source control."
            ),
            evidence_paths=(
                ".github/workflows/ci.yml",
                ".gitignore",
                "tests/test_ci_workflow.py",
                "docs/IMPLEMENTATION_LOG.md",
            ),
            validation_commands=(
                "uv run python -m pytest tests/test_ci_workflow.py -k repository_hygiene",
                "git ls-files reports data/store logs exports screenshots",
            ),
        ),
    )


def _operations_runbook_criteria_part_3() -> tuple[AcceptanceCriterion, ...]:
    return (
        AcceptanceCriterion(
            key="production_daily_candidate_outcome",
            checkbox_text=(
                "* [x] The canonical current-facts daily candidate run "
                "replays Decision, plan, risk, strategy advancement, "
                "same-market-date Account Truth promotion evidence, "
                "per-intent current quote identity, reviewed costs, exact "
                "paper/shadow, and current prior-"
                "execution reconciliation before emitting only a "
                "fingerprinted read-only manual-ticket candidate or named "
                "no-action result; its always-running background caller "
                "uses a verified SSE decision window and one atomic "
                "fail-closed attempt per market date; final Decision/plan "
                "times and every quote are replayed against that window "
                "and a 300-second maximum quote age; Account Truth must "
                "precede the Decision and pass a replayed age limit. The "
                "input identity binds sanitized risk failure, strategy, "
                "paper/shadow, execution closure, and blockers so same-day "
                "drift is retained instead of overwritten. Every ticket and "
                "snapshot share one replayed strategy, human approval, "
                "reviewed fee, comparison, frozen-dataset, and verified "
                "daily-selection/backup binding; deletion, fingerprint "
                "drift, or a legacy missing binding fails closed."
                " They also share one privacy-minimized Account Truth "
                "capture, valuation, ledger, reconciliation, and coverage "
                "binding without account identity or balances; its import "
                "events, human reviews, immutable valuation, and ledger "
                "rows through the stored cutoff are content-bound for "
                "historical replay."
                " Each claimed background attempt persists a bounded "
                "non-authorizing operator alert and sanitized NO-ACTION "
                "notification status without enabling retry."
            ),
            evidence_paths=(
                "server/db.py",
                "server/routes/decision.py",
                "server/services/daily_decision_evidence_automation.py",
                "server/account_truth_gate.py",
                "server/services/daily_candidate_execution_closure.py",
                "server/services/daily_trading_plan.py",
                "server/services/ai_shadow_research_automation.py",
                "server/services/ai_shadow_research_daily_artifacts.py",
                "server/services/strategy_promotion_pipeline.py",
                "server/routes/automation.py",
                "server/routes/trading.py",
                "tests/test_daily_candidate_execution_closure.py",
                "tests/test_daily_candidate_background_schedule.py",
                "tests/test_daily_decision_evidence_automation.py",
                "tests/server/test_account_truth_gate.py",
                "tests/server/test_ai_shadow_research_automation.py",
                "tests/server/test_ai_shadow_research_daily_artifacts.py",
                "tests/test_per_order_gateway_strategy_advancement.py",
                "tests/server/test_decision_trading_plan_routes.py",
                "tests/server/test_automation_routes.py",
                "tests/server/test_trading_routes.py",
            ),
            validation_commands=(
                "uv run python -m pytest tests/test_daily_candidate_background_schedule.py tests/test_daily_candidate_execution_closure.py tests/test_daily_decision_evidence_automation.py tests/server/test_account_truth_gate.py tests/server/test_ai_shadow_research_automation.py tests/server/test_ai_shadow_research_daily_artifacts.py tests/test_per_order_gateway_strategy_advancement.py tests/server/test_decision_trading_plan_routes.py tests/server/test_automation_routes.py tests/server/test_trading_routes.py",
            ),
        ),
        AcceptanceCriterion(
            key="daily_candidate_forward_trial",
            checkbox_text=(
                "* [x] The forward operating trial counts only verified "
                "trading days with one input fingerprint in the latest "
                "frozen strategy-and-reviewed-fee epoch, reads complete "
                "persisted history without merging old epochs, recomputes "
                "the input identity and Account Truth age, rejects future "
                "run dates or run timestamps against one captured as-of, binds "
                "same-day Account Truth and re-resolves its historical "
                "import/review/valuation/ledger-cutoff fingerprint, "
                "replay-valid read-only tickets, a current execution-closure "
                "safe superset with unchanged historical plan/paper/actual facts, "
                "and a fingerprinted privacy-minimized summary of every current "
                "non-paper/shadow OMS order as reconciled actual or terminal "
                "no-fill evidence. That summary is bound into the trial and "
                "human review, so later real-order closure changes invalidate "
                "the old review without counting or attributing real orders to "
                "the 50 simulated-order sample; "
                "current re-resolved strategy promotion plus daily-backup "
                "evidence, and exact drift-clear paper/shadow evidence; 20 days and "
                "50 simulated orders permit only an exact human GO/NO-GO "
                "review."
            ),
            evidence_paths=(
                "server/services/daily_candidate_execution_closure.py",
                "server/services/daily_candidate_trial.py",
                "tests/test_daily_candidate_trial.py",
                "server/services/daily_candidate_production_readiness.py",
                "tests/test_daily_candidate_production_readiness.py",
                "server/routes/automation.py",
                "tests/server/test_automation_routes.py",
            ),
            validation_commands=(
                "uv run python -m pytest tests/test_daily_candidate_trial.py tests/test_daily_candidate_production_readiness.py tests/server/test_automation_routes.py",
            ),
        ),
        AcceptanceCriterion(
            key="daily_candidate_production_operator_runbook",
            checkbox_text=(
                "* [x] Decision Automation shows 20-day / 50-order trial "
                "progress and records GO, continue, or NO-GO without "
                "execution/capital authority; Automation Cockpit v4 "
                "separates exact background-task liveness from a zero-write "
                "financial preflight that can open only risk plus "
                "paper/shadow; it also shows current real-order closure "
                "separately from the simulated sample, and bilingual runbooks define daily "
                "operation and fail-closed recovery."
            ),
            evidence_paths=(
                "server/services/daily_candidate_runtime_status.py",
                "server/services/daily_decision_evidence_automation.py",
                "server/services/reviewed_fee_schedule.py",
                "server/services/automation_cockpit.py",
                "tests/test_daily_candidate_runtime_status.py",
                "tests/test_daily_decision_evidence_automation.py",
                "tests/test_automation_cockpit.py",
                "web/src/features/decision/components/daily-candidate-trial-panel.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "web/src/features/operations/api.ts",
                "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.md",
                "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.zh.md",
            ),
            validation_commands=(
                "uv run python -m pytest tests/test_daily_candidate_runtime_status.py tests/test_daily_decision_evidence_automation.py tests/test_automation_cockpit.py tests/server/test_automation_routes.py",
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "summarizes controlled automation cockpit status"',
                "uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook",
            ),
        ),
        AcceptanceCriterion(
            key="live_daily_candidate_production_readiness_audit",
            checkbox_text=(
                "* [x] A loopback-only, read-only production-readiness "
                "audit combines the live Automation Cockpit financial "
                "preflight, exact monitor task, forward trial, and five-"
                "sequential-iteration research policy into one sanitized "
                "fingerprinted report. Unreachable service, invalid "
                "contracts, stale financial evidence, missing monitor, "
                "legacy research limits, scan truncation, or authority "
                "drift returns non-ready; repository tests cannot make "
                "the live report green."
            ),
            evidence_paths=(
                "server/services/daily_candidate_production_readiness.py",
                "server/daily_candidate_production_readiness_cli.py",
                "scripts/service/audit_daily_candidate_production.py",
                "tests/test_daily_candidate_production_readiness.py",
                "tests/test_daily_candidate_production_readiness_cli.py",
                "scripts/README.md",
                "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.md",
                "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.zh.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_daily_candidate_production_readiness.py tests/test_daily_candidate_production_readiness_cli.py",
                "uv run pytest tests/test_acceptance_audit.py -k operations_runbook",
            ),
        ),
        AcceptanceCriterion(
            key="simulation_evidence_safety_docs",
            checkbox_text=(
                "* [x] README, architecture, roadmap, and implementation "
                "log keep the boundary explicit: paper/shadow records are "
                "simulation evidence and do not submit broker orders."
            ),
            evidence_paths=(
                "README.md",
                "docs/README.en.md",
                "docs/README.zh.md",
                "docs/ARCHITECTURE.md",
                "docs/ROADMAP.md",
                "docs/IMPLEMENTATION_LOG.md",
            ),
            validation_commands=(
                'rg -n "paper/shadow|simulation evidence|does not submit|不会提交券商订单" README.md docs',
                "uv run pytest tests/test_acceptance_audit.py -k operations_runbook",
            ),
        ),
    )


def build_operations_runbook_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for completed Operations and paper/shadow runbook pieces."""
    return AcceptanceAudit(
        criteria=(
            *_operations_runbook_criteria_part_1(),
            *_operations_runbook_criteria_part_2(),
            *_operations_runbook_criteria_part_3(),
        )
    )
