from __future__ import annotations

import pytest

from server.services.market_quote_ingestion import build_quote_ingestion_command

pytestmark = pytest.mark.unit


def _command(
    snapshot: dict[str, object],
    *,
    captured_at: str,
    daily_close_price: float | None = None,
    daily_close_date: str | None = None,
    daily_close_source: str | None = None,
):
    return build_quote_ingestion_command(
        symbol="002594",
        asset_type="stock",
        snapshot=snapshot,
        quote_source="tushare_realtime_quote",
        provider_name="tushare",
        provider_status="live",
        quote_status="live",
        captured_reason="test",
        fetch_run_id=None,
        captured_at=captured_at,
        daily_close_price=daily_close_price,
        daily_close_date=daily_close_date,
        daily_close_source=daily_close_source,
    )


def test_same_session_previous_close_date_is_not_materialized_as_daily_close() -> None:
    command = _command(
        {
            "price": 87.40,
            "timestamp": "2026-09-04T09:36:00+08:00",
            "previous_close": 87.31,
            # Regression: realtime DATE is the current quote session, not the
            # session that owns PRE_CLOSE.
            "previous_close_date": "2026-09-04",
        },
        captured_at="2026-09-04T09:36:01+08:00",
    )

    assert command.previous_close == 87.31
    assert command.previous_close_date is None
    assert command.daily_close_price is None
    assert command.daily_close_date is None
    assert command.daily_close_source is None
    assert command.metadata["discarded_previous_close_date"] == "2026-09-04"
    assert command.metadata["discarded_previous_close_date_reason"] == (
        "not_strictly_before_quote_trade_date"
    )


def test_prior_session_previous_close_is_preserved_as_daily_close_evidence() -> None:
    command = _command(
        {
            "price": 87.40,
            "timestamp": "2026-09-04T09:36:00+08:00",
            "previous_close": 87.31,
            "previous_close_date": "2026-09-03",
        },
        captured_at="2026-09-04T09:36:01+08:00",
    )

    assert command.previous_close == 87.31
    assert command.previous_close_date == "2026-09-03"
    assert command.daily_close_price == 87.31
    assert command.daily_close_date == "2026-09-03"
    assert command.daily_close_source == "reported_previous_close"
    assert "discarded_previous_close_date" not in command.metadata


def test_explicit_verified_same_day_close_bypasses_previous_close_guard() -> None:
    command = _command(
        {
            "price": 87.40,
            "timestamp": "2026-09-04T15:00:00+08:00",
            "previous_close": 87.31,
            "previous_close_date": "2026-09-04",
        },
        captured_at="2026-09-04T15:00:01+08:00",
        daily_close_price=87.40,
        daily_close_date="2026-09-04",
        daily_close_source="market_bar_close",
    )

    assert command.previous_close_date is None
    assert command.daily_close_price == 87.40
    assert command.daily_close_date == "2026-09-04"
    assert command.daily_close_source == "market_bar_close"
