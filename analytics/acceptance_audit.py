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


def build_operations_runbook_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for completed Operations and paper/shadow runbook pieces."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="operations_today_runbook",
                checkbox_text=(
                    "* [x] `/api/operations/today` exposes subsystem health, "
                    "last run, next action, limitations, and paper/shadow "
                    "summary evidence without mutating trading state."
                ),
                evidence_paths=(
                    "server/services/operations_today.py",
                    "server/routes/operations.py",
                    "tests/test_operations_today.py",
                    "tests/server/test_operations_routes.py",
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operations_today.py tests/server/test_operations_routes.py",
                    "npm --prefix web test -- overview-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="scheduler_run_persistence",
                checkbox_text=(
                    "* [x] Scheduler runs record ids, input snapshots, "
                    "fingerprints, idempotency keys, errors, retry state, and "
                    "limitations for runbook review."
                ),
                evidence_paths=(
                    "server/services/market_session_automation.py",
                    "server/services/automation_control.py",
                    "tests/test_market_session_automation.py",
                    "tests/test_automation_control.py",
                    "tests/server/test_automation_routes.py",
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_market_session_automation.py tests/test_automation_control.py tests/server/test_automation_routes.py",
                    'npm --prefix web test -- overview-page.test.tsx -t "failed scheduler run recovery"',
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_run_storage",
                checkbox_text=(
                    "* [x] Paper/shadow runs persist run ids, plan dates, "
                    "fingerprints, counts, evidence refs, limitations, and "
                    "payloads for deterministic review."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/paper_shadow_run.py",
                    "tests/test_paper_shadow_runs.py",
                    "tests/test_paper_shadow_run_service.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_paper_shadow_runs.py tests/test_paper_shadow_run_service.py",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_oms_state_machine",
                checkbox_text=(
                    "* [x] Paper/shadow OMS records use explicit lifecycle "
                    "states and record accepted transitions with timestamp, "
                    "reason, source, and evidence payloads."
                ),
                evidence_paths=(
                    "server/services/oms.py",
                    "server/services/paper_shadow_run.py",
                    "tests/test_oms_service.py",
                    "tests/test_paper_shadow_run_service.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_oms_service.py tests/test_paper_shadow_run_service.py",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_simulation_outcomes",
                checkbox_text=(
                    "* [x] Paper/shadow simulation covers filled, partial, "
                    "rejected, cancelled, expired, failed, fee/tax projection, "
                    "idempotent rerun evidence, OMS transition refs in both "
                    "run and simulated order payloads, simulated fill "
                    "intent/evidence refs, and terminal reason review evidence "
                    "without production ledger mutation."
                ),
                evidence_paths=(
                    "execution/paper_broker.py",
                    "server/services/paper_shadow_run.py",
                    "tests/execution/test_paper_broker.py",
                    "tests/test_paper_shadow_run_service.py",
                ),
                validation_commands=(
                    "uv run pytest tests/execution/test_paper_broker.py tests/test_paper_shadow_run_service.py",
                    "uv run python -m pytest tests/test_paper_shadow_run_service.py -k cancelled_and_expired",
                    "uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_creates_simulated_order_and_fill_without_ledger_mutation -q",
                    "uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_records_failed_run_when_simulation_errors -q",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_run_review_outcomes",
                checkbox_text=(
                    "* [x] Paper/shadow run-level operator reviews are stored "
                    "as audit evidence while preserving raw divergence status "
                    "and exposing a runbook effective status, while keeping "
                    "broker submission disabled."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/routes/operations.py",
                    "server/services/operations_today.py",
                    "tests/test_paper_shadow_runs.py",
                    "tests/test_operations_today.py",
                    "tests/server/test_operations_routes.py",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_paper_shadow_runs.py tests/test_operations_today.py tests/server/test_operations_routes.py",
                    "npm --prefix web test -- trading-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_rich_divergence_report",
                checkbox_text=(
                    "* [x] Paper/shadow divergence summaries compare expected "
                    "strategy behavior, simulated execution, current account "
                    "truth, realized market context, cost evidence, and "
                    "explicit non-submission safety evidence, and persisted "
                    "runs expose structured operator review queues for "
                    "diverged, failed, or missing simulations in Operations, "
                    "Decision, and Overview."
                ),
                evidence_paths=(
                    "server/services/paper_shadow_run.py",
                    "server/services/operations_today.py",
                    "tests/test_paper_shadow_run_service.py",
                    "tests/test_operations_today.py",
                    "tests/server/test_operations_routes.py",
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_paper_shadow_run_service.py",
                    "uv run pytest tests/test_operations_today.py",
                    "uv run pytest tests/server/test_operations_routes.py -k paper_shadow",
                    "npm --prefix web test -- overview-page.test.tsx decision-cockpit-page.test.tsx trading-page.test.tsx",
                    "npm --prefix web run build",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_fallback_review_queue",
                checkbox_text=(
                    "* [x] Operations Today preserves operator review work "
                    "for legacy or partial paper/shadow runs by synthesizing "
                    "read-only review-queue evidence, OMS status paths, and "
                    "transition refs for diverged, failed, or missing "
                    "simulations without broker submission or "
                    "production-ledger mutation."
                ),
                evidence_paths=(
                    "server/services/operations_today.py",
                    "tests/test_operations_today.py",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    'uv run python -m pytest tests/test_operations_today.py -k "legacy_diverged_run or legacy_review_queue or missing_simulation"',
                    "uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_manual_handoff_gate",
                checkbox_text=(
                    "* [x] Operations, Decision, and Overview expose an "
                    "explicit paper/shadow manual-confirmation handoff gate "
                    "with readiness, blockers, review metadata, review-queue "
                    "count, and no-broker/no-ledger-mutation safety evidence."
                ),
                evidence_paths=(
                    "server/services/operations_today.py",
                    "tests/test_operations_today.py",
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    'uv run python -m pytest tests/test_operations_today.py -k "manual_handoff or accepted_shadow_divergence"',
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual handoff gate"',
                    'npm --prefix web test -- overview-page.test.tsx -t "accepted paper shadow review"',
                ),
            ),
            AcceptanceCriterion(
                key="frontend_paper_shadow_next_actions",
                checkbox_text=(
                    "* [x] Decision, Overview, and Trading surfaces show "
                    "paper/shadow next actions and structured review-queue "
                    "summaries for not-run, running, failed, diverged, "
                    "accepted-review, and within-expectations states without "
                    "exposing raw state-machine internals; input snapshot "
                    "summaries and terminal reasons are rendered as public "
                    "review evidence, and accepted reviews display as "
                    "manual-confirmation handoffs."
                ),
                evidence_paths=(
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                    "web/src/features/operations/api.ts",
                ),
                validation_commands=(
                    "npm --prefix web test -- overview-page.test.tsx decision-cockpit-page.test.tsx trading-page.test.tsx",
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "paper shadow review queue"',
                    'npm --prefix web test -- overview-page.test.tsx -t "divergence evidence summary"',
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "terminal paper shadow review reasons"',
                    'npm --prefix web test -- overview-page.test.tsx -t "terminal paper shadow review reasons"',
                    'npm --prefix web test -- trading-page.test.tsx -t "terminal paper shadow review reasons"',
                    'npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"',
                ),
            ),
            AcceptanceCriterion(
                key="automation_run_failure_alerts",
                checkbox_text=(
                    "* [x] Failed paper/shadow automation runs generate "
                    "acknowledgeable operations alerts with input snapshots, "
                    "rerun keys, retry context, limitations, and explicit "
                    "non-submission safety evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/services/automation_cockpit.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "uv run python -m pytest tests/test_automation_alerts.py::test_alert_scan_records_failed_paper_shadow_automation_run -q",
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "failed paper shadow automation recovery"',
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="connector_health_alerts",
                checkbox_text=(
                    "* [x] Incomplete read-only broker connector health "
                    "generates acknowledgeable operations alerts that preserve "
                    "capability scope, read/query capability flags, explicit "
                    "preview/export/dry-run/cancel/submit blockers, "
                    "credential-storage status, and non-submission evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/services/broker_gateway.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="runtime_connector_degradation_alerts",
                checkbox_text=(
                    "* [x] Runtime-degraded read-only broker connector "
                    "snapshots are polled through the broker-gateway health "
                    "contract, local JSON export adapters can provide runtime "
                    "read-only snapshots, and degraded snapshots generate "
                    "acknowledgeable operations alerts with heartbeat/error "
                    "context, capability scope, read/query capability flags, "
                    "explicit preview/export/dry-run/cancel/submit blockers, "
                    "manual-review requirement, and explicit non-submission "
                    "evidence."
                ),
                evidence_paths=(
                    "account_truth/broker_connector.py",
                    "server/services/broker_connector_runtime.py",
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/routes/broker_gateway.py",
                    "server/services/broker_gateway.py",
                    "tests/account_truth/test_broker_connector.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/account_truth/test_broker_connector.py tests/server/test_broker_gateway_routes.py",
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="daily_plan_risk_blocker_alerts",
                checkbox_text=(
                    "* [x] Daily trading-plan risk blockers generate "
                    "acknowledgeable operations alerts with blocker counts, "
                    "risk reasons, manual-review requirement, and explicit "
                    "non-submission evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/services/daily_trading_plan.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "tests/test_daily_trading_plan.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py tests/test_daily_trading_plan.py",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="stale_market_data_alerts",
                checkbox_text=(
                    "* [x] Stale market-data health snapshots generate "
                    "acknowledgeable operations alerts with source health, "
                    "stale-symbol samples, next action, manual-review "
                    "requirement, and explicit non-submission evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/routes/market.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "tests/test_server_routes.py",
                    "web/src/features/market/api.ts",
                    "web/src/features/operations/api.ts",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "uv run pytest tests/test_server_routes.py -k market_data_health",
                ),
            ),
            AcceptanceCriterion(
                key="account_truth_mismatch_alerts",
                checkbox_text=(
                    "* [x] Degraded or blocked Account Truth snapshots "
                    "generate acknowledgeable operations alerts with gate "
                    "status, mismatch counts, review actions, manual-review "
                    "requirement, and explicit non-submission/non-ledger "
                    "mutation evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "account_truth/score.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "tests/account_truth/test_account_truth_score.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "uv run pytest tests/account_truth/test_account_truth_score.py",
                ),
            ),
            AcceptanceCriterion(
                key="paper_shadow_order_divergence_alerts",
                checkbox_text=(
                    "* [x] Paper/shadow diverged or review-required runs "
                    "generate acknowledgeable operations alerts with run id, "
                    "order/fill counts, divergence counts, next review step, "
                    "evidence refs, and explicit non-submission/non-ledger "
                    "mutation evidence."
                ),
                evidence_paths=(
                    "server/services/automation_alerts.py",
                    "server/routes/automation.py",
                    "server/services/paper_shadow_run.py",
                    "tests/test_automation_alerts.py",
                    "tests/server/test_automation_routes.py",
                    "tests/test_paper_shadow_run_service.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_alerts.py tests/server/test_automation_routes.py",
                    "uv run pytest tests/test_paper_shadow_run_service.py",
                ),
            ),
            AcceptanceCriterion(
                key="operations_source_control_hygiene",
                checkbox_text=(
                    "* [x] CI repository hygiene blocks tracked runtime "
                    "databases, logs, exports, screenshots, generated "
                    "reports, local secrets, and agent/plugin state from "
                    "source control."
                ),
                evidence_paths=(
                    ".github/workflows/ci.yml",
                    ".gitignore",
                    "tests/test_ci_workflow.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run python -m pytest tests/test_ci_workflow.py -k repository_hygiene",
                    "git ls-files reports data/store logs exports screenshots",
                ),
            ),
            AcceptanceCriterion(
                key="simulation_evidence_safety_docs",
                checkbox_text=(
                    "* [x] README, architecture, roadmap, and implementation "
                    "log keep the boundary explicit: paper/shadow records are "
                    "simulation evidence and do not submit broker orders."
                ),
                evidence_paths=(
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "docs/ARCHITECTURE.md",
                    "docs/ROADMAP.md",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    'rg -n "paper/shadow|simulation evidence|does not submit|不会提交券商订单" README.md docs',
                    "uv run pytest tests/test_acceptance_audit.py -k operations_runbook",
                ),
            ),
        )
    )


def build_controlled_broker_bridge_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for completed non-submitting broker bridge foundations."""
    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="broker_submission_disabled_default",
                checkbox_text=(
                    "* [x] Broker submission remains disabled by default and "
                    "the live gateway advertises no submit, cancel, preview, "
                    "dry-run, or export authority."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "docs/ARCHITECTURE.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                ),
            ),
            AcceptanceCriterion(
                key="controlled_bridge_policy_whitelist",
                checkbox_text=(
                    "* [x] Controlled broker bridge status exposes a "
                    "non-submitting policy skeleton with explicit connector, "
                    "account, strategy, and symbol whitelists plus required "
                    "gate names before any future live bridge can be enabled; "
                    "Decision Cockpit renders it as read-only evidence."
                ),
                evidence_paths=(
                    "config.example.json",
                    "server/config.py",
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_bootstrap.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "docs/config-reference.zh.md",
                    "docs/ARCHITECTURE.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_bootstrap.py -k controlled_bridge_policy",
                    "uv run pytest tests/test_broker_gateway_service.py -k controlled_bridge_policy",
                    "uv run pytest tests/server/test_broker_gateway_routes.py -k controlled_bridge_policy",
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "controlled bridge policy"',
                ),
            ),
            AcceptanceCriterion(
                key="manual_ticket_preview_export_dry_run",
                checkbox_text=(
                    "* [x] Manual-ticket preview, export, dry-run, and create "
                    "paths are non-submitting, require human broker entry, and "
                    "keep preview/export read-only while preserving the "
                    "controlled-bridge policy snapshot plus account-truth, "
                    "research-evidence, risk, paper/shadow, and manual-"
                    "confirmation gate evidence for audit."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/trading/api.ts",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                    "uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_gateway_creates_ticket_without_broker_submission tests/server/test_broker_gateway_routes.py::test_manual_ticket_route_returns_copyable_ticket -q",
                    "uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_preview_is_dry_run_and_does_not_mutate_oms tests/test_broker_gateway_service.py::test_manual_ticket_export_is_read_only_and_copy_safe tests/test_broker_gateway_service.py::test_manual_ticket_dry_run_records_accepted_event_without_oms_mutation -q",
                    "uv run python -m pytest tests/server/test_broker_gateway_routes.py::test_manual_ticket_preview_route_is_read_only -q",
                    'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
                    "npm --prefix web test -- trading-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="manual_execution_operator_form_context",
                checkbox_text=(
                    "* [x] Manual-ticket export surfaces an operator form with "
                    "user-readable field labels, account alias, fee/tax "
                    "assumptions, net cash impact, remaining-position/cost-basis "
                    "preview, trading-session constraints, and explicit "
                    "non-submission safety flags."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/trading/api.ts",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py -k manual_ticket_export_is_read_only_and_copy_safe",
                    "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_ticket_export_route_is_read_only",
                    'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
                ),
            ),
            AcceptanceCriterion(
                key="manual_execution_preview_draft",
                checkbox_text=(
                    "* [x] Manual execution preview calculates an "
                    "operator-entered fill, fee/tax/transfer-fee cost, net "
                    "cash impact, position/cost context, and production-ledger "
                    "draft plus a deterministic preview fingerprint after "
                    "manual-ticket creation without writing ledger entries, "
                    "changing OMS status, contacting a broker, or submitting "
                    "orders."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/trading/api.ts",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "docs/ROADMAP.md",
                    "docs/ROADMAP.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py -k manual_execution_preview",
                    "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_execution_preview",
                    'npm --prefix web test -- trading-page.test.tsx -t "previews manual execution draft"',
                ),
            ),
            AcceptanceCriterion(
                key="manual_execution_evidence_record",
                checkbox_text=(
                    "* [x] Manual execution evidence can be recorded only "
                    "after manual-ticket creation with a matching deterministic "
                    "preview fingerprint, and it writes a broker-gateway audit "
                    "event without creating fills, changing OMS status, "
                    "writing production ledger entries, contacting a broker, "
                    "or submitting orders."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "docs/ROADMAP.md",
                    "docs/ROADMAP.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py -k manual_execution_evidence",
                    "uv run pytest tests/server/test_broker_gateway_routes.py -k manual_execution_record",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_capability_health_contract",
                checkbox_text=(
                    "* [x] Gateway and connector health contracts expose "
                    "read, query, preview, dry-run, export, cancel, and submit "
                    "capabilities in API and Decision Cockpit without exposing "
                    "credentials."
                ),
                evidence_paths=(
                    "server/config.py",
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_evidence_and_kill_switch_gates",
                checkbox_text=(
                    "* [x] Live-like manual-ticket actions require account "
                    "truth, research evidence, risk, paper/shadow, manual "
                    "confirmation, and a clear global kill switch."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/services/trading_controls.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="staged_account_facts_and_order_query",
                checkbox_text=(
                    "* [x] Gateway account-facts, fill-query, runtime "
                    "read-only connector snapshot query, and order-query "
                    "paths read local OMS, gateway audit, staged broker "
                    "evidence, or runtime connector evidence only without "
                    "broker write contact, credential storage, account-id "
                    "leakage, gateway-event creation, OMS mutation, ledger "
                    "mutation, or order submission, and Automation/Decision "
                    "Cockpit surface the runtime snapshot as compact "
                    "read-only review evidence."
                ),
                evidence_paths=(
                    "account_truth/broker_evidence.py",
                    "account_truth/broker_connector.py",
                    "server/services/automation_cockpit.py",
                    "server/services/broker_gateway.py",
                    "server/routes/automation.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_automation_cockpit.py",
                    "tests/server/test_automation_routes.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_automation_cockpit.py tests/server/test_automation_routes.py -k runtime_connector_snapshot",
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py -k 'account_facts or query or connector_snapshot'",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="decision_cockpit_strategy_promotion_state",
                checkbox_text=(
                    "* [x] Decision Cockpit shows strategy promotion state, "
                    "paper/shadow gate status, missing requirements, audit-only "
                    "pause/retire lifecycle evidence, controlled-bridge-pilot "
                    "rejection, and the live-like disabled boundary as read-only "
                    "evidence."
                ),
                evidence_paths=(
                    "server/services/strategy_promotion_pipeline.py",
                    "server/routes/strategy_promotion.py",
                    "server/services/automation_cockpit.py",
                    "tests/test_strategy_promotion_pipeline.py",
                    "tests/server/test_strategy_promotion_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "docs/README.zh.md",
                    "docs/README.en.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_strategy_promotion_pipeline.py tests/server/test_strategy_promotion_routes.py -k 'lifecycle or controlled_bridge or promotes_ready_strategy'",
                    "npm --prefix web test -- decision-cockpit-page.test.tsx -t 'strategy promotion'",
                ),
            ),
            AcceptanceCriterion(
                key="default_rejected_cancel_audit",
                checkbox_text=(
                    "* [x] Broker cancellation is rejected by default without "
                    "broker contact, while recording an auditable gateway event "
                    "and leaving OMS state unchanged."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/routes/broker_gateway.py",
                    "tests/test_broker_gateway_service.py",
                    "tests/server/test_broker_gateway_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_gateway_service.py tests/server/test_broker_gateway_routes.py",
                ),
            ),
            AcceptanceCriterion(
                key="execution_reconciliation_bridge_evidence",
                checkbox_text=(
                    "* [x] Execution reconciliation compares OMS orders, "
                    "gateway events, staged broker trade evidence, and "
                    "broker fee/tax/net-amount evidence before suggesting any "
                    "review action. Staged broker cost summaries explicitly "
                    "require reconciliation before ledger updates, avoid "
                    "automatic ledger-update recommendations, and mutate no "
                    "ledger facts; Decision Cockpit surfaces the same cost "
                    "evidence for operator review."
                ),
                evidence_paths=(
                    "server/db.py",
                    "server/services/operations_today.py",
                    "server/services/execution_reconciliation.py",
                    "server/routes/operations.py",
                    "server/routes/execution_reconciliation.py",
                    "tests/test_operations_today.py",
                    "tests/test_execution_reconciliation_service.py",
                    "tests/server/test_operations_routes.py",
                    "tests/server/test_execution_reconciliation_routes.py",
                    "web/src/app/router.tsx",
                    "web/src/app/overview-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                ),
                validation_commands=(
                    "uv run pytest tests/test_operations_today.py -k manual_execution_reconciliation_review",
                    "uv run pytest tests/server/test_operations_routes.py -k execution_reconciliation_open_items",
                    "uv run pytest tests/test_execution_reconciliation_service.py tests/server/test_execution_reconciliation_routes.py",
                    'npm --prefix web test -- overview-page.test.tsx -t "manual execution reconciliation review"',
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                ),
            ),
            AcceptanceCriterion(
                key="manual_ticket_to_reconciliation_audit_chain",
                checkbox_text=(
                    "* [x] A deterministic non-submitting audit chain links "
                    "manual confirmation, manual-ticket creation, manual "
                    "execution evidence, staged broker-statement evidence, "
                    "and execution reconciliation. Reconciliation compares "
                    "manual price/cost/net evidence with matching broker "
                    "facts, queues mismatches for review, and preserves OMS "
                    "and production-ledger state; Trading links operators to "
                    "broker-statement import and reconciliation review, and "
                    "Decision renders the compared values without execution "
                    "controls."
                ),
                evidence_paths=(
                    "server/services/broker_gateway.py",
                    "server/services/execution_reconciliation.py",
                    "account_truth/broker_evidence.py",
                    "account_truth/broker_statement.py",
                    "tests/test_execution_reconciliation_service.py",
                    "web/src/features/trading/components/trading-page.tsx",
                    "web/src/features/trading/components/trading-page.test.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                    "docs/ARCHITECTURE.md",
                    "docs/ROADMAP.md",
                    "docs/ROADMAP.zh.md",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_reconciliation_service.py -k 'audit_chain or cost_mismatch'",
                    'npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"',
                    'npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual versus broker reconciliation differences"',
                    'rg -n "manual execution|手工成交|manual-ticket|手工票据" README.md docs',
                ),
            ),
            AcceptanceCriterion(
                key="strategy_broker_boundary_static_guard",
                checkbox_text=(
                    "* [x] Strategy code has no broker adapter access; all "
                    "bridge actions go through policy, risk, OMS, gateway, "
                    "and reconciliation services, with a deterministic static "
                    "guard covering the current strategy tree."
                ),
                evidence_paths=(
                    "analytics/strategy_broker_boundary.py",
                    "tests/test_strategy_broker_boundary.py",
                    "strategy/runtime.py",
                    "strategy/extensions/README.md",
                    "docs/ARCHITECTURE.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_strategy_broker_boundary.py",
                ),
            ),
            AcceptanceCriterion(
                key="decision_cockpit_read_only_bridge_panel",
                checkbox_text=(
                    "* [x] Decision Cockpit surfaces gateway, connector, "
                    "gateway query capabilities, connector read capabilities, "
                    "runtime connector snapshot summaries, staged "
                    "account-facts, staged fill polling, local order query, "
                    "reconciliation status, and broker cost evidence "
                    "as read-only evidence, including strategy promotion "
                    "state and a staged-fill reconciliation review hint, "
                    "without submit, cancel, live-promotion, fill-apply, or "
                    "ledger-sync controls."
                ),
                evidence_paths=(
                    "server/services/automation_cockpit.py",
                    "tests/test_automation_cockpit.py",
                    "tests/server/test_automation_routes.py",
                    "web/src/features/operations/api.ts",
                    "web/src/features/decision/components/decision-cockpit-page.tsx",
                    "web/src/features/decision/components/decision-cockpit-page.test.tsx",
                    "tests/server/test_broker_gateway_routes.py",
                    "tests/server/test_execution_reconciliation_routes.py",
                ),
                validation_commands=(
                    "npm --prefix web test -- decision-cockpit-page.test.tsx",
                    "uv run pytest tests/server/test_broker_gateway_routes.py tests/server/test_execution_reconciliation_routes.py",
                ),
            ),
        )
    )


def build_capital_authorization_stage0_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the completed non-submitting v1.8 Stage 0 slices."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="versioned_fail_closed_authorization_contract",
                checkbox_text=(
                    "* [x] A versioned capital-authorization contract evaluates "
                    "disabled, per-order, and session-bounded modes fail closed "
                    "across scope, expiry, evidence gates, and multi-dimensional "
                    "hard limits."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "docs/ARCHITECTURE.md",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_limits_and_safety_evidence",
                checkbox_text=(
                    "* [x] Evaluation returns deterministic fingerprints, "
                    "structured block reasons, effective limits, remaining "
                    "budgets, and explicit no-submit/no-cancel/no-OMS/no-ledger/"
                    "no-self-expansion safety flags."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="dual_connector_gateway_identity_contract",
                checkbox_text=(
                    "* [x] Capital-authorization v2 separates the read-only "
                    "evidence connector from the execution gateway, requires "
                    "both explicit policy scopes, rejects identical/overlapping "
                    "roles, and requires a verified same-account binding."
                ),
                evidence_paths=(
                    "server/services/capital_authorization.py",
                    "server/routes/capital_authorization.py",
                    "tests/test_capital_authorization.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py tests/server/test_capital_authorization_routes.py -k 'dual or roles or v2' -q",
                ),
            ),
            AcceptanceCriterion(
                key="declared_execution_gateway_not_runtime_authority",
                checkbox_text=(
                    "* [x] Declared execution-gateway id, health, and submit "
                    "capability are fingerprinted evidence only; the shared "
                    "binding remains runtime-unverified and cannot contact a "
                    "broker, submit, or authorize execution."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_binding.py",
                    "server/services/per_order_confirmation.py",
                    "server/services/controlled_session_envelope.py",
                    "tests/test_execution_gateway_binding.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_binding.py tests/test_per_order_confirmation.py tests/test_controlled_session_envelope.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="append_only_evaluation_audit",
                checkbox_text=(
                    "* [x] Preview remains side-effect free, while recorded "
                    "evaluations use append-only local audit events and reuse "
                    "an existing sequential input fingerprint without granting "
                    "runtime authority."
                ),
                evidence_paths=(
                    "server/services/capital_authorization_audit.py",
                    "server/db.py",
                    "tests/test_capital_authorization_audit.py",
                    "tests/server/test_capital_authorization_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="evidence_only_capital_authority_api",
                checkbox_text=(
                    "* [x] Capital-authority status, preview, record-evaluation, "
                    "and list-evaluation APIs expose evidence only; even an "
                    "allowed evaluation leaves execution authority and broker "
                    "submission disabled."
                ),
                evidence_paths=(
                    "server/routes/capital_authorization.py",
                    "server/services/capital_authorization_audit.py",
                    "server/app.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "README.md",
                    "docs/README.en.md",
                    "docs/README.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_authorization_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="credentials_and_static_config_cannot_authorize",
                checkbox_text=(
                    "* [x] API payloads reject undeclared credential fields, "
                    "and static config cannot grant capital execution authority."
                ),
                evidence_paths=(
                    "server/routes/capital_authorization.py",
                    "server/services/capital_authorization_audit.py",
                    "server/config.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_capital_authorization_routes.py -k credential -q",
                ),
            ),
            AcceptanceCriterion(
                key="capital_authorization_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover missing, disabled, expired, "
                    "mismatched, over-budget, upstream-gate, persistence, route, "
                    "sequential-rerun, and no-authority behavior."
                ),
                evidence_paths=(
                    "tests/test_capital_authorization.py",
                    "tests/test_capital_authorization_audit.py",
                    "tests/server/test_capital_authorization_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_capital_authorization.py tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q",
                    "uv run pytest -q",
                ),
            ),
        )
    )


def build_broker_connector_soak_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the completed Stage 1 read-only soak foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="sanitized_local_broker_export_capture",
                checkbox_text=(
                    "* [x] QMT, PTrade, and generic local read-only exports can "
                    "be captured as sanitized cash, position, order, fill, "
                    "health, capability, and source-time evidence without "
                    "storing or returning raw account ids."
                ),
                evidence_paths=(
                    "account_truth/broker_connector.py",
                    "server/services/broker_connector_runtime.py",
                    "server/services/broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_routes.py -k local_broker_exports -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_soak_observation_evidence",
                checkbox_text=(
                    "* [x] Each observation has deterministic snapshot and "
                    "observation fingerprints, append-only local evidence, and "
                    "sequential rerun reuse without broker-write, OMS, or "
                    "production-ledger side effects."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "server/db.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k sanitized_persisted_and_reused -q",
                ),
            ),
            AcceptanceCriterion(
                key="soak_health_capability_fail_closed",
                checkbox_text=(
                    "* [x] Missing read capabilities, any submit capability, "
                    "stale/future/invalid timestamps, source-health degradation, "
                    "missing cash, or connector exceptions fail closed into "
                    "degraded or blocked soak evidence."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k 'stale or submit_capability or exception' -q",
                ),
            ),
            AcceptanceCriterion(
                key="provider_calendar_trading_day_coverage",
                checkbox_text=(
                    "* [x] Healthy-day coverage requires a provider market-"
                    "calendar snapshot and an explicit trading day; missing "
                    "calendars and closed days do not count toward the "
                    "20-trading-day target."
                ),
                evidence_paths=(
                    "data/market_calendar.py",
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k 'market_calendar or twenty_healthy_days' -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_api_and_operations_alerts",
                checkbox_text=(
                    "* [x] Capture, status, and observation APIs remain read-only "
                    "with respect to the broker, OMS, and ledger, while "
                    "degraded/blocked observations create sanitized Operations "
                    "alerts."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "server/services/broker_connector_soak.py",
                    "server/app.py",
                    "server/services/automation_alerts.py",
                    "tests/test_broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py tests/server/test_broker_connector_soak_routes.py tests/test_automation_alerts.py tests/server/test_automation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="operational_soak_does_not_promote",
                checkbox_text=(
                    "* [x] Twenty healthy trading days complete only the "
                    "operational soak; `promotion_ready` remains false until "
                    "Account Truth reconciliation and explicit owner acceptance "
                    "are linked."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak.py",
                    "tests/test_broker_connector_soak.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/ROADMAP.md",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak.py -k twenty_healthy_days -q",
                ),
            ),
            AcceptanceCriterion(
                key="deterministic_operational_soak_phases",
                checkbox_text=(
                    "* [x] Startup, intraday, and end-of-day runbook phases "
                    "persist deterministic evidence; missing or unhealthy "
                    "read-only connector observations block the phase."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/routes/broker_connector_soak.py",
                    "tests/test_broker_connector_soak_runbook.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k 'startup or no_configured' -q",
                ),
            ),
            AcceptanceCriterion(
                key="end_of_day_reconciliation_gate",
                checkbox_text=(
                    "* [x] End-of-day runbook evidence requires a clear "
                    "execution reconciliation with zero open items; otherwise "
                    "it blocks and creates a sanitized Operations alert."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/execution_reconciliation.py",
                    "tests/test_broker_connector_soak_runbook.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k end_of_day -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_recovery_drills",
                checkbox_text=(
                    "* [x] Disconnect, schema-drift, stale-data, duplicate-"
                    "evidence, and restart-recovery drills record deterministic "
                    "pass/fail evidence and verify safe degradation or "
                    "sequential persisted-evidence reuse."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "tests/test_broker_connector_soak_runbook.py",
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py -k drill -q",
                ),
            ),
            AcceptanceCriterion(
                key="readonly_soak_runbook_api_boundary",
                checkbox_text=(
                    "* [x] Run and drill APIs reject undeclared fields and "
                    "credentials, expose only sanitized evidence, and cannot "
                    "submit/cancel orders, mutate OMS/ledger, or grant capital "
                    "authority."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "server/services/broker_connector_soak_runbook.py",
                    "tests/server/test_broker_connector_soak_runbook_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_runbook_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="broker_neutral_soak_operator_runbook",
                checkbox_text=(
                    "* [x] A broker-neutral operator runbook documents local-"
                    "export setup, startup/intraday/end-of-day cadence, drill "
                    "preparation, expected safe states, review steps, and the "
                    "unchanged no-write boundary."
                ),
                evidence_paths=(
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_acceptance_audit.py -k broker_connector_soak -q",
                ),
            ),
        )
    )


def build_per_order_confirmation_foundation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the non-submitting Stage 2 confirmation foundation."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="deterministic_per_order_dossier",
                checkbox_text=(
                    "* [x] A canonical order fingerprint and deterministic "
                    "dossier bind OMS order terms, capital-evaluation evidence, "
                    "Account Truth/research/risk/paper-shadow gateway gates, "
                    "latest connector soak, prior reconciliation, and kill-"
                    "switch state."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/capital_authorization_audit.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'dossier_binds or fingerprint_is_stable' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_review_gates_fail_closed",
                checkbox_text=(
                    "* [x] Dossier review fails closed when the OMS order is not "
                    "manually confirmed, the capital evaluation is missing/"
                    "stale/mismatched/not allowed, required gateway evidence is "
                    "missing or blocked, the latest soak is unhealthy or no "
                    "longer fresh, prior reconciliation is not clear, or the "
                    "kill switch is unavailable/enabled."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'kill_switch or missing_capital' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_hard_submission_blockers",
                checkbox_text=(
                    "* [x] A current signed Stage 1 promotion may clear only "
                    "its Stage 1 blockers, and an exact current non-submitting "
                    "gateway verification may clear only the runtime-verification "
                    "blocker; evidence-connector read-only integrity, runtime "
                    "authority, live gateway, and broker submission remain explicit "
                    "hard blockers."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k dossier_binds -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_signed_stage1_source_binding",
                checkbox_text=(
                    "* [x] Every per-order dossier resolves and fingerprints "
                    "the current Stage 1 promotion dossier, operational source, "
                    "Account Truth source, and verified owner-acceptance id for "
                    "the exact capital-policy connector."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k signed_stage1_promotion_is_bound -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_stage1_drift_fails_closed",
                checkbox_text=(
                    "* [x] Missing, invalid, mismatched, or failed promotion "
                    "resolution remains blocked without leaking provider "
                    "details; source drift changes the per-order dossier and "
                    "invalidates the old artifact-bound operator approval."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "server/routes/per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -k 'source_drift or failed_signed or wires_current' -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_dossier_attestation_reuse",
                checkbox_text=(
                    "* [x] An exact dossier fingerprint can be attested only "
                    "when review gates and an artifact-bound signed operator "
                    "approval pass; the append-only record is sequentially "
                    "reusable verified-identity evidence that does not "
                    "authorize execution."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/db.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k exact_dossier -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_rejection_audit_zero_side_effects",
                checkbox_text=(
                    "* [x] Stale fingerprints and blocked dossiers create "
                    "deterministic rejected confirmation evidence without "
                    "changing OMS, contacting a broker, or mutating the "
                    "production ledger."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'stale_dossier or kill_switch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_confirmation_api_boundary",
                checkbox_text=(
                    "* [x] Status, preview, confirmation, and list APIs reject "
                    "undeclared credential fields and expose no enable, issue-"
                    "authority, submit, cancel, resume, or scale-up operation."
                ),
                evidence_paths=(
                    "server/routes/per_order_confirmation.py",
                    "server/app.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_confirmation_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover evidence "
                    "aggregation, fail-closed gates, hard submission blockers, "
                    "exact-fingerprint reuse, rejection audit, credential "
                    "rejection, and zero execution side effects."
                ),
                evidence_paths=(
                    "tests/test_per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
        )
    )


def build_broker_connector_soak_promotion_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the signed Stage 1.1 promotion dossier."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="promotion_account_truth_source_evidence",
                checkbox_text=(
                    "* [x] Promotion uses a sanitized, source-sensitive Account "
                    "Truth fact built from the latest persisted import, current "
                    "ledger projection, reconciliation items, review decisions, "
                    "and score; only pass/fresh/zero-unresolved evidence is clear."
                ),
                evidence_paths=(
                    "server/account_truth_gate.py",
                    "tests/server/test_account_truth_gate.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_account_truth_gate.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="twenty_clear_reconciled_soak_days",
                checkbox_text=(
                    "* [x] A promotion dossier selects exactly 20 unique "
                    "healthy read-only trading days whose snapshots each bind "
                    "a clear execution reconciliation with zero open items and "
                    "one stable connector account alias/hash."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k promotion_dossier -q",
                ),
            ),
            AcceptanceCriterion(
                key="daily_runbook_phase_coverage",
                checkbox_text=(
                    "* [x] Every selected trading day requires persisted passed "
                    "startup, intraday, and end-of-day runbook evidence for the "
                    "same connector; incomplete phase coverage blocks owner "
                    "acceptance."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k missing_daily_phase -q",
                ),
            ),
            AcceptanceCriterion(
                key="recovery_drill_and_external_assertion_boundary",
                checkbox_text=(
                    "* [x] Disconnect, schema-drift, stale-data, duplicate-"
                    "evidence, and service-instance restart drills must all "
                    "pass; full process and broker-terminal recovery remains an "
                    "explicit signed owner assertion rather than an automated "
                    "claim."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_runbook.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_runbook.py tests/test_broker_connector_soak_promotion.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="source_bound_promotion_dossier",
                checkbox_text=(
                    "* [x] The deterministic promotion fingerprint binds the "
                    "selected observations, phase/run ids, drill ids, latest "
                    "snapshot, account alias/hash, and exact Account Truth "
                    "source fingerprint; source drift requires a new review."
                ),
                evidence_paths=(
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k source_drift -q",
                ),
            ),
            AcceptanceCriterion(
                key="signed_append_only_owner_acceptance",
                checkbox_text=(
                    "* [x] Owner acceptance requires a short-lived Ed25519 "
                    "approval for the exact promotion dossier and matching "
                    "operator label; accepted/rejected records are append-only, "
                    "exact reruns reuse evidence, and cross-dossier approval "
                    "fails closed."
                ),
                evidence_paths=(
                    "server/services/operator_approval.py",
                    "server/services/broker_connector_soak_promotion.py",
                    "tests/test_broker_connector_soak_promotion.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_broker_connector_soak_promotion.py -k 'signed_owner or another_dossier' -q",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_api_zero_execution_authority",
                checkbox_text=(
                    "* [x] Promotion status, dossier preview, acceptance, and "
                    "history APIs reject undeclared credential fields and expose "
                    "no capital/runtime authority issue, budget reservation, "
                    "OMS/ledger mutation, gateway contact, submit, cancel, "
                    "resume, or automatic-promotion action."
                ),
                evidence_paths=(
                    "server/routes/broker_connector_soak.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_broker_connector_soak_routes.py -k promotion -q",
                ),
            ),
            AcceptanceCriterion(
                key="promotion_deterministic_integration_tests",
                checkbox_text=(
                    "* [x] Deterministic Account Truth, promotion-service, "
                    "signature, and route tests cover full evidence, missing "
                    "coverage, blocked Account Truth, source drift, exact reuse, "
                    "rejection audit, credential rejection, and zero execution "
                    "side effects."
                ),
                evidence_paths=(
                    "tests/server/test_account_truth_gate.py",
                    "tests/test_broker_connector_soak_promotion.py",
                    "tests/server/test_broker_connector_soak_routes.py",
                    "tests/test_operator_approval.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_account_truth_gate.py tests/test_broker_connector_soak_promotion.py tests/server/test_broker_connector_soak_routes.py tests/test_operator_approval.py -q",
                ),
            ),
        )
    )


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


def build_execution_batch_reconciliation_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for the exact prior-batch reconciliation gate."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="exact_batch_order_set_contract",
                checkbox_text=(
                    "* [x] A batch manifest binds a non-empty unique set of at "
                    "most 100 non-paper OMS orders to one explicit persisted "
                    "execution-reconciliation run."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'clear_exact or duplicate' -q",
                ),
            ),
            AcceptanceCriterion(
                key="exact_reconciliation_item_and_terminal_state",
                checkbox_text=(
                    "* [x] Every batch order must have exactly one no-action "
                    "reconciliation item whose recorded OMS status still "
                    "matches a current filled, rejected, cancelled, or expired "
                    "terminal state."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'clear_exact or nonterminal' -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_real_fill_linkage_and_quantity",
                checkbox_text=(
                    "* [x] A filled batch order requires exact real-fill "
                    "quantity plus provider, broker-order, Account Truth import, "
                    "and same-run reconciliation linkage; incomplete or excess "
                    "fill evidence blocks the batch."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k filled_batch -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_source_sensitive_fingerprint",
                checkbox_text=(
                    "* [x] OMS order, transition, real-fill, reconciliation "
                    "item, and run facts participate in one deterministic "
                    "fingerprint, and any later source change invalidates the "
                    "recorded prior-batch gate."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k source_changes -q",
                ),
            ),
            AcceptanceCriterion(
                key="batch_append_only_record_and_rejection_audit",
                checkbox_text=(
                    "* [x] Exact clear or blocked batch evidence is append-only "
                    "and sequentially reusable, while stale fingerprints and "
                    "invalid acknowledgement attempts create deterministic "
                    "rejection evidence."
                ),
                evidence_paths=(
                    "server/services/execution_batch_reconciliation.py",
                    "tests/test_execution_batch_reconciliation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_batch_reconciliation.py -k 'append_only or stale_fingerprint' -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_exact_prior_batch_binding",
                checkbox_text=(
                    "* [x] Per-order dossier review requires the request and "
                    "recorded capital evaluation to reference the same resolved "
                    "clear prior-batch fingerprint instead of trusting the "
                    "latest reconciliation run."
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
                key="session_exact_prior_batch_binding",
                checkbox_text=(
                    "* [x] Session-envelope review requires the request and "
                    "recorded capital evaluation to reference the same resolved "
                    "clear prior-batch fingerprint; missing, blocked, or changed "
                    "batch facts fail closed."
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
                key="batch_api_zero_execution_authority",
                checkbox_text=(
                    "* [x] Batch status, preview, record, resolve, and list APIs "
                    "reject undeclared credential fields and cannot issue or "
                    "expand authority, reserve budget, mutate OMS/ledger, "
                    "contact a broker, or submit/cancel an order."
                ),
                evidence_paths=(
                    "server/routes/execution_reconciliation.py",
                    "server/services/execution_batch_reconciliation.py",
                    "tests/server/test_execution_reconciliation_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_execution_reconciliation_routes.py -k execution_batch -q",
                ),
            ),
        )
    )


def build_execution_gateway_verification_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for non-submitting runtime gateway verification."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="runtime_gateway_capability_health_contract",
                checkbox_text=(
                    "* [x] Runtime verification resolves a distinct registered "
                    "execution gateway, verified evidence-connector/account "
                    "binding, complete submit/cancel/query/dry-run/idempotency "
                    "capabilities, and a healthy source-fingerprinted snapshot."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k preview_is_ready -q",
                ),
            ),
            AcceptanceCriterion(
                key="execution_gateway_health_freshness",
                checkbox_text=(
                    "* [x] Gateway health must be healthy, timezone-aware, no "
                    "more than 60 seconds old, not materially future-dated, and "
                    "bound to a valid source fingerprint; missing/stale/provider "
                    "failure evidence fails closed without leaking details."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'source_drift or capability_account' -q",
                ),
            ),
            AcceptanceCriterion(
                key="non_submitting_idempotent_gateway_dry_run",
                checkbox_text=(
                    "* [x] The verifier derives a deterministic client order "
                    "id and requires dry-run acceptance for the exact order "
                    "fingerprint with a valid payload fingerprint, no broker "
                    "order id, submitted=false, and zero reported side effects."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'preview_is_ready or side_effects' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_append_only_reuse",
                checkbox_text=(
                    "* [x] Exact accepted or rejected verification attempts "
                    "are append-only and deterministic; sequential accepted "
                    "reruns reuse one event without submitting or cancelling."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "server/db.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k 'record_reuses or rejected' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_resolve_rechecks_source",
                checkbox_text=(
                    "* [x] Resolution re-runs current capability, binding, "
                    "health, and dry-run checks, rejects source drift, and "
                    "expires recorded verification after five minutes."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k source_drift -q",
                ),
            ),
            AcceptanceCriterion(
                key="no_production_gateway_default",
                checkbox_text=(
                    "* [x] Production registers no execution gateway by "
                    "default; status therefore reports no runtime gateway, "
                    "disabled execution authority, and broker submission false."
                ),
                evidence_paths=(
                    "server/routes/execution_gateway_verification.py",
                    "tests/test_execution_gateway_verification.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py -k status_defaults -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_api_zero_authority",
                checkbox_text=(
                    "* [x] Status, preview, record, resolve, and list APIs "
                    "reject undeclared credential fields and expose no gateway "
                    "registration, authority issue, budget, OMS/ledger, submit, "
                    "cancel, resume, or scale-up operation."
                ),
                evidence_paths=(
                    "server/routes/execution_gateway_verification.py",
                    "server/app.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_execution_gateway_verification_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic service and route tests cover ready, "
                    "missing registration, capability/account/health failure, "
                    "unsafe dry-run, source drift, expiry, reuse, rejection "
                    "audit, credential rejection, and zero broker side effects."
                ),
                evidence_paths=(
                    "tests/test_execution_gateway_verification.py",
                    "tests/server/test_execution_gateway_verification_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py tests/server/test_execution_gateway_verification_routes.py -q",
                ),
            ),
        )
    )


def build_per_order_gateway_verification_binding_acceptance_audit() -> AcceptanceAudit:
    """Return evidence for exact Stage 2.4 verification binding into Stage 2."""

    return AcceptanceAudit(
        criteria=(
            AcceptanceCriterion(
                key="capital_exact_gateway_verification_reference",
                checkbox_text=(
                    "* [x] The recorded manual-each-order capital evaluation "
                    "must contain the exact typed execution-gateway verification "
                    "fingerprint requested by the per-order dossier."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/ARCHITECTURE.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k capital_evaluation_must_reference -q",
                ),
            ),
            AcceptanceCriterion(
                key="current_gateway_verification_exact_scope_binding",
                checkbox_text=(
                    "* [x] Every dossier re-resolves the current verification "
                    "and exactly binds gateway id, read-only evidence connector, "
                    "account alias, OMS order id, canonical order fingerprint, "
                    "and the dry-run order contract."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "server/services/execution_gateway_verification.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'dossier_binds or scope_mismatch' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_scope_mismatch_fails_closed",
                checkbox_text=(
                    "* [x] Missing providers and gateway, connector, account, "
                    "order, fingerprint, status, authority, or submission-state "
                    "mismatches fail closed with sanitized evidence."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k 'scope_mismatch or provider_failures' -q",
                ),
            ),
            AcceptanceCriterion(
                key="gateway_verification_drift_invalidates_approval",
                checkbox_text=(
                    "* [x] Expiry or source drift changes the dossier fingerprint, "
                    "re-blocks review, restores the runtime-verification hard "
                    "blocker, and invalidates the prior artifact-bound approval."
                ),
                evidence_paths=(
                    "server/services/execution_gateway_verification.py",
                    "server/services/per_order_confirmation.py",
                    "tests/test_execution_gateway_verification.py",
                    "tests/test_per_order_confirmation.py",
                ),
                validation_commands=(
                    "uv run pytest tests/test_execution_gateway_verification.py tests/test_per_order_confirmation.py -k 'source_drift or expiry' -q",
                ),
            ),
            AcceptanceCriterion(
                key="verification_clears_no_execution_authority",
                checkbox_text=(
                    "* [x] A clear non-submitting verification removes only the "
                    "runtime-verification blocker; runtime authority, live gateway, "
                    "broker submission, and strategy direct execution remain blocked."
                ),
                evidence_paths=(
                    "server/services/per_order_confirmation.py",
                    "tests/test_per_order_confirmation.py",
                    "docs/CONTROLLED_EXECUTION_PLAN.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py -k dossier_binds -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_gateway_verification_api_contract",
                checkbox_text=(
                    "* [x] Preview and confirmation APIs accept only a valid "
                    "verification fingerprint, inject the closed-by-default runtime "
                    "registry resolver, reject credentials, and expose no submit path."
                ),
                evidence_paths=(
                    "server/routes/per_order_confirmation.py",
                    "server/routes/execution_gateway_verification.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/config-reference.zh.md",
                ),
                validation_commands=(
                    "uv run pytest tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
            AcceptanceCriterion(
                key="per_order_gateway_verification_deterministic_tests",
                checkbox_text=(
                    "* [x] Deterministic tests cover exact binding, capital-reference "
                    "mismatch, scope mismatch, provider failure, source drift, "
                    "approval invalidation, route wiring, and zero execution authority."
                ),
                evidence_paths=(
                    "tests/test_per_order_confirmation.py",
                    "tests/server/test_per_order_confirmation_routes.py",
                    "docs/IMPLEMENTATION_LOG.md",
                ),
                validation_commands=(
                    "uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py -q",
                ),
            ),
        )
    )
