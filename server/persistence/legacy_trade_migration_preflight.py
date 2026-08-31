"""Fail-closed preflight for legacy portfolio-trade migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

_V2_MIGRATION_NAME = "canonicalize_legacy_portfolio_trades"
_V2_TRADE_ECONOMICS_KEY = tuple[str, str, Decimal, Decimal, Decimal, str]
_V2_LEGACY_TIMESTAMP_TZ = ZoneInfo("Asia/Shanghai")


def run_pending_legacy_trade_migration_preflight(
    conn: sqlite3.Connection,
    *,
    version: int,
    name: str,
) -> None:
    if version == 2 and name == _V2_MIGRATION_NAME:
        _assert_no_semantic_legacy_trade_duplicates(conn)


def _assert_no_semantic_legacy_trade_duplicates(
    conn: sqlite3.Connection,
) -> None:
    ledger_by_economics: dict[
        _V2_TRADE_ECONOMICS_KEY,
        list[tuple[object, ...]],
    ] = {}
    for row in conn.execute("""
        SELECT
            id, entry_type, timestamp, symbol, direction, quantity, price,
            commission, gross_amount, net_cash_impact, asset_class
        FROM ledger_entries
        WHERE lower(entry_type) IN ('trade_buy', 'trade_sell')
        ORDER BY id
        """).fetchall():
        side = _ledger_trade_side(row[1], row[4])
        economics = _trade_economics_key(
            symbol=row[3],
            side=side,
            quantity=row[5],
            price=row[6],
            commission=row[7],
            asset_class=row[10],
        )
        if economics is None:
            continue
        ledger_by_economics.setdefault(economics, []).append(
            (row[0], row[2], row[8], row[9])
        )

    for row in conn.execute("""
        SELECT
            id, timestamp, symbol, direction, quantity, price, commission,
            asset_class
        FROM trades
        WHERE lower(direction) IN ('buy', 'sell')
        ORDER BY id
        """).fetchall():
        side = str(row[3]).lower()
        economics = _trade_economics_key(
            symbol=row[2],
            side=side,
            quantity=row[4],
            price=row[5],
            commission=row[6],
            asset_class=row[7],
        )
        if economics is None:
            continue
        quantity = economics[2]
        price = economics[3]
        commission = economics[4]
        gross_amount = quantity * price
        net_cash_impact = (
            -(gross_amount + commission) if side == "buy" else gross_amount - commission
        )
        trade_instant = _trade_instant(row[1])
        for (
            ledger_id,
            ledger_timestamp,
            ledger_gross,
            ledger_net,
        ) in ledger_by_economics.get(economics, ()):
            if _trade_instant(ledger_timestamp) != trade_instant:
                continue
            if not _optional_financial_value_matches(ledger_gross, gross_amount):
                continue
            if not _optional_financial_value_matches(ledger_net, net_cash_impact):
                continue
            raise RuntimeError(
                "legacy portfolio trade duplicates an existing ledger entry: "
                f"trade_id={row[0]}, ledger_entry_id={ledger_id}"
            )


def _ledger_trade_side(entry_type: object, direction: object) -> str | None:
    entry_type_side = {
        "trade_buy": "buy",
        "trade_sell": "sell",
    }.get(str(entry_type or "").strip().lower())
    direction_side = str(direction or "").strip().lower()
    if direction_side and direction_side not in {"buy", "sell"}:
        return None
    if direction_side and direction_side != entry_type_side:
        return None
    return entry_type_side


def _trade_economics_key(
    *,
    symbol: object,
    side: str | None,
    quantity: object,
    price: object,
    commission: object,
    asset_class: object,
) -> _V2_TRADE_ECONOMICS_KEY | None:
    if side not in {"buy", "sell"} or symbol is None:
        return None
    quantity_value = _finite_decimal(quantity)
    price_value = _finite_decimal(price)
    commission_value = _finite_decimal(0 if commission is None else commission)
    if quantity_value is None or price_value is None or commission_value is None:
        return None
    return (
        str(symbol).strip(),
        side,
        quantity_value,
        price_value,
        commission_value,
        "stock" if asset_class is None else str(asset_class).strip().lower(),
    )


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _trade_instant(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(
            "legacy portfolio trade duplicate preflight cannot normalize timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_V2_LEGACY_TIMESTAMP_TZ)
    return parsed.astimezone(timezone.utc)


def _optional_financial_value_matches(
    value: object,
    expected: Decimal,
) -> bool:
    if value is None:
        return True
    actual = _finite_decimal(value)
    return actual is not None and actual == expected


__all__ = ["run_pending_legacy_trade_migration_preflight"]
