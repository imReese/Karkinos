"""Static acceptance evidence manifests.

This module does not promote strategies or execute trades. It records local
evidence files and commands that prove product acceptance criteria for review
and CI checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AcceptanceCriterion:
    key: str
    checkbox_text: str
    evidence_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    is_complete: bool = True

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "checkbox_text": self.checkbox_text,
            "evidence_paths": list(self.evidence_paths),
            "validation_commands": list(self.validation_commands),
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True)
class AcceptanceAudit:
    criteria: tuple[AcceptanceCriterion, ...]

    @property
    def required_count(self) -> int:
        return len(self.criteria)

    @property
    def completed_count(self) -> int:
        return sum(1 for criterion in self.criteria if criterion.is_complete)

    @property
    def is_complete(self) -> bool:
        return self.required_count > 0 and self.completed_count == self.required_count

    @property
    def limitations(self) -> list[str]:
        return [
            "Acceptance evidence is product-readiness proof, not investment advice.",
            "Completion does not enable automatic real-money trading; manual confirmation remains the live-like default.",
            "Evidence relies on deterministic fixtures, local tests, and documented API contracts rather than private account data.",
        ]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "required_count": self.required_count,
            "completed_count": self.completed_count,
            "is_complete": self.is_complete,
            "criteria": [criterion.to_json_dict() for criterion in self.criteria],
            "limitations": self.limitations,
        }


def build_acceptance_audit() -> AcceptanceAudit:
    """Return the v0.2 acceptance criteria mapped to deterministic evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="end_to_end_workflow",
                checkbox_text="* [x] One reproducible end-to-end workflow: data fetch/cache → features → backtest → report → signal → risk gate → dashboard/journal.",
                evidence_paths=(
                    "tests/test_profit_discipline_smoke.py",
                    "analytics/report.py",
                    "server/db.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_profit_discipline_smoke.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="three_benchmarkable_strategies",
                checkbox_text="* [x] At least three benchmarkable strategies:",
                evidence_paths=(
                    "strategy/registry.py",
                    "analytics/benchmark_fixtures.py",
                    "tests/strategy/test_registry_metadata.py",
                    "tests/analytics/test_benchmark_fixtures.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_registry_metadata.py tests/analytics/test_benchmark_fixtures.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="etf_rotation_trend_following",
                checkbox_text="  * [x] ETF rotation / trend-following baseline",
                evidence_paths=("strategy/registry.py",),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_registry_metadata.py",
                ),
            ),
            AcceptanceCriterion(
                key="defensive_allocation_baseline",
                checkbox_text="  * [x] Defensive allocation baseline: equity ETF + bond/gold/cash proxy",
                evidence_paths=("strategy/registry.py",),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_registry_metadata.py",
                ),
            ),
            AcceptanceCriterion(
                key="mean_reversion_or_momentum_candidate",
                checkbox_text="  * [x] A-share/ETF mean-reversion or momentum candidate",
                evidence_paths=("strategy/registry.py",),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_registry_metadata.py",
                ),
            ),
            AcceptanceCriterion(
                key="oos_after_cost_reports",
                checkbox_text="* [x] Each strategy has out-of-sample validation and after-cost report.",
                evidence_paths=(
                    "analytics/oos_validation.py",
                    "analytics/strategy_validation_matrix.py",
                    "tests/analytics/test_oos_validation.py",
                    "tests/analytics/test_strategy_validation_matrix.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_oos_validation.py tests/analytics/test_strategy_validation_matrix.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="portfolio_dashboard_action_queue",
                checkbox_text="* [x] Portfolio dashboard exposes target weights, actual weights, drift, action queue, and risk alerts.",
                evidence_paths=(
                    "server/routes/portfolio.py",
                    "server/models.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py::test_portfolio_cockpit_returns_targets_drift_actions_and_risk_alerts",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="signal_journal_all_decisions",
                checkbox_text="* [x] Signal journal stores every generated signal, whether acted on or ignored.",
                evidence_paths=(
                    "server/db.py",
                    "server/routes/signals.py",
                    "tests/server/test_signal_journal_routes.py",
                    "tests/server/test_trading_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_signal_journal_routes.py tests/server/test_trading_routes.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="mandatory_pre_trade_risk_gate",
                checkbox_text="* [x] Pre-trade risk gate is mandatory for every actionable signal.",
                evidence_paths=(
                    "risk/pre_trade.py",
                    "server/db.py",
                    "tests/test_profit_discipline_smoke.py",
                    "tests/server/test_trading_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_profit_discipline_smoke.py tests/server/test_trading_routes.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="manual_confirm_execution_path",
                checkbox_text="* [x] Manual-confirm execution path is complete.",
                evidence_paths=(
                    "execution/gateway.py",
                    "server/routes/trading.py",
                    "tests/execution/test_gateway.py",
                    "tests/server/test_trading_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/execution/test_gateway.py tests/server/test_trading_routes.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_daily",
                checkbox_text="* [x] Paper/shadow mode can run daily without manual data edits.",
                evidence_paths=(
                    "server/routes/trading.py",
                    "analytics/strategy_promotion_readiness.py",
                    "tests/server/test_trading_routes.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/server/test_trading_routes.py tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="ci_backend_frontend_smoke",
                checkbox_text="* [x] CI runs backend tests, frontend checks, and at least one deterministic smoke path.",
                evidence_paths=(
                    ".github/workflows/ci.yml",
                    "web/package.json",
                    "tests/test_ci_workflow.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_ci_workflow.py",
                    "npm --prefix web run format:check",
                    "npm --prefix web run build",
                    "npm --prefix web run test",
                ),
            ),
            AcceptanceCriterion(
                key="research_tooling_not_advice_docs",
                checkbox_text="* [x] README and docs make clear that Karkinos is research and portfolio tooling, not investment advice.",
                evidence_paths=(
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    'rg -n "not investment advice|不构成投资建议|research and portfolio tooling" README.md docs',
                    "uv run python -m pytest",
                ),
            ),
        )
    )


def build_v04_strategy_lab_acceptance_audit() -> AcceptanceAudit:
    """Return v0.4 Strategy Lab criteria mapped to deterministic evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="documented_extension_area",
                checkbox_text=(
                    "* [x] A documented `strategy/extensions/` or equivalent local "
                    "extension area"
                ),
                evidence_paths=(
                    "strategy/extensions/README.md",
                    "strategy/extensions/.gitignore",
                    "strategy/extensions/examples/local_momentum.py.example",
                    "strategy/extensions/examples/local_momentum.strategy.json.example",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_extension_strategy_registry.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="shared_typed_metadata_contract",
                checkbox_text=(
                    "* [x] Built-in and extension strategies share one typed metadata "
                    "contract:"
                ),
                evidence_paths=(
                    "strategy/schema.py",
                    "strategy/registry.py",
                    "tests/strategy/test_strategy_parameter_schema.py",
                    "tests/strategy/test_extension_strategy_registry.py",
                    "tests/strategy/test_registry_metadata.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_strategy_parameter_schema.py tests/strategy/test_extension_strategy_registry.py tests/strategy/test_registry_metadata.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="strategies_api_typed_schemas",
                checkbox_text=(
                    "* [x] `/api/backtest/strategies` returns typed strategy "
                    "parameter schemas for"
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "server/models.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k 'backtest_strategies_route'",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="backtest_run_generic_params_persisted",
                checkbox_text=(
                    "* [x] `POST /api/backtest/run` accepts generic strategy "
                    "parameters and records"
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "server/bootstrap.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k 'generic_params or unknown_generic_params'",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="web_backtest_registry_one_symbol",
                checkbox_text=(
                    "* [x] The Web Backtest page uses the strategy registry instead "
                    "of a free-text"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/backtest/api.ts",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page",
                    "npm --prefix web run build",
                ),
            ),
            AcceptanceCriterion(
                key="custom_extension_web_api_run",
                checkbox_text=(
                    "* [x] At least one custom extension strategy can be added "
                    "locally, discovered"
                ),
                evidence_paths=(
                    "strategy/extensions/examples/local_momentum.py.example",
                    "strategy/extensions/examples/local_momentum.strategy.json.example",
                    "tests/strategy/test_extension_strategy_registry.py",
                    "tests/test_server_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/strategy/test_extension_strategy_registry.py tests/test_server_routes.py -k 'extension_strategy or local_extension'",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="dataset_snapshot_metadata",
                checkbox_text=(
                    "* [x] Backtest runs record frozen dataset identity, "
                    "provider/cache metadata,"
                ),
                evidence_paths=(
                    "analytics/dataset_snapshot.py",
                    "server/routes/backtest.py",
                    "web/src/features/backtest/components/dataset-snapshot-panel.tsx",
                    "tests/test_server_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k dataset_snapshot",
                    "npm --prefix web test -- backtest-page",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="after_cost_oos_reports_api_web",
                checkbox_text=(
                    "* [x] Backtest reports expose after-cost metrics, cost "
                    "assumptions, slippage"
                ),
                evidence_paths=(
                    "analytics/backtest_metrics.py",
                    "analytics/oos_validation.py",
                    "server/routes/backtest.py",
                    "web/src/features/backtest/components/validation-evidence-panel.tsx",
                    "web/src/features/backtest/components/fills-table.tsx",
                    "web/src/features/backtest/components/equity-drawdown-chart.tsx",
                    "tests/analytics/test_backtest_metrics.py",
                    "tests/analytics/test_oos_validation.py",
                    "tests/test_server_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_backtest_metrics.py tests/analytics/test_oos_validation.py tests/test_server_routes.py -k 'after_cost or oos or backtest_run_returns_metrics_json'",
                    "npm --prefix web test -- backtest-page",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="bounded_parameter_sweep",
                checkbox_text=(
                    "* [x] Parameter sweep runs support bounded grids, persist each "
                    "tested"
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "web/src/features/backtest/components/parameter-sweep-panel.tsx",
                    "tests/test_server_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k backtest_sweep",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="same_dataset_strategy_comparison",
                checkbox_text=(
                    "* [x] Strategy comparison can compare multiple strategies or "
                    "parameter sets on"
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "web/src/features/backtest/components/parameter-compare-panel.tsx",
                    "tests/test_server_routes.py",
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k backtest_compare",
                    "npm --prefix web test -- backtest-page",
                ),
            ),
            AcceptanceCriterion(
                key="research_only_promotion_boundaries",
                checkbox_text=(
                    "* [x] Strategy outputs can be promoted only as research "
                    "evidence; they cannot"
                ),
                evidence_paths=(
                    "analytics/strategy_promotion_readiness.py",
                    "server/routes/backtest.py",
                    "server/routes/trading.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                    "tests/test_server_routes.py",
                    "README.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_strategy_promotion_readiness.py tests/test_server_routes.py -k 'promotion_readiness or backtest_strategy_promotion'",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="backend_deterministic_strategy_lab_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover built-in strategy run, "
                    "extension"
                ),
                evidence_paths=(
                    "tests/test_bootstrap.py",
                    "tests/test_server_routes.py",
                    "tests/strategy/test_extension_strategy_registry.py",
                    "tests/strategy/test_strategy_parameter_schema.py",
                    "tests/analytics/test_backtest_metrics.py",
                    "tests/analytics/test_oos_validation.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_bootstrap.py tests/test_server_routes.py tests/strategy/test_extension_strategy_registry.py tests/strategy/test_strategy_parameter_schema.py tests/analytics/test_backtest_metrics.py tests/analytics/test_oos_validation.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="frontend_strategy_lab_tests",
                checkbox_text=(
                    "* [x] Frontend tests cover strategy selection, dynamic "
                    "parameter controls,"
                ),
                evidence_paths=(
                    "web/src/features/backtest/components/backtest-page.test.tsx",
                    "web/src/features/backtest/components/backtest-page.tsx",
                    "web/src/features/backtest/components/parameter-sweep-panel.tsx",
                    "web/src/features/backtest/components/backtest-report-view.tsx",
                ),
                validation_commands=(
                    "npm --prefix web test -- backtest-page",
                    "npm --prefix web run test",
                ),
            ),
            AcceptanceCriterion(
                key="strategy_lab_docs",
                checkbox_text=(
                    "* [x] README and Chinese docs explain how to add a local "
                    "strategy, run it from"
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "strategy/extensions/README.md",
                ),
                validation_commands=(
                    'rg -n "Strategy Extensions|本地扩展策略|research evidence|不构成投资建议" README.md docs strategy/extensions/README.md',
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                ),
            ),
        )
    )
