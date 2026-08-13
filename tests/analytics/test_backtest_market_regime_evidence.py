from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)


def _handler() -> SimpleNamespace:
    start = datetime(2026, 1, 1)
    return SimpleNamespace(
        _df=pd.DataFrame(
            {
                "timestamp": [start + timedelta(days=index) for index in range(5)],
                "close": [100, 110, 100, 105, 100],
            }
        )
    )


def _result(values: list[str]) -> SimpleNamespace:
    start = datetime(2026, 1, 1)
    return SimpleNamespace(
        equity_curve=[
            (start + timedelta(days=index), Decimal(value))
            for index, value in enumerate(values)
        ]
    )


def test_market_regime_evidence_passes_two_nonnegative_states() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "102", "103", "104"]),
        data_handlers={"600000": _handler()},
    )

    assert evidence["status"] == "pass"
    assert evidence["regime_count"] == 2
    assert evidence["failed_regime_count"] == 0
    assert {item["name"] for item in evidence["regimes"]} == {"rising", "falling"}
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["authorizes_execution"] is False


def test_market_regime_evidence_blocks_losing_or_sparse_state() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "90", "91", "80"]),
        data_handlers={"600000": _handler()},
    )

    assert evidence["status"] == "blocked"
    assert evidence["failed_regime_count"] >= 1
