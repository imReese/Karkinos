"""Acceptance manifests for session foundations."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_controlled_session_envelope_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the proposal-only Stage 3 session foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="session_proposal_scope_and_time_window",
                checkbox_text=(
                    "* [x] A proposal requires one recorded `session_bounded` "
                    "capital evaluation, an explicit deduplicated OMS order set, "
                    "timezone-aware start/expiry timestamps, and a maximum "
                    "30-minute window contained by the capital policy."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/services/capital_authorization.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'window or requires_session_bounded' -q",
                ),
            ),
            AcceptanceCriterion(
                key="conservative_session_budget_projection",
                checkbox_text=(
                    "* [x] Canonical order fingerprints, required gateway "
                    "evidence, conservative gross exposure without buy/sell "
                    "netting, cash, capital, turnover, per-order, position-"
                    "change, liquidity, and projected order-rate budgets are "
                    "bound into a deterministic session envelope."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/services/per_order_confirmation.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'projects_conservative or budget_blocks' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_envelope_fail_closed_gates",
                checkbox_text=(
                    "* [x] Missing/duplicate orders, unsupported OMS states, "
                    "unpriced market orders, out-of-scope symbols, missing/"
                    "blocked evidence, stale connector soak, open reconciliation, "
                    "kill switch, invalid time, or projected budget excess fails "
                    "closed before attestation."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'fail_closed or rejects_stale or budget_blocks' -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_session_attestation_and_rejection_audit",
                checkbox_text=(
                    "* [x] An exact fresh envelope can be attested only after "
                    "review gates pass; sequential reruns reuse append-only "
                    "evidence, while stale fingerprints or blocked envelopes "
                    "create deterministic rejection evidence."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/db.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'exact_session or rejects_stale or freshness_boundary' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_runtime_hard_blockers",
                checkbox_text=(
                    "* [x] Exact per-order gateway verification and current "
                    "session-start Account Truth may clear only their respective "
                    "evidence blockers; Stage 1/2 promotion, read-only evidence-"
                    "connector integrity, per-symbol runtime limits, atomic budget "
                    "reservation, runtime rate limiting, automatic pause, session "
                    "issuance/resume, live gateway, and broker submission remain "
                    "hard blockers after exact prior-batch reconciliation and "
                    "signed operator approval pass."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k projects_conservative -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_no_runtime_side_effect_contract",
                checkbox_text=(
                    "* [x] Every proposal and attestation states that it does "
                    "not issue/enable a runtime session, reserve/consume budget, "
                    "mutate OMS/ledger, contact a broker, submit/cancel orders, "
                    "auto-resume/renew/expand, or scale capital authority."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'exact_session or status_exposes' -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_session_api_boundary",
                checkbox_text=(
                    "* [x] Status, preview, attestation, and list APIs reject "
                    "undeclared credential fields and expose no issue, enable, "
                    "runtime-pause, resume, revoke-runtime, submit, cancel, or "
                    "scale-up action."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_envelope.py",
                    "server/app.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_session_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover time/"
                    "scope/evidence/budget gates, freshness-stable fingerprints, "
                    "exact attestation reuse, rejection audit, credential "
                    "rejection, hard blockers, and zero execution side effects."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_envelope.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
        )
    )


def build_controlled_session_gateway_verification_binding_acceptance_audit() -> (
    AcceptanceAudit
):
    """Return evidence for the exact Stage 3.3 per-order verification set."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="session_exact_gateway_verification_reference_set",
                checkbox_text=(
                    "* [x] A session request maps every OMS order id to one "
                    "unique gateway-verification fingerprint, and the recorded "
                    "`session_bounded` capital evaluation contains exactly the "
                    "same typed verification-reference set."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'map_must_match or capital_evaluation_must_reference' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_current_gateway_verification_exact_binding",
                checkbox_text=(
                    "* [x] Every envelope re-resolves each current verification "
                    "and independently matches gateway, read-only connector, "
                    "account alias, OMS order id, canonical order fingerprint, "
                    "and sanitized dry-run order terms."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification_binding.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'projects_conservative or recorded_gateway_verifications' -q",
                ),
            ),
            AcceptanceCriterion(
                key="one_gateway_verification_failure_blocks_session",
                checkbox_text=(
                    "* [x] Missing, extra, reused, invalid, or mismatched "
                    "verification references and any single-order resolution "
                    "failure block the whole session envelope."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'map_must_match or mismatched_gateway' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_gateway_drift_invalidates_approval",
                checkbox_text=(
                    "* [x] Verification expiry or source drift changes the "
                    "envelope fingerprint, restores the runtime-verification "
                    "hard blocker, and invalidates the prior artifact-bound "
                    "operator approval."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py tests/test_controlled_session_envelope.py -k 'source_drift or expiry' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_verification_set_clears_no_authority",
                checkbox_text=(
                    "* [x] A fully clear verification set removes only the "
                    "runtime-verification blocker; session authority, atomic "
                    "budget reservation, automatic pause, live gateway, broker "
                    "submission, and strategy direct execution remain disabled."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k projects_conservative -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_gateway_verification_api_contract",
                checkbox_text=(
                    "* [x] Preview and attestation APIs validate the bounded "
                    "fingerprint map, inject the closed-by-default runtime "
                    "registry resolver, reject credentials, and expose no "
                    "session-issue or submit path."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_envelope.py",
                    "server/routes/execution_gateway_verification.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_gateway_verification_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact multi-order binding, "
                    "capital-reference-set mismatch, missing/reused references, "
                    "scope/order mismatch, provider failure, source drift, "
                    "approval invalidation, route wiring, and zero execution "
                    "authority."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_envelope.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
        )
    )


def build_session_start_account_truth_binding_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the exact Stage 3.4 Account Truth start gate."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="session_start_current_account_truth_contract",
                checkbox_text=(
                    "* [x] Session-start evidence rebuilds current Account "
                    "Truth and requires a clear reconciliation, passing gate, "
                    "fresh source no more than 120 seconds old, zero unresolved "
                    "mismatches, and explicit zero-authority boundaries."
                ),
                evidence_paths=(
                    "server/account_truth_gate.py",
                    "server/services/session_start_account_truth.py",
                    "tests/test_session_start_account_truth.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_session_start_account_truth.py -k 'preview_is_clear or gate_and_freshness' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_start_account_truth_append_only_resolution",
                checkbox_text=(
                    "* [x] Clear and rejected attempts are append-only and "
                    "deterministic; resolution rechecks the current source, "
                    "detects drift, and expires records after 120 seconds."
                ),
                evidence_paths=(
                    "server/services/session_start_account_truth.py",
                    "server/db.py",
                    "tests/test_session_start_account_truth.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_session_start_account_truth.py -k 'record_reuses or drift_and_expiry or rejected' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_exact_account_truth_capital_binding",
                checkbox_text=(
                    "* [x] The session request and recorded `session_bounded` "
                    "capital evaluation bind the same typed Account Truth "
                    "fingerprint, evidence connector, and account alias."
                ),
                evidence_paths=(
                    "server/services/session_start_account_truth.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'recorded_session_start_account_truth or scope_mismatch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_account_truth_drift_invalidates_approval",
                checkbox_text=(
                    "* [x] Missing providers, identity mismatch, expiry, or "
                    "source drift re-blocks the envelope, restores the Account "
                    "Truth hard blocker, and invalidates the prior artifact-bound "
                    "operator approval without leaking source details."
                ),
                evidence_paths=(
                    "server/services/session_start_account_truth.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 'account_truth_drift or provider_failure' -q",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_clear_removes_no_authority_gate",
                checkbox_text=(
                    "* [x] A clear binding removes only "
                    "`session_account_truth_snapshot_not_bound`; session "
                    "authority, atomic budget reservation, automatic pause, "
                    "live gateway, broker submission, and strategy direct "
                    "execution remain disabled."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k projects_conservative -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_start_account_truth_api_zero_authority",
                checkbox_text=(
                    "* [x] Status, preview, record, resolve, and history APIs "
                    "use the current Account Truth source, reject credentials, "
                    "and expose no authority, session-issue, budget, ledger, or "
                    "broker-submit action."
                ),
                evidence_paths=(
                    "server/routes/session_start_account_truth.py",
                    "server/app.py",
                    "tests/server/test_session_start_account_truth_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_session_start_account_truth_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_start_account_truth_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover clear/blocked facts, "
                    "freshness, append-only reuse, source drift, expiry, "
                    "capital-reference and identity mismatch, provider failure, "
                    "envelope approval invalidation, route wiring, and zero "
                    "execution authority."
                ),
                evidence_paths=(
                    "tests/test_session_start_account_truth.py",
                    "tests/server/test_session_start_account_truth_routes.py",
                    "tests/test_controlled_session_envelope.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_session_start_account_truth.py tests/server/test_session_start_account_truth_routes.py tests/test_controlled_session_envelope.py -q",
                ),
            ),
        )
    )


def build_controlled_session_budget_reservation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the Stage 3.5 atomic budget reservation gate."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="current_signed_attestation_revalidation",
                checkbox_text=(
                    "* [x] Reservation requires a recorded signed envelope and "
                    "re-resolves its exact capital evaluation, Account Truth, "
                    "gateway dry-runs, prior-batch reconciliation, kill switch, "
                    "time window, and currently trusted operator approval."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/services/controlled_session_budget_reservation.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k 're_resolves or reserve_budget' -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_fixed_precision_budget_contract",
                checkbox_text=(
                    "* [x] The immutable reservation fingerprint binds the "
                    "attestation, envelope, authorization/account scope, China "
                    "trading day, exact window, conservative gross/cash/turnover "
                    "amounts, order count, capacities, and fixed 0.0001 CNY units."
                ),
                evidence_paths=(
                    "server/services/controlled_session_budget_reservation.py",
                    "server/db.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k deterministic -q",
                ),
            ),
            AcceptanceCriterion(
                key="atomic_concurrent_budget_gate",
                checkbox_text=(
                    "* [x] SQLite `BEGIN IMMEDIATE` serializes overlapping "
                    "reservations and atomically rejects unavailable capital, "
                    "cash, daily turnover, or order-count budget before insert."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_budget_reservation.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k 'concurrent or checks_cash' -q",
                ),
            ),
            AcceptanceCriterion(
                key="idempotent_reservation_and_rejection_audit",
                checkbox_text=(
                    "* [x] Exact reruns reuse one immutable reservation, each "
                    "attestation can reserve only once, and malformed, stale, "
                    "blocked, or transaction-rejected attempts are append-only "
                    "audit evidence."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_budget_reservation.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k 'idempotently or rejected_reservation' -q",
                ),
            ),
            AcceptanceCriterion(
                key="reservation_source_drift_and_expiry_fail_closed",
                checkbox_text=(
                    "* [x] Source drift, signature/key expiry, blocked gates, or "
                    "window expiry invalidates reservation readiness/resolution; "
                    "expired daily turnover remains conservatively reserved for "
                    "that China trading day until release semantics exist."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/services/controlled_session_budget_reservation.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k revalidates -q",
                ),
            ),
            AcceptanceCriterion(
                key="budget_reservation_api_zero_authority",
                checkbox_text=(
                    "* [x] Status, preview, record, resolve, and history APIs "
                    "reject undeclared credentials and expose no session-issue, "
                    "OMS/ledger mutation, broker submit/cancel, renewal, resume, "
                    "or capital-scale action."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_budget_reservation.py",
                    "server/app.py",
                    "tests/server/test_controlled_session_budget_reservation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_budget_reservation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="budget_reservation_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact signed-envelope "
                    "binding, source revalidation, fixed precision, idempotency, "
                    "real concurrent contention, every budget dimension, "
                    "rejection audit, route wiring, and zero execution authority."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_envelope.py",
                    "tests/test_controlled_session_budget_reservation.py",
                    "tests/server/test_controlled_session_budget_reservation_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py tests/test_controlled_session_budget_reservation.py tests/server/test_controlled_session_budget_reservation_routes.py -q",
                ),
            ),
        )
    )


def build_controlled_session_symbol_budget_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the Stage 3.6 per-symbol runtime budget gate."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="explicit_exact_per_symbol_limit_map",
                checkbox_text=(
                    "* [x] Every envelope requires an explicit positive "
                    "per-symbol limit for exactly the projected symbol set; "
                    "missing, extra, malformed, or over-precision values fail "
                    "closed before attestation."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "server/routes/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k per_symbol_runtime_limits_fail_closed -q",
                ),
            ),
            AcceptanceCriterion(
                key="capital_capped_symbol_limits",
                checkbox_text=(
                    "* [x] Each signed symbol limit is no greater than both the "
                    "recorded capital evaluation's symbol ceiling and effective "
                    "capital, and each conservative projected gross amount fits "
                    "inside its own limit."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k per_symbol_runtime_limits_fail_closed -q",
                ),
            ),
            AcceptanceCriterion(
                key="symbol_limit_signed_artifact_binding",
                checkbox_text=(
                    "* [x] The canonical symbol-limit map is part of the "
                    "envelope and attestation identity, so any limit change "
                    "changes the envelope fingerprint and invalidates the prior "
                    "artifact-bound operator approval."
                ),
                evidence_paths=(
                    "server/services/controlled_session_envelope.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py -k per_symbol_runtime_limit_change -q",
                ),
            ),
            AcceptanceCriterion(
                key="symbol_budget_reservation_contract",
                checkbox_text=(
                    "* [x] The immutable reservation persists fixed-precision "
                    "projected and capacity maps per symbol, and exact reruns "
                    "retain those maps without granting session or broker "
                    "authority."
                ),
                evidence_paths=(
                    "server/services/controlled_session_budget_reservation.py",
                    "server/db.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k 'idempotently or disjoint_symbols' -q",
                ),
            ),
            AcceptanceCriterion(
                key="atomic_concurrent_symbol_budget",
                checkbox_text=(
                    "* [x] The same SQLite `BEGIN IMMEDIATE` transaction sums "
                    "overlapping reservations per symbol, allows disjoint "
                    "symbols inside shared capital, rejects same-symbol "
                    "contention above the strictest limit, and fails closed on "
                    "legacy rows without symbol evidence."
                ),
                evidence_paths=(
                    "server/db.py",
                    "tests/test_controlled_session_budget_reservation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_budget_reservation.py -k 'double_spend_symbol or disjoint_symbols or legacy_reservation' -q",
                ),
            ),
            AcceptanceCriterion(
                key="symbol_limit_api_zero_authority",
                checkbox_text=(
                    "* [x] Envelope APIs require the bounded symbol map, reject "
                    "undeclared credentials and invalid precision, and still "
                    "expose no session-issue, OMS/ledger mutation, broker "
                    "submit/cancel, resume, renewal, or scale-up action."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_envelope.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="symbol_budget_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact-set validation, "
                    "capital ceilings, projection excess, approval invalidation, "
                    "fixed precision, persisted maps, real concurrent same-symbol "
                    "contention, disjoint symbols, route validation, and zero "
                    "execution authority."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_envelope.py",
                    "tests/test_controlled_session_budget_reservation.py",
                    "tests/server/test_controlled_session_envelope_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_envelope.py tests/test_controlled_session_budget_reservation.py tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
        )
    )
