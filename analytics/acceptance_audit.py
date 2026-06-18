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
                checkbox_text="* [x] README and docs make clear that Karkinos is a personal quant research and trading platform, not investment advice.",
                evidence_paths=(
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    'rg -n "not investment advice|不构成投资建议|personal quant research and trading platform|个人量化投研与交易平台" README.md docs',
                    "uv run python -m pytest",
                ),
            ),
        )
    )


def build_strategy_lab_acceptance_audit() -> AcceptanceAudit:
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


def build_research_evidence_acceptance_audit() -> AcceptanceAudit:
    """Return research evidence hardening criteria mapped to evidence."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="versioned_research_evidence_single_backtests",
                checkbox_text=(
                    "* [x] `ResearchEvidenceBundle` exists as a versioned "
                    "backend artifact and is\n  generated for single backtests."
                ),
                evidence_paths=(
                    "analytics/research_evidence.py",
                    "server/routes/backtest.py",
                    "tests/analytics/test_research_evidence.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py",
                    "uv run python -m pytest tests/test_server_routes.py -k research_evidence",
                ),
            ),
            AcceptanceCriterion(
                key="sweeps_and_comparisons_expose_bundle_contract",
                checkbox_text=(
                    "* [x] Parameter sweeps and strategy comparisons persist "
                    "and expose the same\n  evidence-bundle contract for each "
                    "constituent run."
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "server/models.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k 'backtest_sweep or backtest_compare or research_evidence'",
                ),
            ),
            AcceptanceCriterion(
                key="explicit_analyzer_contract",
                checkbox_text=(
                    "* [x] Analyzer outputs are produced through an explicit "
                    "contract rather than\n  ad hoc report fields."
                ),
                evidence_paths=(
                    "analytics/research_evidence.py",
                    "analytics/backtest_metrics.py",
                    "tests/analytics/test_research_evidence.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py",
                ),
            ),
            AcceptanceCriterion(
                key="data_quality_gate_blocks_promotion",
                checkbox_text=(
                    "* [x] Data-quality analyzer status can mark experiments "
                    "`pass`, `degraded`, or\n  `blocked`, and blocked data "
                    "prevents promotion readiness."
                ),
                evidence_paths=(
                    "analytics/research_evidence.py",
                    "analytics/strategy_promotion_readiness.py",
                    "tests/analytics/test_research_evidence.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py tests/analytics/test_strategy_promotion_readiness.py",
                ),
            ),
            AcceptanceCriterion(
                key="bundle_references_core_evidence",
                checkbox_text=(
                    "* [x] Evidence bundles reference dataset snapshot id, "
                    "strategy metadata,\n  after-cost evidence, OOS evidence, "
                    "cost summary, fills/trade statistics, and\n  limitations "
                    "when available."
                ),
                evidence_paths=(
                    "analytics/research_evidence.py",
                    "analytics/dataset_snapshot.py",
                    "analytics/backtest_metrics.py",
                    "tests/analytics/test_research_evidence.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_rolling_oos_evidence",
                checkbox_text=(
                    "* [x] Walk-forward or rolling OOS evidence can be "
                    "generated deterministically\n  for at least one strategy "
                    "fixture."
                ),
                evidence_paths=(
                    "analytics/oos_validation.py",
                    "server/routes/backtest.py",
                    "tests/analytics/test_oos_validation.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_oos_validation.py",
                    "uv run python -m pytest tests/test_server_routes.py -k rolling_oos",
                ),
            ),
            AcceptanceCriterion(
                key="parameter_sweep_robustness_evidence",
                checkbox_text=(
                    "* [x] Parameter sweep reports include stability or "
                    "sensitivity evidence and\n  overfitting warnings grounded "
                    "in the tested grid."
                ),
                evidence_paths=(
                    "analytics/sweep_robustness.py",
                    "server/routes/backtest.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k backtest_sweep",
                ),
            ),
            AcceptanceCriterion(
                key="china_market_assumptions_recorded",
                checkbox_text=(
                    "* [x] China-market assumptions are recorded in each "
                    "evidence bundle, including\n  which assumptions are "
                    "modeled and which are known gaps."
                ),
                evidence_paths=(
                    "analytics/research_evidence.py",
                    "docs/return-accounting.zh.md",
                    "tests/analytics/test_research_evidence.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_readiness_consumes_evidence_gate",
                checkbox_text=(
                    "* [x] Strategy promotion readiness consumes "
                    "evidence-bundle gate status and\n  cannot mark a strategy "
                    "ready when required evidence is missing or blocked."
                ),
                evidence_paths=(
                    "analytics/strategy_promotion_readiness.py",
                    "analytics/research_evidence.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_strategy_promotion_readiness.py",
                ),
            ),
            AcceptanceCriterion(
                key="api_and_reports_do_not_enable_execution",
                checkbox_text=(
                    "* [x] API and saved report files expose the evidence "
                    "bundle without changing\n  live-like execution defaults "
                    "or enabling automatic real-money trading."
                ),
                evidence_paths=(
                    "server/routes/backtest.py",
                    "server/models.py",
                    "analytics/report.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_server_routes.py -k research_evidence",
                    "uv run python -m pytest tests/server/test_trading_controls.py",
                ),
            ),
            AcceptanceCriterion(
                key="backend_deterministic_research_evidence_tests",
                checkbox_text=(
                    "* [x] Backend deterministic tests cover bundle "
                    "generation, analyzer contract,\n  data-quality "
                    "degraded/blocked states, and promotion-gate consumption."
                ),
                evidence_paths=(
                    "tests/analytics/test_research_evidence.py",
                    "tests/analytics/test_strategy_promotion_readiness.py",
                    "tests/test_server_routes.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/analytics/test_research_evidence.py tests/analytics/test_strategy_promotion_readiness.py",
                    "uv run python -m pytest",
                ),
            ),
            AcceptanceCriterion(
                key="docs_explain_research_evidence_boundary",
                checkbox_text=(
                    "* [x] README/docs explain how to interpret the evidence "
                    "bundle and keep it as\n  research evidence rather than "
                    "investment advice."
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    'rg -n "research_evidence_bundle|研究证据包|not investment advice|不是投资建议" README.md docs',
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                ),
            ),
        )
    )


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
