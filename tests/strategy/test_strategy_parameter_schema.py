from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_registry_exposes_typed_strategy_parameter_schema():
    import strategy.builtins  # noqa: F401
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
    import strategy.builtins  # noqa: F401
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


@pytest.mark.parametrize("parameter_type", ["int", "float"])
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"]
)
def test_numeric_strategy_parameters_reject_non_finite_values(
    parameter_type, value
) -> None:
    from strategy.schema import (
        StrategyParameterSchema,
        StrategyParameterValidationError,
        validate_strategy_params,
    )

    # Extension parameters may be unbounded; finite checks cannot depend on min/max.
    with pytest.raises(StrategyParameterValidationError) as error:
        validate_strategy_params(
            "local_strategy",
            [StrategyParameterSchema("amount", parameter_type)],
            {"amount": value},
        )

    assert error.value.errors == [
        {
            "field": "amount",
            "code": "invalid_type",
            "message": f"Parameter 'amount' must be of type {parameter_type}.",
        }
    ]


@pytest.mark.parametrize("num_std", ["NaN", "Infinity", "-Infinity"])
def test_bootstrap_rejects_non_finite_strategy_parameters(num_std) -> None:
    from core.event_bus import EventBus
    from server.bootstrap import build_strategy
    from strategy.schema import StrategyParameterValidationError

    with pytest.raises(StrategyParameterValidationError) as error:
        build_strategy(
            SimpleNamespace(strategy="bollinger", params={"num_std": num_std}),
            EventBus(),
        )

    assert error.value.errors == [
        {
            "field": "num_std",
            "code": "invalid_type",
            "message": "Parameter 'num_std' must be of type float.",
        }
    ]


def test_bootstrap_preserves_finite_numeric_string_parameters() -> None:
    from core.event_bus import EventBus
    from server.bootstrap import build_strategy

    strategy = build_strategy(
        SimpleNamespace(
            strategy="bollinger", params={"bb_period": "2", "num_std": "2.5"}
        ),
        EventBus(),
    )

    assert strategy.bb_period == 2
    assert strategy.num_std == 2.5
