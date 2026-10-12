"""Unit tests for ledger correction read semantics and historical invalidations."""

from __future__ import annotations

import pytest

from server.ledger.models import LedgerEntry
from server.projections.ledger_correction_read import (
    correction_read_evidence,
    is_fund_duplicate_correction,
    restated_ledger_rows,
)
from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    LegacyFundTradeDuplicateExclusionResolution,
)
from server.projections.legacy_fund_trade_duplicate_correction import (
    resolve_legacy_fund_trade_duplicate_exclusions,
)

pytestmark = pytest.mark.unit


def test_resolve_exclusions_empty_when_no_candidates() -> None:
    rows = [
        {
            "id": 1,
            "entry_type": "trade_buy",
            "timestamp": "2026-08-01T10:00:00+08:00",
            "source": "portfolio_trade",
            "amount": 1000.0,
        },
        {
            "id": 2,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-01T09:00:00+08:00",
            "source": "manual",
            "amount": 5000.0,
        },
    ]
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    assert resolution.valid
    assert resolution.excluded_manual_entry_ids == frozenset()
    assert resolution.correction_entry_ids == ()
    assert resolution.blockers == ()


def test_restated_ledger_rows_passes_through_unrestated_ledger() -> None:
    rows = [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-01T09:00:00+08:00",
            "amount": 1000.0,
            "net_cash_impact": 1000.0,
            "source": "manual",
        }
    ]
    restated = restated_ledger_rows(rows)
    assert restated == rows


def test_is_fund_duplicate_correction_identifies_matching_entries() -> None:
    entry_by_type = LedgerEntry(
        id=1,
        entry_type=LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
        timestamp="2026-08-30T17:00:00+08:00",
        amount=0.0,
        source="custom_source",
    )
    assert is_fund_duplicate_correction(entry_by_type)

    entry_by_source = LedgerEntry(
        id=2,
        entry_type="custom_correction",
        timestamp="2026-08-30T17:00:00+08:00",
        amount=0.0,
        source=LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    )
    assert is_fund_duplicate_correction(entry_by_source)

    regular_entry = LedgerEntry(
        id=3,
        entry_type="trade_buy",
        timestamp="2026-08-30T17:00:00+08:00",
        amount=100.0,
        source="portfolio_trade",
    )
    assert not is_fund_duplicate_correction(regular_entry)


def test_correction_read_evidence_empty_candidates() -> None:
    rows = [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-01T09:00:00+08:00",
            "amount": 1000.0,
            "net_cash_impact": 1000.0,
            "source": "manual",
        }
    ]
    entries = [LedgerEntry.from_row(row) for row in rows]
    evidence = correction_read_evidence(entries, rows)
    assert evidence == {}


def test_restated_ledger_rows_fails_closed_on_resolution_blockers() -> None:
    from server.projections.ledger_correction_read import _restated_rows

    rows = [{"id": 1}]
    blocked_resolution = LegacyFundTradeDuplicateExclusionResolution(
        excluded_manual_entry_ids=frozenset(),
        correction_entry_ids=(),
        repair_fingerprints=(),
        blockers=("test_blocker_reason",),
    )
    with pytest.raises(ValueError, match="test_blocker_reason"):
        _restated_rows(rows, blocked_resolution)
