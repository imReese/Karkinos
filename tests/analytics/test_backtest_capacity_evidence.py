from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

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
