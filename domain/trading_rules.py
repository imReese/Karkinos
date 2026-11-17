"""A-share trading rules, order size requirements, and price limit resolver.

Deterministic, provider-independent rules governing trading permissions, board
lot sizes, odd-lot liquidation, and point-in-time price limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from core.types import ZERO, InstrumentType, OrderSide
from domain.a_share_limits import (
    GROWTH_BOARD_RATE,
    MAIN_BOARD_RATE,
    ST_RATE,
    limit_down_price,
    limit_up_price,
    normalize_code,
)
from domain.instrument import Instrument, a_share_identity

A_SHARE_TRADING_RULES_POLICY_ID = "karkinos.a_share.trading_rules.v1"

STAR_LAUNCH_DATE = date(2019, 7, 22)
CHINEXT_REFORM_DATE = date(2020, 8, 24)
BSE_OPEN_DATE = date(2021, 11, 15)
MAIN_BOARD_REFORM_DATE = date(2023, 4, 10)


@dataclass(frozen=True)
class TradingRule:
    """Trading rule and constraints for an instrument on a specific session."""

    rule_id: str
    symbol: str
    exchange: str
    board: str
    is_tradable: bool
    status: str  # "tradable", "suspended", "not_yet_listed", "delisting", "unverified_state", "unsupported"
    blocker_reason: str | None
    limit_pct: Decimal | None  # None indicates no price limit (e.g. IPO initial days)
    has_price_limit: bool
    price_tick: Decimal
    min_order_qty: Decimal
    qty_step: Decimal
    allow_buy: bool
    allow_sell: bool


def resolve_trading_rules(
    symbol: str,
    session_date: date,
    *,
    instrument: Instrument | None = None,
    is_st: bool | None = None,
    listing_date: date | None = None,
    delist_date: date | None = None,
    listing_session_count: int | None = None,
    is_suspended_override: bool | None = None,
    trade_status: str | None = None,
    display_name: str | None = None,
) -> TradingRule:
    """Resolve applicable trading rules for a security on a trading date."""
    if isinstance(session_date, datetime):
        session_date = session_date.date()

    clean_code = normalize_code(symbol)
    identity = a_share_identity(clean_code)

    if identity is None:
        # Non-stock or non-A-share instrument fallback
        if instrument is not None and instrument.instrument_type is InstrumentType.ETF:
            return TradingRule(
                rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                symbol=symbol,
                exchange="SSE" if clean_code.startswith("5") else "SZSE",
                board="etf",
                is_tradable=not is_suspended_override,
                status="suspended" if is_suspended_override else "tradable",
                blocker_reason="nontrading_session_excluded"
                if is_suspended_override
                else None,
                limit_pct=instrument.limit_pct
                if instrument.limit_pct > ZERO
                else Decimal("0.10"),
                has_price_limit=instrument.limit_pct > ZERO,
                price_tick=instrument.price_tick or Decimal("0.001"),
                min_order_qty=instrument.lot_size or Decimal("100"),
                qty_step=instrument.lot_size or Decimal("100"),
                allow_buy=not is_suspended_override,
                allow_sell=not is_suspended_override,
            )
        if instrument is not None:
            has_limit = instrument.limit_pct > ZERO
            return TradingRule(
                rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                symbol=symbol,
                exchange="UNKNOWN",
                board="generic",
                is_tradable=not is_suspended_override,
                status="suspended" if is_suspended_override else "tradable",
                blocker_reason="nontrading_session_excluded"
                if is_suspended_override
                else None,
                limit_pct=instrument.limit_pct if has_limit else None,
                has_price_limit=has_limit,
                price_tick=instrument.price_tick or Decimal("0.01"),
                min_order_qty=instrument.lot_size or Decimal("100"),
                qty_step=instrument.lot_size or Decimal("100"),
                allow_buy=not is_suspended_override,
                allow_sell=not is_suspended_override,
            )
        return TradingRule(
            rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
            symbol=symbol,
            exchange="UNKNOWN",
            board="unsupported",
            is_tradable=False,
            status="unsupported",
            blocker_reason="unsupported_instrument",
            limit_pct=None,
            has_price_limit=False,
            price_tick=Decimal("0.01"),
            min_order_qty=Decimal("100"),
            qty_step=Decimal("100"),
            allow_buy=False,
            allow_sell=False,
        )

    board = identity["board"]
    exchange = identity["exchange"]

    # Listing & Delisting checks
    if listing_date is not None and session_date < listing_date:
        return TradingRule(
            rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
            symbol=symbol,
            exchange=exchange,
            board=board,
            is_tradable=False,
            status="not_yet_listed",
            blocker_reason="not_yet_listed_excluded",
            limit_pct=None,
            has_price_limit=False,
            price_tick=Decimal("0.01"),
            min_order_qty=Decimal("200") if board == "star" else Decimal("100"),
            qty_step=Decimal("200") if board == "star" else Decimal("100"),
            allow_buy=False,
            allow_sell=False,
        )

    if delist_date is not None and session_date >= delist_date:
        return TradingRule(
            rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
            symbol=symbol,
            exchange=exchange,
            board=board,
            is_tradable=False,
            status="delisted",
            blocker_reason="inactive_listing_excluded",
            limit_pct=None,
            has_price_limit=False,
            price_tick=Decimal("0.01"),
            min_order_qty=Decimal("200") if board == "star" else Decimal("100"),
            qty_step=Decimal("200") if board == "star" else Decimal("100"),
            allow_buy=False,
            allow_sell=False,
        )

    # Suspension check
    if is_suspended_override is True or trade_status == "0":
        return TradingRule(
            rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
            symbol=symbol,
            exchange=exchange,
            board=board,
            is_tradable=False,
            status="suspended",
            blocker_reason="nontrading_session_excluded",
            limit_pct=Decimal("0.10"),
            has_price_limit=True,
            price_tick=Decimal("0.01"),
            min_order_qty=Decimal("200") if board == "star" else Decimal("100"),
            qty_step=Decimal("200") if board == "star" else Decimal("100"),
            allow_buy=False,
            allow_sell=False,
        )

    # Delisting period check ("退" in name)
    name = (display_name or (instrument.name if instrument else "")).strip()
    if name and "退" in name:
        return TradingRule(
            rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
            symbol=symbol,
            exchange=exchange,
            board=board,
            is_tradable=False,
            status="delisting",
            blocker_reason="delisting_period_excluded",
            limit_pct=Decimal("0.10"),
            has_price_limit=True,
            price_tick=Decimal("0.01"),
            min_order_qty=Decimal("200") if board == "star" else Decimal("100"),
            qty_step=Decimal("200") if board == "star" else Decimal("100"),
            allow_buy=False,
            allow_sell=False,
        )

    # Infer ST if not provided
    if is_st is None and name:
        import re

        upper_name = name.upper()
        # A-share ST indicators: ST, *ST, SST, S*ST followed by space or non-ASCII (e.g. Chinese)
        # Avoid matching English words like "Stock", "Strategy", "Steel"
        if re.search(r"(?:^|[\s*])S?\*?ST(?:[\s*]|$|[^\x00-\x7F])", upper_name):
            is_st = True

    # IPO Initial days price limit exemption (registration reform)
    is_initial_period = False
    if listing_session_count is not None:
        initial_sessions = 1 if board == "beijing" else 5
        if listing_session_count <= initial_sessions:
            if board == "star" and session_date >= STAR_LAUNCH_DATE:
                is_initial_period = True
            elif board == "chinext" and session_date >= CHINEXT_REFORM_DATE:
                is_initial_period = True
            elif board == "beijing" and session_date >= BSE_OPEN_DATE:
                is_initial_period = True
            elif (
                board in {"sse_main", "szse_main"}
                and session_date >= MAIN_BOARD_REFORM_DATE
            ):
                is_initial_period = True

    # Price limit rate calculation
    if is_initial_period:
        has_price_limit = False
        limit_pct: Decimal | None = None
    else:
        has_price_limit = True
        if board in {"sse_main", "szse_main"}:
            limit_pct = ST_RATE if is_st else MAIN_BOARD_RATE
        elif board == "chinext":
            if session_date < CHINEXT_REFORM_DATE:
                limit_pct = ST_RATE if is_st else MAIN_BOARD_RATE
            else:
                limit_pct = GROWTH_BOARD_RATE
        elif board == "star":
            limit_pct = GROWTH_BOARD_RATE
        elif board == "beijing":
            limit_pct = Decimal("0.30")
        else:
            limit_pct = MAIN_BOARD_RATE

    # Lot size & Step
    if board == "star":
        min_order_qty = Decimal("200")
        qty_step = Decimal("200")
    else:
        min_order_qty = Decimal("100")
        qty_step = Decimal("100")

    return TradingRule(
        rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
        symbol=symbol,
        exchange=exchange,
        board=board,
        is_tradable=True,
        status="tradable",
        blocker_reason=None,
        limit_pct=limit_pct,
        has_price_limit=has_price_limit,
        price_tick=Decimal("0.01"),
        min_order_qty=min_order_qty,
        qty_step=qty_step,
        allow_buy=True,
        allow_sell=True,
    )


def validate_order_lot_size(
    rule: TradingRule,
    side: OrderSide,
    quantity: Decimal,
    *,
    available_qty: Decimal | None = None,
) -> tuple[bool, str | None]:
    """Validate order quantity against trading rule lot size requirements.

    Returns (passed, blocker_reason).
    """
    if quantity <= ZERO:
        return False, "quantity_must_be_positive"

    if side is OrderSide.BUY:
        if quantity < rule.min_order_qty:
            return False, "order_below_minimum_lot"
        if (quantity % rule.qty_step) != ZERO:
            return False, "order_not_multiple_of_lot_step"
        return True, None

    if side is OrderSide.SELL:
        if available_qty is not None:
            if quantity > available_qty:
                return False, "quantity_exceeds_available"
            # Odd-lot liquidation: If available is less than minimum lot,
            # must sell the entire available remainder in one order.
            if available_qty < rule.min_order_qty:
                if quantity != available_qty:
                    return False, "odd_lot_remainder_must_sell_all"
                return True, None
            # Selling all available shares is always allowed even if not round lots
            if quantity == available_qty:
                return True, None

        # Partial sell
        if quantity < rule.min_order_qty:
            return False, "order_below_minimum_lot"
        if (quantity % rule.qty_step) != ZERO:
            return False, "order_not_multiple_of_lot_step"
        return True, None


def calculate_price_limits(
    reference_price: Decimal,
    rule: TradingRule,
) -> tuple[Decimal | None, Decimal | None]:
    """Return (limit_down, limit_up) or (None, None) if no price limit applies."""
    if not rule.has_price_limit or rule.limit_pct is None:
        return None, None
    up = limit_up_price(reference_price, rule.limit_pct, tick=rule.price_tick)
    down = limit_down_price(reference_price, rule.limit_pct, tick=rule.price_tick)
    return down, up


def is_price_within_limits(
    price: Decimal,
    reference_price: Decimal,
    rule: TradingRule,
) -> bool:
    """Return True if price falls strictly within legal [limit_down, limit_up]."""
    if not rule.has_price_limit or rule.limit_pct is None:
        return True
    down, up = calculate_price_limits(reference_price, rule)
    if down is not None and price < down:
        return False
    if up is not None and price > up:
        return False
    return True
