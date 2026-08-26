from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_ARCHITECTURE_MODULES = (
    "server/routes/portfolio.py",
    "server/account_truth_gate.py",
    "server/account_truth_gate_support.py",
    "server/projections/portfolio_quotes.py",
    "server/projections/portfolio_quote_assets.py",
    "server/projections/portfolio_views/historical_series.py",
    "server/projections/portfolio_views/historical_ledger_series.py",
    "server/projections/service.py",
    "server/projections/portfolio_projection_values.py",
    "server/services/market_refresh.py",
    "server/services/market_refresh_provider.py",
)


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _class_methods(relative_path: str, class_name: str) -> set[str]:
    tree = ast.parse(_source(relative_path))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_portfolio_architecture_modules_and_functions_remain_bounded() -> None:
    violations: list[str] = []
    for relative in PORTFOLIO_ARCHITECTURE_MODULES:
        source = _source(relative)
        line_count = len(source.splitlines())
        if line_count > 600:
            violations.append(f"{relative}:module:{line_count}")
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if function_lines > 200:
                violations.append(
                    f"{relative}:{node.name}:{node.lineno}:{function_lines}"
                )

    assert violations == []


def test_trade_http_adapter_delegates_mutation_to_typed_command_service() -> None:
    source = _source("server/http/portfolio_endpoints/trades.py")
    composition = _source("server/routes/portfolio.py")

    assert "dependencies.command_service_factory" in source
    assert "PortfolioTradeCommandService" in composition
    for forbidden in (
        "add_trade",
        "ensure_asset_config",
        "record_manual_trade_sync",
        "insert_ledger_entry",
        "create_pending_fund_order_sync",
        "confirm_pending_fund_order_sync",
        "DELETE FROM",
        "._portfolio",
        "._lock",
    ):
        assert forbidden not in source
    assert "/trade/{trade_id}/corrections" in source
    assert "@router.delete" not in source


def test_portfolio_asset_projection_has_no_write_or_provider_orchestration() -> None:
    source = _source("server/projections/portfolio_assets.py")

    for forbidden in (
        "sqlite3",
        "build_sources",
        "pending_fund_orders",
        "insert_ledger",
        "add_trade",
        "upsert_",
    ):
        assert forbidden not in source


def test_portfolio_http_dependencies_are_explicit_and_have_no_service_locator() -> None:
    dependency_source = _source("server/http/portfolio_endpoints/dependencies.py")
    composition_source = _source("server/routes/portfolio.py")
    endpoint_sources = [
        _source(f"server/http/portfolio_endpoints/{name}.py")
        for name in ("analysis", "cash_flows", "performance", "snapshot", "trades")
    ]

    assert "class PortfolioEndpointDependencies" in dependency_source
    assert "build_portfolio_endpoint_dependencies" in composition_source
    assert "sys.modules" not in composition_source
    for source in endpoint_sources:
        assert "getattr(facade" not in source
        assert "def dependency(" not in source
        assert "endpoints[" not in source
        assert "from server.dependencies import get_app_state" not in source


def test_runtime_portfolio_rebuild_uses_only_canonical_ledger_facts() -> None:
    source = _source("server/services/portfolio_ledger.py")
    source += _source("server/projections/portfolio_positions.py")

    assert "build_portfolio_projection" in source
    assert "get_ledger_entries_sync" in source
    assert "get_trades_sync" not in source
    assert "trades" not in source.casefold()


def test_portfolio_and_account_truth_ledger_projections_never_seed_config_cash() -> (
    None
):
    sources = [
        _source("server/services/portfolio_ledger.py"),
        _source("server/http/portfolio_endpoints/performance.py"),
        _source("server/projections/portfolio_quotes.py"),
        _source("server/projections/portfolio_views/historical_series.py"),
        _source("server/account_truth_gate.py"),
    ]

    for source in sources:
        assert "config.initial_cash" not in source
        assert 'getattr(config, "initial_cash"' not in source


def test_manual_and_pending_trade_uows_own_immediate_transactions() -> None:
    manual_source = _source("server/persistence/manual_trade_uow.py")
    pending_source = _source("server/persistence/pending_fund_confirmation_uow.py")

    assert manual_source.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert pending_source.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert _class_methods(
        "server/persistence/manual_trade_uow.py", "ManualTradeUnitOfWork"
    ) >= {"record", "correct"}
    assert _class_methods(
        "server/persistence/pending_fund_confirmation_uow.py",
        "PendingFundConfirmationUnitOfWork",
    ) >= {"create_pending", "confirm"}

    for source in (manual_source, pending_source):
        assert "valuation_transaction_writer" in source
        assert "_valuation_publisher" not in source
        assert "logger.exception" not in source

    cash_source = _source("server/persistence/portfolio_cash_flow_uow.py")
    for source in (manual_source, pending_source, cash_source):
        assert "validate_portfolio_mutation_valuation" in source
        assert "valuation_snapshot_id" in source
        assert "valuation_snapshot_status" in source


def test_pending_confirmation_requires_human_selected_persisted_nav_evidence() -> None:
    application_source = _source("server/services/portfolio_trade_commands.py")
    pending_source = _source("server/persistence/pending_fund_confirmation_uow.py")
    app_source = _source("server/app.py")

    for forbidden in (
        "build_sources",
        "resolve_fund_buy_fill",
        "fetch_bars",
        "fetch_latest",
        "confirm_pending_fund_orders",
    ):
        assert forbidden not in application_source
    assert "quote_snapshots" in pending_source
    assert "quote_fetch_runs" in pending_source
    assert "manual_explicit_trigger" in pending_source
    assert "confirmed_by" in pending_source
    assert "_confirm_pending_fund_orders_on_startup" not in app_source
    assert "pending-fund-confirm" not in app_source


def test_portfolio_writes_require_exact_command_and_operator_claims() -> None:
    contracts = _source("server/contracts/portfolio_trades.py")
    contracts += _source("server/contracts/portfolio_cash_flows.py")
    claims = _source("server/persistence/portfolio_mutation_claims.py")
    migrations = _source("server/persistence/migrations.py")

    assert contracts.count("command_id: str") >= 6
    assert contracts.count("operator_id: str") >= 6
    assert "portfolio_mutation_claims" in migrations
    assert "request_fingerprint" in migrations
    assert "result_fingerprint" in migrations
    assert "portfolio command_id already belongs" in claims
    assert "content_fingerprint(result)" in claims


def test_legacy_trade_projection_is_never_hard_deleted_in_production() -> None:
    violations: list[str] = []
    for path in (ROOT / "server").rglob("*.py"):
        compact = " ".join(path.read_text(encoding="utf-8").upper().split())
        if "DELETE FROM TRADES" in compact:
            violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_cash_flow_mutations_are_ledger_owned_append_only_units_of_work() -> None:
    route_source = _source("server/http/portfolio_endpoints/cash_flows.py")
    composition_source = _source("server/routes/portfolio.py")
    service_source = _source("server/services/portfolio_cash_flow_commands.py")
    uow_source = _source("server/persistence/portfolio_cash_flow_uow.py")
    ledger_source = _source("server/services/portfolio_ledger.py")

    assert "dependencies.command_service_factory" in route_source
    assert "PortfolioCashFlowCommandService" in composition_source
    for forbidden in (
        "add_cash_flow",
        "delete_cash_flow_sync",
        "insert_ledger_entry",
        "._portfolio",
        "._lock",
    ):
        assert forbidden not in route_source
    assert uow_source.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert "portfolio_cash_flow_correction" in uow_source
    assert "valuation_transaction_writer" in uow_source
    assert "_valuation_publisher" not in uow_source
    assert "install_runtime_portfolio" in service_source
    assert "scheduler._" not in service_source
    assert "get_cash_flows" not in ledger_source
    assert "/cash-flow/{flow_id}/corrections" in route_source
    assert "@r.delete" not in route_source

    violations: list[str] = []
    for path in (ROOT / "server").rglob("*.py"):
        compact = " ".join(path.read_text(encoding="utf-8").upper().split())
        if "DELETE FROM CASH_FLOWS" in compact:
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_financial_facts_trade_surface_exposes_commands_not_split_writes() -> None:
    methods = _class_methods(
        "server/persistence/financial_facts_portfolio.py",
        "PortfolioFactsRepositoryMixin",
    )

    assert {
        "record_cash_flow_sync",
        "correct_cash_flow_sync",
        "record_manual_trade_sync",
        "correct_manual_trade_sync",
    } <= methods
    assert {
        "create_pending_fund_order_sync",
        "confirm_pending_fund_order_sync",
    } <= methods
    assert "add_trade" not in methods
    assert "add_trade_sync" not in methods
    assert "delete_trade" not in methods
    assert "add_cash_flow" not in methods
    assert "delete_cash_flow" not in methods
    assert "mark_pending_fund_order_confirmed_sync" not in methods
