"""Acceptance manifests for fees."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_broker_fee_cost_basis_acceptance_audit() -> AcceptanceAudit:
    """Return completed broker fee and cost-basis fidelity criteria evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="strategy_attribution_component_separation",
                checkbox_text=(
                    "* [x] Strategy performance attribution separates realized, "
                    "unrealized, fee,"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.tsx",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "npm --prefix web test -- strategy-contribution-gate-card",
                ),
            ),
            AcceptanceCriterion(
                key="structured_broker_fee_schedule_config",
                checkbox_text=(
                    "* [x] Local `config.json` supports a structured broker fee "
                    "schedule without"
                ),
                evidence_paths=(
                    "server/config.py",
                    "config.example.json",
                    "tests/test_bootstrap.py",
                    "README.md",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_bootstrap.py",
                    'rg -n "broker_fee_schedule|券商费用规则|fee schedule" README.md docs config.example.json',
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_fee_breakdown",
                checkbox_text=(
                    "* [x] Fee calculation returns a deterministic breakdown for "
                    "commission, stamp"
                ),
                evidence_paths=(
                    "server/services/manual_trade_fees.py",
                    "execution/commission.py",
                    "tests/server/test_manual_trade_fee_service.py",
                    "tests/execution/test_commission.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_manual_trade_fee_service.py tests/execution/test_commission.py",
                ),
            ),
            AcceptanceCriterion(
                key="ledger_entries_preserve_fee_cost_fields",
                checkbox_text=(
                    "* [x] Buy and sell ledger entries preserve gross trade amount, "
                    "net cash impact,"
                ),
                evidence_paths=(
                    "server/routes/ledger.py",
                    "server/routes/portfolio.py",
                    "server/db.py",
                    "server/ledger/models.py",
                    "tests/server/test_ledger_routes.py",
                    "tests/server/test_ledger_repository.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_ledger_routes.py tests/server/test_ledger_repository.py",
                    "uv run python -m pytest tests/test_server_routes.py -k 'trade or fee'",
                ),
            ),
            AcceptanceCriterion(
                key="shared_public_ledger_formatter_surface_contract",
                checkbox_text=(
                    "* [x] A shared public ledger formatter is used by Overview, "
                    "Activity,"
                ),
                evidence_paths=(
                    "web/src/shared/ledger-format.ts",
                    "web/src/features/activity/components/activity-feed.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "web/src/app/router.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.tsx",
                    "web/src/features/activity/ledger-format.test.ts",
                    "web/src/features/overview/pages/overview-page.test.tsx",
                    "web/src/features/risk/pages/risk-page.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- ledger-format overview-page risk-page holding-detail-page account-truth-review-page decision-cockpit-page",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="public_ledger_surfaces_hide_internal_values",
                checkbox_text=(
                    "* [x] User-facing ledger surfaces do not render internal "
                    "values such as"
                ),
                evidence_paths=(
                    "web/src/shared/ledger-format.ts",
                    "web/src/shared/public-labels.ts",
                    "web/src/features/activity/ledger-format.test.ts",
                    "web/src/features/overview/pages/overview-page.test.tsx",
                    "web/src/features/risk/pages/risk-page.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- ledger-format overview-page risk-page holding-detail-page account-truth-review-page decision-cockpit-page",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="public_ledger_notes_keep_core_facts_structured",
                checkbox_text=(
                    "* [x] Public ledger notes follow a consistent localized "
                    "format and never carry"
                ),
                evidence_paths=(
                    "web/src/shared/ledger-format.ts",
                    "web/src/features/activity/ledger-format.test.ts",
                    "web/src/features/activity/components/activity-feed.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "web/src/app/router.tsx",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "npm --prefix web test -- ledger-format overview-page risk-page holding-detail-page account-truth-review-page decision-cockpit-page",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="portfolio_cost_views_distinguish_local_and_broker_cost_basis",
                checkbox_text=(
                    "* [x] Portfolio cost views show both moving average buy "
                    "cost and broker"
                ),
                evidence_paths=(
                    "web/src/features/portfolio/components/positions-table.tsx",
                    "web/src/features/portfolio/positions-table.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "web/src/app/copy.ts",
                    "server/models.py",
                    "server/routes/portfolio.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "npm --prefix web test -- positions-table holding-detail-page",
                    "uv run python -m pytest tests/test_server_routes.py -k broker_cost_basis",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="sell_side_net_proceeds_broker_cost_basis",
                checkbox_text=(
                    "* [x] Sell-side realized P/L and remaining-position "
                    "broker cost basis use net"
                ),
                evidence_paths=(
                    "server/projections/service.py",
                    "tests/server/test_projection_service.py",
                    "server/services/manual_trade_fees.py",
                    "tests/server/test_manual_trade_fee_service.py",
                    "server/routes/ledger.py",
                    "tests/server/test_ledger_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_projection_service.py -k sell_side_net_proceeds",
                    "uv run python -m pytest tests/server/test_manual_trade_fee_service.py tests/server/test_ledger_routes.py -k sell",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="shared_fee_model_contract_across_research_and_ledger",
                checkbox_text=(
                    "* [x] Backtest, paper broker, manual trade preview, and "
                    "ledger projections use"
                ),
                evidence_paths=(
                    "execution/commission.py",
                    "execution/simulator.py",
                    "execution/paper_broker.py",
                    "backtest/engine.py",
                    "server/services/manual_trade_fees.py",
                    "server/projections/service.py",
                    "server/routes/backtest.py",
                    "tests/execution/test_simulator.py",
                    "tests/execution/test_paper_broker.py",
                    "tests/server/test_manual_trade_fee_service.py",
                    "tests/server/test_projection_service.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/execution/test_simulator.py tests/execution/test_paper_broker.py tests/server/test_manual_trade_fee_service.py tests/server/test_projection_service.py",
                    "uv run python -m pytest tests/test_server_routes.py::test_backtest_fill_response_preserves_structured_fee_breakdown",
                ),
            ),
            AcceptanceCriterion(
                key="backend_fee_cost_basis_deterministic_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover A-share buy/sell, "
                    "stamp tax,"
                ),
                evidence_paths=(
                    "execution/commission.py",
                    "server/services/manual_trade_fees.py",
                    "server/routes/ledger.py",
                    "server/projections/service.py",
                    "tests/execution/test_commission.py",
                    "tests/server/test_manual_trade_fee_service.py",
                    "tests/server/test_ledger_routes.py",
                    "tests/server/test_projection_service.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/execution/test_commission.py tests/server/test_manual_trade_fee_service.py tests/server/test_ledger_routes.py tests/server/test_projection_service.py",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="frontend_fee_cost_basis_display_tests",
                checkbox_text=(
                    "* [x] Frontend tests cover fee-breakdown display, "
                    "cost-basis-method display,"
                ),
                evidence_paths=(
                    "web/src/features/activity/pages/activity-page.test.tsx",
                    "web/src/features/activity/ledger-format.test.ts",
                    "web/src/features/activity/trade-form.test.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                    "web/src/features/portfolio/positions-table.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "web/src/shared/ledger-format.ts",
                    "web/src/features/activity/components/activity-feed.tsx",
                    "web/src/features/activity/components/trade-form.tsx",
                    "web/src/features/portfolio/components/positions-table.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- activity-page ledger-format trade-form trading-page positions-table holding-detail-page",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_cost_basis_method_precision_context",
                checkbox_text=(
                    "* [x] Account Truth reconciliation compares "
                    "broker-reported cost basis against"
                ),
                evidence_paths=(
                    "account_truth/reconciliation.py",
                    "server/account_truth_gate.py",
                    "tests/account_truth/test_reconciliation.py",
                    "tests/server/test_account_truth_routes.py",
                    "web/src/shared/public-labels.ts",
                    "web/src/features/account-truth/components/account-truth-review-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/account_truth/test_reconciliation.py tests/server/test_account_truth_routes.py",
                    "npm --prefix web test -- account-truth-review-page",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_health_states",
                checkbox_text=(
                    "* [x] Strategy health can mark assigned strategies as healthy, "
                    "degraded,"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="manual_and_missing_evidence_not_strategy_attributed",
                checkbox_text=(
                    "* [x] Manual trades and missing-evidence movement are never "
                    "attributed to a"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.tsx",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "npm --prefix web test -- strategy-contribution-gate-card",
                ),
            ),
            AcceptanceCriterion(
                key="web_strategy_contribution_user_readable_surface",
                checkbox_text=(
                    "* [x] Web surfaces explain strategy contribution in "
                    "localized user-facing"
                ),
                evidence_paths=(
                    "web/src/app/copy.ts",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.tsx",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "npm --prefix web test -- strategy-contribution-gate-card decision-cockpit-page",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k broker_fee_cost_basis",
                ),
            ),
        )
    )
