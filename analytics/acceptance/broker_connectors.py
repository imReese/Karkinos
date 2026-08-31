"""Acceptance manifests for broker connectors."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_broker_connector_soak_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the completed Stage 1 read-only soak foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="sanitized_local_broker_export_capture",
                checkbox_text=(
                    "* [x] Explicitly configured generic local read-only exports "
                    "can be captured as sanitized cash, position, order, fill, "
                    "health, capability, and source-time evidence without "
                    "storing or returning raw account ids."
                ),
                evidence_paths=(
                    "account_truth/broker_connector.py",
                    "server/services/broker_connector_runtime.py",
                    "server/services/broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_routes.py -k local_broker_export -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_soak_observation_evidence",
                checkbox_text=(
                    "* [x] Each observation has deterministic snapshot and "
                    "observation fingerprints, append-only local evidence, and "
                    "sequential rerun reuse without broker-write, OMS, or "
                    "production-ledger side effects."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "server/db.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k sanitized_persisted_and_reused -q",
                ),
            ),
            AcceptanceCriterion(
                key="soak_health_capability_fail_closed",
                checkbox_text=(
                    "* [x] Missing read capabilities, any submit capability, "
                    "stale/future/invalid timestamps, source-health degradation, "
                    "missing cash, or connector exceptions fail closed into "
                    "degraded or blocked soak evidence."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k 'stale or submit_capability or exception' -q",
                ),
            ),
            AcceptanceCriterion(
                key="provider_calendar_trading_day_coverage",
                checkbox_text=(
                    "* [x] Healthy-day coverage requires a provider market-"
                    "calendar snapshot and an explicit trading day; missing "
                    "calendars and closed days do not count toward the "
                    "20-trading-day target."
                ),
                evidence_paths=(
                    "data/market_calendar.py",
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k 'market_calendar or twenty_unsequenced_healthy_days or twenty_sequence_accepted_days' -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_api_and_operations_alerts",
                checkbox_text=(
                    "* [x] Capture, status, and observation APIs remain read-only "
                    "with respect to the broker, OMS, and ledger, while "
                    "degraded/blocked observations create sanitized Operations "
                    "alerts."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "server/services/broker_connector_soak.py",
                    "server/app.py",
                    "server/services/automation_alerts.py",
                    "tests/test_broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py tests/server/test_broker_connector_soak_routes.py tests/test_automation_alerts.py tests/server/test_automation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="operational_soak_does_not_promote",
                checkbox_text=(
                    "* [x] Twenty healthy trading days complete only the "
                    "operational soak; `promotion_ready` remains false until "
                    "Account Truth reconciliation and explicit owner acceptance "
                    "are linked."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k 'twenty_unsequenced_healthy_days or twenty_sequence_accepted_days' -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_operational_soak_phases",
                checkbox_text=(
                    "* [x] Startup, intraday, and end-of-day runbook phases "
                    "persist deterministic evidence; missing or unhealthy "
                    "read-only connector observations block the phase."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/routes/broker_connector_soak.py",
                    "tests/test_broker_connector_soak_runbook.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k 'startup or no_configured' -q",
                ),
            ),
            AcceptanceCriterion(
                key="end_of_day_reconciliation_gate",
                checkbox_text=(
                    "* [x] End-of-day runbook evidence requires a clear "
                    "execution reconciliation with zero open items; otherwise "
                    "it blocks and creates a sanitized Operations alert."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/execution_reconciliation.py",
                    "tests/test_broker_connector_soak_runbook.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k end_of_day -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_recovery_drills",
                checkbox_text=(
                    "* [x] Disconnect, schema-drift, stale-data, duplicate-"
                    "evidence, and restart-recovery drills record deterministic "
                    "pass/fail evidence and verify safe degradation or "
                    "sequential persisted-evidence reuse."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "tests/test_broker_connector_soak_runbook.py",
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k drill -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_runbook_api_boundary",
                checkbox_text=(
                    "* [x] Run and drill APIs reject undeclared fields and "
                    "credentials, expose only sanitized evidence, and cannot "
                    "submit/cancel orders, mutate OMS/ledger, or grant capital "
                    "authority."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "server/services/broker_connector_soak_runbook.py",
                    "tests/server/test_broker_connector_soak_runbook_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_runbook_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_neutral_soak_operator_runbook",
                checkbox_text=(
                    "* [x] A broker-neutral operator runbook documents local-"
                    "export setup, startup/intraday/end-of-day cadence, drill "
                    "preparation, expected safe states, review steps, and the "
                    "unchanged no-write boundary."
                ),
                evidence_paths=(
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_acceptance_audit.py -k broker_connector_soak -q",
                ),
            ),
        )
    )


def build_per_order_confirmation_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the non-submitting Stage 2 confirmation foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="deterministic_per_order_dossier",
                checkbox_text=(
                    "* [x] A canonical order fingerprint and deterministic "
                    "dossier bind OMS order terms, capital-evaluation evidence, "
                    "Account Truth/research/risk/paper-shadow gateway gates, "
                    "latest connector soak, prior reconciliation, and kill-"
                    "switch state."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/capital_authorization_audit.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'dossier_binds or fingerprint_is_stable' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_review_gates_fail_closed",
                checkbox_text=(
                    "* [x] Dossier review fails closed when the OMS order is not "
                    "manually confirmed, the capital evaluation is missing/"
                    "stale/mismatched/not allowed, required gateway evidence is "
                    "missing or blocked, the latest soak is unhealthy or no "
                    "longer fresh, prior reconciliation is not clear, or the "
                    "kill switch is unavailable/enabled."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'kill_switch or missing_capital' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_hard_submission_blockers",
                checkbox_text=(
                    "* [x] A current signed Stage 1 promotion may clear only "
                    "its Stage 1 blockers, and an exact current non-submitting "
                    "gateway verification may clear only the runtime-verification "
                    "blocker; evidence-connector read-only integrity, runtime "
                    "authority, live gateway, and broker submission remain explicit "
                    "hard blockers."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k dossier_binds -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_signed_broker_promotion_source_binding",
                checkbox_text=(
                    "* [x] Every per-order dossier resolves and fingerprints "
                    "the current Stage 1 promotion dossier, operational source, "
                    "Account Truth source, and verified owner-acceptance id for "
                    "the exact capital-policy connector."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k signed_stage1_promotion_is_bound -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_broker_promotion_evidence_drift_fails_closed",
                checkbox_text=(
                    "* [x] Missing, invalid, mismatched, or failed promotion "
                    "resolution remains blocked without leaking provider "
                    "details; source drift changes the per-order dossier and "
                    "invalidates the old artifact-bound operator approval."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "server/routes/per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -k 'source_drift or failed_signed or wires_current' -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_dossier_attestation_reuse",
                checkbox_text=(
                    "* [x] An exact dossier fingerprint can be attested only "
                    "when review gates and an artifact-bound signed operator "
                    "approval pass; the append-only record is sequentially "
                    "reusable verified-identity evidence that does not "
                    "authorize execution."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/db.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k exact_dossier -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_rejection_audit_zero_side_effects",
                checkbox_text=(
                    "* [x] Stale fingerprints and blocked dossiers create "
                    "deterministic rejected confirmation evidence without "
                    "changing OMS, contacting a broker, or mutating the "
                    "production ledger."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'stale_dossier or kill_switch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_confirmation_api_boundary",
                checkbox_text=(
                    "* [x] Status, preview, confirmation, and list APIs reject "
                    "undeclared credential fields and expose no enable, issue-"
                    "authority, submit, cancel, resume, or scale-up operation."
                ),
                evidence_paths=(
                    "server/routes/per_order_confirmation.py",
                    "server/app.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_confirmation_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover evidence "
                    "aggregation, fail-closed gates, hard submission blockers, "
                    "exact-fingerprint reuse, rejection audit, credential "
                    "rejection, and zero execution side effects."
                ),
                evidence_paths=(
                    "tests/test_per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
        )
    )


def build_broker_connector_soak_promotion_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the signed Stage 1.1 promotion dossier."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="promotion_account_truth_source_evidence",
                checkbox_text=(
                    "* [x] Promotion uses a sanitized, source-sensitive Account "
                    "Truth fact built from the latest persisted import, current "
                    "ledger projection, reconciliation items, review decisions, "
                    "and score; only pass/fresh/zero-unresolved evidence is clear."
                ),
                evidence_paths=(
                    "server/account_truth_gate.py",
                    "tests/server/test_account_truth_gate.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_account_truth_gate.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="twenty_clear_reconciled_soak_days",
                checkbox_text=(
                    "* [x] A promotion dossier selects exactly 20 unique "
                    "healthy read-only trading days whose snapshots each bind "
                    "a clear execution reconciliation with zero open items and "
                    "one stable connector account alias/hash."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k promotion_dossier -q",
                ),
            ),
            AcceptanceCriterion(
                key="daily_runbook_phase_coverage",
                checkbox_text=(
                    "* [x] Every selected trading day requires persisted passed "
                    "startup, intraday, and end-of-day runbook evidence for the "
                    "same connector; incomplete phase coverage blocks owner "
                    "acceptance."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k missing_daily_phase -q",
                ),
            ),
            AcceptanceCriterion(
                key="recovery_drill_and_external_assertion_boundary",
                checkbox_text=(
                    "* [x] Disconnect, schema-drift, stale-data, duplicate-"
                    "evidence, and service-instance restart drills must all "
                    "pass; full process and broker-terminal recovery remains an "
                    "explicit signed owner assertion rather than an automated "
                    "claim."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py tests/test_broker_connector_soak_promotion.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="source_bound_promotion_dossier",
                checkbox_text=(
                    "* [x] The deterministic promotion fingerprint binds the "
                    "selected observations, phase/run ids, drill ids, latest "
                    "snapshot, account alias/hash, and exact Account Truth "
                    "source fingerprint; source drift requires a new review."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k source_drift -q",
                ),
            ),
            AcceptanceCriterion(
                key="signed_append_only_owner_acceptance",
                checkbox_text=(
                    "* [x] Owner acceptance requires a short-lived Ed25519 "
                    "approval for the exact promotion dossier and matching "
                    "operator label; accepted/rejected records are append-only, "
                    "exact reruns reuse evidence, and cross-dossier approval "
                    "fails closed."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k 'signed_owner or another_dossier' -q",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_api_zero_execution_authority",
                checkbox_text=(
                    "* [x] Promotion status, dossier preview, acceptance, and "
                    "history APIs reject undeclared credential fields and expose "
                    "no capital/runtime authority issue, budget reservation, "
                    "OMS/ledger mutation, gateway contact, submit, cancel, "
                    "resume, or automatic-promotion action."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_routes.py -k promotion -q",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_deterministic_integration_tests",
                checkbox_text=(
                    "* [x] Deterministic Account Truth, promotion-service, "
                    "signature, and route tests cover full evidence, missing "
                    "coverage, blocked Account Truth, source drift, exact reuse, "
                    "rejection audit, credential rejection, and zero execution "
                    "side effects."
                ),
                evidence_paths=(
                    "tests/server/test_account_truth_gate.py",
                    "tests/test_broker_connector_soak_promotion.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "tests/test_operator_approval.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_account_truth_gate.py tests/test_broker_connector_soak_promotion.py tests/server/test_broker_connector_soak_routes.py tests/test_operator_approval.py -q",
                ),
            ),
        )
    )
