from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
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
    assert evidence["observation_count"] == 1
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["authorizes_execution"] is False
    assert evidence["does_not_change_capital_authority"] is True


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
