"""Disclosure timing, revision conflicts and scoped financial research panels."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from core.types import Symbol
from data.financials import FinancialResearchStore, FinancialStatementObservation

SYMBOL = Symbol("600000")
DISCLOSED = datetime(2024, 4, 25, 10, tzinfo=timezone.utc)
SOURCE = "synthetic_archive"
SCOPE = "consolidated_annual_CNY"


def observation(**changes):
    values = {
        "symbol": SYMBOL,
        "end_date": date(2023, 12, 31),
        "event_time": DISCLOSED,
        "available_at": DISCLOSED + timedelta(minutes=1),
        "captured_at": DISCLOSED + timedelta(minutes=2),
        "source": SOURCE,
        "scope": SCOPE,
        "revision_id": "annual-original",
        "roe": 12.5,
    }
    return FinancialStatementObservation(**(values | changes))


def latest(store, instant, **changes):
    return store.get_latest_as_of(
        SYMBOL, instant, **({"source": SOURCE, "scope": SCOPE} | changes)
    )


def test_disclosure_date_does_not_admit_intraday_or_later_capture():
    original = observation()
    store = FinancialResearchStore([original])
    assert latest(store, DISCLOSED.replace(hour=7)) is None
    assert latest(store, original.available_at) is None
    assert latest(store, original.captured_at) == original
    backfilled = replace(original, captured_at=DISCLOSED + timedelta(days=30))
    backfill_store = FinancialResearchStore([backfilled])
    assert latest(backfill_store, DISCLOSED + timedelta(days=1)) is None


def test_latest_period_and_revision_are_selected_without_rewriting_history():
    original = observation()
    revised = observation(
        revision_id="annual-revised",
        roe=11.0,
        event_time=DISCLOSED + timedelta(days=30),
        available_at=DISCLOSED + timedelta(days=30),
        captured_at=DISCLOSED + timedelta(days=30),
    )
    # Same explicit statement scope, newer fiscal period available before the
    # older report is restated. It remains the latest-period observation.
    newer = observation(
        revision_id="newer-period",
        end_date=date(2024, 3, 31),
        roe=14.0,
        event_time=DISCLOSED + timedelta(days=2),
        available_at=DISCLOSED + timedelta(days=2),
        captured_at=DISCLOSED + timedelta(days=2),
    )
    store = FinancialResearchStore([revised, newer, original])
    assert latest(store, original.captured_at) == original
    assert latest(store, DISCLOSED + timedelta(days=40)) == newer
    annual_only = FinancialResearchStore([revised, original])
    assert latest(annual_only, DISCLOSED + timedelta(days=40)) == revised
    assert latest(annual_only, original.captured_at) == original


def test_conflicts_fail_closed_while_source_and_scope_remain_separate():
    original = observation()
    store = FinancialResearchStore([original, original])
    with pytest.raises(ValueError, match="revision_conflict"):
        store.add_observation(replace(original, revision_id="ambiguous", roe=99.0))
    with pytest.raises(ValueError, match="revision_conflict"):
        store.add_observation(replace(original, end_date=date(2023, 9, 30)))
    other_source = replace(original, source="another_archive", roe=50.0)
    other_scope = replace(original, scope="parent_annual_CNY", roe=3.0)
    store.add_observation(other_source)
    store.add_observation(other_scope)
    assert latest(store, original.captured_at) == original
    assert (
        latest(store, original.captured_at, source=other_source.source) == other_source
    )
    assert latest(store, original.captured_at, scope=other_scope.scope) == other_scope


def test_panel_keeps_missing_symbols_and_does_not_fill_a_new_missing_field():
    original = observation()
    missing = replace(
        original,
        revision_id="missing-roe",
        roe=None,
        event_time=DISCLOSED + timedelta(days=1),
        available_at=DISCLOSED + timedelta(days=1),
        captured_at=DISCLOSED + timedelta(days=1),
    )
    store = FinancialResearchStore([original, missing])
    symbols = [SYMBOL, Symbol("000001")]
    panel = store.to_cross_sectional_dataframe(
        symbols,
        [DISCLOSED, original.captured_at, missing.captured_at],
        source=SOURCE,
        scope=SCOPE,
    )
    assert panel.columns.tolist() == symbols
    assert panel.iloc[0].isna().all()
    assert panel.iloc[1, 0] == 12.5
    assert pd.isna(panel.iloc[1, 1])
    assert panel.iloc[2].isna().all()
    with pytest.raises(ValueError, match="field_unsupported"):
        store.to_cross_sectional_dataframe(
            symbols, [DISCLOSED], source=SOURCE, scope=SCOPE, field="revision_id"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"event_time": DISCLOSED.replace(tzinfo=None)},
        {"available_at": DISCLOSED - timedelta(seconds=1)},
        {"captured_at": DISCLOSED},
        {"end_date": date(2025, 1, 1)},
        {"roe": float("nan")},
        {"eps": float("inf")},
        {"roe": True},
        {"source": ""},
    ],
)
def test_invalid_financial_observations_are_rejected(changes):
    with pytest.raises(ValueError):
        observation(**changes)


def test_timezone_normalization_and_serialization_preserve_all_time_boundaries():
    local = DISCLOSED.astimezone(timezone(timedelta(hours=8)))
    row = observation(event_time=local)
    assert row.event_time.tzinfo is timezone.utc
    payload = row.to_json_dict()
    assert payload["event_time"] == DISCLOSED.isoformat()
    assert payload["available_at"] != payload["captured_at"]
    assert payload["end_date"] == "2023-12-31"
    json.dumps(payload, allow_nan=False)
    with pytest.raises(ValueError, match="timezone_required"):
        latest(FinancialResearchStore([row]), datetime(2024, 5, 1))
