from __future__ import annotations

import pytest

from analytics.pit_membership import build_pit_membership_evidence


def _snapshot(trade_date: str, symbols: list[str]) -> dict:
    return {
        "trade_date": trade_date,
        "members": [{"symbol": symbol} for symbol in symbols],
    }


def test_pit_membership_passes_when_universe_matches_both_edges():
    evidence = build_pit_membership_evidence(
        universe=["600000", "000001"],
        snapshots=[
            _snapshot("2025-01-02", ["600000", "000001"]),
            _snapshot("2025-08-21", ["600000", "000001", "300750"]),
        ],
        start_date="2025-01-02",
        end_date="2025-08-21",
    )
    assert evidence["status"] == "pass"
    assert evidence["survivorship_bias_detected"] is False
    assert evidence["listed_after_start"] == []
    assert evidence["delisted_before_end"] == []
    assert len(evidence["evidence_fingerprint"]) == 64


def test_pit_membership_detects_survivorship_bias():
    evidence = build_pit_membership_evidence(
        universe=["600000", "000001", "300750"],
        snapshots=[
            # 300750 listed after the window start (survivorship).
            _snapshot("2025-01-02", ["600000", "000001"]),
            _snapshot("2025-08-21", ["600000", "000001", "300750"]),
        ],
        start_date="2025-01-02",
        end_date="2025-08-21",
    )
    assert evidence["status"] == "blocked"
    assert evidence["blocker"] == "survivorship_bias_detected"
    assert evidence["listed_after_start"] == ["300750"]


def test_pit_membership_detects_delisting():
    evidence = build_pit_membership_evidence(
        universe=["600000", "000001"],
        snapshots=[
            _snapshot("2025-01-02", ["600000", "000001"]),
            # 000001 delisted before the window end.
            _snapshot("2025-08-21", ["600000"]),
        ],
        start_date="2025-01-02",
        end_date="2025-08-21",
    )
    assert evidence["status"] == "blocked"
    assert evidence["delisted_before_end"] == ["000001"]


def test_pit_membership_fails_closed_on_missing_snapshot():
    evidence = build_pit_membership_evidence(
        universe=["600000"],
        snapshots=[_snapshot("2025-01-02", ["600000"])],
        start_date="2025-01-02",
        end_date="2025-08-21",
    )
    assert evidence["status"] == "blocked"
    assert evidence["blocker"] == "missing_universe_snapshot"
    assert evidence["missing_edges"] == ["end_date"]


def test_pit_membership_rejects_empty_universe():
    with pytest.raises(ValueError):
        build_pit_membership_evidence(
            universe=[],
            snapshots=[],
            start_date="2025-01-02",
            end_date="2025-08-21",
        )
