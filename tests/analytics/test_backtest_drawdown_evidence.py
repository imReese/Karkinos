from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

from analytics.backtest_drawdown_evidence import (
    BACKTEST_DRAWDOWN_EVIDENCE_SCHEMA_VERSION,
    build_backtest_drawdown_evidence,
    is_valid_complete_backtest_drawdown_evidence,
)


def _curve() -> list[tuple[datetime, Decimal]]:
    start = datetime(2026, 1, 1)
    return [
        (start + timedelta(days=index), Decimal(value))
        for index, value in enumerate(("100", "120", "90", "110"))
    ]


def _rehash(evidence: dict) -> dict:
    core = {
        key: value for key, value in evidence.items() if key != "evidence_fingerprint"
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {**core, "evidence_fingerprint": hashlib.sha256(encoded).hexdigest()}


def test_drawdown_evidence_replays_exact_persisted_equity_curve() -> None:
    curve = _curve()
    evidence = build_backtest_drawdown_evidence(equity_curve=curve)

    assert evidence["schema_version"] == BACKTEST_DRAWDOWN_EVIDENCE_SCHEMA_VERSION
    assert evidence["status"] == "complete"
    assert evidence["max_drawdown_pct"] == "0.25"
    assert evidence["point_count"] == 4
    assert (
        is_valid_complete_backtest_drawdown_evidence(
            evidence,
            expected_max_drawdown=0.25,
            expected_equity_curve=[
                {"timestamp": timestamp.isoformat(), "equity": float(equity)}
                for timestamp, equity in curve
            ],
            expected_initial_equity=100,
            expected_final_equity=110,
        )
        is True
    )


def test_drawdown_validator_rejects_rehashed_summary_or_point_conflict() -> None:
    curve = _curve()
    evidence = build_backtest_drawdown_evidence(equity_curve=curve)

    summary_conflict = deepcopy(evidence)
    summary_conflict["max_drawdown_pct"] = "0.01"
    assert (
        is_valid_complete_backtest_drawdown_evidence(
            _rehash(summary_conflict),
            expected_max_drawdown=0.01,
            expected_equity_curve=curve,
            expected_initial_equity=100,
            expected_final_equity=110,
        )
        is False
    )

    point_conflict = deepcopy(evidence)
    point_conflict["points"][2]["drawdown_pct"] = "0.01"
    assert (
        is_valid_complete_backtest_drawdown_evidence(
            _rehash(point_conflict),
            expected_max_drawdown=0.25,
            expected_equity_curve=curve,
            expected_initial_equity=100,
            expected_final_equity=110,
        )
        is False
    )


def test_drawdown_validator_rejects_persisted_curve_drift() -> None:
    curve = _curve()
    evidence = build_backtest_drawdown_evidence(equity_curve=curve)
    drifted_curve = list(curve)
    drifted_curve[2] = (drifted_curve[2][0], Decimal("91"))

    assert (
        is_valid_complete_backtest_drawdown_evidence(
            evidence,
            expected_max_drawdown=0.25,
            expected_equity_curve=drifted_curve,
            expected_initial_equity=100,
            expected_final_equity=110,
        )
        is False
    )
