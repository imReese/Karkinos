"""Canonical portfolio manual trade projections."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from server.models import (
    TradeCreate,
)
from server.services.asset_metadata import resolve_asset_metadata
from server.services.manual_trade_fees import (
    MANUAL_FEE_INPUT_RULE_ID,
    MANUAL_FEE_INPUT_RULE_VERSION,
    manual_fee_input_payload,
    resolve_manual_trade_fee_breakdown,
)

_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)


def manual_trade_fee_breakdown(commission: float) -> dict[str, str]:
    return manual_fee_input_payload(commission)


def manual_trade_net_cash_impact(
    *, direction: str, gross_amount: float, total_fee: float
) -> float:
    if direction == "buy":
        return -(gross_amount + total_fee)
    return gross_amount - total_fee


def manual_trade_preview_payload(config, body: TradeCreate) -> dict:
    quantity = body.quantity
    price = body.price
    if quantity is None or price is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="quantity and price are required for trade preview",
        )

    commission = body.commission
    configured_fee = None
    note = body.note
    if commission is None:
        configured_fee = resolve_manual_trade_fee_breakdown(
            config,
            asset_class=body.asset_class,
            direction=body.direction,
            quantity=quantity,
            price=price,
            symbol=body.symbol,
        )
        if configured_fee is None:
            commission = 0.0
        else:
            commission = configured_fee.commission
            if not note.strip():
                note = configured_fee.note

    gross_amount = float(quantity) * float(price)
    total_fee = (
        configured_fee.total_fee if configured_fee is not None else float(commission)
    )
    fee_breakdown_json = (
        configured_fee.fee_breakdown_json
        if configured_fee is not None
        else manual_trade_fee_breakdown(commission)
    )
    fee_rule_id = (
        configured_fee.fee_rule_id
        if configured_fee is not None
        else MANUAL_FEE_INPUT_RULE_ID
    )
    fee_rule_version = (
        configured_fee.fee_rule_version
        if configured_fee is not None
        else MANUAL_FEE_INPUT_RULE_VERSION
    )

    return {
        "symbol": body.symbol.strip(),
        "direction": body.direction,
        "quantity": float(quantity),
        "price": float(price),
        "gross_amount": gross_amount,
        "commission": float(commission),
        "total_fee": total_fee,
        "net_cash_impact": manual_trade_net_cash_impact(
            direction=body.direction,
            gross_amount=gross_amount,
            total_fee=total_fee,
        ),
        "fee_breakdown": fee_breakdown_json,
        "fee_rule_id": fee_rule_id,
        "fee_rule_version": fee_rule_version,
        "cost_basis_method": "moving_average_buy_cost",
        "note": note,
    }


def resolve_display_name(state, symbol: str, fallback: str | None = None) -> str:
    return resolve_asset_metadata(
        state,
        symbol,
        fallback_name=fallback,
    ).display_name


def resolve_fund_identity(state, symbol: str) -> dict[str, str]:
    from core.types import Symbol
    from data.manager import build_sources

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    akshare = sources["akshare"]
    symbol_obj = Symbol(symbol.strip())
    display_name = (
        akshare._resolve_open_end_fund_name(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_name")
        else str(symbol_obj)
    ) or str(symbol_obj)
    canonical_symbol = (
        akshare._resolve_open_end_fund_code(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_code")
        else str(symbol_obj)
    ) or str(symbol_obj)
    return {"symbol": canonical_symbol, "display_name": display_name}


def fund_target_trade_date(timestamp: str) -> str:
    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)
    return target_date.isoformat()


__all__ = (
    "fund_target_trade_date",
    "manual_trade_fee_breakdown",
    "manual_trade_net_cash_impact",
    "manual_trade_preview_payload",
    "resolve_display_name",
    "resolve_fund_identity",
)
