"""Strategy registry shared contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("target", "unrelated_modules"),
    [
        ("core.types", ["core.clock", "core.event_bus", "core.events"]),
        (
            "domain.instrument",
            [
                "domain.portfolio",
                "domain.position",
            ],
        ),
        ("risk.rules", ["risk.manager", "risk.limits"]),
        (
            "execution.commission",
            ["execution.simulator", "execution.tracker"],
        ),
        (
            "notification.contracts",
            ["notification.console", "notification.notifier"],
        ),
        (
            "strategy.base",
            [
                "strategy.registry",
                "strategy.schema",
                "strategy.builtins",
                "data.market_calendar",
                "data.manager",
                "data.store",
            ],
        ),
    ],
)
def test_cold_foundation_import_keeps_unrelated_runtime_unloaded(
    target: str, unrelated_modules: list[str]
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import importlib
import json
import sys

importlib.import_module(sys.argv[1])
unexpected = set(json.loads(sys.argv[2])).intersection(sys.modules)
assert not unexpected, sorted(unexpected)
""",
            target,
            json.dumps(unrelated_modules),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_cold_bootstrap_builds_strategy_and_registers_builtin_catalog(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
from types import SimpleNamespace

from core.event_bus import EventBus
from strategy.registry import StrategyRegistry

assert StrategyRegistry.get_info() == []

from server.bootstrap import build_strategy

event_bus = EventBus()
strategy = build_strategy(
    SimpleNamespace(strategy="dual_ma", params={"short_period": 2, "long_period": 5}),
    event_bus,
)
assert strategy.short_period == 2
assert strategy.long_period == 5
assert strategy.event_bus is event_bus

catalog = StrategyRegistry.get_info()
assert {entry["strategy_id"] for entry in catalog} == {
    "bollinger",
    "donchian_breakout",
    "dual_ma",
    "etf_rotation",
    "monthly_rebalance",
    "pairs_ratio_mean_reversion",
    "risk_parity_macro",
    "rsi",
    "time_series_momentum",
    "volatility_target_trend",
}
assert all(entry["source_type"] == "builtin" for entry in catalog)
assert all(
    entry["execution_boundary"]["can_submit_broker_orders"] is False
    for entry in catalog
)
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "KARKINOS_STRATEGY_EXTENSION_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_builtin_and_extension_strategies_share_registry_contract(tmp_path) -> None:
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    extension_dir = tmp_path / "extensions"
    extension_dir.mkdir()
    (extension_dir / "local_breakout.strategy.json").write_text(
        json.dumps(
            {
                "schema_version": "karkinos.strategy.v1",
                "strategy_id": "local_breakout",
                "display_name": "Local Breakout",
                "description": "Local breakout research strategy.",
                "class_path": "strategy.builtins.rsi:RSIStrategy",
                "asset_universe": ["stock"],
                "supported_frequencies": ["1d"],
                "benchmark_role": "local_breakout_research",
                "benchmark_universe": ["stock"],
                "requires_out_of_sample_validation": True,
                "requires_after_cost_report": True,
                "validation_notes": [
                    "Research-only extension; must pass all gates before review."
                ],
                "parameters": [
                    {
                        "name": "breakout_window",
                        "type": "int",
                        "default": 20,
                        "required": False,
                        "min": 2,
                        "max": 250,
                        "description": "Breakout lookback window in trading bars.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    StrategyRegistry.discover_extensions(extension_dir, force=True)

    info_by_id = {entry["strategy_id"]: entry for entry in StrategyRegistry.get_info()}
    builtin = info_by_id["dual_ma"]
    extension = info_by_id["local_breakout"]

    expected_contract_keys = {
        "registry_contract_version",
        "schema_version",
        "strategy_id",
        "name",
        "display_name",
        "description",
        "source_type",
        "is_extension",
        "parameter_schema",
        "params",
        "asset_universe",
        "supported_frequencies",
        "benchmark_role",
        "benchmark_universe",
        "requires_out_of_sample_validation",
        "requires_after_cost_report",
        "validation_notes",
        "execution_boundary",
    }
    assert expected_contract_keys.issubset(builtin)
    assert expected_contract_keys.issubset(extension)

    assert builtin["registry_contract_version"] == "karkinos.strategy_registry.v1"
    assert extension["registry_contract_version"] == "karkinos.strategy_registry.v1"
    assert builtin["schema_version"] == "karkinos.strategy.v1"
    assert extension["schema_version"] == "karkinos.strategy.v1"
    assert builtin["source_type"] == "builtin"
    assert extension["source_type"] == "extension"
    assert builtin["is_extension"] is False
    assert extension["is_extension"] is True
    assert builtin["parameter_schema"] == builtin["params"]
    assert extension["parameter_schema"] == extension["params"]
    assert extension["parameter_schema"][0]["name"] == "breakout_window"

    for entry in (builtin, extension):
        assert entry["execution_boundary"] == {
            "research_only": True,
            "can_submit_broker_orders": False,
            "requires_risk_gate": True,
            "requires_account_truth_gate": True,
            "requires_paper_shadow_review": True,
            "requires_manual_confirmation": True,
        }

    StrategyRegistry.clear_extension_strategies_for_tests()
