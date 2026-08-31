"""Acceptance manifests for approvals."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_controlled_session_signed_replacement_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 3.11 signed paused-session replacement."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="replacement_paused_scope_cannot_bypass_review",
                checkbox_text=(
                    "* [x] Ordinary issuance fails closed while an unexpired "
                    "enabled session in the same authorization/account/strategy "
                    "scope is durably paused; recovery must use the distinct "
                    "signed replacement contract or explicitly revoke and start "
                    "a genuinely new authorization chain."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_authority.py",
                    "server/db.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'signed_replacement' -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_distinct_signed_domain_and_fresh_chain",
                checkbox_text=(
                    "* [x] Replacement requires a new current attestation, a "
                    "new atomic reservation, and a short-lived Ed25519 "
                    "`replace_paused_controlled_session` approval plus matching "
                    "signature possession over the exact replacement artifact; "
                    "issue, revoke, or envelope approvals cannot be reused."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'wrong_operator_action or signed_replacement' tests/test_operator_approval.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_continuous_recovery_evidence",
                checkbox_text=(
                    "* [x] Recovery binds two post-pause clear gate snapshots "
                    "spanning at least 60 seconds, requires the newest snapshot "
                    "to be no older than 30 seconds, resets the stability window "
                    "after any blocked observation, and rechecks the latest fact "
                    "inside the replacement transaction."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'stable_fresh or newer_blocked' -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_equal_or_narrower_boundary",
                checkbox_text=(
                    "* [x] The replacement must preserve authorization, account, "
                    "strategy, and operator identity; use a subset of prior "
                    "orders and symbols; and never increase reserved gross, "
                    "cash, turnover, order count, per-symbol amount, request "
                    "rate, or session duration."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'wider_rate or widening_dimension or signed_replacement' -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_atomic_retire_and_issue",
                checkbox_text=(
                    "* [x] One SQLite `BEGIN IMMEDIATE` transaction records "
                    "replacement and revocation evidence, changes the paused "
                    "predecessor from enabled to revoked, and inserts the new "
                    "bounded session, so old and replacement authority are "
                    "never simultaneously usable."
                ),
                evidence_paths=(
                    "server/db.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'atomically_retires or concurrent_conflicting' -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_one_time_token_and_concurrency",
                checkbox_text=(
                    "* [x] The replacement returns a newly generated token only "
                    "on the first successful response, stores only its salted "
                    "hash, reuses exact retries without reissuing the token, and "
                    "allows only one of two conflicting concurrent handoffs."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'atomically_retires or concurrent_conflicting' -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_strict_non_resume_routes",
                checkbox_text=(
                    "* [x] Strict preview/record/history routes expose signed "
                    "replacement only; undeclared credentials are rejected and "
                    "there is still no in-place resume, renew, widen, runtime "
                    "admit, broker submit, or broker cancel endpoint."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_runtime_authority.py",
                    "tests/server/test_controlled_session_runtime_authority_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_runtime_authority_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="replacement_deterministic_zero_execution_tests",
                checkbox_text=(
                    "* [x] Deterministic signature, recovery-window, widening, "
                    "idempotency, concurrency, stale-preview, route, and token-"
                    "secrecy tests verify zero broker contact, OMS or production-"
                    "ledger mutation, capital scale-up, automatic resume, or "
                    "strategy-direct execution."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/server/test_controlled_session_runtime_authority_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py tests/server/test_controlled_session_runtime_authority_routes.py tests/test_operator_approval.py -q",
                ),
            ),
        )
    )


def build_signed_operator_approval_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 2.2/3.2 signed operator approvals."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="public_key_only_operator_identity_config",
                checkbox_text=(
                    "* [x] Trusted operator identities are configured with an "
                    "operator id, key id, enabled flag, and Ed25519 public key "
                    "only; malformed keys, unsupported algorithms, duplicate "
                    "identities, and private/secret fields fail closed."
                ),
                evidence_paths=(
                    "server/config.py",
                    "config.example.json",
                    "tests/test_bootstrap.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_bootstrap.py -k trusted_operator -q",
                ),
            ),
            AcceptanceCriterion(
                key="domain_bound_operator_challenge",
                checkbox_text=(
                    "* [x] Each short-lived challenge binds a server nonce, "
                    "operator/key identity, action, artifact type, exact "
                    "artifact fingerprint, issued time, and expiry into one "
                    "canonical signing payload."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "tests/test_operator_approval.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operator_approval.py -k 'exact or mismatch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="operator_signature_verification_fail_closed",
                checkbox_text=(
                    "* [x] Ed25519 verification fails closed for invalid "
                    "signatures, expiry, action/type/fingerprint mismatch, "
                    "disabled or rotated keys, and cross-artifact reuse; "
                    "rejections are append-only and exact verification reruns "
                    "reuse one approval record."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/db.py",
                    "tests/test_operator_approval.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operator_approval.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_requires_verified_operator_approval",
                checkbox_text=(
                    "* [x] Per-order confirmation requires a current verified "
                    "approval for the exact dossier fingerprint and matching "
                    "operator label; only the recorded evidence clears the "
                    "identity blocker, without changing OMS or authorizing "
                    "broker submission."
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
                key="session_requires_verified_operator_approval",
                checkbox_text=(
                    "* [x] Controlled-session attestation requires a current "
                    "verified approval for the exact envelope fingerprint and "
                    "matching operator label; it clears only the recorded "
                    "identity blocker and never issues, enables, or resumes a "
                    "runtime session."
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
                key="operator_key_rotation_and_disable_fail_closed",
                checkbox_text=(
                    "* [x] Approval resolution rechecks the currently enabled "
                    "trusted public key and fingerprint, so disabling or "
                    "rotating a key invalidates earlier approval evidence "
                    "instead of preserving stale identity authority."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "tests/test_operator_approval.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operator_approval.py -k 'rotation or disabled' -q",
                ),
            ),
            AcceptanceCriterion(
                key="operator_approval_api_boundary",
                checkbox_text=(
                    "* [x] Status, challenge, verification, and list APIs "
                    "reject undeclared credential/private-key fields, expose "
                    "only sanitized public-key fingerprints and signing "
                    "payloads, and provide no authority, budget, OMS, ledger, "
                    "gateway, submit, cancel, resume, or scale-up action."
                ),
                evidence_paths=(
                    "server/routes/capital_authorization.py",
                    "server/services/operator_approval.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_authorization_routes.py -k operator_approval -q",
                ),
            ),
            AcceptanceCriterion(
                key="operator_approval_deterministic_crypto_tests",
                checkbox_text=(
                    "* [x] Deterministic service, configuration, integration, "
                    "and route tests use the maintained cryptography library "
                    "to cover valid signatures, invalid signatures, expiry, "
                    "replay, key rotation, exact-artifact binding, credential "
                    "rejection, and zero execution-authority side effects."
                ),
                evidence_paths=(
                    "pyproject.toml",
                    "uv.lock",
                    "tests/test_operator_approval.py",
                    "tests/test_bootstrap.py",
                    "tests/test_per_order_confirmation.py",
                    "tests/test_controlled_session_envelope.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operator_approval.py tests/test_bootstrap.py tests/test_per_order_confirmation.py tests/test_controlled_session_envelope.py tests/server/test_capital_authorization_routes.py tests/server/test_per_order_confirmation_routes.py tests/server/test_controlled_session_envelope_routes.py -q",
                ),
            ),
        )
    )
