from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.models import EquitySeriesPoint
from server.projections import service as projection_service
from server.projections.portfolio_views.historical_ledger_series import (
    build_daily_equity_series_from_ledger_history,
)
from server.projections.portfolio_views.historical_series import (
    bind_current_equity_valuation,
    bind_equity_series_valuation,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _ledger_rows() -> list[dict[str, object]]:
    return [
        {
            "id": 3,
            "entry_type": "dividend",
            "timestamp": "2026-08-27T09:00:00+08:00",
            "amount": 5.0,
            "symbol": "600001",
            "asset_class": "stock",
            "source": "manual",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-08-26T10:00:00+08:00",
            "symbol": "600001",
            "direction": "buy",
            "quantity": 10.0,
            "price": 10.0,
            "commission": 0.0,
            "asset_class": "stock",
            "source": "manual",
        },
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-26T09:00:00+08:00",
            "amount": 1000.0,
            "asset_class": "cash",
            "source": "manual",
        },
    ]


class _ProjectionDb:
    def __init__(self, matrix: dict[str, list[dict[str, object]]]) -> None:
        self.matrix = matrix
        self.ledger_reads = 0
        self.matrix_reads = 0
        self.matrix_request: dict[str, object] | None = None

    def get_all_ledger_entries_sync(self) -> list[dict[str, object]]:
        self.ledger_reads += 1
        return _ledger_rows()

    def get_historical_price_matrix_sync(self, **kwargs):
        self.matrix_reads += 1
        self.matrix_request = kwargs
        return self.matrix

    def get_latest_market_bar_before_date_sync(self, *_args, **_kwargs):
        raise AssertionError("single-symbol market reads must not be used")

    def get_latest_daily_close_before_sync(self, *_args, **_kwargs):
        raise AssertionError("single-symbol close reads must not be used")

    def get_latest_quote_before_date_sync(self, *_args, **_kwargs):
        raise AssertionError("single-symbol quote reads must not be used")


def _current_point() -> EquitySeriesPoint:
    return EquitySeriesPoint(
        timestamp="2026-08-27T15:00:00+08:00",
        total=1025.0,
        stocks=120.0,
        funds=0.0,
        others=0.0,
        cash=905.0,
        unrealized_pnl=20.0,
    )


def _fund_degraded_valuation() -> dict[str, object]:
    return {
        "snapshot_id": "valuation-fund-degraded",
        "as_of": "2026-08-27T15:01:00+08:00",
        "trade_date": "2026-08-27",
        "valuation_policy": "karkinos.persisted_valuation.v4",
        "ledger_cutoff_id": 3,
        "ledger_fingerprint": "ledger-fingerprint",
        "quote_set_fingerprint": "quote-fingerprint",
        "status": "degraded",
        "valuation_lanes": [
            {
                "asset_class": "stock",
                "status": "complete",
                "quote_count": 1,
                "complete_quote_count": 1,
                "review_required_quote_count": 0,
                "blocker_statuses": [],
            },
            {
                "asset_class": "fund",
                "status": "degraded",
                "quote_count": 1,
                "complete_quote_count": 0,
                "review_required_quote_count": 1,
                "blocker_statuses": ["confirmed_nav_missing"],
            },
        ],
        "quotes": [
            {
                "symbol": "019999",
                "asset_class": "fund",
                "price": 2.25,
                "quote_status": "confirmed_nav_missing",
            }
        ],
    }


def test_current_valuation_binding_preserves_complete_stock_lane() -> None:
    point = EquitySeriesPoint(
        timestamp="2026-08-27T15:00:00+08:00",
        total=1305.0,
        stocks=120.0,
        funds=280.0,
        others=0.0,
        cash=905.0,
        unrealized_pnl=25.0,
        total_daily_change=15.0,
        stocks_daily_change=10.0,
        funds_daily_change=5.0,
        others_daily_change=0.0,
    )

    bound = bind_current_equity_valuation(point, _fund_degraded_valuation())

    assert bound is not None
    assert bound.total is None
    assert bound.stocks == pytest.approx(120.0)
    assert bound.funds is None
    assert bound.others == pytest.approx(0.0)
    assert bound.unrealized_pnl is None
    assert bound.total_daily_change is None
    assert bound.stocks_daily_change == pytest.approx(10.0)
    assert bound.funds_daily_change is None
    assert bound.others_daily_change == pytest.approx(0.0)
    assert bound.quote_status == "confirmed_nav_missing"
    assert bound.missing_price_symbols == ["019999"]


def test_historical_valuation_binding_preserves_complete_stock_lane() -> None:
    points = [
        EquitySeriesPoint(
            timestamp="2026-08-26T15:00:00+08:00",
            total=1290.0,
            stocks=110.0,
            funds=275.0,
            others=0.0,
            cash=905.0,
            unrealized_pnl=10.0,
            stocks_daily_change=4.0,
            funds_daily_change=6.0,
        ),
        EquitySeriesPoint(
            timestamp="2026-08-27T15:00:00+08:00",
            total=1305.0,
            stocks=120.0,
            funds=280.0,
            others=0.0,
            cash=905.0,
            unrealized_pnl=25.0,
            stocks_daily_change=10.0,
            funds_daily_change=5.0,
        ),
    ]

    bound = bind_equity_series_valuation(points, _fund_degraded_valuation())

    assert [point.total for point in bound] == [None, None]
    assert [point.stocks for point in bound] == pytest.approx([110.0, 120.0])
    assert [point.funds for point in bound] == [None, None]
    assert [point.stocks_daily_change for point in bound] == pytest.approx([4.0, 10.0])
    assert [point.funds_daily_change for point in bound] == [None, None]
    assert all(point.quote_status == "confirmed_nav_missing" for point in bound)


def test_historical_projection_reads_once_and_applies_each_ledger_entry_once(
    monkeypatch,
) -> None:
    db = _ProjectionDb(
        {
            "600001": [
                {
                    "symbol": "600001",
                    "trade_date": "2026-08-26",
                    "timestamp": "2026-08-26T15:00:00+08:00",
                    "price": 11.0,
                    "source": "market_bars",
                },
                {
                    "symbol": "600001",
                    "trade_date": "2026-08-27",
                    "timestamp": "2026-08-27T15:00:00+08:00",
                    "price": 12.0,
                    "source": "market_bars",
                },
            ]
        }
    )
    applied_ids: list[int | None] = []
    original_apply = projection_service._apply_ledger_entry

    def counted_apply(projection, entry) -> None:
        applied_ids.append(entry.id)
        original_apply(projection, entry)

    monkeypatch.setattr(projection_service, "_apply_ledger_entry", counted_apply)

    points = build_daily_equity_series_from_ledger_history(
        SimpleNamespace(db=db),
        selected_range="all",
        current_point=_current_point(),
        now=datetime(2026, 8, 27, 15, 1, tzinfo=_SHANGHAI),
    )

    assert db.ledger_reads == 1
    assert db.matrix_reads == 1
    assert db.matrix_request == {
        "symbols": ["600001"],
        "start_date": "2026-08-26",
        "end_date": "2026-08-27",
    }
    assert applied_ids == [1, 2, 3]
    assert [point.total for point in points] == pytest.approx([1010.0, 1025.0])
    assert [point.stocks for point in points] == pytest.approx([110.0, 120.0])
    assert all(point.missing_price_symbols == [] for point in points)


def test_historical_projection_marks_missing_intermediate_weekday_as_gap() -> None:
    db = _ProjectionDb(
        {
            "600001": [
                {
                    "symbol": "600001",
                    "trade_date": "2026-08-26",
                    "timestamp": "2026-08-26T15:00:00+08:00",
                    "price": 11.0,
                    "source": "market_bars",
                },
                {
                    "symbol": "600001",
                    "trade_date": "2026-08-28",
                    "timestamp": "2026-08-28T15:00:00+08:00",
                    "price": 12.0,
                    "source": "market_bars",
                },
            ]
        }
    )

    points = build_daily_equity_series_from_ledger_history(
        SimpleNamespace(db=db),
        selected_range="all",
        current_point=_current_point().model_copy(
            update={"timestamp": "2026-08-28T15:00:00+08:00"}
        ),
        now=datetime(2026, 8, 28, 15, 1, tzinfo=_SHANGHAI),
    )

    assert [point.timestamp[:10] for point in points] == [
        "2026-08-26",
        "2026-08-27",
        "2026-08-28",
    ]
    assert points[0].total == pytest.approx(1010.0)
    assert points[1].total is None
    assert points[2].total == pytest.approx(1025.0)
    assert points[0].stocks == pytest.approx(110.0)
    assert points[1].stocks is None
    assert points[2].stocks == pytest.approx(120.0)
    assert [point.quote_status for point in points] == ["live", "missing", "live"]
    assert [point.missing_price_symbols for point in points] == [
        [],
        ["600001"],
        [],
    ]


def test_historical_projection_does_not_value_missing_prices_at_cost() -> None:
    db = _ProjectionDb({})

    points = build_daily_equity_series_from_ledger_history(
        SimpleNamespace(db=db),
        selected_range="all",
        current_point=_current_point(),
        now=datetime(2026, 8, 27, 15, 1, tzinfo=_SHANGHAI),
    )

    invested_points = [
        point for point in points if point.timestamp[:10] >= "2026-08-26"
    ]
    assert invested_points
    assert all(point.quote_status == "missing" for point in invested_points)
    assert all(point.missing_price_symbols == ["600001"] for point in invested_points)
    assert all(point.cash == pytest.approx(905.0) for point in invested_points[-1:])
    assert all(point.total is None for point in invested_points)
    assert all(point.stocks is None for point in invested_points)
    assert all(point.funds == pytest.approx(0.0) for point in invested_points)
    assert all(point.others == pytest.approx(0.0) for point in invested_points)
    assert all(point.unrealized_pnl is None for point in invested_points)


def test_historical_projection_rejects_unconfirmed_fund_nav_estimate() -> None:
    db = _ProjectionDb(
        {
            "019999": [
                {
                    "symbol": "019999",
                    "asset_class": "fund",
                    "trade_date": "2026-08-26",
                    "timestamp": "2026-08-26T14:57:00+08:00",
                    "price": 2.25,
                    "source": "eastmoney_fund_estimate",
                },
                {
                    "symbol": "019999",
                    "asset_class": "fund",
                    "trade_date": "2026-08-27",
                    "timestamp": "2026-08-27T14:57:00+08:00",
                    "price": 2.26,
                    "source": "eastmoney_fund_estimate",
                },
            ]
        }
    )
    db.get_all_ledger_entries_sync = lambda: [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-26T09:00:00+08:00",
            "amount": 1000.0,
            "asset_class": "cash",
            "source": "manual",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-08-26T10:00:00+08:00",
            "symbol": "019999",
            "direction": "buy",
            "quantity": 100.0,
            "price": 2.0,
            "commission": 0.0,
            "asset_class": "fund",
            "source": "manual",
        },
    ]

    points = build_daily_equity_series_from_ledger_history(
        SimpleNamespace(db=db),
        selected_range="all",
        current_point=_current_point(),
        now=datetime(2026, 8, 27, 15, 1, tzinfo=_SHANGHAI),
    )

    assert points
    assert all(point.quote_status == "confirmed_nav_missing" for point in points)
    assert all(point.total is None for point in points)
    assert all(point.funds is None for point in points)
    assert all(point.missing_price_symbols == ["019999"] for point in points)


def test_historical_fund_nav_gap_preserves_complete_stock_lane() -> None:
    db = _ProjectionDb(
        {
            "600001": [
                {
                    "symbol": "600001",
                    "asset_class": "stock",
                    "trade_date": "2026-08-26",
                    "timestamp": "2026-08-26T15:00:00+08:00",
                    "price": 11.0,
                    "source": "market_bars",
                },
                {
                    "symbol": "600001",
                    "asset_class": "stock",
                    "trade_date": "2026-08-27",
                    "timestamp": "2026-08-27T15:00:00+08:00",
                    "price": 12.0,
                    "source": "market_bars",
                },
            ],
            "019999": [
                {
                    "symbol": "019999",
                    "asset_class": "fund",
                    "trade_date": "2026-08-26",
                    "timestamp": "2026-08-26T14:57:00+08:00",
                    "price": 2.25,
                    "source": "eastmoney_fund_estimate",
                },
                {
                    "symbol": "019999",
                    "asset_class": "fund",
                    "trade_date": "2026-08-27",
                    "timestamp": "2026-08-27T14:57:00+08:00",
                    "price": 2.26,
                    "source": "eastmoney_fund_estimate",
                },
            ],
        }
    )
    db.get_all_ledger_entries_sync = lambda: [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-08-26T09:00:00+08:00",
            "amount": 1000.0,
            "asset_class": "cash",
            "source": "manual",
        },
        {
            "id": 2,
            "entry_type": "trade_buy",
            "timestamp": "2026-08-26T10:00:00+08:00",
            "symbol": "600001",
            "direction": "buy",
            "quantity": 10.0,
            "price": 10.0,
            "commission": 0.0,
            "asset_class": "stock",
            "source": "manual",
        },
        {
            "id": 3,
            "entry_type": "trade_buy",
            "timestamp": "2026-08-26T10:05:00+08:00",
            "symbol": "019999",
            "direction": "buy",
            "quantity": 100.0,
            "price": 2.0,
            "commission": 0.0,
            "asset_class": "fund",
            "source": "manual",
        },
    ]

    points = build_daily_equity_series_from_ledger_history(
        SimpleNamespace(db=db),
        selected_range="all",
        current_point=_current_point(),
        now=datetime(2026, 8, 27, 15, 1, tzinfo=_SHANGHAI),
    )

    assert [point.stocks for point in points] == pytest.approx([110.0, 120.0])
    assert [point.funds for point in points] == [None, None]
    assert [point.others for point in points] == pytest.approx([0.0, 0.0])
    assert [point.total for point in points] == [None, None]
    assert all(point.unrealized_pnl is None for point in points)
    assert all(point.quote_status == "confirmed_nav_missing" for point in points)
    assert all(point.missing_price_symbols == ["019999"] for point in points)


def test_historical_projection_rejects_unresolved_instrument_type() -> None:
    db = _ProjectionDb({})
    rows = _ledger_rows()
    rows[1] = {**rows[1], "asset_class": ""}
    db.get_all_ledger_entries_sync = lambda: rows

    with pytest.raises(ValueError, match="instrument type is unresolved: missing"):
        build_daily_equity_series_from_ledger_history(
            SimpleNamespace(db=db),
            selected_range="all",
            current_point=_current_point(),
            now=datetime(2026, 8, 27, 15, 1, tzinfo=_SHANGHAI),
        )
