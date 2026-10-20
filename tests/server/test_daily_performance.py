from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.services.account.daily_performance import (
    build_position_daily_context,
    calculate_account_daily_performance,
    mark_position_daily,
    price_at_tick,
)


def test_partial_same_day_add_has_one_after_cost_baseline():
    tz = ZoneInfo("Asia/Shanghai")
    context = build_position_daily_context(
        quantity=400,
        previous_close=25.46,
        same_day_buy_lots=[
            {
                "timestamp": datetime(2026, 7, 10, 10, 0, tzinfo=tz),
                "quantity": 300,
                "price": 24.95,
                "total_cost": 300 * 24.95 + 5.07485,
            }
        ],
    )
    mark = mark_position_daily(context, price=24.60)

    assert context.overnight_quantity == 100
    assert context.baseline_value == pytest.approx(100 * 25.46 + 300 * 24.95 + 5.07485)
    assert context.source == "mixed_previous_close_intraday_trade_cost"
    assert mark.today_change == pytest.approx(-196.07485)


def test_intraday_cutoff_uses_same_context_and_trade_timing():
    tz = ZoneInfo("Asia/Shanghai")
    trade_at = datetime(2026, 7, 10, 10, 0, tzinfo=tz)
    context = build_position_daily_context(
        quantity=400,
        previous_close=25.46,
        same_day_buy_lots=[
            {
                "timestamp": trade_at,
                "quantity": 300,
                "price": 24.95,
                "total_cost": 300 * 24.95 + 5.07485,
            }
        ],
    )

    before = mark_position_daily(
        context,
        price=price_at_tick(
            context,
            tick=datetime(2026, 7, 10, 9, 30, tzinfo=tz),
            quote_points=[],
        ),
        at=datetime(2026, 7, 10, 9, 30, tzinfo=tz),
    )
    after = mark_position_daily(
        context,
        price=price_at_tick(context, tick=trade_at, quote_points=[]),
        at=trade_at,
    )

    assert before.active_quantity == 100
    assert before.today_change == pytest.approx(0)
    assert after.active_quantity == 400
    assert after.today_change == pytest.approx(-56.07485)


def test_same_day_sell_uses_net_proceeds_against_overnight_close():
    tz = ZoneInfo("Asia/Shanghai")
    sell = build_position_daily_context(
        quantity=0,
        previous_close=10.0,
        same_day_buy_lots=[],
        same_day_sell_lots=[
            {
                "timestamp": datetime(2026, 8, 17, 10, 0, tzinfo=tz),
                "quantity": 100,
                "price": 11.0,
                "net_proceeds": 1095.0,
            }
        ],
    )
    mark = mark_position_daily(sell, price=11.0)

    assert sell.overnight_quantity == 100
    assert sell.baseline_value == pytest.approx(1000)
    assert sell.source == "previous_close_intraday_sell"
    assert mark.active_quantity == 0
    assert mark.today_change == pytest.approx(95)
    assert mark.today_change_pct == pytest.approx(1095 / 1000 - 1)


def test_same_day_sell_without_overnight_close_still_fails_closed():
    tz = ZoneInfo("Asia/Shanghai")
    missing = build_position_daily_context(
        quantity=0,
        previous_close=None,
        same_day_buy_lots=[],
        same_day_sell_lots=[
            {
                "timestamp": datetime(2026, 8, 17, 10, 0, tzinfo=tz),
                "quantity": 100,
                "price": 11.0,
                "net_proceeds": 1095.0,
            }
        ],
    )

    assert mark_position_daily(missing, price=11.0).today_change is None
    assert missing.source == "overnight_baseline_unavailable"


def test_partial_same_day_sell_combines_remaining_mark_and_net_proceeds():
    tz = ZoneInfo("Asia/Shanghai")
    context = build_position_daily_context(
        quantity=300,
        previous_close=25.46,
        same_day_buy_lots=[],
        same_day_sell_lots=[
            {
                "timestamp": datetime(2026, 7, 10, 13, 44, tzinfo=tz),
                "quantity": 100,
                "price": 24.95,
                "net_proceeds": 2490,
            }
        ],
    )
    mark = mark_position_daily(context, price=24.60)

    assert context.overnight_quantity == 400
    assert mark.active_quantity == 300
    assert mark.current_value == pytest.approx(7380)
    assert mark.today_change == pytest.approx(7380 + 2490 - 400 * 25.46)


def test_account_daily_equation_is_canonical_and_exposes_market_move():
    performance = calculate_account_daily_performance(
        starting_equity=30046.0,
        ending_equity=29849.92515,
        external_flow=0.0,
    )

    assert performance.equity_delta == pytest.approx(-196.07485)
    assert performance.market_move == pytest.approx(-196.07485)
    assert (
        performance.equity_delta == performance.external_flow + performance.market_move
    )


@pytest.mark.parametrize(
    (
        "opening_quantity",
        "sell_quantity",
        "sell_first",
        "latest_price",
        "previous_close",
        "expected",
    ),
    [
        pytest.param(0, 100, False, 11.0, 9.0, 90.0, id="etf-full-round-trip"),
        pytest.param(0, 40, False, 12.0, 9.0, 150.0, id="etf-partial-sale"),
        pytest.param(100, 100, False, 12.0, 9.0, 390.0, id="overnight-and-today-buys"),
        pytest.param(100, 100, True, 12.0, 9.0, 390.0, id="sell-overnight-then-buy"),
        pytest.param(
            0, 100, False, None, None, 90.0, id="closed-no-quote-or-overnight-baseline"
        ),
    ],
)
def test_etf_daily_pnl_uses_complete_real_ledger_trade_flows(
    tmp_path,
    opening_quantity,
    sell_quantity,
    sell_first,
    latest_price,
    previous_close,
    expected,
):
    from types import SimpleNamespace

    from server.contracts.ledger_mutations import LedgerAppendCommand, LedgerEntryDraft
    from server.db import AppDatabase
    from server.projections.portfolio_positions import resolve_position_today_change

    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    entries = [
        {
            "entry_type": "cash_deposit",
            "amount": 5000.0,
            "asset_class": "cash",
            "timestamp": "2026-10-13T09:00:00+08:00",
        }
    ]
    if opening_quantity:
        entries.append(
            {
                "entry_type": "trade_buy",
                "direction": "buy",
                "quantity": float(opening_quantity),
                "price": 8.0,
                "commission": 5.0,
                "amount": opening_quantity * 8.0,
                "gross_amount": opening_quantity * 8.0,
                "net_cash_impact": -(opening_quantity * 8.0 + 5.0),
                "timestamp": "2026-10-12T14:00:00+08:00",
                "symbol": "518880",
                "asset_class": "etf",
            }
        )
    entries.extend(
        [
            {
                "entry_type": "trade_buy",
                "direction": "buy",
                "quantity": 100.0,
                "price": 10.0,
                "commission": 5.0,
                "amount": 1000.0,
                "gross_amount": 1000.0,
                "net_cash_impact": -1005.0,
                "timestamp": f"2026-10-13T{'11' if sell_first else '10'}:00:00+08:00",
                "symbol": "518880",
                "asset_class": "etf",
            },
            {
                "entry_type": "trade_sell",
                "direction": "sell",
                "quantity": float(sell_quantity),
                "price": 11.0,
                "commission": 5.0,
                "amount": sell_quantity * 11.0,
                "gross_amount": sell_quantity * 11.0,
                "net_cash_impact": sell_quantity * 11.0 - 5.0,
                "timestamp": f"2026-10-13T{'10' if sell_first else '11'}:00:00+08:00",
                "symbol": "518880",
                "asset_class": "etf",
            },
        ]
    )
    for index, entry in enumerate(entries):
        db.append_ledger_entry_sync(
            LedgerAppendCommand(
                operator_id="sanitized-operator",
                request_id=f"daily-flow-{index}",
                entry=LedgerEntryDraft(
                    **entry, source="sanitized_fixture", source_ref=str(index)
                ),
            )
        )

    reopened = AppDatabase(db_path)
    reopened.init_sync()
    ledger_rows = reopened.get_all_ledger_entries_sync()
    quote = (
        {
            "symbol": "518880",
            "instrument_type": "etf",
            "asset_class": "fund",
            "price": latest_price,
            "previous_close": previous_close,
            "previous_close_date": "2026-10-12",
            "quote_timestamp": "2026-10-13T15:00:00+08:00",
            "quote_source": "synthetic_exchange_quote",
            "quote_status": "live",
        }
        if latest_price is not None
        else None
    )
    result = resolve_position_today_change(
        SimpleNamespace(db=reopened, scheduler=None),
        symbol="518880",
        quantity=opening_quantity + 100 - sell_quantity,
        avg_cost=0.0,
        latest_quote=quote,
        latest_price_value=latest_price,
        instrument_type="etf",
        ledger_entries=ledger_rows,
        now=datetime(2026, 10, 13, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result[0] == pytest.approx(expected)
    assert result[1] == pytest.approx(expected / (opening_quantity * 9.0 + 1005.0))
    assert result[-1] == "mixed_previous_close_intraday_trades"
    assert reopened.get_all_ledger_entries_sync() == ledger_rows


@pytest.mark.parametrize("sell_first", [False, True])
def test_intraday_marks_keep_all_trade_costs_and_actual_trade_timing(sell_first):
    tz = ZoneInfo("Asia/Shanghai")
    buy_at = datetime(2026, 10, 13, 11 if sell_first else 10, tzinfo=tz)
    sell_at = datetime(2026, 10, 13, 10 if sell_first else 11, tzinfo=tz)
    opening_quantity = 100 if sell_first else 0
    context = build_position_daily_context(
        quantity=opening_quantity,
        previous_close=9.0 if opening_quantity else None,
        same_day_buy_lots=[
            {"timestamp": buy_at, "quantity": 100, "price": 10, "total_cost": 1005}
        ],
        same_day_sell_lots=[
            {"timestamp": sell_at, "quantity": 100, "price": 11, "net_proceeds": 1095}
        ],
    )
    first = min(buy_at, sell_at)
    first_price = 11.0 if sell_first else 10.0
    during = mark_position_daily(context, price=first_price, at=first)
    final = mark_position_daily(context, price=12.0)

    assert context.overnight_quantity == opening_quantity
    assert during.active_quantity == (0 if sell_first else 100)
    assert during.today_change == pytest.approx(195 if sell_first else -5)
    assert final.today_change == pytest.approx(390 if sell_first else 90)


@pytest.mark.parametrize("sell_before_buy", [False, True])
def test_inconsistent_daily_trade_inventory_fails_closed(sell_before_buy):
    tz = ZoneInfo("Asia/Shanghai")
    buy_at = datetime(2026, 10, 13, 11, tzinfo=tz)
    context = build_position_daily_context(
        quantity=0,
        previous_close=9,
        same_day_buy_lots=[
            {"timestamp": buy_at, "quantity": 100, "price": 10, "total_cost": 1005}
        ],
        same_day_sell_lots=(
            [
                {
                    "timestamp": datetime(2026, 10, 13, 10, tzinfo=tz),
                    "quantity": 100,
                    "price": 11,
                    "net_proceeds": 1095,
                }
            ]
            if sell_before_buy
            else []
        ),
    )
    mark = mark_position_daily(context, price=12)

    assert context.status == "unavailable"
    assert mark.today_change is None
    assert mark.source == "daily_trade_inventory_conflict"


def test_same_timestamp_buy_and_sell_does_not_invent_trade_order():
    timestamp = datetime(2026, 10, 13, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    context = build_position_daily_context(
        quantity=0,
        previous_close=None,
        same_day_buy_lots=[
            {"timestamp": timestamp, "quantity": 100, "price": 10, "total_cost": 1005}
        ],
        same_day_sell_lots=[
            {"timestamp": timestamp, "quantity": 100, "price": 11, "net_proceeds": 1095}
        ],
    )
    mark = mark_position_daily(context, price=None)

    assert context.status == "complete"
    assert context.overnight_quantity == 0
    assert mark.active_quantity == 0
    assert mark.today_change == pytest.approx(90)
