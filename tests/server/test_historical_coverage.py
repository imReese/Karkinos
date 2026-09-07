"""Coverage explains price evidence without changing historical accounting."""

from dataclasses import replace
from datetime import datetime

import pytest

from server.projections.portfolio_read_snapshot import (
    PortfolioReadSnapshot,
    PortfolioReadSnapshotBuildMetrics,
    PortfolioReadSnapshotIdentity,
    PortfolioReadSnapshotRejected,
)
from server.projections.portfolio_views.historical_coverage import (
    HistoricalCoverageEvidence,
    build_historical_coverage,
)
from tests.server.test_market_calendar_dates import _verified_calendar


def _trade(day, *, symbol="600001", kind="stock", sell=False, id=1):
    return dict(
        id=id,
        entry_type="trade_sell" if sell else "trade_buy",
        timestamp=f"2026-09-{day:02}T10:00:00+08:00",
        symbol=symbol,
        asset_class=kind,
        direction="sell" if sell else "buy",
        quantity=10,
        price=10,
    )


def _snapshot(rows=None):
    return PortfolioReadSnapshot(
        identity=PortfolioReadSnapshotIdentity(
            "valuation", 1, "ledger", "market", "receipt", "content", "policy"
        ),
        published_valuation={
            "trade_date": "2026-09-07",
            "as_of": "2026-09-07T17:00:00+08:00",
        },
        ledger_rows=tuple([_trade(1)] if rows is None else rows),
        price_matrix_rows=(),
        intraday_quote_rows=(),
        build_metrics=PortfolioReadSnapshotBuildMetrics(0, 0, 0),
    )


def _price(day, **kwargs):
    return dict(
        symbol="600001",
        instrument_type="stock",
        trade_date=f"2026-09-{day:02}",
        timestamp=f"2026-09-{day:02}T15:00:00+08:00",
        kind="close",
        price=10,
        source="fixture",
        evidence_ref=f"close:{day}",
        **kwargs,
    )


def _evidence(
    snapshot,
    *,
    prices=(),
    calendars=None,
    metadata=None,
    incidents=(),
    evaluated_at=None,
):
    return HistoricalCoverageEvidence(
        snapshot_identity=snapshot.identity,
        evaluated_at=evaluated_at
        or datetime.fromisoformat("2026-09-07T17:00:00+08:00"),
        observations=tuple(prices),
        calendars=tuple(
            [_verified_calendar(2026, closed_dates={"2026-09-02"})]
            if calendars is None
            else calendars
        ),
        metadata=tuple(
            [dict(symbol="600001", asset_type="stock", exchange="SSE")]
            if metadata is None
            else metadata
        ),
        incidents=tuple(incidents),
    )


def test_holiday_is_not_a_gap_but_internal_trading_day_is():
    snapshot = _snapshot()
    evidence = _evidence(snapshot, prices=[_price(d) for d in (1, 4, 7)])
    result = build_historical_coverage(snapshot, evidence)
    assert result == build_historical_coverage(snapshot, evidence)
    by_day = {item.valuation_date: item for item in result.items}
    assert by_day["2026-09-02"].requirement == "not_required"
    assert by_day["2026-09-03"].requirement == "required"
    assert by_day["2026-09-03"].evidence_status == "missing"
    assert by_day["2026-09-03"].gap_position == "internal"
    assert result.confirmed_gap_dates == result.confirmed_gap_instrument_dates == 1
    assert result.status == "incomplete"


@pytest.mark.parametrize(
    "calendars",
    [
        [],
        [_verified_calendar(2026, verified=False)],
        [{"exchange": "SSE", "year": 2026}],
    ],
)
def test_calendar_missing_or_invalid_means_unknown(calendars):
    snapshot = _snapshot()
    result = build_historical_coverage(
        snapshot, _evidence(snapshot, calendars=calendars)
    )
    assert result.status == "unknown"
    assert all(item.requirement == "unknown" for item in result.items)
    assert result.confirmed_gap_instrument_dates == 0


def test_nav_belonging_date_estimate_and_namespace_are_independent_of_requirement():
    snapshot = _snapshot([_trade(1, kind="fund")])
    prices = [
        dict(
            _price(1),
            kind="quote",
            instrument_type="open_end_fund",
            nav_date="2026-09-01",
            quote_status="confirmed",
            timestamp="2026-09-02T20:00:00+08:00",
        ),
        dict(
            _price(3),
            kind="quote",
            instrument_type="open_end_fund",
            nav_date="2026-09-03",
            quote_status="estimated",
        ),
        dict(_price(4), instrument_type="etf"),
        dict(
            _price(7),
            kind="quote",
            instrument_type="open_end_fund",
            quote_status="confirmed",
        ),
    ]
    result = build_historical_coverage(snapshot, _evidence(snapshot, prices=prices))
    by_day = {item.valuation_date: item for item in result.items}
    assert all(
        item.requirement == "unknown"
        and item.requirement_reason == "fund_nav_rule_unavailable"
        for item in result.items
    )
    assert by_day["2026-09-01"].evidence_status == "available"
    assert by_day["2026-09-02"].evidence_status == "missing"
    assert by_day["2026-09-03"].evidence_status == "unverified"
    assert by_day["2026-09-04"].evidence_status == "missing"
    assert by_day["2026-09-07"].evidence_status == "unverified"
    assert result.confirmed_gap_dates == 0


def test_closed_and_reacquired_holding_scope_and_ambiguous_symbol():
    snapshot = _snapshot([_trade(1), _trade(3, sell=True, id=2), _trade(7, id=3)])
    result = build_historical_coverage(snapshot, _evidence(snapshot))
    assert [item.valuation_date for item in result.items] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-07",
    ]
    ambiguous = replace(
        snapshot, ledger_rows=(*snapshot.ledger_rows, _trade(7, kind="etf", id=4))
    )
    with pytest.raises(PortfolioReadSnapshotRejected, match="ambiguous"):
        build_historical_coverage(ambiguous, _evidence(ambiguous))
    mistyped = _snapshot([dict(_trade(1), instrument_type="etf")])
    with pytest.raises(PortfolioReadSnapshotRejected, match="identity mismatch"):
        build_historical_coverage(mistyped, _evidence(mistyped))


def test_candidate_conflicts_invalid_prices_and_unresolved_incidents():
    snapshot = _snapshot()
    prices = [
        _price(1),
        dict(_price(1), price=11, evidence_ref="other"),
        dict(_price(3), price=0),
    ]
    result = build_historical_coverage(snapshot, _evidence(snapshot, prices=prices))
    by_day = {item.valuation_date: item for item in result.items}
    assert by_day["2026-09-01"].evidence_status == "unverified"
    assert "observed_price_conflict" in by_day["2026-09-01"].evidence_reasons
    assert by_day["2026-09-03"].evidence_status == "invalid"
    incident = {"scope": [["stock", "600001"]], "incident_ref": "fixture"}
    result = build_historical_coverage(
        snapshot, _evidence(snapshot, prices=[_price(1)], incidents=[incident])
    )
    assert result.items[0].evidence_status == "unverified"
    assert "unresolved_publication" in result.items[0].evidence_reasons


def test_empty_complete_unknown_and_date_vs_instrument_date_counts():
    empty = _snapshot([])
    assert build_historical_coverage(empty, _evidence(empty)).status == "empty"
    snapshot = _snapshot()
    complete = build_historical_coverage(
        snapshot, _evidence(snapshot, prices=[_price(d) for d in (1, 3, 4, 7)])
    )
    assert complete.status == "complete"
    unknown = build_historical_coverage(snapshot, _evidence(snapshot, metadata=[]))
    assert unknown.status == "unknown"
    two = _snapshot([_trade(1), _trade(1, symbol="600002", id=2)])
    metadata = [
        dict(symbol=s, asset_type="stock", exchange="SSE") for s in ("600001", "600002")
    ]
    result = build_historical_coverage(two, _evidence(two, metadata=metadata))
    assert result.confirmed_gap_instrument_dates == 2 * result.confirmed_gap_dates


def test_input_binding_and_calendar_content_change_are_explicit():
    snapshot = _snapshot()
    evidence = _evidence(snapshot)
    wrong = replace(
        evidence,
        snapshot_identity=replace(snapshot.identity, ledger_fingerprint="wrong"),
    )
    with pytest.raises(PortfolioReadSnapshotRejected, match="identity"):
        build_historical_coverage(snapshot, wrong)
    changed = _evidence(snapshot, calendars=[_verified_calendar(2026)])
    assert (
        build_historical_coverage(snapshot, evidence).evidence_fingerprint
        != build_historical_coverage(snapshot, changed).evidence_fingerprint
    )


def test_closure_cash_events_and_existing_curve_are_unchanged():
    from datetime import datetime
    from types import SimpleNamespace

    from server.models import EquitySeriesPoint
    from server.projections.portfolio_views.historical_ledger_series import (
        build_daily_equity_series_from_ledger_history,
    )

    rows = [
        _trade(1),
        dict(
            id=2,
            entry_type="cash_deposit",
            timestamp="2026-09-02T09:00:00+08:00",
            amount=200,
            asset_class="cash",
        ),
        dict(
            id=3,
            entry_type="cash_withdrawal",
            timestamp="2026-09-02T10:00:00+08:00",
            amount=50,
            asset_class="cash",
        ),
    ]
    snapshot = _snapshot(rows)

    class Db:
        def get_all_ledger_entries_sync(self):
            return rows

        def get_historical_price_matrix_sync(self, **kwargs):
            return {"600001": [_price(d) for d in (1, 3, 4, 7)]}

    state = SimpleNamespace(db=Db())

    def curve():
        return build_daily_equity_series_from_ledger_history(
            state,
            selected_range="all",
            current_point=EquitySeriesPoint(
                timestamp="2026-09-07T15:00:00+08:00",
                total=150,
                stocks=100,
                funds=0,
                others=0,
                cash=50,
            ),
            now=datetime.fromisoformat("2026-09-07T17:00:00+08:00"),
        )

    before = curve()
    result = build_historical_coverage(
        snapshot, _evidence(snapshot, prices=[_price(d) for d in (1, 3, 4, 7)])
    )
    assert result.status == "complete"
    assert before == curve()
    closure = next(item for item in before if item.timestamp.startswith("2026-09-02"))
    assert closure.cash == 50
    assert closure.total is None


def test_legacy_nav_datetime_is_parsed_by_canonical_date_owner():
    snapshot = _snapshot([_trade(1, kind="fund")])
    prices = [
        dict(
            _price(3),
            kind="quote",
            instrument_type="open_end_fund",
            nav_date="2026-09-01 15:00",
            quote_status="confirmed",
        ),
        dict(
            _price(4),
            kind="quote",
            instrument_type="open_end_fund",
            nav_date="invalid",
            quote_status="confirmed",
        ),
    ]
    result = build_historical_coverage(snapshot, _evidence(snapshot, prices=prices))
    by_day = {item.valuation_date: item for item in result.items}
    assert by_day["2026-09-01"].evidence_status == "available"
    assert by_day["2026-09-03"].evidence_status == "missing"
    assert by_day["2026-09-04"].evidence_status == "unverified"


@pytest.mark.parametrize("has_price", [False, True])
def test_fixed_close_snapshot_uses_explicit_diagnostic_clock(has_price):
    snapshot = replace(
        _snapshot(),
        published_valuation={
            "trade_date": "2026-09-07",
            "as_of": "2026-09-07T15:00:00+08:00",
        },
    )
    early = _evidence(
        snapshot,
        prices=[_price(7)] if has_price else [],
        evaluated_at=datetime.fromisoformat("2026-09-07T15:30:00+08:00"),
    )
    late = replace(
        early, evaluated_at=datetime.fromisoformat("2026-09-07T17:00:00+08:00")
    )
    early_report = build_historical_coverage(snapshot, early)
    late_report = build_historical_coverage(snapshot, late)
    assert early_report.items[-1].requirement == "unknown"
    assert late_report.items[-1].requirement == "required"
    assert late_report.items[-1].evidence_status == (
        "available" if has_price else "missing"
    )
    assert (
        late_report.confirmed_gap_instrument_dates
        == early_report.confirmed_gap_instrument_dates + (0 if has_price else 1)
    )
    assert late_report.identity == early_report.identity
    assert late_report.evaluated_at == "2026-09-07T17:00:00+08:00"
    assert early_report.evidence_fingerprint != late_report.evidence_fingerprint
    assert late_report == build_historical_coverage(snapshot, late)
