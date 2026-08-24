"""Acceptance manifests for session runtime."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_controlled_session_runtime_rate_limiter_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 3.7 and Stage 3.18 admission gates."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="runtime_rate_limiter_default_closed",
                checkbox_text=(
                    "* [x] Production exposes only read-only status/history "
                    "routes; there is no public preview, admit, submit, or "
                    "cancel endpoint. Stage 3.9 later supplied authenticated "
                    "sessions and Stage 3.18 requires their fresh live-gate "
                    "source."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_runtime_rate_limiter.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/server/test_controlled_session_runtime_rate_limiter_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_runtime_rate_limiter_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_authenticated_session_admission_binding",
                checkbox_text=(
                    "* [x] Internal admission requires a current enabled and "
                    "authority-verified bounded session, a verified budget "
                    "reservation, clear upstream/kill-switch gates, exact "
                    "session and reservation fingerprints, authorization/"
                    "account/strategy scope, an in-scope order, an active "
                    "window, and an explicit positive rate limit."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'preview or session_pause' -q",
                ),
            ),
            AcceptanceCriterion(
                key="atomic_shared_sliding_rate_window",
                checkbox_text=(
                    "* [x] SQLite `BEGIN IMMEDIATE` enforces a server-time "
                    "60-second sliding window shared by authorization/account, "
                    "uses the strictest overlapping session rate, and admits "
                    "only one contender for the final concurrent slot."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'sliding_window or concurrent_last_slot or strictest_account_rate' -q",
                ),
            ),
            AcceptanceCriterion(
                key="rate_admission_replay_and_idempotency",
                checkbox_text=(
                    "* [x] Exact request retries reuse one immutable admission, "
                    "while a second request for the same session/order or reuse "
                    "of one request id for another order fails closed and is "
                    "audited."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'idempotent or order_and_request_reuse' -q",
                ),
            ),
            AcceptanceCriterion(
                key="session_drift_expiry_provider_failure_blocking",
                checkbox_text=(
                    "* [x] Pause, authority drift, limiter disablement, expiry, "
                    "out-of-scope orders, unsafe rates, and provider failure "
                    "block before admission without leaking session tokens or "
                    "broker credentials."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'session_pause or provider_failure' -q",
                ),
            ),
            AcceptanceCriterion(
                key="rate_admission_evidence_zero_execution_side_effects",
                checkbox_text=(
                    "* [x] Accepted admissions and rejected attempts are "
                    "append-only evidence only: they do not issue, enable, "
                    "resume, renew, or widen a session; mutate OMS/ledger; "
                    "contact a broker; or authorize submission/cancellation."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_rate_limiter_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover default closure, sanitized "
                    "preview, exact binding, persistence, retry, boundary time, "
                    "real concurrency, shared strictest rate, replay conflicts, "
                    "session drift, route exposure, and zero broker authority."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                    "tests/server/test_controlled_session_runtime_rate_limiter_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py tests/server/test_controlled_session_runtime_rate_limiter_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_fresh_live_gate_identity",
                checkbox_text=(
                    "* [x] Internal admission v2 binds the exact latest "
                    "persisted live-gate snapshot id, fingerprint, observed "
                    "time, and session fingerprint into its deterministic "
                    "evidence identity; a snapshot may be no more than 30 "
                    "seconds old."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'preview_is_deterministic' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_live_gate_fail_closed_preview",
                checkbox_text=(
                    "* [x] Preview fails closed when the snapshot provider is "
                    "absent or fails, or when the snapshot is missing, stale, "
                    "future, blocked, or belongs to another session identity. "
                    "Provider values are reduced to a strict sanitized "
                    "allowlist."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'live_gate or missing_live_gate' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_live_gate_atomic_recheck",
                checkbox_text=(
                    "* [x] The admission `BEGIN IMMEDIATE` transaction re-reads "
                    "the latest snapshot before checking replay/rate limits. A "
                    "newer blocked or different snapshot wins over a clear "
                    "preview and leaves no admission row."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py -k 'newer_blocked_gate_snapshot' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_prior_gates_preserved",
                checkbox_text=(
                    "* [x] Existing session enabled/expiry/revocation/pause, "
                    "order scope, reservation, shared strictest rate, request "
                    "idempotency, and concurrency gates remain mandatory; the "
                    "change removes no prior blocker."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py tests/test_controlled_session_automatic_pause.py tests/test_controlled_session_runtime_rate_limiter.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_production_read_only_surface",
                checkbox_text=(
                    "* [x] Production wires the authenticated session and "
                    "persisted live-gate readers but still exposes status/"
                    "history only. There is no public runtime-admit, strategy-"
                    "direct, broker submit/cancel, or recovery action."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_runtime_rate_limiter.py",
                    "tests/server/test_controlled_session_runtime_rate_limiter_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_runtime_rate_limiter_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_admission_v2_deterministic_safety_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover missing providers, stale/"
                    "blocked/future/identity drift, preview-to-transaction "
                    "replacement, revocation race, rate/budget exhaustion, "
                    "exact retry, concurrency, sanitization, and zero OMS/fill/"
                    "ledger/broker side effects."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_live_gates.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_rate_limiter.py tests/test_controlled_session_runtime_authority.py tests/test_controlled_session_live_gates.py -q",
                ),
            ),
        )
    )


def build_controlled_session_automatic_pause_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the Stage 3.8 automatic-pause foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="automatic_pause_default_closed",
                checkbox_text=(
                    "* [x] Production wires only the persisted read-only "
                    "session resolver, configures no live gate provider, and "
                    "exposes only read-only status, state, and event routes; "
                    "there is no public evaluate, pause, resume, submit, or "
                    "cancel endpoint."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_automatic_pause.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/server/test_controlled_session_automatic_pause_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_automatic_pause_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="automatic_pause_exact_session_gate_binding",
                checkbox_text=(
                    "* [x] Internal evaluation requires an exact current, "
                    "enabled, authority-verified session identity and binds a "
                    "sanitized allowlisted gate snapshot, reservation id, and "
                    "deterministic fingerprints without retaining provider "
                    "credentials."
                ),
                evidence_paths=(
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py -k 'clear_gates or identity_drift' -q",
                ),
            ),
            AcceptanceCriterion(
                key="automatic_pause_hard_gate_coverage",
                checkbox_text=(
                    "* [x] Missing gate evidence, Account Truth, risk, prior "
                    "reconciliation, paper/shadow divergence, gateway health, "
                    "market data, budget, rate, kill switch, loss/drawdown, "
                    "rejection, account-change, and consecutive-error facts "
                    "all fail toward pause."
                ),
                evidence_paths=(
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py -k 'hard_gate or provider_failure' -q",
                ),
            ),
            AcceptanceCriterion(
                key="durable_one_way_pause_state",
                checkbox_text=(
                    "* [x] The first valid pause is persisted as immutable "
                    "evidence plus a durable one-way `paused` runtime state; "
                    "later clear gates do not automatically resume, renew, or "
                    "replace that state."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py -k 'idempotent_concurrent' -q",
                ),
            ),
            AcceptanceCriterion(
                key="pause_blocks_runtime_admission_atomically",
                checkbox_text=(
                    "* [x] Runtime rate admission checks durable pause state "
                    "inside its `BEGIN IMMEDIATE` transaction, so an applied "
                    "pause blocks new admissions even if a stale provider still "
                    "claims that the session is enabled."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py -k 'runtime_admission' -q",
                ),
            ),
            AcceptanceCriterion(
                key="automatic_pause_idempotent_sanitized_evidence",
                checkbox_text=(
                    "* [x] Exact and concurrent evaluations reuse one pause "
                    "event, identity conflicts fail closed, and rejected or "
                    "provider-failure evidence remains append-only and "
                    "sanitized."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py -k 'default_closed or idempotent_concurrent or identity_drift or provider_failure' -q",
                ),
            ),
            AcceptanceCriterion(
                key="automatic_pause_deterministic_zero_execution_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover default closure, clear "
                    "no-op evaluation, every hard gate, persistence, real "
                    "concurrency, no automatic resume, identity drift, route "
                    "exposure, atomic rate blocking, secret sanitization, and "
                    "zero broker authority."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_automatic_pause.py",
                    "tests/server/test_controlled_session_automatic_pause_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_automatic_pause.py tests/server/test_controlled_session_automatic_pause_routes.py -q",
                ),
            ),
        )
    )


def build_controlled_session_runtime_authority_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for Stage 3.9 signed runtime-session authority."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="runtime_authority_separate_signed_issuance",
                checkbox_text=(
                    "* [x] Issuance re-resolves one exact current reservation "
                    "and attestation, binds account/strategy/orders/window/rate, "
                    "and requires a new Ed25519 `issue_controlled_session` "
                    "approval plus possession of its signature for the "
                    "deterministic issuance fingerprint; public approval "
                    "history is sanitized and the earlier envelope approval "
                    "cannot be reused as authority."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_authority.py",
                    "server/services/operator_approval.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'preview or wrong_action' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_atomic_single_issue",
                checkbox_text=(
                    "* [x] SQLite `BEGIN IMMEDIATE` permits only one session per "
                    "reservation, validates the persisted reservation identity "
                    "again, reuses exact/concurrent retries, and rejects a "
                    "conflicting session or reservation identity."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'concurrent_exact_issue or token_once' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_hashed_token_authentication",
                checkbox_text=(
                    "* [x] A high-entropy runtime token is returned only on the "
                    "first successful issue response, only a salted hash is "
                    "stored, list/resolve/rejection evidence never exposes it, "
                    "and every internal rate-admission request requires exact "
                    "token authentication."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_authority.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'token_once' tests/test_controlled_session_runtime_rate_limiter.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_expiry_and_source_revalidation",
                checkbox_text=(
                    "* [x] Every resolution rechecks time, durable pause state, "
                    "and the current reservation/attestation chain; expiry, "
                    "source drift, pause, or identity mismatch fails closed "
                    "without automatically renewing, widening, or resuming the "
                    "session."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_authority.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'source_drift or expiry' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_signed_one_way_revocation",
                checkbox_text=(
                    "* [x] Revocation binds an exact session fingerprint and "
                    "allowlisted reason to a separate Ed25519 "
                    "`revoke_controlled_session` approval plus matching "
                    "signature possession, persists one immutable event, changes "
                    "enabled to revoked only once, and exposes no resume or "
                    "re-enable transition."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py -k 'signed_revocation' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_atomic_admission_state_recheck",
                checkbox_text=(
                    "* [x] Rate admission rechecks persistent enabled status, "
                    "session/reservation fingerprints, effective/expiry time, "
                    "and pause state inside its own `BEGIN IMMEDIATE` transaction, "
                    "so a stale authenticated provider cannot race revocation or "
                    "pause."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_runtime_rate_limiter.py",
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_automatic_pause.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py tests/test_controlled_session_automatic_pause.py -k 'atomic_admission or runtime_admission' -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_explicit_non_broker_routes",
                checkbox_text=(
                    "* [x] Public routes expose signed issuance preview/record, "
                    "sanitized session visibility, signed revocation preview/"
                    "record, and history only; there is no resume, renew, widen, "
                    "runtime admit, broker submit, or broker cancel endpoint."
                ),
                evidence_paths=(
                    "server/routes/controlled_session_runtime_authority.py",
                    "server/routes/controlled_session_runtime_rate_limiter.py",
                    "tests/server/test_controlled_session_runtime_authority_routes.py",
                    "tests/server/test_controlled_session_runtime_rate_limiter_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_controlled_session_runtime_authority_routes.py tests/server/test_controlled_session_runtime_rate_limiter_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_authority_deterministic_zero_broker_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact signatures, replay, "
                    "real concurrent issuance, token secrecy/authentication, "
                    "expiry, source drift, signed revocation, stale-provider "
                    "race blocking, strict route models, and zero broker, OMS, "
                    "production-ledger, capital-scale, auto-resume, or auto-renew "
                    "side effects."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_rate_limiter.py",
                    "tests/server/test_controlled_session_runtime_authority_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py tests/test_controlled_session_runtime_rate_limiter.py tests/server/test_controlled_session_runtime_authority_routes.py -q",
                ),
            ),
        )
    )


def build_controlled_session_live_gate_orchestration_acceptance_audit() -> (
    AcceptanceAudit
):
    """Return evidence for Stage 3.10 persisted live-gate orchestration."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="live_gate_monitoring_identity_without_authority",
                checkbox_text=(
                    "* [x] Monitoring resolves the original persistent enabled "
                    "session even when upstream reservation or attestation "
                    "evidence drifts, while explicitly granting no runtime, "
                    "resume, renewal, widening, or broker authority."
                ),
                evidence_paths=(
                    "server/services/controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_runtime_authority.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_runtime_authority.py tests/test_controlled_session_live_gates.py -k 'source_drift or monitoring' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_typed_fail_closed_sources",
                checkbox_text=(
                    "* [x] A typed allowlisted snapshot derives Account Truth, "
                    "risk, paper/shadow, reconciliation, gateway, market data, "
                    "budget/rate, kill switch, loss/drawdown, rejection, "
                    "account-change, and consecutive-error facts from persisted "
                    "sources; missing or invalid facts fail toward pause."
                ),
                evidence_paths=(
                    "server/services/controlled_session_live_gates.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py -k 'clear_snapshot or stale_quote or rejection_spike' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_append_only_snapshot_evidence",
                checkbox_text=(
                    "* [x] Gate snapshots are append-only, fingerprint-bound, "
                    "sanitized, idempotent for an exact observation, queryable "
                    "by session, and rejected as stale after the bounded "
                    "freshness window."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_live_gates.py",
                    "server/routes/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py -k 'clear_snapshot or freshness' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_capture_then_one_way_pause",
                checkbox_text=(
                    "* [x] Every orchestration evaluation captures current "
                    "evidence before applying the existing durable one-way "
                    "pause; clear gates are a no-op and no evaluation can "
                    "automatically resume a paused session."
                ),
                evidence_paths=(
                    "server/services/controlled_session_live_gates.py",
                    "server/services/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py -k 'clear_snapshot or source_drift or kill_switch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_scheduler_and_authenticated_self_check",
                checkbox_text=(
                    "* [x] Periodic evaluation runs only when the explicitly "
                    "started trading scheduler is active, and an operator may "
                    "trigger evaluation only by authenticating the same "
                    "session token; neither path exposes runtime admission or "
                    "execution authority."
                ),
                evidence_paths=(
                    "server/app.py",
                    "server/scheduler.py",
                    "server/routes/controlled_session_automatic_pause.py",
                    "tests/server/test_scheduler_quote_fetch_runs.py",
                    "tests/server/test_controlled_session_automatic_pause_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_scheduler_quote_fetch_runs.py tests/server/test_controlled_session_automatic_pause_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_budget_and_operational_tripwires",
                checkbox_text=(
                    "* [x] Persisted runtime admissions enforce the bounded "
                    "order-count and request-rate view, while stale quotes, "
                    "kill switch activation, rejection spikes, consecutive "
                    "errors, loss/drawdown exhaustion, and unexpected account "
                    "change deterministically trip pause."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/controlled_session_live_gates.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py -k 'budget_exhaustion or stale_quote or rejection_spike' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_sanitized_failure_evidence",
                checkbox_text=(
                    "* [x] Source drift and provider, identity, persistence, or "
                    "evaluation failures remain fail-closed and sanitized; "
                    "stored and returned snapshot evidence contains no runtime "
                    "token or provider credential."
                ),
                evidence_paths=(
                    "server/services/controlled_session_live_gates.py",
                    "server/routes/controlled_session_automatic_pause.py",
                    "tests/test_controlled_session_live_gates.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py -k 'monitoring_identity or freshness' -q",
                ),
            ),
            AcceptanceCriterion(
                key="live_gate_deterministic_zero_execution_tests",
                checkbox_text=(
                    "* [x] Deterministic service, route, scheduler, persistence, "
                    "and source-drift tests verify pause orchestration with zero "
                    "broker submission/cancellation, OMS or production-ledger "
                    "mutation, capital widening, session issue/resume, or "
                    "strategy-to-broker path."
                ),
                evidence_paths=(
                    "tests/test_controlled_session_live_gates.py",
                    "tests/server/test_controlled_session_automatic_pause_routes.py",
                    "tests/server/test_scheduler_quote_fetch_runs.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_controlled_session_live_gates.py tests/server/test_controlled_session_automatic_pause_routes.py tests/server/test_scheduler_quote_fetch_runs.py -q",
                ),
            ),
        )
    )
