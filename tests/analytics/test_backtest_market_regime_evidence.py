from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from analytics.backtest_market_regime_evidence import (
    MARKET_REGIME_EVIDENCE_SCHEMA_VERSION,
    build_backtest_market_regime_evidence,
    is_valid_passed_backtest_market_regime_evidence,
)


def _handler(closes: list[float] | None = None) -> SimpleNamespace:
    start = datetime(2026, 1, 1)
    return SimpleNamespace(
        _df=pd.DataFrame(
            {
                "timestamp": [start + timedelta(days=index) for index in range(5)],
                "close": closes or [100, 110, 100, 105, 100],
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


def test_market_regime_evidence_passes_two_nonnegative_states() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "102", "103", "104"]),
        data_handlers={"600000": _handler()},
    )

    assert evidence["schema_version"] == MARKET_REGIME_EVIDENCE_SCHEMA_VERSION
    assert evidence["status"] == "pass"
    assert evidence["regime_count"] == 2
    assert evidence["failed_regime_count"] == 0
    assert {item["name"] for item in evidence["regimes"]} == {"rising", "falling"}
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["aligned_observation_count"] == 4
    assert len(evidence["aligned_observations"]) == 4
    assert is_valid_passed_backtest_market_regime_evidence(evidence) is True
    assert evidence["authorizes_execution"] is False


def test_market_regime_evidence_blocks_losing_or_sparse_state() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "90", "91", "80"]),
        data_handlers={"600000": _handler()},
    )

    assert evidence["status"] == "blocked"
    assert evidence["failed_regime_count"] >= 1


def test_market_regime_evidence_requires_rising_and_falling_states() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "102", "103", "104"]),
        data_handlers={"600000": _handler([100, 110, 110, 121, 121])},
    )

    assert evidence["status"] == "blocked"
    assert "required_market_regimes_missing" in evidence["issues"]
    assert is_valid_passed_backtest_market_regime_evidence(evidence) is False


def test_market_regime_validator_rejects_rehashed_summary_conflict() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "102", "103", "104"]),
        data_handlers={"600000": _handler()},
    )
    tampered = deepcopy(evidence)
    tampered["regimes"][0]["candidate_net_return"] = "0.999"

    assert is_valid_passed_backtest_market_regime_evidence(_rehash(tampered)) is False


def test_market_regime_validator_rejects_rehashed_observation_conflict() -> None:
    evidence = build_backtest_market_regime_evidence(
        result=_result(["100", "101", "102", "103", "104"]),
        data_handlers={"600000": _handler()},
    )
    tampered = deepcopy(evidence)
    tampered["aligned_observations"][0]["candidate_net_return"] = "0.999"

    assert is_valid_passed_backtest_market_regime_evidence(_rehash(tampered)) is False
