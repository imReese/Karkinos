from __future__ import annotations

import json

import pytest


def test_discovers_extension_manifest_with_typed_metadata(tmp_path):
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    extension_dir = tmp_path / "extensions"
    extension_dir.mkdir()
    (extension_dir / "custom_momentum.strategy.json").write_text(
        json.dumps(
            {
                "schema_version": "karkinos.strategy.v1",
                "strategy_id": "custom_momentum",
                "display_name": "Custom Momentum",
                "description": "Local transparent momentum research strategy.",
                "class_path": "strategy.builtins.rsi:RSIStrategy",
                "asset_universe": ["stock"],
                "supported_frequencies": ["1d"],
                "benchmark_role": "custom_research_momentum",
                "benchmark_universe": ["stock"],
                "requires_out_of_sample_validation": True,
                "requires_after_cost_report": True,
                "validation_notes": [
                    "Research-only extension; must pass risk gates before use."
                ],
                "parameters": [
                    {
                        "name": "lookback",
                        "type": "int",
                        "default": 20,
                        "required": False,
                        "min": 2,
                        "max": 250,
                        "description": "Momentum lookback window in trading bars.",
                    },
                    {
                        "name": "signal_mode",
                        "type": "str",
                        "default": "close_above_average",
                        "required": False,
                        "allowed_values": ["close_above_average", "breakout"],
                        "description": "Transparent signal rule variant.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    StrategyRegistry.discover_extensions(extension_dir, force=True)

    info_by_id = {entry["strategy_id"]: entry for entry in StrategyRegistry.get_info()}
    custom_momentum = info_by_id["custom_momentum"]
    params = {param["name"]: param for param in custom_momentum["parameter_schema"]}

    assert custom_momentum["display_name"] == "Custom Momentum"
    assert custom_momentum["asset_universe"] == ["stock"]
    assert custom_momentum["supported_frequencies"] == ["1d"]
    assert custom_momentum["benchmark_role"] == "custom_research_momentum"
    assert custom_momentum["requires_out_of_sample_validation"] is True
    assert params["lookback"] == {
        "name": "lookback",
        "type": "int",
        "default": 20,
        "required": False,
        "min": 2,
        "max": 250,
        "allowed_values": None,
        "description": "Momentum lookback window in trading bars.",
    }
    assert StrategyRegistry.validate_params(
        "custom_momentum",
        {"lookback": "30", "signal_mode": "breakout"},
    ) == {"lookback": 30, "signal_mode": "breakout"}

    StrategyRegistry.clear_extension_strategies_for_tests()


def test_rejects_extension_manifest_that_requests_live_execution(tmp_path):
    from strategy.registry import StrategyRegistry
    from strategy.schema import StrategyExtensionValidationError

    extension_dir = tmp_path / "extensions"
    extension_dir.mkdir()
    (extension_dir / "unsafe.strategy.json").write_text(
        json.dumps(
            {
                "schema_version": "karkinos.strategy.v1",
                "strategy_id": "unsafe_extension",
                "display_name": "Unsafe Extension",
                "description": "Should never register.",
                "class_path": "strategy.builtins.rsi:RSIStrategy",
                "allow_live_trading": True,
                "parameters": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StrategyExtensionValidationError) as exc_info:
        StrategyRegistry.discover_extensions(extension_dir, force=True)

    assert exc_info.value.errors == [
        {
            "field": "allow_live_trading",
            "code": "unsafe_execution_capability",
            "message": (
                "Extension strategies cannot declare live or real-money "
                "execution capabilities."
            ),
        }
    ]
    assert StrategyRegistry.get("unsafe_extension") is None
