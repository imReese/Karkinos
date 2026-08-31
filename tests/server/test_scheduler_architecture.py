from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_LOOP = PROJECT_ROOT / "server" / "scheduler_loop.py"
SCHEDULER_SIGNALS = PROJECT_ROOT / "server" / "scheduler_signals.py"
MARKET_REFRESH = PROJECT_ROOT / "server" / "services" / "market_refresh.py"
PORTFOLIO_QUOTES = PROJECT_ROOT / "server" / "projections" / "portfolio_quotes.py"


def test_scheduler_loop_depends_on_typed_state_port() -> None:
    source = SCHEDULER_LOOP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_loop = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_scheduler_loop"
    )
    state_annotation = ast.unparse(run_loop.args.args[0].annotation)

    assert state_annotation == "SchedulerLoopState"
    assert "self._scheduler" not in source
    assert "scheduler._" not in source


def test_scheduler_loop_keeps_edges_behind_composition_dependencies() -> None:
    tree = ast.parse(SCHEDULER_LOOP.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "server.scheduler" not in imported_modules
    assert not {
        module
        for module in imported_modules
        if module.startswith(("data.", "execution.", "risk."))
    }


def test_scheduler_signal_projection_has_explicit_inputs() -> None:
    source = SCHEDULER_SIGNALS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "handle_scheduler_signal"
    )

    assert [argument.arg for argument in handler.args.args] == ["event"]
    assert [argument.arg for argument in handler.args.kwonlyargs] == [
        "watchlist",
        "database",
        "portfolio",
        "notifier",
    ]
    assert "scheduler._" not in source


def test_scheduler_quote_batch_uses_one_typed_ingestion_uow() -> None:
    source = SCHEDULER_LOOP.read_text(encoding="utf-8")

    assert "QuoteIngestionCommand(" in source
    assert "persist_quote_ingestion_sync(command)" in source
    assert "save_quote_snapshot_sync" not in source
    assert "save_daily_close_snapshot_sync" not in source
    assert "upsert_latest_quote_sync" not in source
    assert "upsert_instrument_metadata_sync" not in source


def test_runtime_quote_consumers_use_public_scheduler_command() -> None:
    for path in (MARKET_REFRESH, PORTFOLIO_QUOTES):
        source = path.read_text(encoding="utf-8")
        assert "scheduler._latest_quotes" not in source
        assert "publish_runtime_quote" in source
