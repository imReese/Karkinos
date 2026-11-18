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
SSE_SZSE_ST_REFORM_DATE = date(2026, 7, 6)

SUPPORTED_ETF_UNDERLYING: dict[str, str] = {
    # ChiNext ETFs -> 20% on/after 2020-08-24, 10% before
    "159915": "chinext",  # 易方达创业板ETF
    "159949": "chinext",  # 广发创业板ETF
    "159952": "chinext",  # 广发创业板200ETF
    "159977": "chinext",  # 天弘创业板300ETF
    # Main Board / Cross-market SZSE ETFs -> 10%
    "159919": "main",  # 嘉实沪深300ETF
    "159901": "main",  # 易方达深证100ETF
    "159902": "main",  # 华夏中小企业板ETF / 中小100ETF
    "159903": "main",  # 南方深证成份ETF
    "159905": "main",  # 工银瑞信深证红利ETF
    "159906": "main",  # 大成深证成长40ETF
    "159907": "main",  # 广发中小板300ETF
    "159908": "main",  # 博时深证基本面200ETF
    "159910": "main",  # 嘉实深证基本面120ETF
    "159920": "main",  # 华安MSCI中国A股ETF
    # Main Board / Cross-market SSE ETFs -> 10%
    "510050": "main",  # 华夏上证50ETF
    "510300": "main",  # 华泰柏瑞沪深300ETF
    "510500": "main",  # 南方中证500ETF
    "510880": "main",  # 华泰柏瑞红利ETF
}


def resolve_etf_limit_pct(
    clean_code: str,
    session_date: date,
    *,
    instrument: Instrument | None = None,
    strict_security_status: bool = False,
) -> tuple[Decimal | None, str | None]:
    """Resolve ETF price limit rate and classification status.

    Returns (limit_pct, blocker_reason).
    If unverified in strict mode, returns (None, 'etf_underlying_unverified').
    """
    # 1. SSE STAR Market ETFs (all 588xxx series officially track STAR market indices)
    if clean_code.startswith("588"):
        return Decimal("0.20"), None

    # 2. Supported / authoritative ETF classification registry
    underlying = SUPPORTED_ETF_UNDERLYING.get(clean_code)
    if underlying == "chinext":
        rate = (
            Decimal("0.20") if session_date >= CHINEXT_REFORM_DATE else Decimal("0.10")
        )
        return rate, None
    elif underlying == "main":
        return Decimal("0.10"), None
    elif underlying == "star":
        return Decimal("0.20"), None

    # 3. Explicit instrument limit_pct if provided
    if instrument is not None and instrument.limit_pct > ZERO:
        return instrument.limit_pct, None

    # 4. Unknown / unverified underlying
    if strict_security_status:
        return None, "etf_underlying_unverified"
    return Decimal("0.10"), None


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
    strict_security_status: bool = False,
) -> TradingRule:
    """Resolve applicable trading rules for a security on a trading date."""
    if isinstance(session_date, datetime):
        session_date = session_date.date()

    clean_code = normalize_code(symbol)
    identity = a_share_identity(clean_code)

    if identity is None:
        # Non-stock or non-A-share instrument fallback
        if instrument is not None and instrument.instrument_type is InstrumentType.ETF:
            exchange = "SSE" if clean_code.startswith("5") else "SZSE"
            price_tick = instrument.price_tick or Decimal("0.001")
            min_order_qty = instrument.lot_size or Decimal("100")
            qty_step = instrument.lot_size or Decimal("100")

            # In strict mode, verify explicit tradable status
            if strict_security_status:
                has_tradable_evidence = (
                    trade_status in ("1", "trade", "trading")
                    or is_suspended_override is False
                )
                if not has_tradable_evidence and (
                    is_suspended_override is not True and trade_status != "0"
                ):
                    return TradingRule(
                        rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                        symbol=symbol,
                        exchange=exchange,
                        board="etf",
                        is_tradable=False,
                        status="unverified_state",
                        blocker_reason="trading_state_unverified",
                        limit_pct=None,
                        has_price_limit=False,
                        price_tick=price_tick,
                        min_order_qty=min_order_qty,
                        qty_step=qty_step,
                        allow_buy=False,
                        allow_sell=False,
                    )

            if listing_date is not None and session_date < listing_date:
                return TradingRule(
                    rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                    symbol=symbol,
                    exchange=exchange,
                    board="etf",
                    is_tradable=False,
                    status="not_yet_listed",
                    blocker_reason="not_yet_listed_excluded",
                    limit_pct=None,
                    has_price_limit=False,
                    price_tick=price_tick,
                    min_order_qty=min_order_qty,
                    qty_step=qty_step,
                    allow_buy=False,
                    allow_sell=False,
                )

            if delist_date is not None and session_date >= delist_date:
                return TradingRule(
                    rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                    symbol=symbol,
                    exchange=exchange,
                    board="etf",
                    is_tradable=False,
                    status="delisted",
                    blocker_reason="inactive_listing_excluded",
                    limit_pct=None,
                    has_price_limit=False,
                    price_tick=price_tick,
                    min_order_qty=min_order_qty,
                    qty_step=qty_step,
                    allow_buy=False,
                    allow_sell=False,
                )

            if is_suspended_override is True or trade_status == "0":
                return TradingRule(
                    rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                    symbol=symbol,
                    exchange=exchange,
                    board="etf",
                    is_tradable=False,
                    status="suspended",
                    blocker_reason="nontrading_session_excluded",
                    limit_pct=Decimal("0.10"),
                    has_price_limit=True,
                    price_tick=price_tick,
                    min_order_qty=min_order_qty,
                    qty_step=qty_step,
                    allow_buy=False,
                    allow_sell=False,
                )

            etf_limit_pct, etf_blocker = resolve_etf_limit_pct(
                clean_code,
                session_date,
                instrument=instrument,
                strict_security_status=strict_security_status,
            )
            if etf_blocker is not None:
                return TradingRule(
                    rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                    symbol=symbol,
                    exchange=exchange,
                    board="etf",
                    is_tradable=False,
                    status="unverified_state",
                    blocker_reason=etf_blocker,
                    limit_pct=None,
                    has_price_limit=False,
                    price_tick=price_tick,
                    min_order_qty=min_order_qty,
                    qty_step=qty_step,
                    allow_buy=False,
                    allow_sell=False,
                )

            has_limit = etf_limit_pct is not None and etf_limit_pct > ZERO
            return TradingRule(
                rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                symbol=symbol,
                exchange=exchange,
                board="etf",
                is_tradable=True,
                status="tradable",
                blocker_reason=None,
                limit_pct=etf_limit_pct,
                has_price_limit=has_limit,
                price_tick=price_tick,
                min_order_qty=min_order_qty,
                qty_step=qty_step,
                allow_buy=True,
                allow_sell=True,
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

    # In strict security status mode, unverified status blocks execution
    if strict_security_status:
        # Negative evidence takes precedence and will be processed below
        if is_suspended_override is True or trade_status == "0":
            pass
        elif delist_date is not None and session_date >= delist_date:
            pass
        elif listing_date is not None and session_date < listing_date:
            pass
        else:
            # Positive trading evidence required: trade_status == "1" or is_suspended_override is False
            has_tradable_evidence = (
                trade_status in ("1", "trade", "trading")
                or is_suspended_override is False
            )
            if not has_tradable_evidence:
                return TradingRule(
                    rule_id=A_SHARE_TRADING_RULES_POLICY_ID,
                    symbol=symbol,
                    exchange=exchange,
                    board=board,
                    is_tradable=False,
                    status="unverified_state",
                    blocker_reason="trading_state_unverified",
                    limit_pct=None,
                    has_price_limit=False,
                    price_tick=Decimal("0.01"),
                    min_order_qty=Decimal("200") if board == "star" else Decimal("100"),
                    qty_step=Decimal("1") if board == "star" else Decimal("100"),
                    allow_buy=False,
                    allow_sell=False,
                )

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
        limit_pct = None
    elif (
        instrument is not None
        and instrument.limit_pct is not None
        and instrument.limit_pct <= ZERO
    ):
        has_price_limit = False
        limit_pct = None
    else:
        has_price_limit = True
        if board in {"sse_main", "szse_main"}:
            if is_st:
                limit_pct = (
                    ST_RATE
                    if session_date < SSE_SZSE_ST_REFORM_DATE
                    else MAIN_BOARD_RATE
                )
            else:
                limit_pct = MAIN_BOARD_RATE
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
        qty_step = Decimal("1")
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
    if not quantity.is_finite() or quantity <= ZERO:
        return False, "quantity_must_be_positive"

    # Quantities must be integer shares
    if quantity % Decimal("1") != ZERO:
        return False, "quantity_must_be_integer"

    is_star = rule.board == "star"

    if side is OrderSide.BUY:
        if quantity < rule.min_order_qty:
            return False, "order_below_minimum_lot"
        if is_star:
            # STAR statutory rule: minimum 200 shares, increment by 1 share
            if (quantity - Decimal("200")) % rule.qty_step != ZERO:
                return False, "order_not_multiple_of_lot_step"
            return True, None
        else:
            if (quantity % rule.qty_step) != ZERO:
                return False, "order_not_multiple_of_lot_step"
            return True, None

    if side is OrderSide.SELL:
        if available_qty is not None:
            if quantity > available_qty:
                return False, "quantity_exceeds_available"
            # Selling all available shares is always allowed even if not round lots
            if quantity == available_qty:
                return True, None

            if is_star:
                # STAR statutory rules (SSE trading rules section 6.6):
                # 1. "单笔申报数量应当不小于200股"
                # 2. "卖出时，余额不足200股的部分，应当一次性申报卖出"
                if available_qty < Decimal("200"):
                    # Whole holding is less than 200 shares: must sell all at once!
                    if quantity != available_qty:
                        return False, "odd_lot_remainder_must_sell_all"
                    return True, None
                else:
                    # Holding is >= 200 shares. Cannot submit a sell order < 200 shares!
                    if quantity < Decimal("200"):
                        return False, "order_below_minimum_lot"
                    # For quantity >= 200, statutory increment is 1 share
                    if (quantity - Decimal("200")) % rule.qty_step != ZERO:
                        return False, "order_not_multiple_of_lot_step"
                    return True, None
            else:
                # Main Board / ChiNext / BSE / ETF: 100-lot markets
                if available_qty < rule.min_order_qty:
                    if quantity != available_qty:
                        return False, "odd_lot_remainder_must_sell_all"
                    return True, None

                remainder = available_qty % rule.qty_step
                if remainder > ZERO:
                    # Holding contains an odd-lot remainder (< 100).
                    # Valid statutory sell cases:
                    # 1. Selling the exact odd-lot remainder alone
                    if quantity == remainder:
                        return True, None
                    # 2. Selling odd-lot remainder + integer round lots
                    if (
                        quantity > remainder
                        and ((quantity - remainder) % rule.qty_step) == ZERO
                    ):
                        return True, None
                    # 3. Selling integer round lots only, leaving odd-lot remainder intact
                    if (quantity % rule.qty_step) == ZERO and quantity <= (
                        available_qty - remainder
                    ):
                        return True, None
                    # Any other partial split of the odd-lot remainder is illegal
                    return False, "odd_lot_remainder_must_sell_all"

        # Partial sell without odd-lot remainder in available_qty (or available_qty not provided)
        if quantity < rule.min_order_qty:
            return False, "order_below_minimum_lot"
        if is_star:
            if (quantity - Decimal("200")) % rule.qty_step != ZERO:
                return False, "order_not_multiple_of_lot_step"
        else:
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
