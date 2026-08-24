"""Acceptance manifests for execution."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_execution_batch_reconciliation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the exact prior-batch reconciliation gate."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="exact_batch_order_set_contract",
                checkbox_text=(
                    "* [x] A batch manifest binds a non-empty unique set of at "
                    "most 100 non-paper OMS orders to one explicit persisted "
                    "execution-reconciliation run."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'clear_exact or duplicate' -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_reconciliation_item_and_terminal_state",
                checkbox_text=(
                    "* [x] Every batch order must have exactly one no-action "
                    "reconciliation item whose recorded OMS status still "
                    "matches a current filled, rejected, cancelled, or expired "
                    "terminal state."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'clear_exact or nonterminal' -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_real_fill_linkage_and_quantity",
                checkbox_text=(
                    "* [x] A filled batch order requires exact real-fill "
                    "quantity plus provider, broker-order, Account Truth import, "
                    "and same-run reconciliation linkage; incomplete or excess "
                    "fill evidence blocks the batch."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k filled_batch -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_plan_paper_actual_comparison",
                checkbox_text=(
                    "* [x] Every AI-shadow batch replays an exact self-hashed "
                    "plan/paper/actual comparison from the current decision, "
                    "paper run, and imported real-fill sources; missing, changed, "
                    "incomplete, or conflicting evidence blocks the next batch "
                    "and remains human-review-only."
                ),
                evidence_paths=(
                    "server/services/execution_reconciliation.py",
                    "server/services/execution_batch_reconciliation.py",
                    "server/routes/execution_reconciliation.py",
                    "web/src/features/decision/components/plan-paper-actual-comparison.tsx",
                    "tests/test_execution_batch_reconciliation.py",
                    "tests/server/test_execution_reconciliation_routes.py",
                    "web/src/features/decision/components/plan-paper-actual-comparison.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py tests/server/test_execution_reconciliation_routes.py -k 'plan_paper_actual or current_source' -q",
                    "npm --prefix web test -- plan-paper-actual-comparison decision-cockpit-page",
                ),
            ),
            AcceptanceCriterion(
                key="batch_source_sensitive_fingerprint",
                checkbox_text=(
                    "* [x] OMS order, transition, real-fill, reconciliation "
                    "item, and run facts participate in one deterministic "
                    "fingerprint, and any later source change invalidates the "
                    "recorded prior-batch gate."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k source_changes -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_append_only_record_and_rejection_audit",
                checkbox_text=(
                    "* [x] Exact clear or blocked batch evidence is append-only "
                    "and sequentially reusable, while stale fingerprints and "
                    "invalid acknowledgement attempts create deterministic "
                    "rejection evidence."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'append_only or stale_fingerprint' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_exact_prior_batch_binding",
                checkbox_text=(
                    "* [x] Per-order dossier review requires the request and "
                    "recorded capital evaluation to reference the same resolved "
                    "clear prior-batch fingerprint instead of trusting the "
                    "latest reconciliation run."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/routes/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_exact_prior_batch_binding",
                checkbox_text=(
                    "* [x] Session-envelope review requires the request and "
                    "recorded capital evaluation to reference the same resolved "
                    "clear prior-batch fingerprint; missing, blocked, or changed "
                    "batch facts fail closed."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/routes/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_api_zero_execution_authority",
                checkbox_text=(
                    "* [x] Batch status, preview, record, resolve, and list APIs "
                    "reject undeclared credential fields and cannot issue or "
                    "expand authority, reserve budget, mutate OMS/ledger, "
                    "contact a broker, or submit/cancel an order."
                ),
                evidence_paths=(
                    "server/routes/execution_reconciliation.py",
                    "server/services/execution_batch_reconciliation.py",
                    "tests/server/test_execution_reconciliation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_execution_reconciliation_routes.py -k execution_batch -q",
                ),
            ),
        )
    )


def build_execution_gateway_verification_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for non-submitting runtime gateway verification."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="runtime_gateway_capability_health_contract",
                checkbox_text=(
                    "* [x] Runtime verification resolves a distinct registered "
                    "execution gateway, verified evidence-connector/account "
                    "binding, complete submit/cancel/query/dry-run/idempotency "
                    "capabilities, and a healthy source-fingerprinted snapshot."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k preview_is_ready -q",
                ),
            ),
            AcceptanceCriterion(
                key="execution_gateway_health_freshness",
                checkbox_text=(
                    "* [x] Gateway health must be healthy, timezone-aware, no "
                    "more than 60 seconds old, not materially future-dated, and "
                    "bound to a valid source fingerprint; missing/stale/provider "
                    "failure evidence fails closed without leaking details."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'source_drift or capability_account' -q",
                ),
            ),
            AcceptanceCriterion(
                key="non_submitting_idempotent_gateway_dry_run",
                checkbox_text=(
                    "* [x] The verifier derives a deterministic client order "
                    "id and requires dry-run acceptance for the exact order "
                    "fingerprint with a valid payload fingerprint, no broker "
                    "order id, submitted=false, and zero reported side effects."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'preview_is_ready or side_effects' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_append_only_reuse",
                checkbox_text=(
                    "* [x] Exact accepted or rejected verification attempts "
                    "are append-only and deterministic; sequential accepted "
                    "reruns reuse one event without submitting or cancelling."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "server/db.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'record_reuses or rejected' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_resolve_rechecks_source",
                checkbox_text=(
                    "* [x] Resolution re-runs current capability, binding, "
                    "health, and dry-run checks, rejects source drift, and "
                    "expires recorded verification after five minutes."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k source_drift -q",
                ),
            ),
            AcceptanceCriterion(
                key="no_production_gateway_default",
                checkbox_text=(
                    "* [x] Production registers no execution gateway by "
                    "default; status therefore reports no runtime gateway, "
                    "disabled execution authority, and broker submission false."
                ),
                evidence_paths=(
                    "server/routes/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k status_defaults -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_api_zero_authority",
                checkbox_text=(
                    "* [x] Status, preview, record, resolve, and list APIs "
                    "reject undeclared credential fields and expose no gateway "
                    "registration, authority issue, budget, OMS/ledger, submit, "
                    "cancel, resume, or scale-up operation."
                ),
                evidence_paths=(
                    "server/routes/execution_gateway_verification.py",
                    "server/app.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_execution_gateway_verification_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover ready, "
                    "missing registration, capability/account/health failure, "
                    "unsafe dry-run, source drift, expiry, reuse, rejection "
                    "audit, credential rejection, and zero broker side effects."
                ),
                evidence_paths=(
                    "tests/test_execution_gateway_verification.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py tests/server/test_execution_gateway_verification_routes.py -q",
                ),
            ),
        )
    )


def build_per_order_gateway_verification_binding_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for exact Stage 2.4 verification binding into Stage 2."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="capital_exact_gateway_verification_reference",
                checkbox_text=(
                    "* [x] The recorded manual-each-order capital evaluation "
                    "must contain the exact typed execution-gateway verification "
                    "fingerprint requested by the per-order dossier."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k capital_evaluation_must_reference -q",
                ),
            ),
            AcceptanceCriterion(
                key="current_gateway_verification_exact_scope_binding",
                checkbox_text=(
                    "* [x] Every dossier re-resolves the current verification "
                    "and exactly binds gateway id, read-only evidence connector, "
                    "account alias, OMS order id, canonical order fingerprint, "
                    "and the dry-run order contract."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/execution_gateway_verification.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'dossier_binds or scope_mismatch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_scope_mismatch_fails_closed",
                checkbox_text=(
                    "* [x] Missing providers and gateway, connector, account, "
                    "order, fingerprint, status, authority, or submission-state "
                    "mismatches fail closed with sanitized evidence."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'scope_mismatch or provider_failures' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_drift_invalidates_approval",
                checkbox_text=(
                    "* [x] Expiry or source drift changes the dossier fingerprint, "
                    "re-blocks review, restores the runtime-verification hard "
                    "blocker, and invalidates the prior artifact-bound approval."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "server/services/per_order_confirmation.py",
                    "tests/test_execution_gateway_verification.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py tests/test_per_order_confirmation.py -k 'source_drift or expiry' -q",
                ),
            ),
            AcceptanceCriterion(
                key="verification_clears_no_execution_authority",
                checkbox_text=(
                    "* [x] A clear non-submitting verification removes only the "
                    "runtime-verification blocker; runtime authority, live gateway, "
                    "broker submission, and strategy direct execution remain blocked."
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
                key="per_order_gateway_verification_api_contract",
                checkbox_text=(
                    "* [x] Preview and confirmation APIs accept only a valid "
                    "verification fingerprint, inject the closed-by-default runtime "
                    "registry resolver, reject credentials, and expose no submit path."
                ),
                evidence_paths=(
                    "server/routes/per_order_confirmation.py",
                    "server/routes/execution_gateway_verification.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_gateway_verification_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact binding, capital-reference "
                    "mismatch, scope mismatch, provider failure, source drift, "
                    "approval invalidation, route wiring, and zero execution authority."
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


def build_persisted_controlled_execution_operator_view_acceptance_audit() -> (
    AcceptanceAudit
):
    """Return evidence for Stage 3.19 persisted operator read boundaries."""

    focused = (
        "uv run pytest tests/test_controlled_execution_operator_view.py "
        "tests/test_broker_lifecycle_evidence_view.py "
        "tests/test_automation_cockpit.py tests/test_automation_alerts.py "
        "tests/server/test_automation_routes.py "
        "tests/server/test_broker_gateway_routes.py -q"
    )
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="persisted_controlled_execution_operator_projection",
                checkbox_text=(
                    "* [x] Automation Cockpit projects bounded-session capital, "
                    "headroom, expiry, last order/submission, reconciliation, "
                    "live-gate, pause, and blocker evidence from persisted facts "
                    "only, with no provider or runtime-connector call."
                ),
                evidence_paths=(
                    "server/services/controlled_execution_operator_view.py",
                    "server/services/automation_cockpit.py",
                    "tests/test_controlled_execution_operator_view.py",
                    "tests/test_automation_cockpit.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="operator_projection_fail_closed_and_no_recovery_action",
                checkbox_text=(
                    "* [x] Missing, stale, expired, revoked, paused, unreconciled, "
                    "invalid, or truncated evidence remains explicit and blocked; "
                    "the projection cannot issue, renew, resume, widen, submit, "
                    "cancel, or automatically scale capital."
                ),
                evidence_paths=(
                    "server/services/controlled_execution_operator_view.py",
                    "tests/test_controlled_execution_operator_view.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="persisted_broker_lifecycle_health_boundary",
                checkbox_text=(
                    "* [x] Broker health and lifecycle queries derive only from "
                    "persisted generic collector runs. Reads never open a source "
                    "file, call an edge adapter, contact a provider, or refresh "
                    "account facts."
                ),
                evidence_paths=(
                    "server/services/broker_lifecycle_evidence_view.py",
                    "server/services/broker_gateway.py",
                    "tests/test_broker_lifecycle_evidence_view.py",
                    "tests/test_broker_gateway_service.py",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="broker_adapter_and_legacy_snapshot_migration_boundary",
                checkbox_text=(
                    "* [x] Provider is provenance only; third-party adapters remain "
                    "replaceable and default-unregistered pending separate review "
                    "and user authorization. The legacy runtime snapshot entry is "
                    "migration-only and no longer returns live account facts."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(focused,),
            ),
            AcceptanceCriterion(
                key="operator_and_alert_read_only_surfaces",
                checkbox_text=(
                    "* [x] Decision Cockpit and automation alerts expose sanitized "
                    "persisted evidence and safety flags; an explicit scan records "
                    "idempotent current per-order source/candidate blockers without "
                    "submit, cancel, ledger, OMS, risk, or authority mutation."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/services/current_per_order_review_projection.py",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "tests/test_automation_alerts.py",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    focused,
                    "npm --prefix web test -- --run src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="operator_read_boundary_deterministic_validation",
                checkbox_text=(
                    "* [x] Deterministic fake/fixture tests cover empty defaults, "
                    "restart-safe persisted evidence, missing/blocked collector "
                    "state, current-review source drift, idempotent blocker alerts, "
                    "adapter-call rejection, and zero broker or financial-state "
                    "side effects."
                ),
                evidence_paths=(
                    "tests/test_controlled_execution_operator_view.py",
                    "tests/test_broker_lifecycle_evidence_view.py",
                    "tests/test_automation_alerts.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(focused,),
            ),
        )
    )
