"""Executable verification for server.services.research domain package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from server.services.research.factors import (
    get_curated_universe,
    list_curated_universes,
)
from server.services.research.instruments import (
    RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION,
    build_research_operation_instruments,
)


def test_cold_dataset_import_isolates_ai_and_preserves_strategy_bootstrap() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import sys
import server.services.research.datasets
import server.services.research.dataset_inputs
from importlib.util import find_spec

assert find_spec("server.services.research_datasets") is None
assert find_spec("server.services.backtest_dataset_inputs") is None

unexpected = {
    "server.services.research.factory",
    "server.ai_runtime.strategy_research",
    "server.ai_runtime.strategy_research_backtest",
    "server.ai_runtime.capture",
    "server.ai_runtime.store",
}.intersection(sys.modules)
assert not unexpected, sorted(unexpected)

from strategy.registry import StrategyRegistry
assert StrategyRegistry.get("dual_ma") is None

from core.event_bus import EventBus
from server.bootstrap import build_strategy
from types import SimpleNamespace

strategy = build_strategy(
    SimpleNamespace(strategy="dual_ma", params={"short_period": 2, "long_period": 5}),
    EventBus(),
)
assert strategy.short_period == 2
assert strategy.long_period == 5
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_curated_universes_via_domain() -> None:
    universes = list_curated_universes()
    assert len(universes) >= 3
    ids = {u["universe_id"] for u in universes}
    assert "core_etf_universe" in ids

    core = get_curated_universe("core_etf_universe")
    assert core is not None
    assert core["universe_id"] == "core_etf_universe"
    assert len(core["members"]) >= 5


def test_research_operation_instruments_via_domain() -> None:
    db = SimpleNamespace(
        get_instrument_metadata_batch_sync=lambda symbols, asset_type: [
            {"symbol": "600000", "display_name": "浦发银行", "source": "test"}
        ]
    )
    preview = {
        "status": "available",
        "operations": [{"symbol": "600000", "operation": "buy_candidate"}],
    }
    result = build_research_operation_instruments(db, preview)
    assert result["resolved_count"] == 1
    assert result["items"][0]["display_name"] == "浦发银行"
    assert result["schema_version"] == RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION
