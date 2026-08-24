"""Acceptance manifests for reviews."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_signed_broker_adapter_release_review_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the signed provider-neutral adapter review journey."""

    backend = (
        "uv run pytest tests/test_signed_broker_adapter_release_review.py "
        "tests/server/test_signed_broker_adapter_release_review_routes.py "
        "tests/account_truth/test_broker_adapter_release.py "
        "tests/account_truth/test_broker_adapter_conformance.py -q"
    )
    web = (
        "npm --prefix web test -- --run "
        "src/features/operations/"
        "signed-broker-adapter-release-review-operator-panel.test.tsx "
        "src/features/trading/components/trading-page.test.tsx"
    )
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="strict_provider_neutral_release_manifest",
                checkbox_text=(
                    "* [x] The release manifest is an exact provider-neutral, "
                    "credential-free, read-only contract that rejects unknown "
                    "fields, writable capabilities, sensitive keys, and unsafe "
                    "process or data-ownership boundaries."
                ),
                evidence_paths=(
                    "account_truth/broker_adapter_release.py",
                    "tests/account_truth/test_broker_adapter_release.py",
                    "docs/broker-adapter-release-review.en.md",
                    "docs/broker-adapter-release-review.zh.md",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="latest_conformance_exact_acceptance_binding",
                checkbox_text=(
                    "* [x] Acceptance requires the newest passing deterministic "
                    "conformance report for the exact manifest and persists its "
                    "run and report fingerprints; newer or drifted evidence "
                    "fails closed."
                ),
                evidence_paths=(
                    "account_truth/broker_adapter_conformance.py",
                    "account_truth/broker_adapter_release.py",
                    "tests/account_truth/test_broker_adapter_conformance.py",
                    "tests/test_signed_broker_adapter_release_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="exact_signed_operator_review_dossier",
                checkbox_text=(
                    "* [x] One short-lived Ed25519 approval binds the canonical "
                    "manifest, exact current review, conformance evidence, "
                    "decision, reason, timestamp, and acknowledgement; the "
                    "approval id becomes part of the append-only review identity."
                ),
                evidence_paths=(
                    "server/services/signed_broker_adapter_release_review.py",
                    "server/services/operator_approval.py",
                    "tests/test_signed_broker_adapter_release_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="preview_record_drift_and_retry_integrity",
                checkbox_text=(
                    "* [x] Conformance or current-review drift between signed "
                    "preview and transactional record is rejected; exact retry "
                    "reuses one row while conflicting review ids or inputs fail "
                    "closed without a second effect."
                ),
                evidence_paths=(
                    "account_truth/broker_adapter_release.py",
                    "server/services/signed_broker_adapter_release_review.py",
                    "tests/test_signed_broker_adapter_release_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="append_only_reject_and_one_way_revoke",
                checkbox_text=(
                    "* [x] Accept, reject, and revoke are append-only; rejection "
                    "can preserve a structurally valid safety decision, revocation "
                    "requires the exact accepted release, and a revoked identity "
                    "cannot be resumed in place."
                ),
                evidence_paths=(
                    "account_truth/broker_adapter_release.py",
                    "server/services/signed_broker_adapter_release_review.py",
                    "tests/test_signed_broker_adapter_release_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="strict_api_and_operator_approval_contract",
                checkbox_text=(
                    "* [x] Status, list, preview, and record routes reject extra "
                    "fields and credentials, while the challenge API schema is "
                    "kept exactly aligned with the service action-to-artifact "
                    "whitelist."
                ),
                evidence_paths=(
                    "server/routes/signed_broker_adapter_release_review.py",
                    "server/routes/capital_authorization.py",
                    "tests/server/test_signed_broker_adapter_release_review_routes.py",
                    "tests/server/test_capital_authorization_routes.py",
                ),
                validation_commands=(
                    backend,
                    "uv run pytest tests/server/test_capital_authorization_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="default_collapsed_no_database_edit_web_review",
                checkbox_text=(
                    "* [x] Trading provides a default-collapsed, no-database-edit "
                    "accept/reject/revoke journey with zero release reads while "
                    "closed, local nested credential-key rejection before POST, "
                    "and exact signed request bodies."
                ),
                evidence_paths=(
                    "web/src/features/operations/signed-broker-adapter-release-review-operator-panel.tsx",
                    "web/src/features/operations/signed-broker-adapter-release-review-operator-panel.test.tsx",
                    "web/src/features/trading/components/trading-page.tsx",
                ),
                validation_commands=(web,),
            ),
            AcceptanceCriterion(
                key="eligibility_only_zero_provider_or_authority_side_effects",
                checkbox_text=(
                    "* [x] The review creates only collector-eligibility evidence: "
                    "it selects, contacts, and registers no provider, exposes no "
                    "submit/cancel action, grants no execution or capital authority, "
                    "and leaves OMS, ledger, risk, and Account Truth unchanged."
                ),
                evidence_paths=(
                    "server/services/signed_broker_adapter_release_review.py",
                    "tests/test_signed_broker_adapter_release_review.py",
                    "web/src/features/operations/signed-broker-adapter-release-review-operator-panel.test.tsx",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(backend, web),
            ),
        )
    )


def build_strategy_learning_review_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the persisted human-reviewed strategy learning queue."""

    backend = (
        "uv run pytest tests/test_strategy_learning_review.py "
        "tests/server/test_strategy_learning_routes.py "
        "tests/server/test_signal_journal_routes.py -q"
    )
    web = (
        "npm --prefix web test -- --run "
        "src/features/backtest/components/strategy-learning-review-panel.test.tsx "
        "src/features/backtest/components/backtest-page.test.tsx"
    )
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="latest_persisted_human_review_projection",
                checkbox_text=(
                    "* [x] The queue projects only the latest persisted human "
                    "outcome review per signal and explicitly excludes unreviewed "
                    "signals from silent learning classification."
                ),
                evidence_paths=(
                    "server/services/decision_outcome_review.py",
                    "server/services/strategy_learning_review.py",
                    "tests/test_strategy_learning_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="stored_review_and_event_replay_integrity",
                checkbox_text=(
                    "* [x] Replay verifies the append-only event chain and exact "
                    "stored request, target, identity, signal, reviewer, decision, "
                    "outcome, note, and timestamp bindings before learning."
                ),
                evidence_paths=(
                    "server/services/decision_outcome_review.py",
                    "tests/server/test_signal_journal_routes.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="current_canonical_target_revalidation",
                checkbox_text=(
                    "* [x] Every queue read rebuilds the current canonical target; "
                    "target drift or failed audit replay blocks the item and cannot "
                    "produce a strategy-research handoff."
                ),
                evidence_paths=(
                    "server/services/strategy_learning_review.py",
                    "tests/test_strategy_learning_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="deterministic_learning_actions_and_exact_evidence",
                checkbox_text=(
                    "* [x] Reviewed outcomes map deterministically to safe human "
                    "actions with exact review, signal, target, valuation, ledger, "
                    "and contribution references; private review notes are omitted."
                ),
                evidence_paths=(
                    "server/services/strategy_learning_review.py",
                    "tests/test_strategy_learning_review.py",
                    "web/src/features/backtest/components/strategy-learning-review-panel.tsx",
                ),
                validation_commands=(backend, web),
            ),
            AcceptanceCriterion(
                key="copy_only_human_started_research_boundary",
                checkbox_text=(
                    "* [x] Evidence-not-supported reviews create only a copyable "
                    "research question; a human must separately start evidence "
                    "capture and research, while AI and memory remain off."
                ),
                evidence_paths=(
                    "server/services/strategy_learning_review.py",
                    "web/src/features/backtest/components/strategy-learning-review-panel.tsx",
                    "web/src/features/backtest/components/strategy-learning-review-panel.test.tsx",
                ),
                validation_commands=(backend, web),
            ),
            AcceptanceCriterion(
                key="read_only_fail_closed_learning_api",
                checkbox_text=(
                    "* [x] The learning surface is GET-only and creates no schema, "
                    "refresh, provider contact, database write, financial "
                    "recalculation, strategy mutation, or execution authority."
                ),
                evidence_paths=(
                    "server/routes/strategy_learning.py",
                    "tests/server/test_strategy_learning_routes.py",
                    "tests/test_strategy_learning_review.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="strategy_lab_non_authorizing_action_queue",
                checkbox_text=(
                    "* [x] Strategy Lab exposes counts, blockers, exact evidence, "
                    "and safe next actions without a write control, model trigger, "
                    "strategy-change control, or execution/capital authority."
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/strategy-learning-review-panel.tsx",
                    "web/src/features/backtest/components/strategy-learning-review-panel.test.tsx",
                ),
                validation_commands=(web,),
            ),
        )
    )


def build_controlled_per_order_pilot_readiness_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the non-authorizing per-order pilot admission view."""

    backend = (
        "uv run pytest tests/test_controlled_per_order_pilot_readiness.py "
        "tests/server/test_operations_routes.py tests/test_operations_today.py -q"
    )
    web = (
        "npm --prefix web test -- --run "
        "src/features/operations/components/operations-page.test.tsx"
    )
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="canonical_six_gate_persisted_admission_projection",
                checkbox_text=(
                    "* [x] One deterministic projection composes exactly six "
                    "persisted-only gates for source safety, read-only release, "
                    "signed soak, manual-each-order write release, exact scope, "
                    "and absence of unresolved execution or session authority."
                ),
                evidence_paths=(
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "tests/test_controlled_per_order_pilot_readiness.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="exact_release_soak_write_scope_binding",
                checkbox_text=(
                    "* [x] Admission requires exactly one observing accepted and "
                    "conformance-clear read-only release, its matching signed soak, "
                    "one current manual-each-order write release, and one coherent "
                    "provider, gateway, account, connector, and release scope."
                ),
                evidence_paths=(
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "server/services/controlled_broker_write_release.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_controlled_per_order_pilot_readiness.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="unfinished_order_and_session_authority_interlock",
                checkbox_text=(
                    "* [x] Any unresolved controlled-order journey, truncated "
                    "attention scan, or active or blocked session authority fails "
                    "closed before an exact-order review may be opened."
                ),
                evidence_paths=(
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "server/services/controlled_execution_operator_view.py",
                    "tests/test_controlled_per_order_pilot_readiness.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="source_failure_and_contract_drift_fail_closed",
                checkbox_text=(
                    "* [x] Missing, malformed, authorizing, or exception-producing "
                    "source contracts become explicit blockers; Operations reuses "
                    "one adapter projection so a single response cannot mix two "
                    "read-side snapshots."
                ),
                evidence_paths=(
                    "server/routes/operations.py",
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "tests/server/test_operations_routes.py",
                    "tests/test_controlled_per_order_pilot_readiness.py",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="stable_fingerprint_and_exact_resolution_evidence",
                checkbox_text=(
                    "* [x] Unchanged persisted evidence reproduces one fingerprint, "
                    "while gate or scope drift changes it; every blocked gate keeps "
                    "its evidence and safe next action visible."
                ),
                evidence_paths=(
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "tests/test_controlled_per_order_pilot_readiness.py",
                    "web/src/features/operations/controlled-per-order-pilot-readiness-panel.tsx",
                ),
                validation_commands=(backend, web),
            ),
            AcceptanceCriterion(
                key="operations_api_non_authority_contract",
                checkbox_text=(
                    "* [x] The Operations GET response carries the complete "
                    "non-authority contract and degrades unsafe runtime flags or "
                    "source construction failures into a blocked projection rather "
                    "than a false pass or provider call."
                ),
                evidence_paths=(
                    "server/routes/operations.py",
                    "tests/server/test_operations_routes.py",
                    "web/src/features/operations/api.ts",
                ),
                validation_commands=(backend,),
            ),
            AcceptanceCriterion(
                key="scoped_read_only_gate_matrix_surfaces_contract_failure",
                checkbox_text=(
                    "* [x] Operations keeps safe optional readiness compact, opens "
                    "an unsafe read-side contract immediately, preserves every "
                    "blocker and resolution without a generic status placeholder, "
                    "validates all six "
                    "unique gates, and exposes no submit, cancel, provider-selection, "
                    "or capital control."
                ),
                evidence_paths=(
                    "web/src/features/operations/controlled-per-order-pilot-readiness-panel.tsx",
                    "web/src/features/operations/components/operations-page.tsx",
                    "web/src/features/operations/components/operations-page.test.tsx",
                ),
                validation_commands=(web,),
            ),
            AcceptanceCriterion(
                key="review_entry_only_not_release_or_execution_authority",
                checkbox_text=(
                    "* [x] A clear matrix permits only a handoff to the separate "
                    "exact-order evidence review; it does not complete v1.8, select "
                    "or contact a provider, submit or cancel, mutate financial "
                    "facts, grant capital authority, or enable automatic scale-up."
                ),
                evidence_paths=(
                    "server/services/controlled_per_order_pilot_readiness.py",
                    "web/src/features/operations/controlled-per-order-pilot-readiness-panel.tsx",
                    "docs/ROADMAP.md",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(backend, web),
            ),
        )
    )
