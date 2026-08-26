"""Canonical portfolio historical series projections."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from server.ledger.models import LedgerEntry
from server.models import (
    EquityPoint,
    EquitySeriesPoint,
)
from server.projections.portfolio_views.historical_ledger_series import (
    build_daily_equity_series_from_ledger_history,
    equity_series_bucket,
    historical_quote_for_equity_day,
    ledger_entry_timestamp,
    load_ledger_entries_for_equity_series,
    quote_valuation_date,
)
from server.projections.portfolio_views.intraday_series import (
    build_cn_session_ticks,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.market_hours import get_shanghai_now
from server.services.valuation_snapshot import (
    valuation_identity_fields,
)

_CN_AFTERNOON_CLOSE = time(15, 0)

_SH_TZ = ZoneInfo("Asia/Shanghai")

_EQUITY_SERIES_RANGE_DAYS = {
    "5d": 5,
    "1m": 31,
    "6m": 183,
    "1y": 366,
}

_CAPITAL_INFLOW_LEDGER_TYPES = {"cash_deposit", "deposit"}

_CAPITAL_OUTFLOW_LEDGER_TYPES = {"cash_withdrawal", "cash_withdraw", "withdraw"}


def daily_equity_series_for_range(
    points: list[EquitySeriesPoint],
    selected_range: str,
) -> list[EquitySeriesPoint]:
    """Materialize sparse ledger valuation points into day-level chart points."""

    if selected_range == "1d" or len(points) < 2:
        return points

    parsed_points = [
        (timestamp, point)
        for point in points
        if (timestamp := _parse_quote_timestamp(point.timestamp)) is not None
    ]
    if len(parsed_points) < 2:
        return points

    parsed_points.sort(key=lambda item: item[0])
    end_timestamp = parsed_points[-1][0]
    range_days = _EQUITY_SERIES_RANGE_DAYS.get(selected_range)
    if range_days is None:
        start_timestamp = parsed_points[0][0]
    else:
        start_timestamp = end_timestamp - timedelta(days=range_days)

    start_date = start_timestamp.date()
    end_date = end_timestamp.date()
    event_index = 0
    active_point: EquitySeriesPoint | None = None

    while (
        event_index < len(parsed_points)
        and parsed_points[event_index][0] <= start_timestamp
    ):
        active_point = parsed_points[event_index][1]
        event_index += 1

    daily_points: list[EquitySeriesPoint] = []
    current_date = start_date
    while current_date <= end_date:
        day_end = datetime.combine(
            current_date,
            time(23, 59, 59),
            tzinfo=end_timestamp.tzinfo or _SH_TZ,
        )
        while (
            event_index < len(parsed_points)
            and parsed_points[event_index][0] <= day_end
        ):
            active_point = parsed_points[event_index][1]
            event_index += 1

        is_range_start = current_date == start_date
        is_range_end = current_date == end_date
        is_trading_day = current_date.weekday() < 5
        should_emit_day = is_range_start or is_trading_day
        if active_point is not None and should_emit_day:
            point_timestamp = (
                end_timestamp
                if is_range_end
                else datetime.combine(
                    current_date,
                    _CN_AFTERNOON_CLOSE,
                    tzinfo=end_timestamp.tzinfo or _SH_TZ,
                )
            )
            daily_points.append(
                active_point.model_copy(
                    update={"timestamp": point_timestamp.isoformat()}
                )
            )

        current_date += timedelta(days=1)

    return daily_points or points


def equity_points_from_series(
    points: list[EquitySeriesPoint],
) -> list[EquityPoint]:
    by_date: dict[str, EquityPoint] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        if point.total is None:
            continue
        by_date[point_date] = EquityPoint(
            timestamp=point.timestamp,
            equity=float(point.total),
        )
    return list(by_date.values())


def ledger_capital_flow_amount(entry: LedgerEntry) -> Decimal | None:
    entry_type = (entry.entry_type or "").strip().lower()
    if entry_type not in _CAPITAL_INFLOW_LEDGER_TYPES | _CAPITAL_OUTFLOW_LEDGER_TYPES:
        return None
    if entry.amount is None:
        return None
    amount = Decimal(str(entry.amount))
    if entry_type in _CAPITAL_OUTFLOW_LEDGER_TYPES:
        return -amount
    return amount


def cash_flow_adjusted_equity_points_from_series(
    state,
    points: list[EquitySeriesPoint],
) -> list[EquityPoint]:
    raw_points = equity_points_from_series(points)
    if len(raw_points) < 2:
        return raw_points

    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return raw_points

    by_date: dict[str, EquitySeriesPoint] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if point_date and point.total is not None:
            by_date[point_date] = point

    parsed_points = [
        (timestamp, point)
        for point in by_date.values()
        if (timestamp := _parse_quote_timestamp(point.timestamp)) is not None
    ]
    parsed_points.sort(key=lambda item: item[0])
    if len(parsed_points) < 2:
        return raw_points

    try:
        ledger_entries = load_ledger_entries_for_equity_series(db)
    except (KeyError, TypeError, ValueError):
        return raw_points

    flow_events = []
    for entry in ledger_entries:
        timestamp = ledger_entry_timestamp(entry)
        amount = ledger_capital_flow_amount(entry)
        if timestamp is not None and amount is not None:
            flow_events.append((timestamp, amount))
    flow_events.sort(key=lambda item: item[0])

    event_index = 0
    first_timestamp, first_point = parsed_points[0]
    initial_units = Decimal("0")
    while (
        event_index < len(flow_events)
        and flow_events[event_index][0] <= first_timestamp
    ):
        initial_units += flow_events[event_index][1]
        event_index += 1

    first_total = Decimal(str(first_point.total))
    if initial_units <= 0 or first_total <= 0:
        return raw_points

    units = initial_units
    unit_price = first_total / units
    unitized_points: list[tuple[EquitySeriesPoint, Decimal]] = [
        (first_point, unit_price)
    ]

    last_parsed_index = len(parsed_points) - 1
    for point_index, (timestamp, point) in enumerate(parsed_points[1:], start=1):
        period_flow = Decimal("0")
        while (
            event_index < len(flow_events) and flow_events[event_index][0] <= timestamp
        ):
            period_flow += flow_events[event_index][1]
            event_index += 1
        if point_index == last_parsed_index:
            while event_index < len(flow_events):
                period_flow += flow_events[event_index][1]
                event_index += 1

        total = Decimal(str(point.total))
        pre_flow_equity = total - period_flow
        if units <= 0 or pre_flow_equity <= 0:
            return raw_points

        unit_price = pre_flow_equity / units
        if unit_price <= 0:
            return raw_points
        units += period_flow / unit_price
        if units <= 0:
            return raw_points

        unitized_points.append((point, unit_price))

    latest_units = units
    return [
        EquityPoint(
            timestamp=point.timestamp,
            equity=float(unit_price * latest_units),
        )
        for point, unit_price in unitized_points
    ]


def trim_non_trading_terminal_series_point(
    points: list[EquitySeriesPoint],
) -> list[EquitySeriesPoint]:
    if len(points) < 2:
        return points
    timestamp = _parse_quote_timestamp(points[-1].timestamp)
    if timestamp is not None and timestamp.weekday() >= 5:
        return points[:-1]
    previous_timestamp = _parse_quote_timestamp(points[-2].timestamp)
    if (
        points[-1].quote_status == "stale"
        and timestamp is not None
        and previous_timestamp is not None
        and timestamp.date() > previous_timestamp.date()
    ):
        return points[:-1]
    return points


def trim_intraday_terminal_series_point(
    points: list[EquitySeriesPoint],
    *,
    now: datetime | None = None,
) -> list[EquitySeriesPoint]:
    if len(points) < 2:
        return points
    timestamp = _parse_quote_timestamp(points[-1].timestamp)
    if timestamp is None:
        return points
    point_date = timestamp.astimezone(_SH_TZ).date()
    point_time = timestamp.astimezone(_SH_TZ).time().replace(tzinfo=None)
    valuation_trade_date = points[-1].valuation_trade_date
    if valuation_trade_date:
        if (
            valuation_trade_date != point_date.isoformat()
            and point_time != _CN_AFTERNOON_CLOSE
        ):
            return points[:-1]
        return points
    current = (now or get_shanghai_now()).astimezone(_SH_TZ)
    if point_date == current.date() and point_time != _CN_AFTERNOON_CLOSE:
        return points[:-1]
    return points


def equity_series_status_rank(status: str | None) -> int:
    if status in {"missing", "error"}:
        return 0
    if status == "stale":
        return 1
    return 2


def dedupe_equity_series_points_by_date(
    points: list[EquitySeriesPoint],
) -> list[EquitySeriesPoint]:
    by_date: dict[str, EquitySeriesPoint] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        existing = by_date.get(point_date)
        if existing is None:
            by_date[point_date] = point
            continue
        existing_timestamp = _parse_quote_timestamp(existing.timestamp)
        point_timestamp = _parse_quote_timestamp(point.timestamp)
        existing_score = (
            1 if existing.valuation_snapshot_id else 0,
            equity_series_status_rank(existing.quote_status),
            existing_timestamp or datetime.min.replace(tzinfo=_SH_TZ),
        )
        point_score = (
            1 if point.valuation_snapshot_id else 0,
            equity_series_status_rank(point.quote_status),
            point_timestamp or datetime.min.replace(tzinfo=_SH_TZ),
        )
        if point_score >= existing_score:
            by_date[point_date] = point
    return [by_date[day] for day in sorted(by_date)]


def equity_series_metadata_by_date(
    points: list[EquitySeriesPoint],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    valuation_status_by_date: dict[str, str] = {}
    missing_symbols_by_date: dict[str, list[str]] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        valuation_status_by_date[point_date] = point.quote_status
        missing_symbols = getattr(point, "missing_price_symbols", None)
        if missing_symbols:
            missing_symbols_by_date[point_date] = list(missing_symbols)
    return valuation_status_by_date, missing_symbols_by_date


def daily_equity_series_from_ledger_history(
    state,
    *,
    selected_range: str,
    current_point: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    return build_daily_equity_series_from_ledger_history(
        state,
        selected_range=selected_range,
        current_point=current_point,
        now=get_shanghai_now(),
    )


def flat_intraday_equity_series_from_current(
    current: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if current is None:
        return []

    current_timestamp = _parse_quote_timestamp(current.timestamp) or get_shanghai_now()
    ticks = build_cn_session_ticks(
        current_timestamp.date(),
        current_timestamp.tzinfo or _SH_TZ,
        full_session=True,
    )
    if not ticks:
        return [current]

    return [
        current.model_copy(update={"timestamp": tick.isoformat()}) for tick in ticks
    ]


def bind_equity_series_valuation(
    points: list[EquitySeriesPoint],
    valuation_snapshot: dict,
) -> list[EquitySeriesPoint]:
    identity = valuation_identity_fields(valuation_snapshot)
    return [point.model_copy(update=identity) for point in points]


def bind_current_equity_valuation(
    point: EquitySeriesPoint | None,
    valuation_snapshot: dict,
) -> EquitySeriesPoint | None:
    if point is None:
        return None
    return point.model_copy(
        update={
            "timestamp": valuation_snapshot["as_of"],
            **valuation_identity_fields(valuation_snapshot),
        }
    )


def equity_series_matches_valuation(
    points: list[EquitySeriesPoint],
    valuation_snapshot_id: str | None,
) -> bool:
    if not points:
        return True
    return points[-1].valuation_snapshot_id == valuation_snapshot_id


__all__ = (
    "bind_current_equity_valuation",
    "bind_equity_series_valuation",
    "cash_flow_adjusted_equity_points_from_series",
    "daily_equity_series_for_range",
    "daily_equity_series_from_ledger_history",
    "dedupe_equity_series_points_by_date",
    "equity_points_from_series",
    "equity_series_bucket",
    "equity_series_matches_valuation",
    "equity_series_metadata_by_date",
    "equity_series_status_rank",
    "flat_intraday_equity_series_from_current",
    "historical_quote_for_equity_day",
    "ledger_capital_flow_amount",
    "ledger_entry_timestamp",
    "load_ledger_entries_for_equity_series",
    "quote_valuation_date",
    "trim_intraday_terminal_series_point",
    "trim_non_trading_terminal_series_point",
)
