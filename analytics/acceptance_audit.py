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
                    "strategy/extensions/template.py.example",
                    "strategy/extensions/template.strategy.json.example",
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
                    "strategy/extensions/template.py.example",
                    "strategy/extensions/template.strategy.json.example",
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
                    "web/src/app/overview-page.test.tsx",
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
                    "scripts/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/export_acceptance_audit.py --audit strategy_assignment",
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
                    "web/src/app/return-calendar-card.test.tsx",
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
                    "web/src/app/market-page.test.tsx",
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
                    "web/src/app/overview-page.test.tsx",
                    "web/src/app/return-calendar-card.test.tsx",
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
                    "scripts/export_acceptance_audit.py",
                    "tests/test_acceptance_audit.py",
                    "tests/test_acceptance_audit_cli.py",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_acceptance_audit.py",
                    "uv run python -m pytest tests/test_acceptance_audit_cli.py",
                    "uv run python scripts/export_acceptance_audit.py --audit market_data_reliability",
                ),
            ),
        )
    )


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
                    "web/src/app/overview-page.test.tsx",
                    "web/src/app/risk-page.test.tsx",
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
                    "web/src/app/overview-page.test.tsx",
                    "web/src/app/risk-page.test.tsx",
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
                    "web/src/app/activity-page.test.tsx",
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
                    "uv run python scripts/export_acceptance_audit.py --audit single_instrument_strategy_loop",
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
