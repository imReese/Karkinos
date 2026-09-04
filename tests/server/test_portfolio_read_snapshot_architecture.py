"""Executable boundaries for the production portfolio read snapshot."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _imported_names(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def test_production_portfolio_consumers_use_the_canonical_snapshot_adapter() -> None:
    module = "server.projections.portfolio_read_snapshot_persistence"
    consumers = (
        "server/projections/portfolio_quotes.py",
        "server/projections/portfolio_positions.py",
        "server/projections/portfolio_views/historical_ledger_series.py",
        "server/projections/portfolio_views/historical_series.py",
        "server/projections/portfolio_views/intraday_series.py",
        "server/projections/portfolio_views/live_holdings.py",
        "server/http/portfolio_endpoints/performance.py",
        "server/http/portfolio_endpoints/analysis.py",
    )

    for relative_path in consumers:
        imported = _imported_names(PROJECT_ROOT / relative_path, module)
        assert "portfolio_read_snapshot_for_state" in imported, relative_path

    dependency_source = (PROJECT_ROOT / "server/dependencies.py").read_text(
        encoding="utf-8"
    )
    assert "bind_portfolio_read_request_state" in dependency_source
    assert 'if scope["type"] != "http"' in dependency_source
    assert "with bind_portfolio_read_request_state()" in dependency_source


def test_unused_parallel_market_generation_repository_is_not_shipped() -> None:
    assert not (PROJECT_ROOT / "data/market_generation_store.py").exists()
    assert not (PROJECT_ROOT / "data/market_generation_models.py").exists()

    data_store_source = (PROJECT_ROOT / "data/store.py").read_text(encoding="utf-8")
    assert "MarketGenerationStore" not in data_store_source
    assert "market_generation_store" not in data_store_source

    adapter_source = (
        PROJECT_ROOT / "server/projections/portfolio_read_snapshot_persistence.py"
    ).read_text(encoding="utf-8")
    assert "_read_persisted_market_revision" in adapter_source
    assert "bar_meta" in adapter_source
    assert "market_generation_publications" not in adapter_source


def test_canonical_snapshot_adapter_has_no_provider_dependency() -> None:
    path = PROJECT_ROOT / "server/projections/portfolio_read_snapshot_persistence.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert not any(name.startswith("data.providers") for name in imports)
