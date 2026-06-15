from __future__ import annotations

import pytest


def test_registry_exposes_typed_strategy_parameter_schema():
    import strategy.examples  # noqa: F401
    from strategy.registry import StrategyRegistry

    info_by_id = {entry["strategy_id"]: entry for entry in StrategyRegistry.get_info()}
    dual_ma = info_by_id["dual_ma"]
    params = {param["name"]: param for param in dual_ma["parameter_schema"]}

    assert dual_ma["display_name"] == "Dual Moving Average"
    assert dual_ma["benchmark_role"] == "etf_rotation_trend_following"
    assert params["short_period"] == {
        "name": "short_period",
        "type": "int",
        "default": 5,
        "required": False,
        "min": 1,
        "max": 250,
        "allowed_values": None,
        "description": "Short moving-average window in trading bars.",
    }
    assert params["long_period"] == {
        "name": "long_period",
        "type": "int",
        "default": 20,
        "required": False,
        "min": 2,
        "max": 500,
        "allowed_values": None,
        "description": "Long moving-average window in trading bars.",
    }


def test_strategy_params_validate_defaults_types_unknowns_and_cross_fields():
    import strategy.examples  # noqa: F401
    from strategy.registry import StrategyRegistry
    from strategy.schema import StrategyParameterValidationError

    assert StrategyRegistry.validate_params("dual_ma", None) == {
        "short_period": 5,
        "long_period": 20,
    }
    assert StrategyRegistry.validate_params(
        "dual_ma",
        {"short_period": "3", "long_period": 9},
    ) == {"short_period": 3, "long_period": 9}

    with pytest.raises(StrategyParameterValidationError) as unknown_error:
        StrategyRegistry.validate_params("dual_ma", {"lookback": 20})
    assert unknown_error.value.errors == [
        {
            "field": "lookback",
            "code": "unknown_parameter",
            "message": "Unknown parameter 'lookback' for strategy 'dual_ma'.",
        }
    ]

    with pytest.raises(StrategyParameterValidationError) as cross_field_error:
        StrategyRegistry.validate_params(
            "dual_ma",
            {"short_period": 20, "long_period": 20},
        )
    assert cross_field_error.value.errors == [
        {
            "field": "short_period",
            "code": "cross_field_validation_failed",
            "message": "short_period must be less than long_period.",
        }
    ]
