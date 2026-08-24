"""Acceptance manifests for capital scaling."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_capital_scaling_review_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the Stage 4 capital scaling review foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="versioned_capital_tier_and_scaling_evidence",
                checkbox_text=(
                    "* [x] Versioned current/proposed capital tiers and a "
                    "deterministic evidence contract cover reviewed trading "
                    "days, orders/fills/rejects, reconciliation latency/gaps, "
                    "slippage, after-cost result, drawdown, capacity, liquidity, "
                    "paper/shadow divergence, disconnects, policy violations, "
                    "and incidents."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review.py",
                    "tests/test_capital_scaling_review.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k 'strong_evidence or fingerprint_is_sensitive' -q",
                ),
            ),
            AcceptanceCriterion(
                key="scale_up_evidence_thresholds",
                checkbox_text=(
                    "* [x] Scale-up review requires at least 20 reviewed "
                    "trading days, 50 orders, required Account Truth and "
                    "provenance references, passing fill/rejection/slippage/"
                    "after-cost/drawdown/capacity/liquidity/reconciliation/"
                    "divergence/disconnect thresholds, and a proposed tier "
                    "that actually widens at least one explicit limit."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k 'strong_evidence or insufficient_sample or same_tier' -q",
                ),
            ),
            AcceptanceCriterion(
                key="protective_scaling_recommendations_precede_expansion",
                checkbox_text=(
                    "* [x] Invalid or insufficient evidence recommends hold, "
                    "degraded execution quality recommends scale-down, and "
                    "critical incidents, policy violations, unresolved "
                    "reconciliation, or current-tier drawdown exhaustion "
                    "recommends disable before any scale-up review."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k 'invalid_evidence or degraded_execution or critical_incident or drawdown' -q",
                ),
            ),
            AcceptanceCriterion(
                key="append_only_scaling_evaluation",
                checkbox_text=(
                    "* [x] Preview is side-effect free; recorded evaluations "
                    "use deterministic fingerprints and append-only sequential "
                    "reuse without changing authority."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review_audit.py",
                    "server/db.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k evaluation_and_hold -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_human_decision_cannot_exceed_evidence",
                checkbox_text=(
                    "* [x] Human review decisions bind one persisted evaluation "
                    "fingerprint; a human may choose the recommendation or a "
                    "safer action but cannot request scale-up when the evidence "
                    "recommendation is hold/scale-down/disable."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k 'cannot_exceed or unresolved' -q",
                ),
            ),
            AcceptanceCriterion(
                key="scale_up_requires_separate_new_authorization",
                checkbox_text=(
                    "* [x] Even an eligible scale-up decision only records a "
                    "request for a separate new authorization; automatic "
                    "scale-up, new authorization issuance, runtime limit "
                    "mutation, execution resume, and broker submission remain "
                    "disabled."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_review.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k 'hold_decision or status_exposes' -q",
                ),
            ),
            AcceptanceCriterion(
                key="capital_scaling_review_api_boundary",
                checkbox_text=(
                    "* [x] Status, preview, evaluation, decision, and list APIs "
                    "reject undeclared credential fields and expose no apply-"
                    "tier, issue-authority, mutate-limit, enable/resume "
                    "execution, submit/cancel, or automatic scale-up action."
                ),
                evidence_paths=(
                    "server/routes/capital_scaling_review.py",
                    "server/app.py",
                    "tests/server/test_capital_scaling_review_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_scaling_review_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="capital_scaling_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover "
                    "eligibility, hold, scale-down, disable, invalid evidence, "
                    "provenance, fingerprint reuse, safer human choice, rejected "
                    "overreach, credential rejection, and zero authority side "
                    "effects."
                ),
                evidence_paths=(
                    "tests/test_capital_scaling_review.py",
                    "tests/server/test_capital_scaling_review_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py tests/server/test_capital_scaling_review_routes.py -q",
                ),
            ),
        )
    )


def build_capital_scaling_evidence_resolution_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the fail-closed Stage 4.1 source resolver."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="persisted_scaling_source_resolution",
                checkbox_text=(
                    "* [x] Broker-soak observations, execution-reconciliation "
                    "runs, paper/shadow runs, and risk decisions resolve by "
                    "typed identifier from persisted stores rather than by "
                    "trusting the caller-provided reference string alone."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_resolution.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py -k links_supported -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_source_window_and_clear_state_gates",
                checkbox_text=(
                    "* [x] Missing, invalid, out-of-window, or non-clear "
                    "persisted source facts fail closed with typed blockers; "
                    "only sanitized source fingerprints and status fields are "
                    "returned."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_resolution.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py -k 'non_clear or links_supported' -q",
                ),
            ),
            AcceptanceCriterion(
                key="computed_scaling_aggregates_are_required",
                checkbox_text=(
                    "* [x] Account Truth, after-cost, incident-window, and "
                    "capacity/liquidity refs must resolve through a recorded "
                    "computed evidence window; caller-declared aggregate "
                    "metrics alone remain blocked."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_resolution.py",
                    "server/services/capital_scaling_review_audit.py",
                    "server/services/capital_scaling_evidence_window.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py -k 'computed_window or unresolved_persisted' -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_evaluation_binds_resolution_fingerprint",
                checkbox_text=(
                    "* [x] Preview and recorded evaluation evidence bind the "
                    "review-input fingerprint to a deterministic persisted-"
                    "source resolution fingerprint, so source changes create a "
                    "different evaluation identity while exact reruns reuse the "
                    "append-only record."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py -k 'source_sensitive or evaluation_and_hold' -q",
                ),
            ),
            AcceptanceCriterion(
                key="unresolved_sources_cannot_request_scale_up",
                checkbox_text=(
                    "* [x] A mathematically eligible scale-up recommendation "
                    "is converted to hold when persisted sources are unresolved; "
                    "attempted human overreach is rejected and audited without "
                    "issuing authority."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_review.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_review.py -k unresolved_persisted -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_resolution_zero_execution_side_effects",
                checkbox_text=(
                    "* [x] Evidence resolution remains read-only with respect "
                    "to Account Truth, OMS, runtime limits, broker gateway, and "
                    "production ledger; automatic scale-up and broker "
                    "submission remain disabled."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_resolution.py",
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_review.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py -q",
                ),
            ),
        )
    )


def build_capital_scaling_evidence_window_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for deterministic Stage 4.2 computed windows."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="sanitized_timely_account_truth_point_snapshot",
                checkbox_text=(
                    "* [x] Account Truth point snapshots persist only a "
                    "sanitized pass/fresh/zero-unresolved score summary, "
                    "require capture within 15 minutes of the source import, "
                    "and reuse an append-only deterministic identity."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k account_truth_snapshot -q",
                ),
            ),
            AcceptanceCriterion(
                key="distinct_account_truth_window_boundaries",
                checkbox_text=(
                    "* [x] A review window requires two distinct clear Account "
                    "Truth point snapshots near its start and end boundaries; "
                    "missing, stale, blocked, reused-as-both, or out-of-"
                    "tolerance boundary evidence fails closed."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k 'clear_evidence_window or missing_boundaries' -q",
                ),
            ),
            AcceptanceCriterion(
                key="modified_dietz_after_cost_window",
                checkbox_text=(
                    "* [x] After-cost return is computed from persisted start/"
                    "end portfolio equity and time-weighted external cash "
                    "flows using Modified Dietz; incomplete boundary or "
                    "Account Truth coverage blocks the fact."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k 'clear_evidence_window or missing_boundaries' -q",
                ),
            ),
            AcceptanceCriterion(
                key="persisted_incident_window_aggregation",
                checkbox_text=(
                    "* [x] Incident evidence counts persisted critical alerts, "
                    "rejected live submit/cancel attempts, and read-only "
                    "connector disconnect observations without treating "
                    "acknowledgement as deletion of incident history."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k incident_fact -q",
                ),
            ),
            AcceptanceCriterion(
                key="reconciled_real_fill_capacity_evidence",
                checkbox_text=(
                    "* [x] Capacity/liquidity and slippage metrics use only "
                    "non-simulated fills with broker/provider/order linkage "
                    "plus Account Truth, reconciliation, capacity-model, and "
                    "market-data references; incomplete real-fill metadata "
                    "blocks the fact and maximum utilization is retained."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k 'clear_evidence_window or incomplete_real_fill' -q",
                ),
            ),
            AcceptanceCriterion(
                key="computed_window_input_and_append_only_boundary",
                checkbox_text=(
                    "* [x] Evidence-window preview accepts only a time window "
                    "and boundary tolerance; computed metrics cannot be "
                    "supplied by the caller, while recorded windows are "
                    "append-only, fingerprinted, and sequentially reusable."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "server/routes/capital_scaling_review.py",
                    "tests/test_capital_scaling_evidence_window.py",
                    "tests/server/test_capital_scaling_review_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py tests/server/test_capital_scaling_review_routes.py -k 'clear_evidence_window or evidence_routes' -q",
                ),
            ),
            AcceptanceCriterion(
                key="computed_window_scan_truncation_fails_closed",
                checkbox_text=(
                    "* [x] Any capped source scan that reaches its 5,000-row "
                    "limit is marked truncated and blocks the computed fact "
                    "instead of treating unseen rows as evidence that no "
                    "incident, cash flow, fill, or boundary fact exists."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k truncated_source_scan -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_resolver_metric_and_fill_coverage",
                checkbox_text=(
                    "* [x] The resolver requires Account Truth and verifies the "
                    "recorded window, per-fact fingerprint, exact review "
                    "window, clear status, metric equality, and fill coverage "
                    "before a scale-up request can be recorded."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review.py",
                    "server/services/capital_scaling_evidence_resolution.py",
                    "server/services/capital_scaling_review_audit.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py -k 'computed_window or all_resolved' -q",
                ),
            ),
            AcceptanceCriterion(
                key="scaling_evidence_window_api_zero_execution_authority",
                checkbox_text=(
                    "* [x] Evidence status/snapshot/window APIs reject "
                    "undeclared credential or metric fields and expose no "
                    "authority issue, limit mutation, OMS/ledger write, broker "
                    "submit/cancel, resume, or automatic scale-up operation."
                ),
                evidence_paths=(
                    "server/routes/capital_scaling_review.py",
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/server/test_capital_scaling_review_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_scaling_review_routes.py -k evidence_routes -q",
                ),
            ),
        )
    )


def build_capital_scaling_operating_sample_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for deterministic Stage 4.3 operating samples."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="computed_operating_sample_from_persisted_facts",
                checkbox_text=(
                    "* [x] The operating sample computes reviewed trading "
                    "days and non-paper OMS order counts from persisted "
                    "broker-soak, order, transition, and fill facts inside the "
                    "review window."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k clear_evidence_window -q",
                ),
            ),
            AcceptanceCriterion(
                key="terminal_outcome_counting_semantics",
                checkbox_text=(
                    "* [x] Filled, rejected, partially filled, cancelled, "
                    "expired, and nonterminal outcomes remain distinct; filled "
                    "counts require reconciled real quantity and invalid or "
                    "overfilled samples fail closed."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k terminal_outcome -q",
                ),
            ),
            AcceptanceCriterion(
                key="order_covered_reconciliation_latency",
                checkbox_text=(
                    "* [x] The latest reconciliation run must cover every "
                    "sampled order, unresolved items are counted, and p95 "
                    "latency is derived from persisted order/fill/transition "
                    "time to the first no-action reconciliation."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k reconciliation_coverage -q",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_divergence_sample",
                checkbox_text=(
                    "* [x] Paper/shadow divergence is counted from persisted "
                    "paper/shadow order facts for the same window, and a real "
                    "order sample without paper/shadow comparison evidence is "
                    "blocked."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k 'clear_evidence_window or terminal_outcome' -q",
                ),
            ),
            AcceptanceCriterion(
                key="cash_flow_unitized_max_drawdown",
                checkbox_text=(
                    "* [x] Maximum drawdown is computed from cash-flow-unitized "
                    "portfolio equity so deposits and withdrawals do not "
                    "masquerade as trading profit or loss."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k unitized_drawdown -q",
                ),
            ),
            AcceptanceCriterion(
                key="operating_sample_coverage_fails_closed",
                checkbox_text=(
                    "* [x] Missing Account Truth, healthy broker-day, real-fill "
                    "linkage, OMS terminal state, reconciliation latency, "
                    "paper/shadow sample, drawdown series, or complete capped "
                    "scan blocks the operating sample."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_window.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py -k 'missing_reconciliation or truncated_source_scan or missing_boundaries' -q",
                ),
            ),
            AcceptanceCriterion(
                key="operating_sample_metric_equality_resolution",
                checkbox_text=(
                    "* [x] `operating_sample:<window_id>` is a required clear "
                    "source and the resolver compares all nine caller-declared "
                    "sample, reconciliation, divergence, and drawdown metrics "
                    "to the recorded fact exactly."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_review.py",
                    "server/services/capital_scaling_evidence_resolution.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_resolution.py -k computed_window -q",
                ),
            ),
            AcceptanceCriterion(
                key="operating_sample_deterministic_identity",
                checkbox_text=(
                    "* [x] Operating-sample source references, metrics, "
                    "blockers, and assumptions participate in the evidence-"
                    "window fingerprint, so exact reruns reuse one append-only "
                    "record and source changes produce a new identity."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "server/services/capital_scaling_evidence_resolution.py",
                    "tests/test_capital_scaling_evidence_window.py",
                    "tests/test_capital_scaling_evidence_resolution.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py tests/test_capital_scaling_evidence_resolution.py -k 'clear_evidence_window or source_sensitive' -q",
                ),
            ),
            AcceptanceCriterion(
                key="operating_sample_zero_execution_authority",
                checkbox_text=(
                    "* [x] Operating-sample computation and resolution are "
                    "read-only with respect to Account Truth, OMS, runtime "
                    "limits, production ledger, and broker gateway; they never "
                    "issue authority or submit/cancel an order."
                ),
                evidence_paths=(
                    "server/services/capital_scaling_evidence_window.py",
                    "server/services/capital_scaling_evidence_resolution.py",
                    "server/routes/capital_scaling_review.py",
                    "tests/server/test_capital_scaling_review_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_scaling_evidence_window.py tests/test_capital_scaling_evidence_resolution.py tests/server/test_capital_scaling_review_routes.py -q",
                ),
            ),
        )
    )
