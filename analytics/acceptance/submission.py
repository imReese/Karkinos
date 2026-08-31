"""Acceptance manifests for submission."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_controlled_broker_submission_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 3.12 one-shot broker submission recovery."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="broker_submission_default_closed_dependencies",
                checkbox_text=(
                    "* [x] Production remains default-closed: the submission "
                    "service is unavailable without an explicitly injected "
                    "write gateway, current signed release-evidence resolver, "
                    "trusted operator key, and kill-switch provider; no "
                    "automatic or strategy-direct mode is enabled."
                ),
                evidence_paths=(
                    "server/routes/controlled_broker_submission.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                    "tests/server/test_controlled_broker_submission_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py tests/server/test_controlled_broker_submission_routes.py -k 'default_closed or default_closed_without' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_current_exact_order_gates",
                checkbox_text=(
                    "* [x] One exact non-paper `manually_confirmed` OMS order "
                    "must re-resolve its current per-order confirmation, "
                    "Account Truth, risk, paper/shadow, exact prior-batch "
                    "reconciliation, signed connector promotion, and runtime "
                    "gateway verification both in preview and again after the "
                    "final submit-signature proof but before intent prepare; "
                    "source or fingerprint drift fails closed."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k recorded_confirmation_resolves -q",
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'confirmation_drift_after_final_signature' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_distinct_final_signature",
                checkbox_text=(
                    "* [x] Broker contact requires a separate short-lived "
                    "Ed25519 `submit_confirmed_broker_order` approval and "
                    "signature-possession proof over the exact order, client "
                    "order id, gateway, release evidence, dry-run, and submit "
                    "fingerprint; the same approval and trusted key are "
                    "re-resolved after atomic prepare and must remain current "
                    "at the final pre-call gate. Earlier or revoked approvals "
                    "cannot be reused."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                    "tests/test_operator_approval.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'wrong_final_signature' tests/test_operator_approval.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_atomic_intent_and_oms_transition",
                checkbox_text=(
                    "* [x] One SQLite `BEGIN IMMEDIATE` transaction persists "
                    "the immutable submit intent and moves OMS from "
                    "`manually_confirmed` to `submission_pending` before any "
                    "external call; exact retries are read-only and concurrent "
                    "requests permit at most one gateway submission."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'signed_submit or concurrent' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_fresh_gateway_and_release_gates",
                checkbox_text=(
                    "* [x] Submit preview and the final pre-call check require "
                    "the exact gateway capabilities, fresh healthy status, "
                    "side-effect-free dry-run, current signed broker/regulatory "
                    "release assertions, and a clear kill switch; changed or "
                    "missing facts reject before broker contact."
                ),
                evidence_paths=(
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'default_closed or kill_switch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_explicit_result_without_ledger",
                checkbox_text=(
                    "* [x] Definitive accepted and rejected gateway responses "
                    "persist distinct intent/OMS outcomes with sanitized broker "
                    "evidence, while ambiguous responses become "
                    "`submission_unknown`; no path writes fills or the "
                    "production ledger."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'signed_submit or explicit_broker_rejection or unknown_submit' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_query_only_unknown_recovery",
                checkbox_text=(
                    "* [x] An unknown submission can never call submit again; "
                    "after a deterministic 30-second wait, recovery may only "
                    "query the same idempotent client order id. Its exact "
                    "short-lived approval and trusted key are re-resolved "
                    "after the atomic query claim and must remain current "
                    "before gateway contact; query failure or ambiguity "
                    "remains unknown."
                ),
                evidence_paths=(
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'unknown_submit or definitive_not_found' -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_submission_strict_routes_and_deterministic_tests",
                checkbox_text=(
                    "* [x] Strict status/preview/submit/query-recovery/history "
                    "routes reject undeclared credentials and expose no "
                    "strategy submission, automatic execution, session-wide "
                    "submission, capital widening, broker cancel, fill apply, "
                    "or ledger-sync action outside the separately signed exact "
                    "cancellation contract; deterministic tests cover terminal, "
                    "unknown, retry, concurrency, signature, and kill-switch "
                    "boundaries."
                ),
                evidence_paths=(
                    "server/routes/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                    "tests/server/test_controlled_broker_submission_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py tests/server/test_controlled_broker_submission_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_execution_edge_conformance_contract",
                checkbox_text=(
                    "* [x] A separate provider-neutral execution-edge fixture "
                    "contract proves default-closed dry-run, submit, query-only "
                    "unknown recovery, explicit cancel identity, concurrency, "
                    "restart, idempotency, disconnect, and partial-cancel "
                    "semantics without registering or contacting an adapter."
                ),
                evidence_paths=(
                    "account_truth/broker_execution_edge_conformance.py",
                    "account_truth/broker_execution_edge_conformance_fixtures.py",
                    "scripts/broker/run_broker_execution_edge_conformance.py",
                    "tests/account_truth/test_broker_execution_edge_conformance.py",
                    "tests/scripts/test_run_broker_execution_edge_conformance.py",
                    "docs/broker-execution-edge-conformance.en.md",
                ),
                validation_commands=(
                    "uv run pytest tests/account_truth/test_broker_execution_edge_conformance.py tests/scripts/test_run_broker_execution_edge_conformance.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_cancellation_exact_signed_atomic_command",
                checkbox_text=(
                    "* [x] Broker cancellation is a separate, default-closed "
                    "command bound to one submitted intent, exact broker/client "
                    "ids, current persisted lifecycle observation, remaining "
                    "quantity, current signed release, fresh gateway health, "
                    "and a short-lived `cancel_exact_controlled_broker_order` "
                    "signature that is re-resolved after atomic prepare and "
                    "must remain current at the final pre-call gate. `BEGIN "
                    "IMMEDIATE` permits at most one external cancel effect "
                    "across duplicates, concurrency, and restart."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/controlled_broker_cancellation.py",
                    "server/routes/controlled_broker_submission.py",
                    "tests/test_controlled_broker_cancellation.py",
                    "tests/server/test_controlled_broker_submission_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_cancellation.py -k 'signed_exact or duplicate_restart or lifecycle_drift or definitive_gateway' -q",
                    "uv run pytest tests/server/test_controlled_broker_submission_routes.py -k signed_cancellation -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_cancellation_query_only_non_authoritative_recovery",
                checkbox_text=(
                    "* [x] A prepared, requested, rejected, or unknown cancel "
                    "command is never re-cancelled. Recovery requires another "
                    "exact short-lived signature and may only query after a "
                    "deterministic wait. Its approval and trusted key are "
                    "re-resolved after the atomic query claim and must remain "
                    "current before gateway contact; gateway responses remain "
                    "sanitized, non-authoritative telemetry and cannot mutate "
                    "lifecycle, OMS, ledger, risk, kill switch, interlock, or "
                    "capital authority. Only newer explicit lifecycle "
                    "ingestion proves cancellation."
                ),
                evidence_paths=(
                    "server/services/controlled_broker_cancellation.py",
                    "tests/test_controlled_broker_cancellation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_cancellation.py -k 'timeout or restart_from_prepared or sensitive_gateway' -q",
                ),
            ),
        )
    )


def build_controlled_submission_interlock_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 3.13 submission interlock and visibility."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="unreconciled_submission_preview_interlock",
                checkbox_text=(
                    "* [x] Preview and status fail closed when any other "
                    "controlled intent is `prepared`, `submitted`, or "
                    "`submission_unknown`; the response identifies only "
                    "sanitized intent/order/status evidence and never treats "
                    "an accepted broker acknowledgement as reconciliation."
                ),
                evidence_paths=(
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'interlock' -q",
                ),
            ),
            AcceptanceCriterion(
                key="unreconciled_submission_atomic_write_interlock",
                checkbox_text=(
                    "* [x] The same interlock is rechecked inside SQLite "
                    "`BEGIN IMMEDIATE` before intent insertion, so two "
                    "different concurrently confirmed orders cannot both "
                    "receive permission for an external call."
                ),
                evidence_paths=(
                    "server/db.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'atomic_interlock' -q",
                ),
            ),
            AcceptanceCriterion(
                key="interlock_safe_terminal_release",
                checkbox_text=(
                    "* [x] Only a definitive rejected/not-found outcome removes "
                    "the current interlock in this stage; unknown and accepted-"
                    "but-unreconciled outcomes remain blocked, exact retries "
                    "remain read-only, and recovery remains query-only."
                ),
                evidence_paths=(
                    "server/services/controlled_broker_submission.py",
                    "server/db.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py -k 'definitive_rejection_clears or unknown_submit' -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_submission_reconciliation_states",
                checkbox_text=(
                    "* [x] Execution reconciliation consumes persisted submit "
                    "intent evidence and distinguishes pending/unknown, "
                    "accepted awaiting broker evidence, matching staged broker "
                    "evidence, quantity/evidence conflict, and definitive "
                    "rejection without inferring fills."
                ),
                evidence_paths=(
                    "server/services/execution_reconciliation.py",
                    "tests/test_execution_reconciliation_service.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_reconciliation_service.py -k 'controlled' -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_submission_no_ledger_or_oms_inference",
                checkbox_text=(
                    "* [x] Matching imported broker evidence remains an open "
                    "human reconciliation item; it does not infer an OMS fill, "
                    "apply a broker callback, write a fill, mutate the "
                    "production ledger, or clear the next-order interlock."
                ),
                evidence_paths=(
                    "server/services/execution_reconciliation.py",
                    "tests/test_execution_reconciliation_service.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_reconciliation_service.py -k 'submitted_controlled_broker_evidence' -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_submission_critical_alert",
                checkbox_text=(
                    "* [x] Automation alert scanning raises a critical, "
                    "sanitized alert for an unknown controlled submission, "
                    "states that new submissions are blocked, and exposes only "
                    "query recovery with resubmission disabled."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "tests/test_automation_alerts.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py -k 'unknown_controlled_submission' -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_submission_operations_visibility",
                checkbox_text=(
                    "* [x] Operations surfaces controlled-submission review and "
                    "unknown counts, the sanitized first open item, and the "
                    "query-recovery next action from each order's latest "
                    "reconciliation fact ahead of ordinary execution review, "
                    "without deleting history or adding a submit, retry, or "
                    "ledger action."
                ),
                evidence_paths=(
                    "server/services/operations_today.py",
                    "server/routes/operations.py",
                    "tests/test_operations_today.py",
                    "tests/server/test_operations_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operations_today.py -k 'unknown_controlled_submission' tests/server/test_operations_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_submission_interlock_boundary",
                checkbox_text=(
                    "* [x] Deterministic concurrency, terminal, unknown, "
                    "reconciliation, alert, and Operations tests preserve "
                    "manual final authority and prove no strategy-direct or "
                    "automatic submission, broker cancel, fill apply, ledger "
                    "sync, reconciliation self-clear, or capital widening."
                ),
                evidence_paths=(
                    "tests/test_controlled_broker_submission.py",
                    "tests/test_execution_reconciliation_service.py",
                    "tests/test_automation_alerts.py",
                    "tests/test_operations_today.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_broker_submission.py tests/test_execution_reconciliation_service.py tests/test_automation_alerts.py tests/test_operations_today.py -q",
                ),
            ),
        )
    )


def build_controlled_submission_reconciliation_clearance_acceptance_audit() -> (
    AcceptanceAudit
):
    """Return evidence for Stage 3.14 signed full-fill clearance."""

    focused = (
        "uv run pytest tests/test_controlled_submission_reconciliation_clearance.py "
        "tests/test_execution_reconciliation_service.py "
        "tests/test_controlled_broker_submission.py "
        "tests/server/test_controlled_broker_submission_routes.py -q"
    )
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="clearance_exact_latest_evidence",
                checkbox_text=(
                    "* [x] Clearance is available only for the current `submitted` "
                    "controlled intent and its latest exact "
                    "`controlled_submission_broker_evidence_available` "
                    "reconciliation item; superseded or changed evidence fails closed."
                ),
                evidence_paths=(
                    "server/services/controlled_submission_reconciliation_clearance.py",
                    "server/services/execution_reconciliation.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_exact_full_fill_aggregation",
                checkbox_text=(
                    "* [x] Matching broker trade events must come from one validated "
                    "import and aggregate to the exact OMS quantity; partial totals, "
                    "cross-import aggregation, side/symbol drift, and changed row "
                    "fingerprints remain blocked."
                ),
                evidence_paths=(
                    "server/services/execution_reconciliation.py",
                    "server/services/controlled_submission_reconciliation_clearance.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_account_truth_binding",
                checkbox_text=(
                    "* [x] Clearance re-resolves Account Truth no older than 120 "
                    "seconds and requires clear gates, zero unresolved reconciliation "
                    "items, covered ledger evidence, and the same broker import and "
                    "file fingerprint as the selected trade events."
                ),
                evidence_paths=(
                    "server/services/controlled_submission_reconciliation_clearance.py",
                    "server/account_truth_gate.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_distinct_operator_signature",
                checkbox_text=(
                    "* [x] Final clearance requires a separate short-lived Ed25519 "
                    "`clear_controlled_submission_reconciliation` approval and "
                    "signature-possession proof bound to the exact clearance "
                    "fingerprint; submission signatures cannot be reused."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/controlled_submission_reconciliation_clearance.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                    "tests/test_operator_approval.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_atomic_terminal_write",
                checkbox_text=(
                    "* [x] One SQLite `BEGIN IMMEDIATE` transaction records real "
                    "fills, moves OMS `submitted -> accepted -> filled`, persists the "
                    "signed clearance, and appends a terminal no-action reconciliation "
                    "fact without mutating the production ledger."
                ),
                evidence_paths=(
                    "server/db.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_atomic_interlock_release",
                checkbox_text=(
                    "* [x] The cross-order interlock releases only after that atomic "
                    "persisted clearance; exact concurrent retries are idempotent, "
                    "conflicting retries fail closed, and an open or manually tagged "
                    "reconciliation item cannot release it."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_broker_submission.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                    "tests/test_controlled_broker_submission.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_downstream_reconciliation_linkage",
                checkbox_text=(
                    "* [x] Recorded fills retain provider, broker-order, Account Truth "
                    "import, row-fingerprint, and clearance-run linkage so exact prior-"
                    "batch reconciliation can consume them while ledger application "
                    "remains a separate reviewed workflow."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_controlled_submission_reconciliation_clearance.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="clearance_strict_routes_and_boundary",
                checkbox_text=(
                    "* [x] Strict status/preview/record/history routes reject "
                    "undeclared credentials and expose no strategy-direct or automatic "
                    "submission, partial-fill clearance, broker cancel, automatic "
                    "ledger sync, session widening, or capital increase action."
                ),
                evidence_paths=(
                    "server/routes/controlled_broker_submission.py",
                    "tests/server/test_controlled_broker_submission_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(focused,),
            ),
        )
    )
