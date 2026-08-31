"""Acceptance manifests for strategy."""

from __future__ import annotations

from analytics.acceptance.models import AcceptanceAudit, AcceptanceCriterion


def build_strategy_assignment_acceptance_audit() -> AcceptanceAudit:
    """Return completed v0.8 Strategy Assignment criteria evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="account_strategy_assignment_api",
                checkbox_text=(
                    "* [x] A capability-based account strategy assignment API "
                    "exists and can read"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "server/models.py",
                    "tests/server/test_account_strategy_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="account_strategy_assignment_scope_updates",
                checkbox_text=(
                    "* [x] Account strategy assignment can be updated for "
                    "account, asset-class, or"
                ),
                evidence_paths=(
                    "server/models.py",
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/features/backtest/api.ts",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "npm --prefix web run build",
                ),
            ),
            AcceptanceCriterion(
                key="assignment_storage_is_audit_only",
                checkbox_text=(
                    "* [x] Assignment storage is auditable and does not mutate "
                    "ledger entries,"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                ),
            ),
            AcceptanceCriterion(
                key="backtest_strategy_assignment_surface",
                checkbox_text=(
                    "* [x] Backtest Web shows available strategies first, then "
                    "run configuration,"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/backtest/api.ts",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page",
                    "npm --prefix web test",
                ),
            ),
            AcceptanceCriterion(
                key="backtest_strategy_pnl_attribution_status",
                checkbox_text=(
                    "* [x] Backtest Web clearly states when strategy P/L "
                    "attribution is not started,"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/app/copy.ts",
                ),
                validation_commands=("npm --prefix web test -- backtest-page",),
            ),
            AcceptanceCriterion(
                key="localized_strategy_names",
                checkbox_text=(
                    "* [x] Strategy IDs remain internal audit keys while Web "
                    "surfaces localized"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/strategy-metadata-snapshot-panel.tsx",
                    "web/src/app/copy.ts",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=("npm --prefix web test -- backtest-page",),
            ),
            AcceptanceCriterion(
                key="deterministic_strategy_attribution_refs",
                checkbox_text=(
                    "* [x] Signals, action candidates, risk decisions, review "
                    "decisions, orders, and"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "server/db.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_contribution_separation",
                checkbox_text=(
                    "* [x] Strategy contribution report separates realized "
                    "P/L, unrealized P/L,"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/features/backtest/components/backtest-page.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_contribution_excludes_unattributed",
                checkbox_text=(
                    "* [x] Strategy contribution API never assigns cash "
                    "deposits, withdrawals,"
                ),
                evidence_paths=(
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_contribution_evidence_gated_surfaces",
                checkbox_text=(
                    "* [x] Overview, Portfolio, Backtest, Decision, and "
                    "review surfaces expose"
                ),
                evidence_paths=(
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.tsx",
                    "web/src/features/account-strategy/components/strategy-contribution-gate-card.test.tsx",
                    "web/src/app/router.tsx",
                    "web/src/features/overview/pages/overview-page.test.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- strategy-contribution-gate-card overview-page backtest-page decision-cockpit-page",
                ),
            ),
            AcceptanceCriterion(
                key="decision_degrades_on_missing_attribution",
                checkbox_text=(
                    "* [x] Decision summaries degrade or block strategy-driven "
                    "recommendations when"
                ),
                evidence_paths=(
                    "server/routes/decision.py",
                    "tests/test_server_routes.py",
                    "web/src/features/decision/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py::test_decision_today_requires_strategy_attribution_for_assigned_strategy",
                    "npm --prefix web test -- decision-cockpit-page",
                ),
            ),
            AcceptanceCriterion(
                key="backend_strategy_assignment_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover assignment "
                    "defaults, updates,"
                ),
                evidence_paths=(
                    "tests/server/test_account_strategy_routes.py",
                    "tests/test_server_routes.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest tests/test_server_routes.py::test_decision_today_requires_strategy_attribution_for_assigned_strategy",
                ),
            ),
            AcceptanceCriterion(
                key="frontend_strategy_assignment_tests",
                checkbox_text=(
                    "* [x] Frontend tests cover strategy catalog first-screen "
                    "rendering, current"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page decision-cockpit-page",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_assignment_docs_boundary",
                checkbox_text=(
                    "* [x] README/docs explain strategy assignment and "
                    "contribution reporting as"
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    'rg -n "strategy assignment|策略分配|not investment advice|不构成投资建议" README.md docs',
                ),
            ),
            AcceptanceCriterion(
                key="strategy_assignment_acceptance_audit_cli",
                checkbox_text=(
                    "* [x] Acceptance audit manifest and CLI include the "
                    "strategy assignment and"
                ),
                evidence_paths=(
                    "analytics/acceptance_audit.py",
                    "scripts/ci/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/ci/export_acceptance_audit.py --audit strategy_assignment",
                ),
            ),
        )
    )


def build_market_data_reliability_acceptance_audit() -> AcceptanceAudit:
    """Return completed Market Data Reliability criteria evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="capability_market_data_adapter",
                checkbox_text=(
                    "* [x] A capability-based market data adapter interface exists "
                    "for daily bars,"
                ),
                evidence_paths=(
                    "data/market_data.py",
                    "tests/data/test_market_data_contract.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_contract.py",
                ),
            ),
            AcceptanceCriterion(
                key="shared_data_status_vocabulary",
                checkbox_text=(
                    "* [x] Daily bars, intraday bars, snapshots, and replay events "
                    "normalize into a"
                ),
                evidence_paths=(
                    "data/market_data.py",
                    "web/src/shared/market-data-status.ts",
                    "tests/data/test_market_data_contract.py",
                    "web/src/shared/market-data-status.test.ts",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_contract.py",
                    "npm --prefix web test -- market-data-status",
                ),
            ),
            AcceptanceCriterion(
                key="market_records_preserve_metadata",
                checkbox_text=(
                    "* [x] Market data records keep source, timestamp, trading "
                    "session, adjustment"
                ),
                evidence_paths=(
                    "data/market_data.py",
                    "tests/data/test_market_data_contract.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_contract.py",
                ),
            ),
            AcceptanceCriterion(
                key="market_data_quality_diagnostics",
                checkbox_text=(
                    "* [x] Data-quality diagnostics detect missing trading dates, "
                    "non-trading days,"
                ),
                evidence_paths=(
                    "data/market_data.py",
                    "tests/data/test_market_data_quality.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_quality.py",
                ),
            ),
            AcceptanceCriterion(
                key="manual_and_scheduled_refresh_boundaries",
                checkbox_text=(
                    "* [x] Manual refresh and scheduled refresh flows can update "
                    "intraday quotes,"
                ),
                evidence_paths=(
                    "data/market_data_refresh.py",
                    "tests/data/test_market_data_refresh.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_refresh.py",
                ),
            ),
            AcceptanceCriterion(
                key="frozen_dataset_replay",
                checkbox_text=(
                    "* [x] Dataset snapshots can be frozen and replayed "
                    "deterministically for"
                ),
                evidence_paths=(
                    "data/market_data_replay.py",
                    "tests/data/test_market_data_replay.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_replay.py",
                ),
            ),
            AcceptanceCriterion(
                key="market_data_status_consumer_contract",
                checkbox_text=(
                    "* [x] Overview valuation, return calendar, Backtest, "
                    "and Strategy Runtime use"
                ),
                evidence_paths=(
                    "web/src/shared/market-data-status.ts",
                    "web/src/shared/market-data-status.test.ts",
                    "web/src/features/account/components/overview-cards.tsx",
                    "web/src/features/account/components/equity-curve-card.tsx",
                    "web/src/features/account/components/equity-curve-card.test.tsx",
                    "web/src/features/account/components/return-calendar-card.test.tsx",
                    "web/src/features/backtest/components/dataset-snapshot-panel.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "data/market_data_replay.py",
                    "tests/data/test_market_data_replay.py",
                ),
                validation_commands=(
                    "npm --prefix web test -- market-data-status.test.ts equity-curve-card.test.tsx return-calendar-card.test.tsx backtest-page.test.tsx",
                    "uv run python -m pytest tests/data/test_market_data_replay.py",
                ),
            ),
            AcceptanceCriterion(
                key="one_day_net_value_chart_contract",
                checkbox_text=(
                    "* [x] The 1D net-value chart can represent intraday "
                    "market movement, cash-flow"
                ),
                evidence_paths=(
                    "web/src/features/account/components/equity-curve-card.tsx",
                    "web/src/features/account/components/equity-curve-card.test.tsx",
                    "server/routes/portfolio.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "npm --prefix web test -- equity-curve-card.test.tsx",
                    'uv run python -m pytest tests/test_server_routes.py -k "portfolio_equity_curve_series_1d or current_equity_series_point_marks_confirmed_nav_missing_fund_estimate"',
                ),
            ),
            AcceptanceCriterion(
                key="web_data_status_surface_copy",
                checkbox_text=(
                    "* [x] Web data-status surfaces expose localized, "
                    "user-readable status and next"
                ),
                evidence_paths=(
                    "web/src/shared/market-data-status.ts",
                    "web/src/shared/market-data-status.test.ts",
                    "web/src/features/account/components/dashboard-quick-actions.tsx",
                    "web/src/features/account/components/dashboard-quick-actions.test.tsx",
                    "web/src/app/router.tsx",
                    "web/src/features/market/pages/market-page.test.tsx",
                    "web/src/features/settings/components/settings-page.tsx",
                    "web/src/features/settings/components/settings-page.test.tsx",
                    "web/src/features/backtest/components/dataset-snapshot-panel.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/app/layout/app-shell.tsx",
                    "web/src/app/layout/app-shell.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- market-data-status.test.ts dashboard-quick-actions.test.tsx market-page.test.tsx settings-page.test.tsx backtest-page.test.tsx app-shell.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="backend_market_data_deterministic_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover adapter "
                    "normalization, freshness"
                ),
                evidence_paths=(
                    "data/market_data.py",
                    "data/market_data_refresh.py",
                    "data/market_data_replay.py",
                    "tests/data/test_market_data_contract.py",
                    "tests/data/test_market_data_quality.py",
                    "tests/data/test_market_data_refresh.py",
                    "tests/data/test_market_data_replay.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/data/test_market_data_contract.py tests/data/test_market_data_quality.py tests/data/test_market_data_refresh.py tests/data/test_market_data_replay.py",
                ),
            ),
            AcceptanceCriterion(
                key="frontend_market_data_status_tests",
                checkbox_text=(
                    "* [x] Frontend tests cover data-status rendering, "
                    "estimated-versus-confirmed"
                ),
                evidence_paths=(
                    "web/src/shared/market-data-status.test.ts",
                    "web/src/features/overview/pages/overview-page.test.tsx",
                    "web/src/features/account/components/return-calendar-card.test.tsx",
                    "web/src/features/account/components/equity-curve-card.test.tsx",
                    "web/src/features/account/components/dashboard-quick-actions.test.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- market-data-status.test.ts overview-page.test.tsx return-calendar-card.test.tsx equity-curve-card.test.tsx dashboard-quick-actions.test.tsx backtest-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="market_data_reliability_docs",
                checkbox_text=(
                    "* [x] README/docs explain the market-data reliability "
                    "workflow and privacy"
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    'rg -n "Market Data Reliability Workflow|市场数据可靠性工作流|not investment advice|不构成投资建议|privacy|隐私" README.md docs/README.zh.md docs/README.en.md docs/ROADMAP.md',
                ),
            ),
            AcceptanceCriterion(
                key="acceptance_audit_cli_capability",
                checkbox_text=(
                    "* [x] Acceptance audit manifest and CLI include the "
                    "market-data reliability"
                ),
                evidence_paths=(
                    "analytics/acceptance_audit.py",
                    "scripts/ci/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                    "uv run python -m pytest tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/ci/export_acceptance_audit.py --audit market_data_reliability",
                ),
            ),
        )
    )


def build_single_instrument_strategy_loop_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the read-only single-instrument strategy loop."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="dataset_snapshot_and_strategy_registry",
                checkbox_text=(
                    "* [x] Dataset snapshot evidence and strategy registry are "
                    "both present in the one-symbol flow."
                ),
                evidence_paths=(
                    "strategy/registry.py",
                    "backtest/engine.py",
                    "server/routes/backtest.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_backtest_signal_preview_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="single_symbol_after_cost_backtest",
                checkbox_text=(
                    "* [x] A single-symbol after-cost backtest can feed the "
                    "preview chain without writing production trading facts."
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "backtest/engine.py",
                    "execution/commission.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_backtest_signal_preview_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="today_signal_preview",
                checkbox_text=(
                    "* [x] Today's signal preview returns standardized candidate "
                    "actions or no-action reasons as research evidence."
                ),
                evidence_paths=(
                    "analytics/strategy_signal_preview.py",
                    "server/routes/backtest.py",
                    "tests/strategy/test_signal_preview.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_signal_preview.py tests/server/test_backtest_signal_preview_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="risk_gate_preview",
                checkbox_text=(
                    "* [x] The preview path runs a read-only risk gate before "
                    "paper/shadow simulation."
                ),
                evidence_paths=(
                    "risk/pre_trade.py",
                    "server/routes/backtest.py",
                    "tests/risk/test_pre_trade.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/risk/test_pre_trade.py tests/server/test_backtest_signal_preview_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_preview",
                checkbox_text=(
                    "* [x] Paper/shadow preview simulates order and fill evidence "
                    "while remaining isolated from the real ledger."
                ),
                evidence_paths=(
                    "execution/paper_broker.py",
                    "server/routes/backtest.py",
                    "analytics/shadow_review.py",
                    "tests/execution/test_paper_broker.py",
                    "tests/analytics/test_shadow_review.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/execution/test_paper_broker.py tests/analytics/test_shadow_review.py tests/server/test_backtest_signal_preview_routes.py",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="attribution_preview_boundary",
                checkbox_text=(
                    "* [x] Attribution preview exposes evidence counts and a "
                    "manual review linkage candidate without claiming strategy P/L."
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "tests/server/test_backtest_signal_preview_routes.py",
                    "web/src/features/backtest/api.ts",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "README.md",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_backtest_signal_preview_routes.py -k attribution_preview",
                    "npm --prefix web test -- backtest-page -t 'summarizes attribution preview'",
                ),
            ),
            AcceptanceCriterion(
                key="holding_level_attribution_review_readiness",
                checkbox_text=(
                    "* [x] Portfolio holding detail exposes symbol-filtered "
                    "attribution evidence, evidence-chain refs, and "
                    "review-readiness prerequisites without claiming strategy P/L."
                ),
                evidence_paths=(
                    "server/models.py",
                    "server/routes/account_strategy.py",
                    "tests/server/test_account_strategy_routes.py",
                    "web/src/app/copy.ts",
                    "web/src/features/account-strategy/api.ts",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "web/src/shared/public-labels.ts",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_account_strategy_routes.py -k holding_strategy_attribution",
                    "npm --prefix web test -- backtest-page -t 'summarizes attribution preview evidence without claiming strategy pnl'",
                    "npm --prefix web test -- holding-detail-page -t 'holding attribution evidence|attribution review readiness'",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k single_instrument_strategy_loop",
                ),
            ),
            AcceptanceCriterion(
                key="decision_to_holding_attribution_handoff",
                checkbox_text=(
                    "* [x] Decision candidate cards link directly to "
                    "symbol-scoped holding attribution review without "
                    "creating orders or mutating the ledger."
                ),
                evidence_paths=(
                    "web/src/app/copy.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "npm --prefix web test -- decision-cockpit-page -t 'links decision candidates to holding attribution review'",
                    "npm --prefix web test -- backtest-page -t 'summarizes attribution preview evidence without claiming strategy pnl'",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k single_instrument_strategy_loop",
                ),
            ),
            AcceptanceCriterion(
                key="web_paper_shadow_attribution_boundary",
                checkbox_text=(
                    "* [x] Web Backtest explicitly explains the post-risk "
                    "paper/shadow next step and blocks strategy P/L attribution "
                    "when production fills are not linked."
                ),
                evidence_paths=(
                    "web/src/app/copy.ts",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page -t 'previews paper shadow simulation after a passed risk preview|summarizes attribution preview evidence'",
                    "uv run python -m pytest tests/test_acceptance_audit.py -k single_instrument_strategy_loop",
                    "uv run python scripts/ci/export_acceptance_audit.py --audit single_instrument_strategy_loop",
                ),
            ),
            AcceptanceCriterion(
                key="web_user_readable_loop_surface",
                checkbox_text=(
                    "* [x] Web strategy-loop surfaces use localized, "
                    "user-readable language without exposing internal reason "
                    "codes or raw evidence refs."
                ),
                evidence_paths=(
                    "web/src/app/copy.ts",
                    "web/src/app/copy.test.ts",
                    "web/src/shared/public-labels.ts",
                    "web/src/shared/public-labels.test.ts",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.tsx",
                    "web/src/features/portfolio/components/holding-detail-page.test.tsx",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page copy public-labels holding-detail-page decision-cockpit-page",
                    "npm --prefix web run format:check",
                ),
            ),
        )
    )
