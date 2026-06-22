"""Strategy registry shared contract tests."""

from __future__ import annotations

import json


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
