"""Acceptance manifests for account."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_account_truth_acceptance_audit() -> AcceptanceAudit:
    """Return Account Truth and reconciliation criteria mapped to evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="canonical_broker_statement_csv_docs",
                checkbox_text=(
                    "* [x] A canonical broker statement CSV format is documented "
                    "with safe\n  synthetic examples."
                ),
                evidence_paths=(
                    "docs/account-truth-import.zh.md",
                    "README.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    'rg -n "canonical broker statement CSV|安全合成样例|broker evidence" README.md docs',
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                ),
            ),
            AcceptanceCriterion(
                key="import_preview_parse_validate_fingerprint",
                checkbox_text=(
                    "* [x] Import preview parses, normalizes, validates, and "
                    "fingerprints local CSV\n  rows without writing production "
                    "ledger entries."
                ),
                evidence_paths=(
                    "account_truth/broker_statement.py",
                    "tests/account_truth/test_broker_statement.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_broker_statement.py",
                ),
            ),
            AcceptanceCriterion(
                key="import_runs_store_metadata",
                checkbox_text=(
                    "* [x] Import runs store source type, file fingerprint, row "
                    "counts, validation\n  status, duplicate counts, timestamps, "
                    "and limitations."
                ),
                evidence_paths=(
                    "account_truth/broker_evidence.py",
                    "tests/account_truth/test_broker_evidence_repository.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_broker_evidence_repository.py",
                ),
            ),
            AcceptanceCriterion(
                key="typed_broker_evidence_events",
                checkbox_text=(
                    "* [x] Imported rows normalize into typed broker evidence "
                    "events: trade\n  buy/sell, dividend, fee, tax, transfer, "
                    "position snapshot, and cash snapshot."
                ),
                evidence_paths=(
                    "account_truth/broker_statement.py",
                    "account_truth/broker_evidence.py",
                    "tests/account_truth/test_broker_statement.py",
                    "tests/account_truth/test_broker_evidence_repository.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_broker_statement.py tests/account_truth/test_broker_evidence_repository.py",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_duplicate_detection",
                checkbox_text=(
                    "* [x] File-level and row-level duplicate detection exists "
                    "and is deterministic."
                ),
                evidence_paths=(
                    "account_truth/broker_statement.py",
                    "account_truth/broker_evidence.py",
                    "tests/account_truth/test_broker_statement.py",
                    "tests/account_truth/test_broker_evidence_repository.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_broker_statement.py tests/account_truth/test_broker_evidence_repository.py",
                ),
            ),
            AcceptanceCriterion(
                key="persist_broker_evidence_without_ledger_mutation",
                checkbox_text=(
                    "* [x] Valid imports can be persisted as broker evidence "
                    "without auto-mutating\n  existing ledger entries."
                ),
                evidence_paths=(
                    "account_truth/broker_evidence.py",
                    "tests/account_truth/test_broker_evidence_repository.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_broker_evidence_repository.py",
                ),
            ),
            AcceptanceCriterion(
                key="reconciliation_compares_account_facts",
                checkbox_text=(
                    "* [x] Reconciliation compares broker evidence against "
                    "Karkinos ledger, cash,\n  positions, fees, taxes, and cost basis."
                ),
                evidence_paths=(
                    "account_truth/reconciliation.py",
                    "tests/account_truth/test_reconciliation.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_reconciliation.py",
                ),
            ),
            AcceptanceCriterion(
                key="reconciliation_report_exposes_differences",
                checkbox_text=(
                    "* [x] Reconciliation reports expose "
                    "pass/warning/mismatch/blocked status,\n  per-symbol "
                    "differences, cash differences, fee/tax differences, "
                    "cost-basis\n  differences, and suggested review actions."
                ),
                evidence_paths=(
                    "account_truth/reconciliation.py",
                    "tests/account_truth/test_reconciliation.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_reconciliation.py",
                ),
            ),
            AcceptanceCriterion(
                key="manual_review_decisions",
                checkbox_text=(
                    "* [x] Manual review can mark reconciliation items as "
                    "accepted, ignored, known\n  difference, ledger candidate, "
                    "or needs investigation."
                ),
                evidence_paths=(
                    "account_truth/manual_review.py",
                    "tests/account_truth/test_manual_review.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_manual_review.py",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_score_report_gate",
                checkbox_text=(
                    "* [x] Account Truth Score is exposed through API/report "
                    "and reflects cash,\n  position, fee, cost-basis, data "
                    "freshness, and unresolved mismatch state."
                ),
                evidence_paths=(
                    "account_truth/score.py",
                    "tests/account_truth/test_account_truth_score.py",
                    "server/routes/decision.py",
                    "analytics/strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_account_truth_score.py",
                    "uv run python -m pytest tests/test_server_routes.py -k account_truth_score",
                ),
            ),
            AcceptanceCriterion(
                key="decision_and_promotion_truth_gate",
                checkbox_text=(
                    "* [x] Decision platform and promotion readiness degrade or "
                    "block when account\n  truth is insufficient."
                ),
                evidence_paths=(
                    "server/routes/decision.py",
                    "analytics/strategy_promotion_readiness.py",
                    "tests/test_server_routes.py",
                    "tests/test_decision_cockpit_acceptance.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k account_truth_score",
                    "uv run python -m pytest tests/analytics/test_strategy_promotion_readiness.py",
                ),
            ),
            AcceptanceCriterion(
                key="no_broker_login_or_order_submission",
                checkbox_text=(
                    "* [x] No broker login, broker password storage, broker "
                    "order submission, or\n  default real-money automation is "
                    "introduced."
                ),
                evidence_paths=(
                    "account_truth/broker_statement.py",
                    "account_truth/broker_evidence.py",
                    "account_truth/reconciliation.py",
                    "account_truth/manual_review.py",
                    "account_truth/score.py",
                    "server/routes/decision.py",
                    "analytics/strategy_promotion_readiness.py",
                    "README.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    'rg -n "broker password|broker order submission|automatic real-money|自动真钱|券商订单" README.md docs account_truth server/routes/decision.py analytics/strategy_promotion_readiness.py',
                    "uv run python -m pytest tests/account_truth tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest tests/test_server_routes.py -k decision",
                ),
            ),
            AcceptanceCriterion(
                key="backend_deterministic_account_truth_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover parser, validation, "
                    "duplicate\n  detection, staging, reconciliation, review "
                    "decisions, account truth score,\n  and decision-platform "
                    "degradation."
                ),
                evidence_paths=(
                    "tests/account_truth/test_broker_statement.py",
                    "tests/account_truth/test_broker_evidence_repository.py",
                    "tests/account_truth/test_reconciliation.py",
                    "tests/account_truth/test_manual_review.py",
                    "tests/account_truth/test_account_truth_score.py",
                    "tests/test_server_routes.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest tests/test_server_routes.py -k account_truth_score",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_docs_boundary",
                checkbox_text=(
                    "* [x] README/docs explain the import workflow, privacy "
                    "boundary, and that\n  broker evidence is audit tooling, "
                    "not investment advice."
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.zh.md",
                    "docs/account-truth-import.zh.md",
                ),
                validation_commands=(
                    'rg -n "Account Truth|privacy|隐私|audit tooling|not investment advice|不是投资建议" README.md docs',
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_acceptance_audit_cli",
                checkbox_text=(
                    "* [x] Acceptance audit manifest and CLI include the "
                    "account truth /\n  reconciliation capability using "
                    "capability-based naming."
                ),
                evidence_paths=(
                    "analytics/acceptance_audit.py",
                    "scripts/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/export_acceptance_audit.py --audit account_truth",
                ),
            ),
        )
    )


def build_account_truth_review_acceptance_audit() -> AcceptanceAudit:
    """Return Account Truth review-center criteria mapped to evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="account_truth_review_surface",
                checkbox_text=(
                    "* [x] A user-facing Account Truth review surface exists."
                ),
                evidence_paths=(
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                    "web/src/app/router.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- account-truth-review-page",
                    "npm --prefix web run build",
                ),
            ),
            AcceptanceCriterion(
                key="import_runs_listing",
                checkbox_text=(
                    "* [x] Import runs can be listed with row counts, "
                    "validation status, duplicate"
                ),
                evidence_paths=(
                    "server/routes/account_truth.py",
                    "account_truth/broker_evidence.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="reconciliation_report_listing_detail",
                checkbox_text=(
                    "* [x] Reconciliation reports can be listed and inspected "
                    "by status: pass,"
                ),
                evidence_paths=(
                    "server/routes/account_truth.py",
                    "account_truth/reconciliation.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="reconciliation_item_evidence_fields",
                checkbox_text=(
                    "* [x] Reconciliation items show broker value, Karkinos "
                    "value, difference,"
                ),
                evidence_paths=(
                    "account_truth/reconciliation.py",
                    "server/routes/account_truth.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_reconciliation.py tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="manual_review_actions",
                checkbox_text=(
                    "* [x] Manual review actions can mark differences as "
                    "accepted, ignored,"
                ),
                evidence_paths=(
                    "account_truth/manual_review.py",
                    "server/routes/account_truth.py",
                    "tests/account_truth/test_manual_review.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_manual_review.py tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="ledger_candidate_safety",
                checkbox_text=(
                    "* [x] Ledger candidates do not mutate the production "
                    "ledger without explicit"
                ),
                evidence_paths=(
                    "server/routes/account_truth.py",
                    "tests/server/test_account_truth_routes.py",
                    "account_truth/manual_review.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_truth_routes.py -k ledger_candidate",
                ),
            ),
            AcceptanceCriterion(
                key="score_api_web_component_reasons",
                checkbox_text=(
                    "* [x] Account Truth Score is visible in API and Web UI "
                    "with component-level"
                ),
                evidence_paths=(
                    "account_truth/score.py",
                    "server/routes/account_truth.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_truth_routes.py -k score",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="decision_degraded_blocked_surface",
                checkbox_text=(
                    "* [x] Decision summaries degrade or block when unresolved "
                    "account-truth issues"
                ),
                evidence_paths=(
                    "server/routes/decision.py",
                    "web/src/features/decision/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_decision_cockpit_acceptance.py",
                    "npm --prefix web test -- decision-cockpit-page",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_readiness_account_truth_gate",
                checkbox_text=(
                    "* [x] Strategy promotion readiness shows account-truth "
                    "gate status."
                ),
                evidence_paths=(
                    "analytics/strategy_promotion_readiness.py",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_strategy_promotion_readiness.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="citic_query_window_batch_non_authority",
                checkbox_text=(
                    "* [x] Reviewed CITIC query windows detect gaps and overlaps "
                    "and unresolved source integrity blocks promotion evidence, "
                    "without proving\n  complete account coverage or granting "
                    "Account Truth, reconciliation, execution, or capital authority."
                ),
                evidence_paths=(
                    "server/services/citic_source_query_window_review.py",
                    "server/services/citic_source_follow_up.py",
                    "server/services/account_truth_evidence_readiness.py",
                    "server/services/account_truth_replay.py",
                    "server/routes/account_truth.py",
                    "tests/test_citic_query_window_batch_assessment.py",
                    "tests/test_citic_source_follow_up.py",
                    "tests/test_account_truth_evidence_readiness.py",
                    "tests/server/test_account_truth_gate.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/features/account-truth/api.ts",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_citic_query_window_batch_assessment.py tests/test_citic_source_follow_up.py tests/test_account_truth_evidence_readiness.py tests/server/test_account_truth_gate.py tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="backend_deterministic_review_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover import-run "
                    "listing, reconciliation"
                ),
                evidence_paths=(
                    "tests/server/test_account_truth_routes.py",
                    "tests/account_truth/test_manual_review.py",
                    "tests/account_truth/test_account_truth_score.py",
                    "tests/test_decision_cockpit_acceptance.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_truth_routes.py tests/account_truth/test_manual_review.py tests/account_truth/test_account_truth_score.py tests/test_decision_cockpit_acceptance.py tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="frontend_account_truth_review_tests",
                checkbox_text=(
                    "* [x] Frontend tests cover Account Truth review rendering, "
                    "status filters,"
                ),
                evidence_paths=(
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- account-truth-review-page decision-cockpit-page backtest-page",
                    "npm --prefix web test",
                ),
            ),
            AcceptanceCriterion(
                key="review_workflow_docs_boundary",
                checkbox_text=(
                    "* [x] README/docs explain the review workflow as audit "
                    "tooling, not investment"
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    'rg -n "Account Truth Review Center|Account Truth 复核中心|audit tooling|不构成投资建议|not investment advice" README.md docs',
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_review_acceptance_audit_cli",
                checkbox_text=(
                    "* [x] Acceptance audit manifest and CLI include the "
                    "account-truth review"
                ),
                evidence_paths=(
                    "analytics/acceptance_audit.py",
                    "scripts/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/export_acceptance_audit.py --audit account_truth_review",
                ),
            ),
        )
    )
