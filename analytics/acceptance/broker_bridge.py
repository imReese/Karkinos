"""Acceptance manifests for broker bridge."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def _controlled_broker_bridge_foundation_criteria_part_1() -> (
    tuple[AcceptanceCriterion, ...]
):
    return (
        AcceptanceCriterion(
            key="broker_submission_disabled_default",
            checkbox_text=(
                "* [x] Broker submission remains disabled by default and "
                "the live gateway advertises no submit, cancel, preview, "
                "dry-run, or export authority."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "docs/ARCHITECTURE.md",
                "docs/ROADMAP.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
            ),
        ),
        AcceptanceCriterion(
            key="controlled_bridge_policy_whitelist",
            checkbox_text=(
                "* [x] Controlled broker bridge status exposes a "
                "non-submitting policy skeleton with explicit connector, "
                "account, strategy, and symbol whitelists plus required "
                "gate names before any future live bridge can be enabled; "
                "Decision Cockpit renders it as read-only evidence."
            ),
            evidence_paths=(
                "config.example.json",
                "server/config.py",
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_bootstrap.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "docs/config-reference.zh.md",
                "docs/ARCHITECTURE.md",
                "docs/ROADMAP.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_bootstrap.py -k controlled_bridge_policy",
                "uv run pytest tests/test_broker_gateway_service.py -k controlled_bridge_policy",
                "uv run pytest tests/server/test_broker_gateway_routes.py -k controlled_bridge_policy",
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "controlled bridge policy"',
            ),
        ),
        AcceptanceCriterion(
            key="manual_ticket_preview_export_dry_run",
            checkbox_text=(
                "* [x] Manual-ticket preview, export, dry-run, and create "
                "paths are non-submitting, require human broker entry, and "
                "keep preview/export read-only while requiring the latest "
                "signed current per-order confirmation, re-resolving its "
                "capital, Account Truth, Decision, risk, paper/shadow, "
                "adapter/soak, gateway, and reconciliation facts, and "
                "binding the confirmation, dossier, four source "
                "fingerprints, and controlled-bridge policy for audit."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/services/current_per_order_dossier.py",
                "server/services/current_per_order_dossier_factory.py",
                "server/services/per_order_confirmation.py",
                "server/services/per_order_gateway_evidence.py",
                "server/routes/broker_gateway.py",
                "tests/test_current_per_order_dossier.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/trading/api.ts",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                "uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_gateway_creates_ticket_without_broker_submission tests/server/test_broker_gateway_routes.py::test_manual_ticket_route_returns_copyable_ticket -q",
                "uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_preview_is_dry_run_and_does_not_mutate_oms tests/test_broker_gateway_service.py::test_manual_ticket_export_is_read_only_and_copy_safe tests/test_broker_gateway_service.py::test_manual_ticket_dry_run_records_accepted_event_without_oms_mutation -q",
                "uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_preview_requires_current_per_order_confirmation_provider tests/test_broker_gateway_service.py::test_manual_ticket_preview_rechecks_blocked_current_risk_source tests/test_broker_gateway_service.py::test_manual_ticket_dry_run_records_current_account_truth_rejection tests/server/test_broker_gateway_routes.py::test_manual_ticket_preview_route_rechecks_current_account_truth -q",
                "uv run python -m pytest tests/test_current_per_order_dossier.py::test_current_confirmation_resolution_requires_latest_signed_four_gate_dossier tests/test_current_per_order_dossier.py::test_current_confirmation_resolution_fails_closed_after_paper_source_drift tests/test_broker_gateway_service.py::test_manual_execution_preview_fingerprint_tracks_current_gate_drift -q",
                "uv run python -m pytest tests/server/test_broker_gateway_routes.py::test_manual_ticket_preview_route_is_read_only -q",
                'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
                "npm --prefix web test -- trading-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="manual_execution_operator_form_context",
            checkbox_text=(
                "* [x] Manual-ticket export surfaces an operator form with "
                "user-readable field labels, account alias, fee/tax "
                "assumptions, net cash impact, remaining-position/cost-basis "
                "preview, trading-session constraints, and explicit "
                "non-submission safety flags."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/trading/api.ts",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py -k manual_ticket_export_is_read_only_and_copy_safe",
                "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_ticket_export_route_is_read_only",
                'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
            ),
        ),
        AcceptanceCriterion(
            key="manual_execution_preview_draft",
            checkbox_text=(
                "* [x] Manual execution preview calculates an "
                "operator-entered fill, fee/tax/transfer-fee cost, net "
                "cash impact, position/cost context, and production-ledger "
                "draft plus a deterministic preview fingerprint after "
                "manual-ticket creation without writing ledger entries, "
                "changing OMS status, contacting a broker, or submitting "
                "orders."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/trading/api.ts",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
                "docs/README.en.md",
                "docs/README.zh.md",
                "docs/ROADMAP.md",
                "docs/ROADMAP.zh.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py -k manual_execution_preview",
                "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_execution_preview",
                'npm --prefix web test -- trading-page.test.tsx -t "previews manual execution draft"',
            ),
        ),
        AcceptanceCriterion(
            key="manual_execution_evidence_record",
            checkbox_text=(
                "* [x] Manual execution evidence can be recorded only "
                "after manual-ticket creation with a matching deterministic "
                "preview fingerprint, and it writes a broker-gateway audit "
                "event without creating fills, changing OMS status, "
                "writing production ledger entries, contacting a broker, "
                "or submitting orders."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "docs/README.en.md",
                "docs/README.zh.md",
                "docs/ROADMAP.md",
                "docs/ROADMAP.zh.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py -k manual_execution_evidence",
                "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_execution_record",
            ),
        ),
        AcceptanceCriterion(
            key="gateway_capability_health_contract",
            checkbox_text=(
                "* [x] Gateway and connector health contracts expose "
                "read, query, preview, dry-run, export, cancel, and submit "
                "capabilities in API and Decision Cockpit without exposing "
                "credentials."
            ),
            evidence_paths=(
                "server/config.py",
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="gateway_evidence_and_kill_switch_gates",
            checkbox_text=(
                "* [x] Live-like manual-ticket actions require account "
                "truth, research evidence, risk, paper/shadow, manual "
                "confirmation, and a clear global kill switch."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/services/trading_controls.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="staged_account_facts_and_order_query",
            checkbox_text=(
                "* [x] Gateway account-facts, fill-query, order-query, and "
                "broker lifecycle paths read persisted OMS, gateway audit, "
                "staged broker evidence, or generic collector-run evidence "
                "only. Automation/Decision Cockpit projects sanitized "
                "bounded-session and lifecycle evidence without provider "
                "contact, credential storage, account-id leakage, gateway-"
                "event creation, OMS/ledger mutation, or order submission."
            ),
            evidence_paths=(
                "account_truth/broker_evidence.py",
                "server/services/automation_cockpit.py",
                "server/services/broker_gateway.py",
                "server/services/broker_lifecycle_evidence_view.py",
                "server/services/controlled_execution_operator_view.py",
                "server/routes/automation.py",
                "server/routes/broker_gateway.py",
                "tests/test_automation_cockpit.py",
                "tests/server/test_automation_routes.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_automation_cockpit.py tests/server/test_automation_routes.py tests/test_controlled_execution_operator_view.py -q",
                "uv run pytest tests/test_broker_lifecycle_evidence_view.py tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py -q",
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
    )


def _controlled_broker_bridge_foundation_criteria_part_2() -> (
    tuple[AcceptanceCriterion, ...]
):
    return (
        AcceptanceCriterion(
            key="decision_cockpit_strategy_promotion_state",
            checkbox_text=(
                "* [x] Decision Cockpit shows strategy promotion state, "
                "paper/shadow gate status, missing requirements, audit-only "
                "pause/retire lifecycle evidence, controlled-bridge-pilot "
                "rejection, and the live-like disabled boundary as read-only "
                "evidence."
            ),
            evidence_paths=(
                "server/services/strategy_promotion_pipeline.py",
                "server/routes/strategy_promotion.py",
                "server/services/automation_cockpit.py",
                "tests/test_strategy_promotion_pipeline.py",
                "tests/server/test_strategy_promotion_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "docs/README.zh.md",
                "docs/README.en.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_strategy_promotion_pipeline.py tests/server/test_strategy_promotion_routes.py -k 'lifecycle or controlled_bridge or claimed_readiness or live_like_promotion'",
                "npm --prefix web test -- decision-cockpit-page.test.tsx -t 'strategy promotion'",
            ),
        ),
        AcceptanceCriterion(
            key="default_rejected_cancel_audit",
            checkbox_text=(
                "* [x] Broker cancellation is rejected by default without "
                "broker contact, while recording an auditable gateway event "
                "and leaving OMS state unchanged."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/routes/broker_gateway.py",
                "tests/test_broker_gateway_service.py",
                "tests/server/test_broker_gateway_routes.py",
            ),
            validation_commands=(
                "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
            ),
        ),
        AcceptanceCriterion(
            key="execution_reconciliation_bridge_evidence",
            checkbox_text=(
                "* [x] Execution reconciliation compares OMS orders, "
                "gateway events, staged broker trade evidence, and "
                "broker fee/tax/net-amount evidence before suggesting any "
                "review action. Staged broker cost summaries explicitly "
                "require reconciliation before ledger updates, avoid "
                "automatic ledger-update recommendations, and mutate no "
                "ledger facts; Decision Cockpit surfaces the same cost "
                "evidence for operator review."
            ),
            evidence_paths=(
                "server/db.py",
                "server/services/operations_today.py",
                "server/services/execution_reconciliation.py",
                "server/routes/operations.py",
                "server/routes/execution_reconciliation.py",
                "tests/test_operations_today.py",
                "tests/test_execution_reconciliation_service.py",
                "tests/server/test_operations_routes.py",
                "tests/server/test_execution_reconciliation_routes.py",
                "web/src/app/router.tsx",
                "web/src/features/overview/pages/overview-page.test.tsx",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
            ),
            validation_commands=(
                "uv run pytest tests/test_operations_today.py -k manual_execution_reconciliation_review",
                "uv run pytest tests/server/test_operations_routes.py -k execution_reconciliation_open_items",
                "uv run pytest tests/test_execution_reconciliation_service.py tests/server/test_execution_reconciliation_routes.py",
                'npm --prefix web test -- overview-page.test.tsx -t "manual execution reconciliation review"',
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
            ),
        ),
        AcceptanceCriterion(
            key="manual_ticket_to_reconciliation_audit_chain",
            checkbox_text=(
                "* [x] A deterministic non-submitting audit chain links "
                "manual confirmation, manual-ticket creation, manual "
                "execution evidence, staged broker-statement evidence, "
                "and execution reconciliation. Reconciliation compares "
                "manual price/cost/net evidence with matching broker "
                "facts, queues mismatches for review, and preserves OMS "
                "and production-ledger state; Trading links operators to "
                "broker-statement import and reconciliation review, and "
                "Decision renders the compared values without execution "
                "controls."
            ),
            evidence_paths=(
                "server/services/broker_gateway.py",
                "server/services/execution_reconciliation.py",
                "account_truth/broker_evidence.py",
                "account_truth/broker_statement.py",
                "tests/test_execution_reconciliation_service.py",
                "web/src/features/trading/components/trading-page.tsx",
                "web/src/features/trading/components/trading-page.test.tsx",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "README.md",
                "docs/README.en.md",
                "docs/README.zh.md",
                "docs/ARCHITECTURE.md",
                "docs/ROADMAP.md",
                "docs/ROADMAP.zh.md",
                "docs/IMPLEMENTATION_LOG.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_execution_reconciliation_service.py -k 'audit_chain or cost_mismatch'",
                'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
                'npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual versus broker reconciliation differences"',
                'rg -n "manual execution|手工成交|manual-ticket|手工票据" README.md docs',
            ),
        ),
        AcceptanceCriterion(
            key="strategy_broker_boundary_static_guard",
            checkbox_text=(
                "* [x] Strategy and research code, promotion and learning "
                "orchestration, deterministic risk, Decision, AI runtime and "
                "route entry points, and capital authorization/scaling evidence "
                "surfaces have no direct broker adapter or authority-service "
                "access. Controlled-session authority, budget, gate, pause, and "
                "rate services cannot cross into broker write authority; all "
                "bridge actions remain behind policy, Account Truth, risk, OMS, "
                "gateway, and reconciliation services, with deterministic static "
                "guards covering every protected domain."
            ),
            evidence_paths=(
                "analytics/strategy_broker_boundary.py",
                "tests/test_strategy_broker_boundary.py",
                "analytics/research_evidence.py",
                "strategy/runtime.py",
                "risk",
                "server/ai_runtime",
                "server/routes/ai_research.py",
                "server/routes/decision.py",
                "server/routes/strategy_promotion.py",
                "server/services/strategy_promotion_pipeline.py",
                "server/routes/capital_scaling_review.py",
                "server/services/capital_authorization.py",
                "server/services/capital_scaling_review.py",
                "server/services/controlled_session_runtime_authority.py",
                "server/services/controlled_session_automatic_pause.py",
                "server/services/controlled_session_budget_reservation.py",
                "server/services/controlled_session_live_gates.py",
                "server/services/controlled_session_runtime_rate_limiter.py",
                "server/services/controlled_session_envelope.py",
                "strategy/extensions/README.md",
                "docs/ARCHITECTURE.md",
                "docs/ROADMAP.md",
            ),
            validation_commands=(
                "uv run pytest tests/test_strategy_broker_boundary.py",
            ),
        ),
        AcceptanceCriterion(
            key="decision_cockpit_read_only_bridge_panel",
            checkbox_text=(
                "* [x] Decision Cockpit surfaces gateway, connector, "
                "gateway query capabilities, connector read capabilities, "
                "runtime connector snapshot summaries, staged "
                "account-facts, staged fill polling, local order query, "
                "reconciliation status, and broker cost evidence "
                "as read-only evidence, including strategy promotion "
                "state and a staged-fill reconciliation review hint, "
                "without submit, cancel, live-promotion, fill-apply, or "
                "ledger-sync controls."
            ),
            evidence_paths=(
                "server/services/automation_cockpit.py",
                "tests/test_automation_cockpit.py",
                "tests/server/test_automation_routes.py",
                "web/src/features/operations/api.ts",
                "web/src/features/decision/components/decision-cockpit-page.tsx",
                "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                "tests/server/test_broker_gateway_routes.py",
                "tests/server/test_execution_reconciliation_routes.py",
            ),
            validation_commands=(
                "npm --prefix web test -- decision-cockpit-page.test.tsx",
                "uv run pytest tests/server/test_broker_gateway_routes.py tests/server/test_execution_reconciliation_routes.py",
            ),
        ),
    )


def build_controlled_broker_bridge_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for completed non-submitting broker bridge foundations."""
    return AcceptanceAudit(
        criteria=(
            *_controlled_broker_bridge_foundation_criteria_part_1(),
            *_controlled_broker_bridge_foundation_criteria_part_2(),
        )
    )


def build_capital_authorization_stage0_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the completed non-submitting v1.8 Stage 0 slices."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="versioned_fail_closed_authorization_contract",
                checkbox_text=(
                    "* [x] A versioned capital-authorization contract evaluates "
                    "disabled, per-order, and session-bounded modes fail closed "
                    "across scope, expiry, evidence gates, and multi-dimensional "
                    "hard limits."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "docs/ARCHITECTURE.md",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_limits_and_safety_evidence",
                checkbox_text=(
                    "* [x] Evaluation returns deterministic fingerprints, "
                    "structured block reasons, effective limits, remaining "
                    "budgets, and explicit no-submit/no-cancel/no-OMS/no-ledger/"
                    "no-self-expansion safety flags."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="dual_connector_gateway_identity_contract",
                checkbox_text=(
                    "* [x] Capital-authorization v2 separates the read-only "
                    "evidence connector from the execution gateway, requires "
                    "both explicit policy scopes, rejects identical/overlapping "
                    "roles, and requires a verified same-account binding."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "server/routes/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py tests/server/test_capital_authorization_routes.py -k 'dual or roles or v2' -q",
                ),
            ),
            AcceptanceCriterion(
                key="declared_execution_gateway_not_runtime_authority",
                checkbox_text=(
                    "* [x] Declared execution-gateway id, health, and submit "
                    "capability are fingerprinted evidence only; the shared "
                    "binding remains runtime-unverified and cannot contact a "
                    "broker, submit, or authorize execution."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_binding.py",
                    "server/services/per_order_confirmation.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_execution_gateway_binding.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_binding.py tests/test_per_order_confirmation.py tests/test_controlled_session_envelope.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="append_only_evaluation_audit",
                checkbox_text=(
                    "* [x] Preview remains side-effect free, while recorded "
                    "evaluations use append-only local audit events and reuse "
                    "an existing sequential input fingerprint without granting "
                    "runtime authority."
                ),
                evidence_paths=(
                    "server/services/capital_authorization_audit.py",
                    "server/db.py",
                    "tests/test_capital_authorization_audit.py",
                    "tests/server/test_capital_authorization_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="evidence_only_capital_authority_api",
                checkbox_text=(
                    "* [x] Capital-authority status, preview, record-evaluation, "
                    "and list-evaluation APIs expose evidence only; even an "
                    "allowed evaluation leaves execution authority and broker "
                    "submission disabled."
                ),
                evidence_paths=(
                    "server/routes/capital_authorization.py",
                    "server/services/capital_authorization_audit.py",
                    "server/app.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_authorization_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="credentials_and_static_config_cannot_authorize",
                checkbox_text=(
                    "* [x] API payloads reject undeclared credential fields, "
                    "and static config cannot grant capital execution authority."
                ),
                evidence_paths=(
                    "server/routes/capital_authorization.py",
                    "server/services/capital_authorization_audit.py",
                    "server/config.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_authorization_routes.py -k credential -q",
                ),
            ),
            AcceptanceCriterion(
                key="capital_authorization_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover missing, disabled, expired, "
                    "mismatched, over-budget, upstream-gate, persistence, route, "
                    "sequential-rerun, and no-authority behavior."
                ),
                evidence_paths=(
                    "tests/test_capital_authorization.py",
                    "tests/test_capital_authorization_audit.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q",
                    "uv run pytest -q",
                ),
            ),
        )
    )
