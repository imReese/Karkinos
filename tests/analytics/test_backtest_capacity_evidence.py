from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.backtest_capacity_evidence import (
    build_backtest_capacity_evidence,
    is_valid_passed_backtest_capacity_evidence,
)
from core.types import Symbol


def _handler(*, volume: int = 10_000) -> SimpleNamespace:
    return SimpleNamespace(
        _df=pd.DataFrame(
            {
                "timestamp": [datetime(2026, 1, 5)],
                "close": [Decimal("10")],
                "volume": [volume],
            }
        )
    )


def _fill(*, quantity: str = "500") -> SimpleNamespace:
    return SimpleNamespace(
        symbol=Symbol("600000"),
        timestamp=datetime(2026, 1, 5),
        fill_quantity=Decimal(quantity),
        fill_price=Decimal("10"),
    )


def test_capacity_evidence_passes_with_exact_bar_and_bounded_participation() -> None:
    evidence = build_backtest_capacity_evidence(
        fills=[_fill()],
        data_handlers={Symbol("600000"): _handler()},
        initial_cash=Decimal("100000"),
    )

    assert evidence["status"] == "pass"
    assert evidence["capacity_utilization_pct"] == "0.05"
    assert evidence["liquidity_utilization_pct"] == "0.5"
    assert evidence["gross_turnover"] == "5000"
    assert evidence["observation_count"] == 1
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["authorizes_execution"] is False
    assert evidence["does_not_change_capital_authority"] is True
    assert (
        is_valid_passed_backtest_capacity_evidence(
            evidence,
            expected_initial_cash="100000",
            expected_gross_turnover="5000",
        )
        is True
    )
    assert (
        is_valid_passed_backtest_capacity_evidence(
            evidence,
            expected_initial_cash="200000",
        )
        is False
    )
    assert (
        is_valid_passed_backtest_capacity_evidence(
            evidence,
            expected_initial_cash="100000",
            expected_gross_turnover="4999",
        )
        is False
    )


def test_capacity_evidence_blocks_missing_bar_or_over_capacity() -> None:
    missing = build_backtest_capacity_evidence(
        fills=[_fill()],
        data_handlers={},
        initial_cash=Decimal("100000"),
    )
    overloaded = build_backtest_capacity_evidence(
        fills=[_fill(quantity="20000")],
        data_handlers={Symbol("600000"): _handler()},
        initial_cash=Decimal("100000"),
    )

    assert missing["status"] == "blocked"
    assert missing["issues"] == ["capacity_fill_or_bar_invalid:0"]
    assert overloaded["status"] == "blocked"
    assert Decimal(overloaded["capacity_utilization_pct"]) > 1
    assert Decimal(overloaded["liquidity_utilization_pct"]) > 1
    assert is_valid_passed_backtest_capacity_evidence(missing) is False
    assert is_valid_passed_backtest_capacity_evidence(overloaded) is False


def test_capacity_validator_rejects_rehashed_aggregate_or_formula_conflict() -> None:
    evidence = build_backtest_capacity_evidence(
        fills=[_fill()],
        data_handlers={Symbol("600000"): _handler()},
        initial_cash=Decimal("100000"),
    )
    core = {
        key: value for key, value in evidence.items() if key != "evidence_fingerprint"
    }
    aggregate_conflict = _refingerprint(
        {
            **core,
            "capacity_utilization_pct": "0.4",
        }
    )
    formula_conflict = _refingerprint(
        {
            **core,
            "observations": [
                {
                    **evidence["observations"][0],
                    "liquidity_utilization_pct": "0.4",
                }
            ],
            "liquidity_utilization_pct": "0.4",
        }
    )
    turnover_conflict = _refingerprint(
        {
            **core,
            "gross_turnover": "4999",
        }
    )

    assert is_valid_passed_backtest_capacity_evidence(aggregate_conflict) is False
    assert is_valid_passed_backtest_capacity_evidence(formula_conflict) is False
    assert is_valid_passed_backtest_capacity_evidence(turnover_conflict) is False


def _refingerprint(payload: dict) -> dict:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **payload,
        "evidence_fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


@pytest.mark.parametrize("sides", [("buy", "buy"), ("buy", "sell")])
def test_same_bar_absolute_participation_and_turnover_do_not_net(sides):
    fills = [_fill(quantity="60"), _fill(quantity="60")]
    for fill, side in zip(fills, sides, strict=True):
        fill.side = side
    evidence = build_backtest_capacity_evidence(
        fills=fills,
        data_handlers={Symbol("600000"): _handler(volume=1000)},
        initial_cash=Decimal("100000"),
    )

    assert evidence["schema_version"] == "karkinos.backtest_capacity.v2"
    assert evidence["status"] == "blocked"
    assert [row["raw_volume_participation"] for row in evidence["observations"]] == [
        "0.06",
        "0.06",
    ]
    assert len(evidence["bar_observations"]) == 1
    aggregate = evidence["bar_observations"][0]
    assert aggregate["fill_indexes"] == [0, 1]
    assert aggregate["gross_fill_quantity"] == "120"
    assert aggregate["gross_fill_notional"] == "1200"
    assert aggregate["raw_volume_participation"] == "0.12"
    assert Decimal(evidence["liquidity_utilization_pct"]) == Decimal("1.2")
    assert evidence["gross_turnover"] == "1200"
    assert is_valid_passed_backtest_capacity_evidence(evidence) is False


@pytest.mark.parametrize("separate", ["symbol", "day"])
def test_different_instruments_or_execution_bars_have_separate_capacity(separate):
    fills = [_fill(quantity="60"), _fill(quantity="60")]
    handlers = {Symbol("600000"): _handler(volume=1000)}
    if separate == "symbol":
        fills[1].symbol = Symbol("600001")
        handlers[fills[1].symbol] = _handler(volume=1000)
    else:
        fills[1].timestamp += timedelta(days=1)
        frame = handlers[Symbol("600000")]._df
        second = frame.copy()
        second["timestamp"] += timedelta(days=1)
        handlers[Symbol("600000")]._df = pd.concat([frame, second], ignore_index=True)
    evidence = build_backtest_capacity_evidence(
        fills=fills, data_handlers=handlers, initial_cash=Decimal("100000")
    )

    assert evidence["status"] == "pass"
    assert len(evidence["bar_observations"]) == 2
    assert Decimal(evidence["liquidity_utilization_pct"]) == Decimal("0.6")
    assert is_valid_passed_backtest_capacity_evidence(evidence) is True


def test_same_instant_in_different_timezones_is_one_execution_bar():
    fills = [_fill(quantity="60"), _fill(quantity="60")]
    fills[0].timestamp = datetime(2026, 1, 5, 7, tzinfo=timezone.utc)
    fills[1].timestamp = fills[0].timestamp.astimezone(timezone(timedelta(hours=8)))
    handler = _handler(volume=1000)
    handler._df["timestamp"] = [fills[0].timestamp]
    evidence = build_backtest_capacity_evidence(
        fills=fills,
        data_handlers={Symbol("600000"): handler},
        initial_cash=Decimal("100000"),
    )

    assert evidence["status"] == "blocked"
    assert len(evidence["bar_observations"]) == 1
    assert evidence["bar_observations"][0]["timestamp"] == "2026-01-05T07:00:00+00:00"


def test_group_ratio_uses_total_quantity_before_division_at_exact_limit():
    evidence = build_backtest_capacity_evidence(
        fills=[_fill(quantity="1") for _ in range(3)],
        data_handlers={Symbol("600000"): _handler(volume=30)},
        initial_cash=Decimal("100000"),
    )
    assert evidence["bar_observations"][0]["raw_volume_participation"] == "0.1"
    assert Decimal(evidence["liquidity_utilization_pct"]) == 1
    assert is_valid_passed_backtest_capacity_evidence(evidence) is True


@pytest.mark.parametrize("quantity,expected", [("40", True), ("60", False)])
def test_legacy_report_is_unchanged_but_admission_rechecks_combined_participation(
    quantity, expected
):
    evidence = build_backtest_capacity_evidence(
        fills=[_fill(quantity=quantity), _fill(quantity=quantity)],
        data_handlers={Symbol("600000"): _handler(volume=1000)},
        initial_cash=Decimal("100000"),
    )
    evidence.update(
        schema_version="karkinos.backtest_capacity.v1",
        capacity_model_ref="karkinos.backtest.capacity.daily_bar_participation.v1",
        status="pass",
        liquidity_utilization_pct=evidence["observations"][0][
            "liquidity_utilization_pct"
        ],
    )
    del evidence["bar_observations"]
    del evidence["evidence_fingerprint"]
    for row in evidence["observations"]:
        del row["fill_quantity"], row["bar_volume"]
    legacy = _refingerprint(evidence)
    original = json.dumps(legacy, sort_keys=True)

    assert is_valid_passed_backtest_capacity_evidence(legacy) is expected
    assert json.dumps(legacy, sort_keys=True) == original


@pytest.mark.parametrize("defect", ["group", "quantity", "volume", "bar_notional"])
def test_validator_recomputes_grouped_evidence_even_when_payload_is_rehashed(defect):
    evidence = build_backtest_capacity_evidence(
        fills=[_fill(quantity="40"), _fill(quantity="40")],
        data_handlers={Symbol("600000"): _handler(volume=1000)},
        initial_cash=Decimal("100000"),
    )
    del evidence["evidence_fingerprint"]
    if defect == "group":
        evidence["bar_observations"][0]["gross_fill_quantity"] = "40"
    elif defect == "quantity":
        evidence["observations"][0]["fill_quantity"] = "1"
    elif defect == "volume":
        del evidence["observations"][0]["bar_volume"]
    else:
        evidence["observations"][0]["bar_notional"] = "1"
    assert is_valid_passed_backtest_capacity_evidence(_refingerprint(evidence)) is False


@pytest.mark.parametrize("missing", ["volume", "close", "fill_price", "fill_quantity"])
def test_missing_liquidity_or_fill_notional_inputs_stay_blocked(missing):
    handler, fill = _handler(), _fill()
    if missing in {"volume", "close"}:
        del handler._df[missing]
    else:
        setattr(fill, missing, None)
    evidence = build_backtest_capacity_evidence(
        fills=[fill],
        data_handlers={Symbol("600000"): handler},
        initial_cash=Decimal("100000"),
    )
    assert evidence["status"] == "blocked"
    assert evidence["bar_observations"] == []
    assert is_valid_passed_backtest_capacity_evidence(evidence) is False


@pytest.mark.parametrize("limit", ["0", "NaN", "-0.1", "Infinity", "1.1"])
def test_invalid_participation_limit_has_stable_validation_error(limit):
    with pytest.raises(ValueError, match="^daily_volume_participation_limit_invalid$"):
        build_backtest_capacity_evidence(
            fills=[_fill()],
            data_handlers={Symbol("600000"): _handler()},
            initial_cash=Decimal("100000"),
            max_daily_volume_participation=Decimal(limit),
        )
